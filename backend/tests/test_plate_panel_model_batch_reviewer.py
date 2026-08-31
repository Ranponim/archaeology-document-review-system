from __future__ import annotations

from app.services.plate_panel_model_batch_reviewer import PlatePanelModelBatchReviewer
from app.services.plate_panel_model_resolver import (
    PlatePanelModelCandidate,
    PlatePanelModelDecision,
    PlatePanelModelRequest,
    PlatePanelModelResolver,
)
from app.services.visual_asset_matcher import VisualAssetMatch


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve(self, request: PlatePanelModelRequest) -> PlatePanelModelDecision:
        self.calls.append(request.panel_id)
        return PlatePanelModelDecision(
            verdict="match",
            candidate_id=request.candidates[0].source_asset_id,
            confidence=0.99,
            rationale="same original photograph",
        )


def _request(
    panel_id: str,
    top_score: float,
    second_score: float = 0.0,
) -> PlatePanelModelRequest:
    candidates = [
        PlatePanelModelCandidate(
            source_asset_id=f"{panel_id}-a",
            image_path=f"/{panel_id}-a.jpg",
            retrieval_score=top_score,
        )
    ]
    if second_score > 0.0:
        candidates.append(
            PlatePanelModelCandidate(
                source_asset_id=f"{panel_id}-b",
                image_path=f"/{panel_id}-b.jpg",
                retrieval_score=second_score,
            )
        )
    return PlatePanelModelRequest(
        panel_id=panel_id,
        pdf_path=f"/{panel_id}.pdf",
        physical_page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
        candidates=tuple(candidates),
    )


def test_model_budget_excludes_deterministic_verified_panels() -> None:
    client = RecordingClient()
    reviewer = PlatePanelModelBatchReviewer(
        PlatePanelModelResolver(client, auto_confidence=0.95),
        max_reviews=1,
    )
    deterministic = _request("deterministic", 0.99)
    model_a = _request("model-a", 0.94)
    model_b = _request("model-b", 0.90)

    result = reviewer.review(
        requests=[deterministic, model_a, model_b],
        deterministic_matches={
            "deterministic": VisualAssetMatch(source_asset_id="det-source", score=0.99)
        },
    )

    assert client.calls == ["model-a"]
    assert result.attempted_model_reviews == 1
    assert result.resolutions["deterministic"].status == "DETERMINISTIC_VERIFIED"
    assert result.resolutions["model-a"].status == "MODEL_VERIFIED"
    assert result.deferred_panel_ids == ("model-b",)


def test_batch_prioritizes_strong_top1_and_margin() -> None:
    client = RecordingClient()
    reviewer = PlatePanelModelBatchReviewer(
        PlatePanelModelResolver(client, auto_confidence=0.95),
        max_reviews=2,
    )
    weak_margin = _request("weak-margin", 0.95, 0.949)
    strong = _request("strong", 0.96, 0.80)
    medium = _request("medium", 0.95, 0.85)

    result = reviewer.review(
        requests=[weak_margin, medium, strong],
        deterministic_matches={},
    )

    assert client.calls == ["strong", "medium"]
    assert result.deferred_panel_ids == ("weak-margin",)


def test_no_candidate_panel_is_unresolved_without_model_call() -> None:
    client = RecordingClient()
    reviewer = PlatePanelModelBatchReviewer(
        PlatePanelModelResolver(client, auto_confidence=0.95),
        max_reviews=10,
    )
    request = PlatePanelModelRequest(
        panel_id="no-candidate",
        pdf_path="plate.pdf",
        physical_page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
        candidates=(),
    )

    result = reviewer.review(requests=[request], deterministic_matches={})

    assert client.calls == []
    assert result.attempted_model_reviews == 0
    assert result.resolutions["no-candidate"].status == "UNRESOLVED"
    assert result.deferred_panel_ids == ()
