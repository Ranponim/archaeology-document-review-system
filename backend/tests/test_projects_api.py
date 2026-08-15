import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.domain.models import DocumentVersion, Project
from app.graph.project_repository import ProjectNotFoundError, ProjectRepository
from app.main import create_app
from app.services.file_store import FileStore


class FakeProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}
        self.versions: dict[str, list[DocumentVersion]] = {}
        self.fail_document_write = False
        self.failed_runs: dict[str, tuple[str, bool]] = {}

    def create_project(self, name: str, internal_code: str | None) -> Project:
        project = Project(id=str(uuid4()), name=name, internal_code=internal_code)
        self.projects[project.id] = project
        self.versions[project.id] = []
        return project

    def get_project(self, project_id: str):
        project = self.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        versions = self.versions[project_id]
        return {
            "project": project,
            "document_versions": versions,
            "analysis_runs": [
                {
                    "id": version.analysis_run_id,
                    "status": (
                        "failed"
                        if version.analysis_run_id in self.failed_runs
                        else "queued"
                    ),
                    "step": "ingest",
                    "document_version_id": version.id,
                    "error_code": self.failed_runs.get(
                        version.analysis_run_id, (None, False)
                    )[0],
                    "retryable": self.failed_runs.get(
                        version.analysis_run_id, (None, False)
                    )[1],
                }
                for version in versions
            ],
        }

    def add_document_version(self, project_id, stored, stage):
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        if self.fail_document_write:
            raise RuntimeError("graph failed for " + stored.uri + " " + stored.sha256)
        version = DocumentVersion(
            id=str(uuid4()),
            document_id=str(uuid4()),
            analysis_run_id=str(uuid4()),
            uri=stored.uri,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type=stored.mime_type,
            original_name=stored.original_name,
            stage=stage,
        )
        self.versions[project_id].append(version)
        return version

    def fail_ingest(self, analysis_run_id, code, retryable):
        self.failed_runs[analysis_run_id] = (code, retryable)
        return True

    def prepare_ingest_retry(self, project_id, analysis_run_id):
        versions = self.versions.get(project_id)
        if versions is None:
            raise ProjectNotFoundError(project_id)
        if not any(version.analysis_run_id == analysis_run_id for version in versions):
            from app.graph.project_repository import AnalysisRunNotFoundError

            raise AnalysisRunNotFoundError(analysis_run_id)

        failure = self.failed_runs.get(analysis_run_id)
        if failure is None:
            return "queued"
        if failure[1]:
            del self.failed_runs[analysis_run_id]
            return "queued"
        return "failed"


@pytest.fixture
def repository():
    return FakeProjectRepository()


@pytest.fixture
def enqueued_runs():
    return []


@pytest.fixture
def client(tmp_path, repository, enqueued_runs):
    app = create_app(
        file_store=FileStore(tmp_path),
        project_repository=repository,
        ingest_enqueuer=lambda run_id: (
            enqueued_runs.append(run_id) or f"ingest-{run_id}"
        ),
    )
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client


