import pytest
from pydantic import ValidationError

from app.api.review_run_contract import ReviewRoundRunTriggerRequest


def test_proofreading_run_requires_review_round_id():
    with pytest.raises(ValidationError):
        ReviewRoundRunTriggerRequest.model_validate({
            "enableVlm": False,
            "enableAiReview": False,
        })


def test_direct_version_ids_are_not_part_of_the_runtime_run_contract():
    request = ReviewRoundRunTriggerRequest.model_validate({
        "reviewRoundId": "round_7",
        "bodyVersionId": "ignored_legacy_body",
        "plateVersionId": "ignored_legacy_plate",
        "drawingVersionId": "ignored_legacy_drawing",
        "versionStage": "99차",
        "enableVlm": False,
        "enableAiReview": True,
    })
    assert request.review_round_id == "round_7"
    assert not hasattr(request, "body_version_id")
    assert not hasattr(request, "plate_version_id")
    assert not hasattr(request, "drawing_version_id")
    assert not hasattr(request, "version_stage")
