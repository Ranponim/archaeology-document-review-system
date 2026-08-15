import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.domain.models import Project


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
            "analysis_runs": []
        }


def test_ai_analyze_endpoint_triggers_analysis(monkeypatch):
    app = create_app()
    app.state.project_repository = FakeProjectRepository()
    
    client = TestClient(app)
    resp = client.post(
        "/api/projects/p1/analyze",
        json={"model": "openai/gpt-5.6-luna"}
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "analysisRunId" in data
    assert data["model"] == "openai/gpt-5.6-luna"
    assert data["status"] == "queued"


def test_get_candidates_endpoint(monkeypatch):
    app = create_app()
    app.state.project_repository = FakeProjectRepository()
    
    client = TestClient(app)
    resp = client.get("/api/projects/p1/candidates")
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data
    assert data["projectId"] == "p1"
