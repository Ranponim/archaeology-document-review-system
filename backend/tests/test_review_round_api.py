from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
import pytest
from fastapi.testclient import TestClient

from app.domain.models import Document, DocumentVersion, Project
from app.domain.review_round import ReviewRound
from app.graph.project_repository import (
    ProjectNotFoundError,
    ReviewRoundNotFoundError,
)
from app.main import create_app


class FakeProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[str, Project] = {
            "p1": Project(id="p1", name="산노리 유적", internal_code="NONSAN-001")
        }
        self.documents: dict[str, list[Document]] = {"p1": []}
        self.versions: dict[str, list[DocumentVersion]] = {"p1": []}
        self.rounds: dict[str, list[ReviewRound]] = {"p1": []}

    def get_project(self, project_id: str) -> dict[str, Any]:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        return {
            "project": self.projects[project_id],
            "id": project_id,
            "name": self.projects[project_id].name,
            "internal_code": self.projects[project_id].internal_code,
            "documents": self.documents.get(project_id, []),
            "document_versions": self.versions.get(project_id, []),
            "analysis_runs": [],
        }

    def create_review_round(
        self,
        project_id: str,
        body_version_id: str | None = None,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        notes: str | None = None,
    ) -> ReviewRound:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        rounds = self.rounds.setdefault(project_id, [])
        next_seq = len(rounds) + 1
        round_obj = ReviewRound(
            id=f"round_{project_id}_{next_seq}",
            project_id=project_id,
            sequence=next_seq,
            status="reviewing",
            body_version_id=body_version_id,
            plate_version_id=plate_version_id,
            drawing_version_id=drawing_version_id,
            created_at="2026-08-17T15:00:00Z",
            approved_at=None,
            notes=notes,
        )
        rounds.append(round_obj)
        return round_obj

    def list_review_rounds(self, project_id: str) -> list[ReviewRound]:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        return list(self.rounds.get(project_id, []))

    def get_review_round(
        self, project_id: str, round_id: str
    ) -> ReviewRound | None:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        for r in self.rounds.get(project_id, []):
            if r.id == round_id:
                return r
        return None

    def approve_review_round(
        self, project_id: str, round_id: str
    ) -> ReviewRound:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        rounds = self.rounds.get(project_id, [])
        for i, r in enumerate(rounds):
            if r.id == round_id:
                approved = replace(
                    r,
                    status="approved",
                    approved_at="2026-08-17T15:30:00Z",
                )
                rounds[i] = approved
                return approved
        raise ReviewRoundNotFoundError(
            f"Review round {round_id} not found in project {project_id}"
        )


@pytest.fixture
def fake_repo() -> FakeProjectRepository:
    return FakeProjectRepository()


@pytest.fixture
def client(fake_repo: FakeProjectRepository) -> TestClient:
    app = create_app(project_repository=fake_repo)
    return TestClient(app)


