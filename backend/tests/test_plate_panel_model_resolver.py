from __future__ import annotations

from dataclasses import replace

from app.services.plate_panel_model_resolver import (
    PlatePanelModelCandidate,
    PlatePanelModelDecision,
    PlatePanelModelRequest,
    PlatePanelModelResolver,
)
from app.services.visual_asset_matcher import VisualAssetMatch


class FakeClient:
    def __init__(self, decisions: dict[str, PlatePanelModelDecision]) -> None:
        self.decisions = decisions
        self.calls: list[str] = []

    def resolve(self, request: PlatePanelModelRequest) -> PlatePanelModelDecision:
        self.calls.append(request.panel_id)
        return self.decisions[request.panel_id]


def _candidate(asset_id: str, score: float = 0.90) -> PlatePanelModelCandidate:
    return PlatePanelModelCandidate(
        source_asset_id=asset_id,
        image_path=f"/images/{asset_id}.jpg",
        retrieval_score=score,
    )


def _request(
    panel_id: str,
    *,
    pdf_path: str = "plate.pdf",
    candidates: tuple[PlatePanelModelCandidate, ...] | None = None,
) -> PlatePanelModelRequest:
    return PlatePanelModelRequest(
        panel_id=panel_id,
        pdf_path=pdf_path,
        physical_page=1,
        bbox=(0.1, 0.1, 0.9, 0.9),
        candidates=candidates or (_candidate("a"), _candidate("b", 0.85)),
    )


def _match(candidate_id: str, confidence: float = 0.98) -> PlatePanelModelDecision:
    return PlatePanelModelDecision(
        verdict="match",
        candidate_id=candidate_id,
        confidence=confidence,
        rationale="same original photograph",
    )


def test_deterministic_verified_panels_bypass_model() -> None:
    request = _request("panel-1")
    client = FakeClient({"panel-1": _match("b")})
    resolver = PlatePanelModelResolver(client, auto_confidence=0.95)

    results = resolver.resolve(
        requests=[request],
        deterministic_matches={
            "panel-1": VisualAssetMatch(source_asset_id="deterministic", score=0.99)
        },
    )

    assert client.calls == []
    assert results["panel-1"].status == "DETERMINISTIC_VERIFIED"
    assert results["panel-1"].selected_source_asset_id == "deterministic"


def test_high_confidence_closed_world_match_is_model_verified() -> None:
    request = _request("panel-1")
    client = FakeClient({"panel-1": _match("a", 0.98)})
    resolver = PlatePanelModelResolver(client, auto_confidence=0.95)

    result = resolver.resolve(requests=[request], deterministic_matches={})["panel-1"]

    assert result.status == "MODEL_VERIFIED"
    assert result.selected_source_asset_id == "a"
    assert result.gate_reason == "model_verified"


def test_candidate_outside_closed_world_is_never_model_verified() -> None:
    request = _request("panel-1")
    client = FakeClient({"panel-1": _match("not-supplied", 0.99)})
    resolver = PlatePanelModelResolver(client, auto_confidence=0.95)

    result = resolver.resolve(requests=[request], deterministic_matches={})["panel-1"]

    assert result.status == "REVIEW_REQUIRED"
    assert result.selected_source_asset_id is None
    assert result.gate_reason == "candidate_outside_closed_world"


def test_low_confidence_match_remains_review_required() -> None:
    request = _request("panel-1")
    client = FakeClient({"panel-1": _match("a", 0.94)})
    resolver = PlatePanelModelResolver(client, auto_confidence=0.95)

    result = resolver.resolve(requests=[request], deterministic_matches={})["panel-1"]

    assert result.status == "REVIEW_REQUIRED"
    assert result.selected_source_asset_id == "a"
    assert result.gate_reason == "confidence_below_threshold"


def test_ambiguous_and_none_fail_closed() -> None:
    request_a = _request("panel-a")
    request_b = _request("panel-b")
    client = FakeClient(
        {
            "panel-a": PlatePanelModelDecision(
                verdict="ambiguous", candidate_id=None, confidence=0.80, rationale="close"
            ),
            "panel-b": PlatePanelModelDecision(
                verdict="none", candidate_id=None, confidence=0.90, rationale="no same photo"
            ),
        }
    )
    resolver = PlatePanelModelResolver(client, auto_confidence=0.95)

    results = resolver.resolve(
        requests=[request_a, request_b], deterministic_matches={}
    )

    assert results["panel-a"].status == "REVIEW_REQUIRED"
    assert results["panel-b"].status == "UNRESOLVED"


def test_same_pdf_model_assignment_collision_downgrades_both() -> None:
    request_a = _request("panel-a", pdf_path="same.pdf")
    request_b = _request("panel-b", pdf_path="same.pdf")
    client = FakeClient({"panel-a": _match("a"), "panel-b": _match("a")})
    resolver = PlatePanelModelResolver(client, auto_confidence=0.95)

    results = resolver.resolve(
        requests=[request_a, request_b], deterministic_matches={}
    )

    assert results["panel-a"].status == "REVIEW_REQUIRED"
    assert results["panel-b"].status == "REVIEW_REQUIRED"
    assert results["panel-a"].gate_reason == "assignment_conflict"
    assert results["panel-b"].gate_reason == "assignment_conflict"


def test_same_source_can_be_reused_across_distinct_pdf_revisions() -> None:
    request_a = _request("panel-a", pdf_path="rev-a.pdf")
    request_b = _request("panel-b", pdf_path="rev-b.pdf")
    client = FakeClient({"panel-a": _match("a"), "panel-b": _match("a")})
    resolver = PlatePanelModelResolver(client, auto_confidence=0.95)

    results = resolver.resolve(
        requests=[request_a, request_b], deterministic_matches={}
    )

    assert results["panel-a"].status == "MODEL_VERIFIED"
    assert results["panel-b"].status == "MODEL_VERIFIED"
