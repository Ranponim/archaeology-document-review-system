from __future__ import annotations

import pytest

from app.services.panel_provenance_resolver import PanelProvenanceResolver
from app.services.panel_provenance_vlm import PanelProvenanceVLMResult
from app.services.visual_asset_matcher import (
    RankedVisualCandidate,
    VisualAssetMatch,
    VisualPanelAssessment,
)


class _FakeVLM:
    def __init__(self, results: dict[bytes, PanelProvenanceVLMResult]) -> None:
        self.results = results
        self.calls: list[tuple[bytes, bytes]] = []

    async def compare(self, *, panel_bytes: bytes, candidate_bytes: bytes, **kwargs):
        self.calls.append((panel_bytes, candidate_bytes))
        return self.results[candidate_bytes]


def _assessment(status: str, ids=("a", "b")) -> VisualPanelAssessment:
    candidates = tuple(
        RankedVisualCandidate(source_asset_id=source_id, score=0.95 - index * 0.01)
        for index, source_id in enumerate(ids)
    )
    match = (
        VisualAssetMatch(source_asset_id=ids[0], score=0.99)
        if status == "VERIFIED"
        else None
    )
    return VisualPanelAssessment(
        status=status,
        best_score=0.99 if status == "VERIFIED" else 0.95,
        margin=0.04,
        candidates=candidates,
        match=match,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["VERIFIED", "INSUFFICIENT_PANEL", "NO_CANDIDATE"])
async def test_noneligible_assessments_never_call_vlm(status):
    fake = _FakeVLM({})
    resolver = PanelProvenanceResolver(vlm=fake)

    decision = await resolver.resolve(
        assessment=_assessment(status),
        panel_bytes=b"panel",
        candidate_images={"a": b"a-image", "b": b"b-image"},
    )

    assert fake.calls == []
    if status == "VERIFIED":
        assert decision.status == "DETERMINISTIC_VERIFIED"
        assert decision.source_asset_id == "a"
        assert decision.final_verified is True
    else:
        assert decision.status == "UNRESOLVED"
        assert decision.source_asset_id is None
        assert decision.final_verified is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["BELOW_SCORE", "AMBIGUOUS_MARGIN"])
async def test_unresolved_deterministic_cases_are_eligible_for_visual_adjudication(status):
    fake = _FakeVLM(
        {
            b"a-image": PanelProvenanceVLMResult(
                verdict="SAME_SOURCE",
                confidence=0.96,
            ),
            b"b-image": PanelProvenanceVLMResult(
                verdict="DIFFERENT_SOURCE",
                confidence=0.99,
            ),
        }
    )
    resolver = PanelProvenanceResolver(vlm=fake, minimum_vlm_confidence=0.90)

    decision = await resolver.resolve(
        assessment=_assessment(status),
        panel_bytes=b"panel",
        candidate_images={"a": b"a-image", "b": b"b-image"},
    )

    assert len(fake.calls) == 2
    assert decision.status == "AI_SUPPORTED_REVIEW"
    assert decision.source_asset_id == "a"
    assert decision.confidence == pytest.approx(0.96)
    assert decision.final_verified is False


@pytest.mark.asyncio
async def test_multiple_supported_candidates_fail_closed():
    fake = _FakeVLM(
        {
            b"a-image": PanelProvenanceVLMResult("SAME_SOURCE", 0.97),
            b"b-image": PanelProvenanceVLMResult("SAME_SOURCE", 0.96),
        }
    )
    resolver = PanelProvenanceResolver(vlm=fake, minimum_vlm_confidence=0.90)

    decision = await resolver.resolve(
        assessment=_assessment("BELOW_SCORE"),
        panel_bytes=b"panel",
        candidate_images={"a": b"a-image", "b": b"b-image"},
    )

    assert decision.status == "UNRESOLVED"
    assert decision.source_asset_id is None
    assert decision.final_verified is False


@pytest.mark.asyncio
async def test_low_confidence_same_source_fails_closed():
    fake = _FakeVLM(
        {
            b"a-image": PanelProvenanceVLMResult("SAME_SOURCE", 0.72),
            b"b-image": PanelProvenanceVLMResult("DIFFERENT_SOURCE", 0.99),
        }
    )
    resolver = PanelProvenanceResolver(vlm=fake, minimum_vlm_confidence=0.90)

    decision = await resolver.resolve(
        assessment=_assessment("AMBIGUOUS_MARGIN"),
        panel_bytes=b"panel",
        candidate_images={"a": b"a-image", "b": b"b-image"},
    )

    assert decision.status == "UNRESOLVED"
    assert decision.source_asset_id is None
    assert decision.final_verified is False
