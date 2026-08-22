from app.api.review_run_contract import ReviewRoundRunTriggerRequest
from app.domain.review_round import ReviewRound
from app.graph.schema import CONSTRAINTS


def test_graph_schema_reserves_reference_corpus_and_derived_artifact_identity() -> None:
    constraint_names = {name for name, _label in CONSTRAINTS}
    assert "reference_corpus_id_unique" in constraint_names
    assert "derived_artifact_id_unique" in constraint_names


def test_review_round_domain_exposes_reference_corpus_identity() -> None:
    fields = ReviewRound.__dataclass_fields__
    assert "reference_corpus_id" in fields


def test_optional_ai_and_vlm_are_off_by_default() -> None:
    request = ReviewRoundRunTriggerRequest(reviewRoundId="round-1")
    assert request.enable_ai_review is False
    assert request.enable_vlm is False
