import pytest

from app.domain.review_models import CorrectionCandidateData
from app.services.development_review_control import DevelopmentReviewBudget


def _candidate(cid: str, category: str, object_id: str) -> CorrectionCandidateData:
    return CorrectionCandidateData(
        candidate_id=cid,
        rule_category=category,
        archaeology_object_id=object_id,
        severity="high",
        confidence=0.95,
        original_text=cid,
    )


def test_budget_freezes_after_full_rule_scan_and_limits_expensive_operations():
    budget = DevelopmentReviewBudget(max_expensive_operations=3)
    budget.record_rule_candidates([
        _candidate("n1", "numeric_value", "obj1"),
        _candidate("t1", "feature_or_artifact_id", "obj2"),
        _candidate("r1", "figure_plate_table_photo_ref", "obj3"),
        _candidate("p1", "direction_period_term", "obj4"),
    ])

    assert budget.allow_visual("plate") is True
    assert budget.allow_visual("drawing") is True
    assert budget.allow_ai("obj1") is True
    assert budget.allow_ai("obj2") is False
    assert budget.expensive_operations == 3


def test_budget_uses_selected_rule_objects_for_ai():
    budget = DevelopmentReviewBudget(max_expensive_operations=10)
    budget.record_rule_candidates([
        _candidate("a", "numeric_value", "objA"),
        _candidate("b", "feature_or_artifact_id", "objB"),
    ])
    assert budget.allow_ai("other") is False
    assert budget.allow_ai("objA") is True


def test_summary_keeps_raw_deduped_selected_counts_separate():
    budget = DevelopmentReviewBudget(max_expensive_operations=10)
    repeated = _candidate("a1", "numeric_value", "objA")
    duplicate = CorrectionCandidateData(
        candidate_id="a2",
        rule_category=repeated.rule_category,
        archaeology_object_id=repeated.archaeology_object_id,
        severity=repeated.severity,
        confidence=repeated.confidence,
        original_text=repeated.original_text,
    )
    budget.record_rule_candidates([repeated, duplicate])
    stats = budget.summary(selected_candidates=1)
    assert stats["raw_findings"] == 2
    assert stats["deduped_findings"] == 1
    assert stats["selected_candidates"] == 1
    assert stats["development_budget"] == 10
