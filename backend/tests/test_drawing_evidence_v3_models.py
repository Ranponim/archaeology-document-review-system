from app.domain.drawing_evidence import ContextFact
from app.domain.drawing_evidence_v3 import (
    BodyDrawingEvidencePacket,
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
    DrawingV3Resolution,
    DrawingV3SourceResult,
    DrawingVisualRegion,
)


def test_v3_contracts_carry_body_bbox_and_evidence_family():
    evidence = DrawingV3Evidence(
        id="ev:feature",
        family="archaeology_signature",
        method="exact_feature_pair",
        value="토광묘:1",
        supports=True,
        weak=False,
    )
    body = BodyDrawingEvidencePacket(
        publication_kind="drawing",
        number="52",
        raw_texts=("도면 52. 2지점 조선시대 1호 토광묘",),
        source_node_ids=("block-52",),
        source_sha256="bodysha",
        document_version_id="version-1",
        physical_page=12,
        source_bbox=(10.0, 20.0, 110.0, 220.0),
        visual_regions=(),
    )

    assert body.physical_page == 12
    assert body.source_bbox == (10.0, 20.0, 110.0, 220.0)
    assert evidence.family == "archaeology_signature"
    assert evidence.weak is False


def test_v3_source_candidate_decision_and_resolution_contracts_are_composable():
    fact = ContextFact(
        kind="site_point",
        value="2지점",
        normalized_value="2",
        source_kind="source",
    )
    region = DrawingVisualRegion(
        region_id="source:asset-1",
        image_path="/tmp/source-asset-1.png",
        page=1,
        bbox=None,
        confidence=1.0,
        source_sha256="sourcesha",
    )
    evidence = DrawingV3Evidence(
        id="ev:site",
        family="spatial_signature",
        method="exact_site_point",
        value="2",
    )
    source = DrawingSourceEvidencePacket(
        source_asset_id="asset-1",
        source_sha256="sourcesha",
        original_name="sample.ai",
        source_path="site/sample.ai",
        raw_text="2지점",
        publication_kind="drawing",
        internal_numbers=("52",),
        facts=(fact,),
        visual_regions=(region,),
        evidence=(evidence,),
    )
    candidate = DrawingCandidatePacket(
        candidate_id="candidate:drawing:52",
        publication_kind="drawing",
        number="52",
        raw_texts=("도면 52. 2지점",),
        facts=(fact,),
        visual_regions=(),
        local_score=8.0,
        evidence=(evidence,),
        hard_contradiction=False,
        strong_contradiction_ids=(),
    )
    decision = CodexDrawingDecision(
        run_id="run-1",
        model="codex-model",
        verdict="match",
        candidate_id=candidate.candidate_id,
        confidence=0.99,
        cited_support_ids=(evidence.id,),
        cited_contradiction_ids=(),
        reason_codes=("site_match",),
        summary="same site",
    )
    result = DrawingV3SourceResult(
        source_asset_id=source.source_asset_id,
        status="AUTO_VERIFIED",
        candidates=(candidate,),
        decision=decision,
        selected_candidate_id=candidate.candidate_id,
    )
    resolution = DrawingV3Resolution(source_results=(result,))

    assert resolution.source_results[0].decision == decision
    assert resolution.source_results[0].status == "AUTO_VERIFIED"
