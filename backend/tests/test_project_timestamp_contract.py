from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.graph.project_repository import ProjectRepository
from app.main import create_app
from app.services.file_store import FileStore
from tests.test_projects_api import FakeProjectRepository


class _ListResult:
    def __init__(self, records):
        self.records = records


class _ListDriver:
    def __init__(self):
        self.queries: list[str] = []

    def execute_query(self, query: str, **_kwargs):
        self.queries.append(query)
        return _ListResult(
            [
                {
                    "id": "newer",
                    "name": "최근 프로젝트",
                    "internalCode": None,
                    "createdAt": "2026-08-18T01:00:00Z",
                    "updatedAt": "2026-08-18T02:00:00Z",
                }
            ]
        )


def test_list_projects_exposes_timestamps_and_orders_legacy_rows_last():
    driver = _ListDriver()
    projects = ProjectRepository(driver=driver).list_projects()

    assert projects[0].created_at == "2026-08-18T01:00:00Z"
    assert projects[0].updated_at == "2026-08-18T02:00:00Z"
    query = driver.queries[0]
    assert "project.createdAt IS NULL" in query
    assert "project.createdAt DESC" in query
    assert "project.name ASC" in query
    assert "project.id ASC" in query


class _TimestampRepository:
    def list_projects(self):
        return [
            SimpleNamespace(
                id="project-1",
                name="산노리",
                internal_code="NONSAN-001",
                created_at="2026-08-18T01:00:00Z",
                updated_at="2026-08-18T02:00:00Z",
            )
        ]


def test_projects_api_serializes_created_at_and_updated_at(tmp_path):
    app = create_app(
        file_store=FileStore(tmp_path),
        project_repository=_TimestampRepository(),
        ingest_enqueuer=lambda run_id: run_id,
    )
    with TestClient(app) as client:
        response = client.get("/api/projects")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "project-1",
            "name": "산노리",
            "internalCode": "NONSAN-001",
            "createdAt": "2026-08-18T01:00:00Z",
            "updatedAt": "2026-08-18T02:00:00Z",
        }
    ]


def test_publication_documents_endpoint_rejects_source_only_hwp_before_graph_write(tmp_path):
    repository = FakeProjectRepository()
    project = repository.create_project("산노리", None)
    enqueued: list[str] = []
    app = create_app(
        file_store=FileStore(tmp_path),
        project_repository=repository,
        ingest_enqueuer=lambda run_id: enqueued.append(run_id) or run_id,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project.id}/documents?stage=source&kind=report_body",
            files={
                "file": (
                    "source.hwp",
                    b"HWP-SOURCE-BYTES",
                    "application/x-hwp",
                )
            },
        )

    assert response.status_code == 422
    assert repository.versions[project.id] == []
    assert enqueued == []
    assert list(tmp_path.rglob("source.hwp")) == []
