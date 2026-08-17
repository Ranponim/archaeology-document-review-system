import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Document, DocumentVersion, Project, VersionInput
from app.graph.project_repository import ProjectNotFoundError, ProjectRepository
from app.main import create_app
from app.services.file_store import FileStore


class FakeProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}
        self.documents: dict[str, list[Document]] = {}
        self.versions: dict[str, list[DocumentVersion]] = {}
        self.fail_document_write = False
        self.failed_runs: dict[str, tuple[str, bool]] = {}

    def create_project(self, name: str, internal_code: str | None) -> Project:
        project = Project(id=str(uuid4()), name=name, internal_code=internal_code)
        self.projects[project.id] = project
        self.documents[project.id] = []
        self.versions[project.id] = []
        return project

    def list_projects(self) -> list[Project]:
        return list(self.projects.values())

    def get_project(self, project_id: str):
        project = self.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        versions = self.versions[project_id]
        documents = self.documents[project_id]
        return {
            "project": project,
            "documents": documents,
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

    def get_project_documents(self, project_id: str) -> list[Document]:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        return self.documents[project_id]

    def get_document_versions(self, document_id: str) -> list[DocumentVersion]:
        results = []
        for v_list in self.versions.values():
            for v in v_list:
                if v.document_id == document_id:
                    results.append(v)
        return results

    def get_document_version_by_id(self, version_id: str) -> DocumentVersion | None:
        for v_list in self.versions.values():
            for v in v_list:
                if v.id == version_id:
                    return v
        return None

    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ) -> VersionInput | None:
        if project_id not in self.projects:
            return None
        v_list = self.versions.get(project_id, [])
        doc_map = {d.id: d for d in self.documents.get(project_id, [])}
        for v in v_list:
            doc = doc_map.get(v.document_id)
            doc_kind = doc.kind if doc else "report_body"
            if doc_kind != kind:
                continue
            if stage is not None and v.stage != stage:
                continue
            if version_id is not None and v.id != version_id:
                continue
            return VersionInput(
                version_id=v.id,
                document_id=v.document_id,
                project_id=project_id,
                kind=doc_kind,
                stage=v.stage,
                uri=v.uri,
                sha256=v.sha256,
                mime_type=v.mime_type,
            )
        return None

    def add_document_version(

        self,
        project_id,
        stored,
        stage="source",
        kind="report_body",
        title=None,
    ):
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        if self.fail_document_write:
            raise RuntimeError("graph failed for " + stored.uri + " " + stored.sha256)
        existing_doc = next(
            (d for d in self.documents[project_id] if d.kind == kind),
            None,
        )
        if existing_doc is None:
            existing_doc = Document(
                id=str(uuid4()),
                project_id=project_id,
                kind=kind,
                title=title if title is not None else stored.original_name,
            )
            self.documents[project_id].append(existing_doc)
        version = DocumentVersion(
            id=str(uuid4()),
            document_id=existing_doc.id,
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
        "createdAt": None,
        "updatedAt": None,
    }


def test_list_projects_returns_all_created_projects(client):
    res1 = client.post("/api/projects", json={"name": "프로젝트 1"})
    res2 = client.post("/api/projects", json={"name": "프로젝트 2"})
    assert res1.status_code == 201
    assert res2.status_code == 201

    list_res = client.get("/api/projects")
    assert list_res.status_code == 200
    projects = list_res.json()
    assert len(projects) >= 2
    names = [p["name"] for p in projects]
    assert "프로젝트 1" in names
    assert "프로젝트 2" in names


def test_health_endpoint_reports_only_a_fixed_ready_status(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
            "progress_stage": None,
            "progress_message": None,
            "current_page": None,
            "total_pages": None,
        }
    ]


def test_upload_accepts_stages_1cha_2cha_3cha_final_and_shares_document_id(
    client, repository
):
    project = client.post("/api/projects", json={"name": "산노리"}).json()
    stages = ["1차", "2차", "3차", "final"]
    version_ids = []

    for stage in stages:
        res = client.post(
            f"/api/projects/{project['id']}/documents?stage={stage}&kind=report_body",
            files={"file": (f"{stage}.pdf", b"%PDF", "application/pdf")},
        )
        assert res.status_code == 202
        version_ids.append(res.json()["documentVersionId"])

    detail = client.get(f"/api/projects/{project['id']}").json()
    assert len(detail["documentVersions"]) == 4
    doc_ids = {v["documentId"] for v in detail["documentVersions"]}
    assert len(doc_ids) == 1
    assert [v["stage"] for v in detail["documentVersions"]] == stages