def test_create_review_round_sequence_1(client: TestClient):
    payload = {
        "bodyVersionId": "ver_body_1",
        "plateVersionId": "ver_plate_1",
        "drawingVersionId": "ver_draw_1",
        "notes": "1차 검수 시작",
    }
    response = client.post("/api/v1/projects/p1/rounds", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == "round_p1_1"
    assert data["projectId"] == "p1"
    assert data["sequence"] == 1
    assert data["status"] == "reviewing"
    assert data["bodyVersionId"] == "ver_body_1"
    assert data["plateVersionId"] == "ver_plate_1"
    assert data["drawingVersionId"] == "ver_draw_1"
    assert data["notes"] == "1차 검수 시작"
    assert data["createdAt"] == "2026-08-17T15:00:00Z"
    assert data["approvedAt"] is None


def test_subsequent_create_increments_sequence_and_links_reused_versions(
    client: TestClient,
):
    # Round 1
    r1 = client.post(
        "/api/v1/projects/p1/rounds",
        json={"bodyVersionId": "ver_body_1", "plateVersionId": "ver_plate_1"},
    )
    assert r1.status_code == 201
    assert r1.json()["sequence"] == 1

    # Round 2 - new body version, reused plate version
    r2 = client.post(
        "/api/v1/projects/p1/rounds",
        json={"bodyVersionId": "ver_body_2", "plateVersionId": "ver_plate_1"},
    )
    assert r2.status_code == 201
    data2 = r2.json()
    assert data2["id"] == "round_p1_2"
    assert data2["sequence"] == 2
    assert data2["bodyVersionId"] == "ver_body_2"
    assert data2["plateVersionId"] == "ver_plate_1"
    assert data2["drawingVersionId"] is None


def test_list_review_rounds_sequence_order(client: TestClient):
    client.post(
        "/api/v1/projects/p1/rounds",
        json={"bodyVersionId": "ver_body_1", "notes": "R1"},
    )
    client.post(
        "/api/v1/projects/p1/rounds",
        json={"bodyVersionId": "ver_body_2", "notes": "R2"},
    )

    response = client.get("/api/v1/projects/p1/rounds")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 2
    assert data["items"][0]["sequence"] == 1
    assert data["items"][0]["notes"] == "R1"
    assert data["items"][1]["sequence"] == 2
    assert data["items"][1]["notes"] == "R2"


def test_get_single_review_round_details(client: TestClient):
    post_res = client.post(
        "/api/v1/projects/p1/rounds",
        json={
            "bodyVersionId": "ver_b1",
            "plateVersionId": "ver_p1",
            "drawingVersionId": "ver_d1",
            "notes": "Detail test",
        },
    )
    assert post_res.status_code == 201
    round_id = post_res.json()["id"]

    get_res = client.get(f"/api/v1/projects/p1/rounds/{round_id}")
    assert get_res.status_code == 200
    round_data = get_res.json()
    assert round_data["id"] == round_id
    assert round_data["projectId"] == "p1"
    assert round_data["sequence"] == 1
    assert round_data["status"] == "reviewing"
    assert round_data["bodyVersionId"] == "ver_b1"
    assert round_data["plateVersionId"] == "ver_p1"
    assert round_data["drawingVersionId"] == "ver_d1"
    assert round_data["notes"] == "Detail test"


def test_approve_review_round(client: TestClient):
    post_res = client.post(
        "/api/v1/projects/p1/rounds",
        json={"bodyVersionId": "ver_b1"},
    )
    round_id = post_res.json()["id"]

    approve_res = client.post(f"/api/v1/projects/p1/rounds/{round_id}/approve")
    assert approve_res.status_code == 200
    approved_data = approve_res.json()
    assert approved_data["id"] == round_id
    assert approved_data["status"] == "approved"
    assert approved_data["approvedAt"] == "2026-08-17T15:30:00Z"

    # Verify persisted status via GET
    get_res = client.get(f"/api/v1/projects/p1/rounds/{round_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "approved"
    assert get_res.json()["approvedAt"] == "2026-08-17T15:30:00Z"


def test_404_responses_for_non_existent_project_or_round(client: TestClient):
    # Non-existent project on create round
    res1 = client.post(
        "/api/v1/projects/non_existent_proj/rounds",
        json={"bodyVersionId": "ver_b1"},
    )
    assert res1.status_code == 404

    # Non-existent project on list rounds
    res2 = client.get("/api/v1/projects/non_existent_proj/rounds")
    assert res2.status_code == 404

    # Non-existent round on get round
    res3 = client.get("/api/v1/projects/p1/rounds/non_existent_round")
    assert res3.status_code == 404

    # Non-existent project on get round
    res4 = client.get("/api/v1/projects/non_existent_proj/rounds/round_1")
    assert res4.status_code == 404

    # Non-existent round on approve round
    res5 = client.post("/api/v1/projects/p1/rounds/non_existent_round/approve")
    assert res5.status_code == 404

    # Non-existent project on approve round
    res6 = client.post("/api/v1/projects/non_existent_proj/rounds/round_1/approve")
    assert res6.status_code == 404
