import pytest
from pydantic import ValidationError

from app.api.schemas import RunTriggerRequest


def test_proofreading_run_requires_review_round_id():
    with pytest.raises(ValidationError):
        RunTriggerRequest.model_validate({
            "enableVlm": False,
            "enableAiReview": False,
        })


def test_direct_version_ids_are_not_part_of_the_production_run_contract():
    request = RunTriggerRequest.model_validate({
        "reviewRoundId": "round_7",
        "enableVlm": False,
        "enableAiReview": True,
    })
    assert request.review_round_id == "round_7"
    assert not hasattr(request, "body_version_id")
    assert not hasattr(request, "plate_version_id")
    assert not hasattr(request, "drawing_version_id")
    assert not hasattr(request, "version_stage")
