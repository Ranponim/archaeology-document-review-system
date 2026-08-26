from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.drawing_review_contract import (
    DrawingReviewCandidateResponse,
    DrawingReviewCaseResponse,
    DrawingReviewResolveRequest,
    DrawingReviewResolveResponse,
)
from app.graph.drawing_evidence_repository_v3 import (
    DrawingReviewConflictError,
    DrawingReviewNotFoundError,
)
from app.main import create_app


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


class FakeProjectRepository:
    def __init__(self):
        self.calls = []

    def get_project(self, project_id):
        self.calls.append(project_id)
        return {"project": {"id": project_id}}


class FakeDrawingReviewRepository:
    def __init__(self):
        self.list_calls = []
        self.resolve_calls = []
        self.raise_on_resolve = None

    def list_v3_review_cases(self, project_id):
        self.list_calls.append(project_id)
        return [
            {
                "source_asset_id": "source-a",
                "source_name": "source-a.ai",
                "source_image_url": "/api/v1/assets/drawing-regions/source/render",
                "source_text": "2지점 1호 토광묘",
                "codex_candidate_id": "candidate:52",
                "codex_confidence": 0.91,
                "codex_summary": "사람 확인 필요",
                "candidates": [
                    {
                        "candidate_id": "candidate:52",
                        "publication_kind": "drawing",
                        "number": "52",
                        "caption": "도면 52. 2지점 1호 토광묘",
                        "image_url": None,
                        "local_score": 18.0,
                        "evidence_summary": ["2지점 일치"],
                        "contradiction_summary": [],
                    }
                ],
            }
        ]

    def resolve_v3_review(
        self, project_id, source_asset_id, action, candidate_id, reviewer
    ):
        self.resolve_calls.append(
            (project_id, source_asset_id, action, candidate_id, reviewer)
        )
        if self.raise_on_resolve is not None:
            raise self.raise_on_resolve
        return {
            "source_asset_id": source_asset_id,
            "action": action,
            "candidate_id": candidate_id,
            "final_status": (
                "HUMAN_UNRESOLVED" if action == "none" else "HUMAN_VERIFIED"
            ),
        }


def make_client():
    project_repo = FakeProjectRepository()
    drawing_repo = FakeDrawingReviewRepository()
    app = create_app(project_repository=project_repo)
    app.state.drawing_evidence_repository = drawing_repo
    return TestClient(app), project_repo, drawing_repo


def test_get_drawing_reviews_enforces_project_scope_and_returns_queue():
    client, project_repo, drawing_repo = make_client()

    response = client.get("/api/v1/projects/project-1/drawing-reviews")

    assert response.status_code == 200
    assert project_repo.calls == ["project-1"]
    assert drawing_repo.list_calls == ["project-1"]
    payload = response.json()
    assert payload[0]["source_asset_id"] == "source-a"
    assert payload[0]["candidates"][0]["number"] == "52"


def test_post_drawing_review_resolve_calls_repository():
    client, project_repo, drawing_repo = make_client()

    response = client.post(
        "/api/v1/projects/project-1/drawing-reviews/source-a/resolve",
        json={
            "action": "choose",
            "candidate_id": "candidate:53",
            "reviewer": "reviewer-1",
        },
    )

    assert response.status_code == 200
    assert project_repo.calls == ["project-1"]
    assert drawing_repo.resolve_calls == [
        ("project-1", "source-a", "choose", "candidate:53", "reviewer-1")
    ]
    assert response.json()["final_status"] == "HUMAN_VERIFIED"


def test_post_none_with_candidate_is_422():
    client, _, drawing_repo = make_client()

    response = client.post(
        "/api/v1/projects/project-1/drawing-reviews/source-a/resolve",
        json={"action": "none", "candidate_id": "candidate:52"},
    )

    assert response.status_code == 422
    assert drawing_repo.resolve_calls == []


def test_review_conflict_maps_to_409():
    client, _, drawing_repo = make_client()
    drawing_repo.raise_on_resolve = DrawingReviewConflictError("invalid candidate")

    response = client.post(
        "/api/v1/projects/project-1/drawing-reviews/source-a/resolve",
        json={"action": "choose", "candidate_id": "candidate:999"},
    )

    assert response.status_code == 409


def test_missing_review_maps_to_404():
    client, _, drawing_repo = make_client()
    drawing_repo.raise_on_resolve = DrawingReviewNotFoundError("source-a")

    response = client.post(
        "/api/v1/projects/project-1/drawing-reviews/source-a/resolve",
        json={"action": "approve", "candidate_id": "candidate:52"},
    )

    assert response.status_code == 404
