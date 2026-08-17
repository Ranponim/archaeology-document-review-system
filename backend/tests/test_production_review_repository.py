from app.domain.review_models import CorrectionCandidateData
from app.graph.production_review_repository import ProductionReviewRepository


def test_high_risk_category_restores_high_severity_at_persistence_boundary():
    repo = ProductionReviewRepository(None)
    candidate = CorrectionCandidateData(
        candidate_id="legacy",
        rule_category="numeric_value",
        severity="medium",
        analysis_run_id="run_1",
    )
    param = repo._candidate_to_param(candidate)
    assert param["severity"] == "high"


def test_explicit_low_severity_is_not_promoted_for_low_category():
    repo = ProductionReviewRepository(None)
    candidate = CorrectionCandidateData(
        candidate_id="legacy",
        rule_category="annotation_resolution",
        severity="low",
        analysis_run_id="run_1",
    )
    param = repo._candidate_to_param(candidate)
    assert param["severity"] == "low"
