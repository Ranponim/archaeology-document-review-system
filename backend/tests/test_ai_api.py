"""Task 12: the legacy /analyze no-op path is removed.

``POST /api/projects/{id}/analyze`` and the duplicated no-op candidates
endpoint no longer exist: they return 404 and perform zero queue/analysis
work. The single authoritative production pipeline is ``POST
/api/v1/projects/{id}/runs`` -> RQ worker (plan Task 12 / §9 "one
authoritative production pipeline").
"""
from fastapi.testclient import TestClient

from app.domain.models import Project
from app.main import create_app


class FakeProjectRepository:
    def __init__(self):
        self.projects = {
            "p1": Project(id="p1", name="산노리", internal_code="NONSAN-001")
        }

    def get_project(self, project_id: str) -> dict:
        if project_id not in self.projects:
            from app.graph.project_repository import ProjectNotFoundError
            raise ProjectNotFoundError(project_id)
        return {
            "id": project_id,
            "name": "산노리",
            "internal_code": "NONSAN-001",
            "document_versions": [],
            "analysis_runs": [],
        }


def _app_with_recording_enqueuer():
    enqueued = []

    def recording_enqueuer(analysis_run_id: str) -> str:
        enqueued.append(analysis_run_id)
        return f"proofreading-{analysis_run_id}"

    app = create_app(
        project_repository=FakeProjectRepository(),
        run_enqueuer=recording_enqueuer,
    )
    return TestClient(app), enqueued


def test_legacy_analyze_endpoint_removed_returns_404_and_enqueues_nothing():
    client, enqueued = _app_with_recording_enqueuer()

    resp = client.post(
        "/api/projects/p1/analyze",
        json={"model": "openai/gpt-5.6-luna"},
    )

    assert resp.status_code == 404
    assert enqueued == []


def test_legacy_analyze_missing_project_still_404():
    client, enqueued = _app_with_recording_enqueuer()

    resp = client.post(
        "/api/projects/nonexistent/analyze",
        json={"model": "openai/gpt-5.6-luna"},
    )

    assert resp.status_code == 404
    assert enqueued == []


def test_legacy_duplicate_candidates_endpoint_removed():
    """The legacy /api/projects/{id}/candidates no-op placeholder is gone; the
    canonical candidates endpoint lives on the /api/v1 reviews router."""
    client, _ = _app_with_recording_enqueuer()

    resp = client.get("/api/projects/p1/candidates")

    assert resp.status_code == 404