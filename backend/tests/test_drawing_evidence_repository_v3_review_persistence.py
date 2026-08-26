from __future__ import annotations

from app.domain.drawing_evidence import ContextFact
from app.domain.drawing_evidence_v3 import (
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
    DrawingV3Resolution,
    DrawingV3SourceResult,
    DrawingVisualRegion,
)
from app.graph.drawing_evidence_repository_v3 import DrawingEvidenceRepositoryV3


class CaptureDriver:
    def __init__(self):
        self.calls = []

    def execute_query(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return ([], None, None)


def test_v3_persists_source_snapshot_source_evidence_and_review_visuals():
    driver = CaptureDriver()
    repo = DrawingEvidenceRepositoryV3(driver)

    source_ev = DrawingV3Evidence(
        id="source-ev-1",
        family="spatial_signature",
        method="source_site_point",
        value="2지점",
        supports=True,
        weak=False,
    )
    source = DrawingSourceEvidencePacket(
        source_asset_id="source-a",
        source_sha256="sha-source-a",
        original_name="source-a.ai",
        source_path="drawings/source-a.ai",
        raw_text="2지점 1호 토광묘",
        publication_kind="drawing",
        internal_numbers=(),
        facts=(
            ContextFact(
                kind="site_point",
                value="2지점",
                normalized_value="2",
                source_kind="drawing_ai",
                source_node_id="source-a",
                source_sha256="sha-source-a",
            ),
        ),
        visual_regions=(
            DrawingVisualRegion(
                region_id="source:source-a",
                image_path="/data/derived/corpus-1/source-a.png",
                page=1,
                bbox=None,
                confidence=1.0,
                source_sha256="sha-source-a",
            ),
        ),
        evidence=(source_ev,),
    )
    candidate_ev = DrawingV3Evidence(
        id="candidate-ev-1",
        family="archaeology_signature",
        method="feature_pair",
        value="1호 토광묘",
        supports=True,
        weak=False,
    )
    candidate = DrawingCandidatePacket(
        candidate_id="candidate:source-a:drawing:52",
        publication_kind="drawing",
        number="52",
        raw_texts=("도면 52. 2지점 1호 토광묘",),
        facts=(),
        visual_regions=(
            DrawingVisualRegion(
                region_id="body:caption-52",
                image_path="/data/derived/corpus-1/body-52.png",
                page=12,
                bbox=(0.0, 0.0, 1.0, 1.0),
                confidence=1.0,
                source_sha256="body-sha",
            ),
        ),
        local_score=18.0,
        evidence=(candidate_ev,),
        hard_contradiction=False,
        strong_contradiction_ids=(),
    )
    decision = CodexDrawingDecision(
        run_id="run-a",
        model="gpt-5.3-codex",
        verdict="match",
        candidate_id=candidate.candidate_id,
        confidence=0.91,
        cited_support_ids=(source_ev.id, candidate_ev.id),
        cited_contradiction_ids=(),
        reason_codes=("site_and_feature",),
        summary="review required because confidence is below auto threshold",
    )
    resolution = DrawingV3Resolution(
        source_results=(
            DrawingV3SourceResult(
                source_asset_id="source-a",
                status="REVIEW_REQUIRED",
                candidates=(candidate,),
                decision=decision,
                selected_candidate_id=candidate.candidate_id,
                diagnostics={},
            ),
        ),
        diagnostics={},
    )

    repo.save_v3_resolution(
        "project-1",
        "corpus-1",
        resolution,
        auto_promote=False,
        sources=(source,),
    )

    joined = "\n".join(query for query, _ in driver.calls)
    assert "DRAWING_V3_SOURCE_SNAPSHOTS" in joined
    assert "DRAWING_V3_SOURCE_EVIDENCE" in joined
    assert "DRAWING_V3_REVIEW_VISUALS" in joined

    visual_call = next(
        kwargs for query, kwargs in driver.calls if "DRAWING_V3_REVIEW_VISUALS" in query
    )
    kinds = {(row["owner_type"], row["region_id"]) for row in visual_call["visuals"]}
    assert ("source", "source:source-a") in kinds
    assert ("candidate", "body:caption-52") in kinds

    source_evidence_call = next(
        kwargs for query, kwargs in driver.calls if "DRAWING_V3_SOURCE_EVIDENCE" in query
    )
    assert source_evidence_call["evidence"][0]["id"] == "source-ev-1"
