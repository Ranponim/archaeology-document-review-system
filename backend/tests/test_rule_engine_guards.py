from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.domain.canonical_models import ArchaeologyObjectData, DrawingData, PlateData
from app.domain.document_structure import CaptionData, ParsedPage, TextBlockData
from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.services.drawing_parser import DrawingIndex
from app.services.plate_parser import PlateIndex
from app.services.proofreading_orchestrator import ProofreadingOrchestrator
from app.services.rule_engine import RuleEngine, prioritize_and_cap_candidates


def test_morphology_guard_distinct_archaeological_types_do_not_trigger_false_positives():
    """Morphology vocabulary guard: 토광묘 vs 수혈, 석관묘 vs 석곽묘, 주거지 vs 수혈주거지

    are distinct archaeological classifications and must NOT trigger type
    inconsistency or false morphology errors when mentioned in context or across
    evidence without referring to the exact same object in a contradictory
    manner.
    """
    engine = RuleEngine()

    obj_pit_tomb = ArchaeologyObjectData(
        object_id="obj_pit_tomb_2",
        site="1지점",
        period="청동기시대",
        type="토광묘",
        number="2호",
        canonical_name="1지점 청동기시대 2호 토광묘",
    )

    # Evidence 1: mentions the 2호 토광묘 and nearby 수혈 features
    ev1 = EvidenceData(
        id="ev_guard_1",
        value="2호 토광묘 바닥면에서 석기가 출토되었으며 인근에는 수혈 3기가 분포한다.",
        document_version_id="ver_1",
        page_id="ver_1_p10",
        source_sha256="hash1",
        kind="text_claim",
    )

    # Evidence 2: describes 2호 토광묘 structure
    ev2 = EvidenceData(
        id="ev_guard_2",
        value="2호 토광묘는 평면 장방형의 형태를 띤다.",
        document_version_id="ver_2",
        page_id="ver_2_p12",
        source_sha256="hash2",
        kind="text_claim",
    )

    candidates = engine.check_object_consistency(
        archaeology_object=obj_pit_tomb,
        evidences=[ev1, ev2],
    )

    # Must NOT produce type mismatch/inconsistency candidate for '수혈' vs '토광묘'
    type_conflicts = [
        c for c in candidates if c.rule_category == "feature_or_artifact_id"
    ]
    assert len(type_conflicts) == 0, f"Unexpected type conflicts: {type_conflicts}"


def test_morphology_guard_drawing_reference_suhyeol_with_body_togwangmyo():
    """Given a body text mentioning 토광묘 and a drawing mentioning 수혈, no

    cross-reference or morphology false positive candidate is generated.
    """
    engine = RuleEngine()

    obj_pit_tomb = ArchaeologyObjectData(
        object_id="obj_pit_tomb_2",
        site="1지점",
        type="토광묘",
        number="2호",
        canonical_name="2호 토광묘",
    )

    # Body references drawing 5
    ev_ref = EvidenceData(
        id="ev_ref_suhyeol",
        kind="reference",
        value="도면 5",
        document_version_id="ver_1",
        page_id="ver_1_p10",
        source_sha256="hash1",
    )

    # Drawing 5 is titled "수혈 평단면도" (general pit drawing referenced in context)
    drawing_5 = DrawingData(
        drawing_id="dr_5",
        number="5",
        physical_page=50,
        title="수혈 평단면도",
        source_sha256="dr_hash",
    )
    drawing_index = DrawingIndex(drawings=[drawing_5])

    candidates = engine.check_object_consistency(
        archaeology_object=obj_pit_tomb,
        evidences=[ev_ref],
        drawing_index=drawing_index,
        drawings=[drawing_5],
    )

    ref_conflicts = [
        c for c in candidates if c.rule_category == "figure_plate_table_photo_ref"
    ]
    assert len(ref_conflicts) == 0, f"Unexpected reference conflicts: {ref_conflicts}"


def test_morphology_guard_dwelling_and_pit_dwelling_are_compatible():
    """'주거지' vs '수혈주거지' are compatible archaeological terms (supertype/subtype)

    and must NOT trigger a false type inconsistency on the same feature.
    """
    engine = RuleEngine()

    obj_dwelling = ArchaeologyObjectData(
        object_id="obj_dwelling_1",
        site="1지점",
        type="수혈주거지",
        number="1호",
        canonical_name="1호 수혈주거지",
    )

    ev1 = EvidenceData(
        id="ev_dw_1",
        value="1호 수혈주거지 내부에서 노지가 확인되었다.",
        document_version_id="ver_1",
        page_id="ver_1_p20",
        source_sha256="hash1",
        kind="text_claim",
    )
    ev2 = EvidenceData(
        id="ev_dw_2",
        value="1호 주거지는 구릉 남사면에 입지한다.",
        document_version_id="ver_2",
        page_id="ver_2_p22",
        source_sha256="hash2",
        kind="text_claim",
    )

    candidates = engine.check_object_consistency(
        archaeology_object=obj_dwelling,
        evidences=[ev1, ev2],
    )

    type_conflicts = [
        c for c in candidates if c.rule_category == "feature_or_artifact_id"
    ]
    assert len(type_conflicts) == 0, f"Unexpected type conflicts: {type_conflicts}"


