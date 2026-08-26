from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.drawing_review_contract import (
    DrawingReviewCandidateResponse,
    DrawingReviewCaseResponse,
    DrawingReviewResolveRequest,
    DrawingReviewResolveResponse,
)


def test_drawing_review_candidate_contract():
    row = DrawingReviewCandidateResponse(
        candidate_id="candidate:asset-1:drawing:52",
        publication_kind="drawing",
        number="52",
        caption="도면 52. 2지점 1호 토광묘",
        image_url="/api/v1/assets/candidate-52.png",
        local_score=18.5,
        evidence_summary=["2지점 일치", "1호 토광묘 일치"],
        contradiction_summary=[],
    )
    assert row.number == "52"
    assert row.local_score == 18.5


def test_drawing_review_case_contract():
    case = DrawingReviewCaseResponse(
        source_asset_id="asset-1",
        source_name="도면 원본.ai",
        source_image_url=None,
        source_text="2지점 1호 토광묘",
        codex_candidate_id="candidate:asset-1:drawing:52",
        codex_confidence=0.98,
        codex_summary="52가 가장 일치",
        candidates=[],
    )
    assert case.codex_confidence == 0.98


@pytest.mark.parametrize("action", ["approve", "choose"])
def test_approve_and_choose_require_candidate(action):
    with pytest.raises(ValidationError):
        DrawingReviewResolveRequest(action=action, candidate_id=None)


def test_none_requires_null_candidate():
    with pytest.raises(ValidationError):
        DrawingReviewResolveRequest(action="none", candidate_id="candidate:52")

    request = DrawingReviewResolveRequest(action="none", candidate_id=None)
    assert request.action == "none"
    assert request.candidate_id is None
    assert request.reviewer == "human"


def test_resolve_response_contract():
    response = DrawingReviewResolveResponse(
        source_asset_id="asset-1",
        action="choose",
        candidate_id="candidate:asset-1:drawing:53",
        final_status="HUMAN_VERIFIED",
    )
    assert response.final_status == "HUMAN_VERIFIED"
