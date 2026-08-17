import pytest
from pydantic import ValidationError

from app.api.review_run_contract import ReviewRoundRunTriggerRequest


def test_proofreading_run_requires_review_round_id():
    with pytest.raises(ValidationError):
        ReviewRoundRunTriggerRequest.model_validate({
            "enableVlm": False,
            "enableAiReview": False,
        })


def test_direct_version_ids_are_rejected_by_runtime_run_contract():
    with pytest.raises(ValidationError) as exc_info:
        ReviewRoundRunTriggerRequest.model_validate({
            "reviewRoundId": "round_7",
            "bodyVersionId": "legacy_body",
            "plateVersionId": "legacy_plate",
            "drawingVersionId": "legacy_drawing",
            "versionStage": "99차",
            "enableVlm": False,
            "enableAiReview": True,
        })

    errors = exc_info.value.errors()
    forbidden = {
        error["loc"][0]
        for error in errors
        if error["type"] == "extra_forbidden"
    }
    assert forbidden == {
        "bodyVersionId",
        "plateVersionId",
        "drawingVersionId",
        "versionStage",
    }