def test_morphology_guard_true_contradiction_still_detected():
    """True contradictory types for the exact same resolved object entity (e.g.

    6호 석관묘 vs 6호 석곽묘 or 6호 토광묘) MUST still be detected.
    """
    engine = RuleEngine()

    obj_cist = ArchaeologyObjectData(
        object_id="obj_cist_6",
        site="1지점",
        type="석관묘",
        number="6호",
        canonical_name="6호 석관묘",
    )

    ev1 = EvidenceData(
        id="ev_cist_1",
        value="6호 석관묘는 주축이 동서방향이다.",
        document_version_id="ver_1",
        page_id="ver_1_p30",
        source_sha256="hash1",
        kind="text_claim",
    )
    ev2 = EvidenceData(
        id="ev_cist_2",
        value="6호 석곽묘는 주축이 남북방향이다.",
        document_version_id="ver_2",
        page_id="ver_2_p32",
        source_sha256="hash2",
        kind="text_claim",
    )

    candidates = engine.check_object_consistency(
        archaeology_object=obj_cist,
        evidences=[ev1, ev2],
    )

    type_conflicts = [
        c for c in candidates if c.rule_category == "feature_or_artifact_id"
    ]
    assert len(type_conflicts) >= 1
    cand = type_conflicts[0]
    assert "석관묘" in (cand.original_text or "") or "석관묘" in (cand.proposed_text or "")
    assert "석곽묘" in (cand.proposed_text or "") or "석곽묘" in (cand.original_text or "")


def test_candidate_budget_prioritization_and_cap_top_10():
    """Total candidates must NOT exceed 10.

    Candidates must be prioritized deterministically: critical -> high -> medium -> low,
    tie-broken by confidence desc, preserving highest-severity errors.
    """
    candidates = [
        CorrectionCandidateData(
            candidate_id=f"cand_low_{i}",
            rule_category="annotation_resolution",
            confidence=0.99,
            severity="low",
        )
        for i in range(5)
    ] + [
        CorrectionCandidateData(
            candidate_id=f"cand_med_{i}",
            rule_category="direction_period_term",
            confidence=0.85,
            severity="medium",
        )
        for i in range(5)
    ] + [
        CorrectionCandidateData(
            candidate_id=f"cand_high_{i}",
            rule_category="numeric_value",
            confidence=0.90 + (i * 0.01),
            severity="high",
        )
        for i in range(4)
    ] + [
        CorrectionCandidateData(
            candidate_id=f"cand_crit_{i}",
            rule_category="feature_or_artifact_id",
            confidence=0.95,
            severity="critical",
        )
        for i in range(2)
    ]

    # Total 16 candidates: 2 critical, 4 high, 5 medium, 5 low
    capped = prioritize_and_cap_candidates(candidates, max_candidates=10)

    assert len(capped) == 10
    # Top 10 must contain all 2 critical
    crit_cands = [c for c in capped if getattr(c, "severity", "") == "critical"]
    assert len(crit_cands) == 2

    # Top 10 must contain all 4 high
    high_cands = [c for c in capped if getattr(c, "severity", "") == "high"]
    assert len(high_cands) == 4

    # The remaining 4 slots must be filled by medium candidates (not low candidates)
    med_cands = [c for c in capped if getattr(c, "severity", "") == "medium"]
    assert len(med_cands) == 4

    low_cands = [c for c in capped if getattr(c, "severity", "") == "low"]
    assert len(low_cands) == 0


@pytest.mark.anyio
async def test_proofreading_orchestrator_candidate_budget_cap():
    """ProofreadingOrchestrator respects candidate budget <= 10 when max_candidates is set."""
    orchestrator = ProofreadingOrchestrator(allow_degraded_mode=True, max_candidates=10)

    # Construct parsed body pages with multiple items
    p1 = ParsedPage(
        physical_page=1,
        printed_page=1,
        header="",
        raw_text="",
        normalized_text="",
        text_blocks=[
            TextBlockData(
                block_id="b1",
                text="1호 토광묘 길이 200cm (도면 : , 도판 : )",
                normalized_text="1호 토광묘 길이 200cm (도면 : , 도판 : )",
                order=1,
            ),
            TextBlockData(
                block_id="b2",
                text="2호 석관묘 길이 300cm (도면 : , 도판 : )",
                normalized_text="2호 석관묘 길이 300cm (도면 : , 도판 : )",
                order=2,
            ),
            TextBlockData(
                block_id="b3",
                text="3호 석관묘 길이 400cm (도면 : , 도판 : )",
                normalized_text="3호 석관묘 길이 400cm (도면 : , 도판 : )",
                order=3,
            ),
        ],
    )

    res = await orchestrator.run_proofreading(
        project_id="proj_budget_test",
        body_version_id="ver_body",
        body_pages=[p1],
        enable_vlm=False,
        enable_ai_review=False,
        max_candidates=10,
    )

    assert len(res.candidates) <= 10
    assert res.summary["total_candidates"] <= 10
