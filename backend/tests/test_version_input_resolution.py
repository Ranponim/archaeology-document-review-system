from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient

from app.domain.models import Document, DocumentVersion, Project, VersionInput
from app.graph.project_repository import (
    DocumentVersionNotFoundError,
    ProjectNotFoundError,
    ProjectRepository,
)
from app.graph.review_repository import ReviewRepository
from app.main import create_app
from app.services.proofreading_orchestrator import (
    OrchestratorResult,
    ProofreadingOrchestrator,
)


class FakeNeo4jRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class FakeNeo4jDriver:
    def __init__(self, records_to_return: list[dict[str, Any]] | None = None):
        self.queries: list[dict[str, Any]] = []
        self.records_to_return = [
            FakeNeo4jRecord(r) for r in (records_to_return or [])
        ]

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        return self.records_to_return, None, None


class FakeReviewRepositoryForOrchestrator:
    def __init__(self):
        self.runs: dict[str, dict[str, Any]] = {}
        self.saved_pages: list[Any] = []
        self.saved_evidences: list[Any] = []
        self.saved_candidates: list[Any] = []

    def create_analysis_run(
        self,
        project_id: str,
        run_id: str,
        *,
        body_version_id: str,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        body_pdf_path: str | None = None,
        plate_pdf_path: str | None = None,
        drawing_pdf_path: str | None = None,
        enable_vlm: bool = True,
        enable_ai_review: bool = True,
        version_stage: str = "1차",
    ):
        self.runs[run_id] = {
            "project_id": project_id,
            "run_id": run_id,
            "status": "queued",
            "step": "queued",
            "body_version_id": body_version_id,
        }

    def save_analysis_run(
        self,
        project_id: str,
        run_id: str,
        status: str,
        step: str,
        error_code: str | None = None,
        retryable: bool = False,
    ):
        self.runs[run_id] = {
            "project_id": project_id,
            "run_id": run_id,
            "status": status,
            "step": step,
            "error_code": error_code,
            "retryable": retryable,
        }

    def save_pages_and_blocks(self, version_id: str, pages: list[Any]):
        self.saved_pages.extend(pages)

    def save_evidences(self, evidences: list[Any]):
        self.saved_evidences.extend(evidences)

    def save_candidates(self, project_id: str, candidates: list[Any], analysis_run_id: str):
        self.saved_candidates.extend(candidates)


class MockProjectRepository:
    def __init__(self):
        self.projects = {
            "proj_1": Project(id="proj_1", name="산노리 유적", internal_code="NONSAN-001")
        }
        self.documents = {
            "proj_1": [Document(id="doc_body_1", project_id="proj_1", kind="report_body", title="보고서 본문")]
        }
        self.versions = {
            "proj_1": [
                DocumentVersion(
                    id="ver_body_real_001",
                    document_id="doc_body_1",
                    analysis_run_id="run_init",
                    uri="incoming/proj_1/sha1/body.pdf",
                    sha256="sha256_real_body_hash",
                    size_bytes=10240,
                    mime_type="application/pdf",
                    original_name="body.pdf",
                    stage="1차",
                )
            ]
        }

    def get_project(self, project_id: str) -> dict:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        return {
            "project": self.projects[project_id],
            "documents": self.documents.get(project_id, []),
            "document_versions": self.versions.get(project_id, []),
            "analysis_runs": [],
        }

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


# =============================================================================
# 1. VersionInput Dataclass Contract Tests
# =============================================================================

def test_version_input_dataclass_contract():
    vi = VersionInput(
        version_id="ver_001",
        document_id="doc_001",
        project_id="proj_001",
        kind="report_body",
        stage="1차",
        uri="incoming/proj_001/abc/report.pdf",
        sha256="abc123sha",
    )
    assert vi.version_id == "ver_001"
    assert vi.document_id == "doc_001"
    assert vi.project_id == "proj_001"
    assert vi.kind == "report_body"
    assert vi.stage == "1차"
    assert vi.uri == "incoming/proj_001/abc/report.pdf"
    assert vi.sha256 == "abc123sha"
    assert vi.mime_type == "application/pdf"

    # Verify frozen immutability
    with pytest.raises(Exception):
        vi.version_id = "new_id"  # type: ignore


# =============================================================================
# 2. ProjectRepository Resolution Method Tests
# =============================================================================

