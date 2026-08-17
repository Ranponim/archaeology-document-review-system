from fastapi.testclient import TestClient

from app.domain.models import Project, VersionInput
from app.domain.review_round import ReviewRound
from app.graph.project_repository import ProjectNotFoundError
from app.main import create_app


class StrictProjectRepository:
    def __init__(self) -> None:
        self.project = Project(id="p1", name="산노리 유적", internal_code="NONSAN-001")
        self.round = ReviewRound(
            id="round-2",
            project_id="p1",
            sequence=2,
            body_version_id="body-v2",
            plate_version_id="plate-v1",
            drawing_version_id="drawing-v1",
        )
        self.versions = {
            ("report_body", "body-v2"): VersionInput(
                version_id="body-v2",
                document_id="body-doc",
                project_id="p1",
                kind="report_body",
                stage="source",
                uri="incoming/p1/body/body.pdf",
                sha256="body-sha",
                mime_type="application/pdf",
            ),
            ("plate_book", "plate-v1"): VersionInput(
                version_id="plate-v1",
                document_id="plate-doc",
                project_id="p1",
                kind="plate_book",
                stage="source",
                uri="incoming/p1/plate/plate.pdf",
                sha256="plate-sha",
                mime_type="application/pdf",
            ),
            ("drawing_book", "drawing-v1"): VersionInput(
                version_id="drawing-v1",
                document_id="drawing-doc",
                project_id="p1",
                kind="drawing_book",
                stage="source",
                uri="incoming/p1/drawing/drawing.pdf",
                sha256="drawing-sha",
                mime_type="application/pdf",
            ),
        }

    def get_project(self, project_id: str):
        if project_id != "p1":
            raise ProjectNotFoundError(project_id)
        return {"project": self.project, "documents": [], "document_versions": [], "analysis_runs": []}

    def get_review_round(self, project_id: str, round_id: str):
        if project_id == "p1" and round_id == self.round.id:
            return self.round
        return None

    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ):
        if project_id != "p1" or not version_id:
            return None
        value = self.versions.get((kind, version_id))
        if value is None:
            return None
        if stage is not None and value.stage != stage:
            return None
        return value


class CapturingReviewRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.failed: list[dict] = []

    def create_analysis_run(self, **kwargs) -> None:
        self.created.append(dict(kwargs))

    def save_analysis_run(self, **kwargs) -> None:
        self.failed.append(dict(kwargs))


def strict_client():
    project_repository = StrictProjectRepository()
    review_repository = CapturingReviewRepository()
    enqueued: list[str] = []

    def enqueue(run_id: str) -> str:
        enqueued.append(run_id)
        return run_id

    app = create_app(
        project_repository=project_repository,
        review_repository=review_repository,
        run_enqueuer=enqueue,
    )
    return TestClient(app), review_repository, enqueued


def test_run_requires_review_round_id():
    client, review_repository, enqueued = strict_client()
    response = client.post("/api/v1/projects/p1/runs", json={})
    assert response.status_code == 422
    assert review_repository.created == []
    assert enqueued == []


def test_run_rejects_legacy_only_version_payload():
    client, review_repository, enqueued = strict_client()
    response = client.post(
        "/api/v1/projects/p1/runs",
        json={"bodyVersionId": "body-v2"},
    )
    assert response.status_code == 422
    assert review_repository.created == []
    assert enqueued == []


def test_run_rejects_review_round_plus_direct_version_id():
    client, review_repository, enqueued = strict_client()
    response = client.post(
        "/api/v1/projects/p1/runs",
        json={"reviewRoundId": "round-2", "bodyVersionId": "body-v999"},
    )
    assert response.status_code == 422
    assert review_repository.created == []
    assert enqueued == []


def test_run_rejects_review_round_plus_stage():
    client, review_repository, enqueued = strict_client()
    response = client.post(
        "/api/v1/projects/p1/runs",
        json={"reviewRoundId": "round-2", "versionStage": "3차"},
    )
    assert response.status_code == 422
    assert review_repository.created == []
    assert enqueued == []


def test_run_rejects_review_round_plus_server_pdf_path():
    client, review_repository, enqueued = strict_client()
    response = client.post(
        "/api/v1/projects/p1/runs",
        json={"reviewRoundId": "round-2", "bodyPdfPath": "/tmp/body.pdf"},
    )
    assert response.status_code == 422
    assert review_repository.created == []
    assert enqueued == []


def test_run_route_has_one_strict_published_contract():
    client, _, _ = strict_client()
    openapi = client.app.openapi()
    path = openapi["paths"]["/api/v1/projects/{project_id}/runs"]
    assert set(path) == {"post"}
    operation = path["post"]
    assert operation["operationId"].startswith("trigger_review_round_run_")
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/ReviewRoundRunTriggerRequest")


def test_valid_run_uses_only_versions_owned_by_review_round():
    client, review_repository, enqueued = strict_client()
    response = client.post(
        "/api/v1/projects/p1/runs",
        json={
            "reviewRoundId": "round-2",
            "enableVlm": False,
            "enableAiReview": False,
        },
    )
    assert response.status_code == 202
    assert len(review_repository.created) == 1
    created = review_repository.created[0]
    assert created["project_id"] == "p1"
    assert created["review_round_id"] == "round-2"
    assert created["body_version_id"] == "body-v2"
    assert created["plate_version_id"] == "plate-v1"
    assert created["drawing_version_id"] == "drawing-v1"
    assert created["enable_vlm"] is False
    assert created["enable_ai_review"] is False
    assert enqueued == [created["run_id"]]
