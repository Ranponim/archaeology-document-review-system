import pytest
from fastapi.testclient import TestClient
from rq.exceptions import DuplicateJobError
from rq.job import validate_job_id

from app.domain.models import Project
from app.jobs.queue import enqueue_ai_analysis
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


class FakeJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, FakeJob] = {}
        self.enqueue_calls = 0

    def fetch_job(self, job_id: str):
        return self.jobs.get(job_id)

    def enqueue(self, function_name: str, analysis_run_id: str, project_id: str, model: str, **kwargs):
        self.enqueue_calls += 1
        assert function_name == "app.jobs.worker.run_ai_analysis_job"
        assert kwargs["job_id"] == f"ai-analysis-{analysis_run_id}"
        job = FakeJob(kwargs["job_id"])
        self.jobs[job.id] = job
        return job


class RacingQueue(FakeQueue):
    def __init__(self) -> None:
        super().__init__()
        self.first_lookup = True

    def fetch_job(self, job_id: str):
        if self.first_lookup:
            self.first_lookup = False
            return None
        return self.jobs.get(job_id)

    def enqueue(self, function_name: str, analysis_run_id: str, project_id: str, model: str, **kwargs):
        job = FakeJob(kwargs["job_id"])
        self.jobs[job.id] = job
        raise DuplicateJobError(job.id)


def test_ai_analyze_endpoint_triggers_analysis():
    enqueued_calls = []

    def mock_ai_enqueuer(analysis_run_id: str, project_id: str, model: str) -> str:
        enqueued_calls.append({
            "analysis_run_id": analysis_run_id,
            "project_id": project_id,
            "model": model,
        })
        return f"ai-analysis-{analysis_run_id}"

    app = create_app(ai_enqueuer=mock_ai_enqueuer)
    app.state.project_repository = FakeProjectRepository()

    client = TestClient(app)
    resp = client.post(
        "/api/projects/p1/analyze",
        json={"model": "openai/gpt-5.6-luna"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "analysisRunId" in data
    assert data["model"] == "openai/gpt-5.6-luna"
    assert data["status"] == "queued"
    assert len(enqueued_calls) == 1
    assert enqueued_calls[0] == {
        "analysis_run_id": data["analysisRunId"],
        "project_id": "p1",
        "model": "openai/gpt-5.6-luna",
    }


def test_ai_analyze_endpoint_missing_project_returns_404():
    app = create_app()
    app.state.project_repository = FakeProjectRepository()

    client = TestClient(app)
    resp = client.post(
        "/api/projects/nonexistent/analyze",
        json={"model": "openai/gpt-5.6-luna"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


def test_ai_analyze_endpoint_queue_error_returns_500_sanitized():
    def failing_ai_enqueuer(analysis_run_id: str, project_id: str, model: str) -> str:
        raise ConnectionError("redis://secret-password@redis:6379/0")

    app = create_app(ai_enqueuer=failing_ai_enqueuer)
    app.state.project_repository = FakeProjectRepository()

    client = TestClient(app)
    resp = client.post(
        "/api/projects/p1/analyze",
        json={"model": "openai/gpt-5.6-luna"},
    )
    assert resp.status_code == 500
    assert resp.json()["code"] == "server_error"
    assert "secret-password" not in resp.text


def test_get_candidates_endpoint():
    app = create_app()
    app.state.project_repository = FakeProjectRepository()

    client = TestClient(app)
    resp = client.get("/api/projects/p1/candidates")
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data
    assert data["projectId"] == "p1"
    assert data["total"] == 0
    assert data["candidates"] == []


def test_enqueue_ai_analysis_uses_stable_job_id_and_deduplicates():
    queue = FakeQueue()

    first = enqueue_ai_analysis("run-123", "p1", "gpt-5.6", queue=queue)
    second = enqueue_ai_analysis("run-123", "p1", "gpt-5.6", queue=queue)

    assert first == "ai-analysis-run-123"
    assert second == first
    assert queue.enqueue_calls == 1
    validate_job_id(first)


def test_enqueue_ai_analysis_recovers_when_another_request_wins_the_enqueue_race():
    queue = RacingQueue()

    job_id = enqueue_ai_analysis("run-123", "p1", "gpt-5.6", queue=queue)
    assert job_id == "ai-analysis-run-123"


@pytest.mark.parametrize("invalid_id", ["", "  ", "run:1", "run/1"])
def test_enqueue_ai_analysis_rejects_an_invalid_analysis_run_id(invalid_id):
    with pytest.raises(ValueError):
        enqueue_ai_analysis(invalid_id, "p1", "gpt-5.6", queue=FakeQueue())