def test_project_repository_get_document_version_by_id_found():
    record_data = {
        "id": "ver_test_001",
        "document_id": "doc_test_001",
        "analysis_run_id": "run_test_001",
        "uri": "incoming/p1/hash/body.pdf",
        "sha256": "deadbeef1234",
        "size_bytes": 45000,
        "mime_type": "application/pdf",
        "original_name": "body.pdf",
        "stage": "1차",
    }
    driver = FakeNeo4jDriver([record_data])
    repo = ProjectRepository(driver)

    result = repo.get_document_version_by_id("ver_test_001")
    assert result is not None
    assert isinstance(result, DocumentVersion)
    assert result.id == "ver_test_001"
    assert result.document_id == "doc_test_001"
    assert result.sha256 == "deadbeef1234"
    assert result.stage == "1차"


def test_project_repository_get_document_version_by_id_not_found():
    driver = FakeNeo4jDriver([])
    repo = ProjectRepository(driver)

    result = repo.get_document_version_by_id("ver_missing")
    assert result is None


def test_project_repository_resolve_version_input_success():
    record_data = {
        "version_id": "ver_test_002",
        "document_id": "doc_test_002",
        "project_id": "proj_test_001",
        "kind": "report_body",
        "stage": "2차",
        "uri": "incoming/proj_test_001/hash/report.pdf",
        "sha256": "feedbeef5678",
        "mime_type": "application/pdf",
    }
    driver = FakeNeo4jDriver([record_data])
    repo = ProjectRepository(driver)

    result = repo.resolve_version_input(
        project_id="proj_test_001",
        kind="report_body",
        stage="2차",
    )
    assert result is not None
    assert isinstance(result, VersionInput)
    assert result.version_id == "ver_test_002"
    assert result.document_id == "doc_test_002"
    assert result.project_id == "proj_test_001"
    assert result.kind == "report_body"
    assert result.stage == "2차"
    assert result.sha256 == "feedbeef5678"


def test_project_repository_resolve_version_input_not_found():
    driver = FakeNeo4jDriver([])
    repo = ProjectRepository(driver)

    result = repo.resolve_version_input(
        project_id="proj_test_001",
        kind="report_body",
        stage="3차",
    )
    assert result is None


# =============================================================================
# 3. ProofreadingOrchestrator Fail-Closed Invariant Tests
# =============================================================================

@pytest.mark.anyio
async def test_orchestrator_fails_closed_when_body_version_id_is_empty():
    review_repo = FakeReviewRepositoryForOrchestrator()
    orchestrator = ProofreadingOrchestrator(review_repo=review_repo)

    with pytest.raises((ValueError, DocumentVersionNotFoundError)):
        await orchestrator.run_proofreading(
            project_id="proj_1",
            body_version_id="",
            analysis_run_id="run_fail_1",
        )

    # Verify AnalysisRun was marked as failed
    run_state = review_repo.runs.get("run_fail_1")
    assert run_state is not None
    assert run_state["status"] == "failed"


@pytest.mark.anyio
async def test_orchestrator_fails_closed_when_body_version_not_found_in_repository():
    review_repo = FakeReviewRepositoryForOrchestrator()
    project_repo = MockProjectRepository()
    orchestrator = ProofreadingOrchestrator(
        review_repo=review_repo,
        project_repo=project_repo,
    )

    with pytest.raises(DocumentVersionNotFoundError):
        await orchestrator.run_proofreading(
            project_id="proj_1",
            body_version_id="ver_non_existent",
            analysis_run_id="run_fail_2",
        )

    run_state = review_repo.runs.get("run_fail_2")
    assert run_state is not None
    assert run_state["status"] == "failed"


@pytest.mark.anyio
async def test_orchestrator_fails_closed_when_body_pdf_file_missing_on_disk():
    review_repo = FakeReviewRepositoryForOrchestrator()
    orchestrator = ProofreadingOrchestrator(review_repo=review_repo)

    with pytest.raises((FileNotFoundError, ValueError)):
        await orchestrator.run_proofreading(
            project_id="proj_1",
            body_version_id="ver_valid_id",
            body_pdf_path="/path/to/nonexistent/disk_file_xyz_12345.pdf",
            analysis_run_id="run_fail_3",
        )

    run_state = review_repo.runs.get("run_fail_3")
    assert run_state is not None
    assert run_state["status"] == "failed"