def test_create_project_returns_public_project_fields(client):
    response = client.post(
        "/api/projects",
        json={"name": "산노리", "internalCode": "NONSAN-001"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": response.json()["id"],
        "name": "산노리",
        "internalCode": "NONSAN-001",
    }


def test_upload_creates_queued_ingest_run_and_preserves_bytes(
    client, repository, tmp_path, enqueued_runs
):
    project = client.post("/api/projects", json={"name": "산노리"}).json()

    response = client.post(
        f"/api/projects/{project['id']}/documents?stage=source",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["documentVersionId"]
    assert body["analysisRunId"]
    version = repository.versions[project["id"]][0]
    assert version.id == body["documentVersionId"]
    assert (tmp_path / version.uri).read_bytes() == b"%PDF"
    assert enqueued_runs == [body["analysisRunId"]]


def test_upload_queue_failure_does_not_report_acceptance_and_marks_run_retryable(
    client, repository
):
    project = client.post("/api/projects", json={"name": "산노리"}).json()

    def unavailable_queue(_run_id):
        raise ConnectionError("redis://secret-host:6379/0")

    client.app.state.ingest_enqueuer = unavailable_queue

    response = client.post(
        f"/api/projects/{project['id']}/documents?stage=source",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )

    assert response.status_code == 500
    version = repository.versions[project["id"]][0]
    assert repository.failed_runs[version.analysis_run_id] == ("api_error", True)
    assert "secret-host" not in response.text
    detail = client.get(f"/api/projects/{project['id']}").json()
    assert detail["analysisRuns"][0]["status"] == "failed"
    assert detail["analysisRuns"][0]["errorCode"] == "api_error"
    assert detail["analysisRuns"][0]["retryable"] is True


def test_retry_after_queue_recovery_reuses_the_same_run_without_duplicate_job(
    client, repository
):
    project = client.post("/api/projects", json={"name": "산노리"}).json()
    client.app.state.ingest_enqueuer = lambda _run_id: (_ for _ in ()).throw(
        ConnectionError("redis unavailable")
    )
    failed_upload = client.post(
        f"/api/projects/{project['id']}/documents?stage=source",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )
    assert failed_upload.status_code == 500
    version = repository.versions[project["id"]][0]
    run_id = version.analysis_run_id

    queued_jobs: set[str] = set()

    def restored_queue(analysis_run_id):
        queued_jobs.add(f"ingest-{analysis_run_id}")
        return f"ingest-{analysis_run_id}"

    client.app.state.ingest_enqueuer = restored_queue
    retry_url = f"/api/projects/{project['id']}/analysis-runs/{run_id}/retry"

    first_retry = client.post(retry_url)
    second_retry = client.post(retry_url)

    assert first_retry.status_code == 202
    assert first_retry.json() == {"analysisRunId": run_id, "status": "queued"}
    assert second_retry.status_code == 202
    assert second_retry.json() == first_retry.json()
    assert queued_jobs == {f"ingest-{run_id}"}
    assert len(repository.versions[project["id"]]) == 1


def test_retry_rejects_a_non_retryable_failure_without_enqueueing(client, repository):
    project = client.post("/api/projects", json={"name": "산노리"}).json()
    upload = client.post(
        f"/api/projects/{project['id']}/documents?stage=source",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )
    run_id = upload.json()["analysisRunId"]
    repository.failed_runs[run_id] = ("conversion_error", False)
    enqueued: list[str] = []
    client.app.state.ingest_enqueuer = enqueued.append

    response = client.post(
        f"/api/projects/{project['id']}/analysis-runs/{run_id}/retry"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "input_error"
    assert enqueued == []


def test_retry_queue_failure_is_sanitized_and_remains_recoverable(
    client, repository, caplog
):
    project = client.post("/api/projects", json={"name": "산노리"}).json()
    upload = client.post(
        f"/api/projects/{project['id']}/documents?stage=source",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )
    run_id = upload.json()["analysisRunId"]
    repository.failed_runs[run_id] = ("api_error", True)

    def unavailable_queue(_analysis_run_id):
        raise ConnectionError("redis://private-host:6379/0")

    client.app.state.ingest_enqueuer = unavailable_queue

    response = client.post(
        f"/api/projects/{project['id']}/analysis-runs/{run_id}/retry"
    )

    assert response.status_code == 500
    assert set(response.json()) == {"code", "request_id"}
    assert "private-host" not in response.text
    assert "private-host" not in caplog.text
    assert repository.failed_runs[run_id] == ("api_error", True)


def test_retry_hides_an_analysis_run_owned_by_another_project(client):
    first_project = client.post("/api/projects", json={"name": "첫째"}).json()
    second_project = client.post("/api/projects", json={"name": "둘째"}).json()
    upload = client.post(
        f"/api/projects/{first_project['id']}/documents?stage=source",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )

    response = client.post(
        f"/api/projects/{second_project['id']}/analysis-runs/"
        f"{upload.json()['analysisRunId']}/retry"
    )

    assert response.status_code == 404
    assert set(response.json()) == {"code", "request_id"}


def test_get_project_returns_versions_and_analysis_runs_without_storage_secrets(
    client,
):
    project = client.post("/api/projects", json={"name": "산노리"}).json()
    client.post(
        f"/api/projects/{project['id']}/documents?stage=source",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )

    response = client.get(f"/api/projects/{project['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == project["id"]
    assert body["documentVersions"][0]["originalName"] == "a.pdf"
    assert body["analysisRuns"][0]["status"] == "queued"
    assert "uri" not in body["documentVersions"][0]
    assert "sha256" not in body["documentVersions"][0]


def test_upload_rejects_invalid_stage_before_storing_bytes(client, tmp_path):
    project = client.post("/api/projects", json={"name": "산노리"}).json()

    response = client.post(
        f"/api/projects/{project['id']}/documents?stage=published",
        files={"file": ("a.pdf", b"PRIVATE-ORIGINAL-BYTES", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "input_error"
    assert list(tmp_path.rglob("*")) == []


def test_upload_rejects_invalid_mime_with_sanitized_error(client, tmp_path):
    project = client.post("/api/projects", json={"name": "산노리"}).json()

    response = client.post(
        f"/api/projects/{project['id']}/documents?stage=source",
        files={
            "file": (
                "private.exe",
                b"PRIVATE-ORIGINAL-BYTES",
                "application/x-msdownload",
            )
        },
    )

    assert response.status_code == 400
    assert set(response.json()) == {"code", "request_id"}
    assert response.json()["code"] == "input_error"
    assert "PRIVATE-ORIGINAL-BYTES" not in response.text
    assert "private.exe" not in response.text
    assert list(tmp_path.rglob("*")) == []


def test_upload_missing_project_returns_404_without_storing_bytes(client, tmp_path):
    response = client.post(
        f"/api/projects/{uuid4()}/documents?stage=source",
        files={"file": ("a.pdf", b"PRIVATE-ORIGINAL-BYTES", "application/pdf")},
    )

    assert response.status_code == 404
    assert set(response.json()) == {"code", "request_id"}
    assert response.json()["code"] == "input_error"
    assert list(tmp_path.rglob("*")) == []


def test_graph_failure_never_returns_202_or_leaks_file_metadata(
    client, repository, tmp_path, caplog
):
    project = client.post("/api/projects", json={"name": "산노리"}).json()
    repository.fail_document_write = True

    response = client.post(
        f"/api/projects/{project['id']}/documents?stage=source",
        files={
            "file": (
                "private.pdf",
                b"PRIVATE-ORIGINAL-BYTES",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 500
    assert set(response.json()) == {"code", "request_id"}
    assert response.json()["code"] == "server_error"
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
    assert "PRIVATE-ORIGINAL-BYTES" not in response.text
    assert "private.pdf" not in response.text
    expected_hash = hashlib.sha256(b"PRIVATE-ORIGINAL-BYTES").hexdigest()
    assert "PRIVATE-ORIGINAL-BYTES" not in caplog.text
    assert "private.pdf" not in caplog.text
    assert expected_hash not in caplog.text
    assert "incoming/" not in caplog.text
    assert not repository.versions[project["id"]]
    # The immutable blob is intentionally retained for reconciliation. Deleting it
    # here could break a concurrent successful upload of the same content address.
    assert [path for path in tmp_path.rglob("*") if path.is_file()]


def test_storage_failure_is_handled_before_asgi_and_sanitizes_server_error(
    client, caplog
):
    class FailingFileStore:
        async def store_upload(self, project_id, upload):
            raise RuntimeError(
                "storage failed: incoming/private.pdf "
                + "f" * 64
                + " PRIVATE-ORIGINAL-BYTES"
            )

    project = client.post("/api/projects", json={"name": "산노리"}).json()
    client.app.state.file_store = FailingFileStore()

    response = client.post(
        f"/api/projects/{project['id']}/documents?stage=source",
        files={
            "file": (
                "private.pdf",
                b"PRIVATE-ORIGINAL-BYTES",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 500
    assert response.json()["code"] == "server_error"
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
    for secret in (
        "PRIVATE-ORIGINAL-BYTES",
        "private.pdf",
        "f" * 64,
        "incoming/",
    ):
        assert secret not in response.text
        assert secret not in caplog.text


def test_get_missing_project_returns_sanitized_404(client):
    response = client.get(f"/api/projects/{uuid4()}")

    assert response.status_code == 404
    assert set(response.json()) == {"code", "request_id"}
    assert response.json()["code"] == "input_error"


def test_project_repository_reads_project_versions_and_queued_runs():
    class SnapshotDriver:
        def execute_query(self, _query, **kwargs):
            assert kwargs["project_id"] == "project-1"
            assert kwargs["database_"] == "isolated_test"
            return (
                [
                    {
                        "project": {
                            "id": "project-1",
                            "name": "산노리",
                            "internalCode": "NONSAN-001",
                        },
                        "documentVersions": [
                            {
                                "id": "version-1",
                                "documentId": "document-1",
                                "analysisRunId": "run-1",
                                "uri": "incoming/project/hash/a.pdf",
                                "sha256": "a" * 64,
                                "sizeBytes": 4,
                                "mimeType": "application/pdf",
                                "originalName": "a.pdf",
                                "stage": "source",
                            }
                        ],
                        "analysisRuns": [
                            {
                                "id": "run-1",
                                "status": "queued",
                                "step": "ingest",
                                "documentVersionId": "version-1",
                            }
                        ],
                    }
                ],
                None,
                None,
            )

    snapshot = ProjectRepository(
        SnapshotDriver(), database="isolated_test"
    ).get_project("project-1")

    assert snapshot["project"] == Project(
        id="project-1", name="산노리", internal_code="NONSAN-001"
    )
    assert snapshot["document_versions"][0].original_name == "a.pdf"
    assert snapshot["analysis_runs"] == [
        {
            "id": "run-1",
            "status": "queued",
            "step": "ingest",
            "document_version_id": "version-1",
            "error_code": None,
            "retryable": False,
        }
    ]
