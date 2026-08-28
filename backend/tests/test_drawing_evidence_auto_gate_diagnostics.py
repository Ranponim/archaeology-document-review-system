from __future__ import annotations

from app.domain.drawing_evidence_v3 import (
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
)
from app.services.drawing_evidence_resolver_v3 import DrawingEvidenceResolverV3


def _evidence(eid: str, family: str, *, weak: bool) -> DrawingV3Evidence:
    return DrawingV3Evidence(
        id=eid,
        family=family,
        method="test",
        value=eid,
        supports=True,
        weak=weak,
    )


def test_review_result_records_exact_auto_gate_diagnostics_for_weak_support_only():
    source = DrawingSourceEvidencePacket(
        source_asset_id="asset-1",
        source_sha256="sha-1",
        original_name="asset-1.ai",
        source_path="site/asset-1.ai",
        raw_text="",
        publication_kind="drawing",
        internal_numbers=(),
        facts=(),
        visual_regions=(),
        evidence=(),
    )
    candidate = DrawingCandidatePacket(
        candidate_id="candidate:asset-1:drawing:35",
        publication_kind="drawing",
        number="35",
        raw_texts=("도면 35. 고려시대 1호 석곽묘 평·입단면도 및 출토유물",),
        facts=(),
        visual_regions=(),
        local_score=10.0,
        evidence=(
            _evidence("ev:site", "spatial_signature", weak=True),
            _evidence("ev:feature", "archaeology_signature", weak=True),
        ),
        hard_contradiction=False,
        strong_contradiction_ids=(),
    )
    decision = CodexDrawingDecision(
        run_id="run-1",
        model="gpt-5.6-luna",
        verdict="match",
        candidate_id=candidate.candidate_id,
        confidence=0.98,
        cited_support_ids=tuple(item.id for item in candidate.evidence),
        cited_contradiction_ids=(),
        reason_codes=("visual_match",),
        summary="visual match",
    )

    class Generator:
        def generate(self, source_packet, bodies, limit=10):
            return (candidate,)

    class Client:
        def resolve(self, source_packet, candidates):
            return decision

    result = DrawingEvidenceResolverV3(Generator(), Client()).resolve_observations(
        "corpus-1", [source], []
    )
    item = result.source_results[0]

    assert item.status == "REVIEW_REQUIRED"
    assert item.diagnostics["auto_gate_reason"] == "weak_support_only"
    assert item.diagnostics["cited_support_ids"] == ["ev:site", "ev:feature"]
    assert item.diagnostics["cited_support_families"] == [
        "archaeology_signature",
        "spatial_signature",
    ]
    assert item.diagnostics["cited_nonweak_count"] == 0
    assert item.diagnostics["cited_contradiction_ids"] == []