@pytest.mark.anyio
async def test_orchestrator_fails_closed_when_plate_pdf_file_missing_on_disk():
    from app.domain.document_structure import ParsedPage
    review_repo = FakeReviewRepositoryForOrchestrator()
    orchestrator = ProofreadingOrchestrator(review_repo=review_repo)

    sample_page = ParsedPage(
        physical_page=1,
        printed_page=1,
        header="헤더",
        raw_text="샘플",
        normalized_text="샘플",
    )


    with pytest.raises((FileNotFoundError, ValueError)):
        await orchestrator.run_proofreading(
            project_id="proj_1",
            body_version_id="ver_valid_id",
            body_pages=[sample_page],
            plate_pdf_path="/path/to/nonexistent/plate_missing_xyz_9999.pdf",
            analysis_run_id="run_fail_4",
        )

    run_state = review_repo.runs.get("run_fail_4")
    assert run_state is not None
    assert run_state["status"] == "failed"


# =============================================================================
# 4. Elimination of Synthetic Fallbacks in Reviews API
# =============================================================================

def test_reviews_api_rejects_missing_body_version_without_fallback():
    # Setup project with no document versions
    proj_repo = MockProjectRepository()
    proj_repo.versions["proj_1"] = []  # No versions exist!

    app = create_app(project_repository=proj_repo)
    client = TestClient(app)

    # Trigger run without bodyVersionId -> MUST FAIL with 404 (not fallback to ver_proj_1_body)
    resp = client.post("/api/v1/projects/proj_1/runs", json={})
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


def test_reviews_api_rejects_non_existent_body_version_id():
    proj_repo = MockProjectRepository()
    app = create_app(project_repository=proj_repo)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/projects/proj_1/runs",
        json={"bodyVersionId": "ver_does_not_exist_999"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


def test_reviews_api_rejects_non_existent_plate_version_id():
    proj_repo = MockProjectRepository()
    app = create_app(project_repository=proj_repo)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/projects/proj_1/runs",
        json={
            "bodyVersionId": "ver_body_real_001",
            "plateVersionId": "ver_plate_missing_001",
        },
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


def test_reviews_api_resolves_real_version_and_enqueues_async_run():
    proj_repo = MockProjectRepository()
    rev_repo = FakeReviewRepositoryForOrchestrator()
    orch_calls: list[str] = []

    class FakeOrch:
        async def run_proofreading(self, project_id: str, body_version_id: str, **kwargs):
            orch_calls.append(body_version_id)
            return OrchestratorResult(
                project_id=project_id,
                analysis_run_id="run_resolved_001",
                status="completed",
                pages_parsed=5,
                objects_resolved=3,
                references_resolved=10,
                candidates=[],
                evidences=[],
                objects=[],
                plates=[],
                drawings=[],
            )

    enqueued: list[str] = []
    app = create_app(
        project_repository=proj_repo,
        review_repository=rev_repo,
        orchestrator=FakeOrch(),
        run_enqueuer=lambda run_id: enqueued.append(run_id) or f"proofreading-{run_id}",
    )
    client = TestClient(app)

    # 1. Calling with explicit valid bodyVersionId -> queued + enqueued
    resp1 = client.post(
        "/api/v1/projects/proj_1/runs",
        json={"bodyVersionId": "ver_body_real_001"},
    )
    assert resp1.status_code == 202
    data1 = resp1.json()
    assert data1["status"] == "queued"
    assert data1["runId"].startswith("run_")
    assert rev_repo.runs[data1["runId"]]["status"] == "queued"
    assert rev_repo.runs[data1["runId"]]["body_version_id"] == "ver_body_real_001"
    assert enqueued == [data1["runId"]]

    # 2. Calling without bodyVersionId -> auto-resolves report_body for "1차"
    resp2 = client.post(
        "/api/v1/projects/proj_1/runs",
        json={"versionStage": "1차"},
    )
    assert resp2.status_code == 202
    data2 = resp2.json()
    assert data2["status"] == "queued"
    assert rev_repo.runs[data2["runId"]]["body_version_id"] == "ver_body_real_001"
    assert enqueued[-1] == data2["runId"]

    assert orch_calls == [], "proofreading must not run inside the request"
