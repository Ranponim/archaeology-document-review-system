from __future__ import annotations

import hashlib

from app.domain.drawing_evidence_v3 import (
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
    DrawingVisualRegion,
)
from app.services.drawing_evidence_resolver_v3 import DrawingEvidenceResolverV3


def _visual_support_id(
    source: DrawingSourceEvidencePacket,
    candidate: DrawingCandidatePacket,
) -> str:
    payload = "\0".join(
        (
            source.source_asset_id,
            source.visual_regions[0].region_id,
            candidate.candidate_id,
            candidate.visual_regions[0].region_id,
        )
    ).encode("utf-8")
    return "drawing-v3-visual-support:" + hashlib.sha256(payload).hexdigest()[:32]


def _weak_semantic(eid: str) -> DrawingV3Evidence:
    return DrawingV3Evidence(
        id=eid,
        family="weak_filename_semantic",
        method="filename_semantic",
        value=eid,
        supports=True,
        weak=True,
    )


def _source() -> DrawingSourceEvidencePacket:
    return DrawingSourceEvidencePacket(
        source_asset_id="asset-1",
        source_sha256="source-sha",
        original_name="1지점 고려시대 1호 석곽묘 평입단면도.ai",
        source_path="본문 도면/1지점/source.ai",
        raw_text="",
        publication_kind="drawing",
        internal_numbers=(),
        facts=(),
        visual_regions=(
            DrawingVisualRegion(
                region_id="source:asset-1",
                image_path="/tmp/source.png",
                page=1,
                bbox=None,
                confidence=1.0,
                source_sha256="source-sha",
            ),
        ),
        evidence=(),
    )


def _candidate(*, weak_semantic: bool = True) -> DrawingCandidatePacket:
    evidence = (
        (_weak_semantic("ev:filename:site"), _weak_semantic("ev:filename:feature"))
        if weak_semantic
        else ()
    )
    return DrawingCandidatePacket(
        candidate_id="candidate:asset-1:drawing:35",
        publication_kind="drawing",
        number="35",
        raw_texts=("도면 35. 고려시대 1호 석곽묘 평·입단면도 및 출토유물",),
        facts=(),
        visual_regions=(
            DrawingVisualRegion(
                region_id="body:drawing:35",
                image_path="/tmp/body-35.png",
                page=12,
                bbox=(1.0, 1.0, 10.0, 10.0),
                confidence=1.0,
                source_sha256="body-sha",
            ),
        ),
        local_score=10.0,
        evidence=evidence,
        hard_contradiction=False,
        strong_contradiction_ids=(),
    )


def _resolve(
    source: DrawingSourceEvidencePacket,
    candidate: DrawingCandidatePacket,
    *,
    visual_support_ids: tuple[str, ...],
):
    decision = CodexDrawingDecision(
        run_id="run-1",
        model="gpt-5.6-luna",
        verdict="match",
        candidate_id=candidate.candidate_id,
        confidence=0.97,
        cited_support_ids=tuple(item.id for item in candidate.evidence),
        cited_contradiction_ids=(),
        reason_codes=("visual_match",),
        summary="material visual agreement",
        cited_visual_support_ids=visual_support_ids,
    )

    class Generator:
        def generate(self, source_packet, bodies, limit=10):
            return (candidate,)

    class Client:
        def resolve(self, source_packet, candidates):
            return decision

    return DrawingEvidenceResolverV3(Generator(), Client()).resolve_observations(
        "corpus-1", [source], []
    ).source_results[0]


def test_weak_semantic_plus_closed_world_visual_support_can_auto_verify():
    source = _source()
    candidate = _candidate()
    visual_support_id = _visual_support_id(source, candidate)

    item = _resolve(source, candidate, visual_support_ids=(visual_support_id,))

    assert item.status == "AUTO_VERIFIED"
    assert item.diagnostics["auto_gate_reason"] == "auto_verified"
    assert item.diagnostics["cited_visual_support_ids"] == [visual_support_id]
    assert item.diagnostics["cited_support_families"] == [
        "visual_signature",
        "weak_filename_semantic",
    ]
    assert item.diagnostics["cited_nonweak_count"] == 1


def test_visual_support_id_outside_selected_candidate_fails_closed():
    source = _source()
    candidate = _candidate()

    item = _resolve(
        source,
        candidate,
        visual_support_ids=("drawing-v3-visual-support:invented",),
    )

    assert item.status == "REVIEW_REQUIRED"
    assert item.diagnostics["auto_gate_reason"] == "invalid_visual_support"


def test_visual_support_alone_is_not_enough_for_auto_verification():
    source = _source()
    candidate = _candidate(weak_semantic=False)
    visual_support_id = _visual_support_id(source, candidate)

    item = _resolve(source, candidate, visual_support_ids=(visual_support_id,))

    assert item.status == "REVIEW_REQUIRED"
    assert item.diagnostics["auto_gate_reason"] == "insufficient_support_families"
    assert item.diagnostics["cited_support_families"] == ["visual_signature"]
    assert item.diagnostics["cited_nonweak_count"] == 1
