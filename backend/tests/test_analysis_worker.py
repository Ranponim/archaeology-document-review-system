"""Task 12 tests: canonical proofreading executes on the RQ worker.

- ``enqueue_proofreading`` enqueues ``app.jobs.worker.run_analysis_worker``
  exactly once per run id (stable job id + dedupe), mirroring the ingest queue.
- ``_run_analysis_worker`` claims the queued run (concurrency-safe CAS: a
  second worker attempt on an already running/completed run does not
  re-execute), executes the canonical graph-first proofreading with
  version_pages/version_ids resolution, and records completed/failed with
  error_code + retryable semantics.
- ``run_analysis_worker`` (the RQ entry) raises RetryableAnalysisError only
  for retryable failures, mirroring execute_ingest_job.
"""
from dataclasses import dataclass, field
from typing import Any

import pytest
from rq.exceptions import DuplicateJobError
from rq.job import validate_job_id

from app.jobs.queue import enqueue_proofreading
from app.jobs.worker import (
    RetryableAnalysisError,
    _run_analysis_worker,
    run_analysis_worker,
)
from app.services.proofreading_orchestrator import OrchestratorResult


# ---------------------------------------------------------------------------
# Fake run repository (mirrors FakeIngestRepository conventions)
# ---------------------------------------------------------------------------


@dataclass
class AnalysisRunState:
    id: str
    status: str = "queued"
    step: str = "analysis"
    error_code: str | None = None
    retryable: bool = False


class FakeAnalysisRunRepository:
    def __init__(
        self,
        run_id: str = "run_abc123",
        *,
        body_version_id: str = "ver_body_01",
        project_id: str = "p1",
    ) -> None:
        self.run = AnalysisRunState(run_id)
        self.project_id = project_id
        self.body_version_id = body_version_id
        self.saved: list[dict[str, Any]] = []

    def _claim_context(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "body_version_id": self.body_version_id,
            "plate_version_id": None,
            "drawing_version_id": None,
            "body_pdf_path": None,
            "plate_pdf_path": None,
            "drawing_pdf_path": None,
            "enable_vlm": False,
            "enable_ai_review": False,
            "version_stage": "1차",
        }

    def claim_analysis(self, analysis_run_id: str):
        assert analysis_run_id == self.run.id
        can_retry = self.run.status == "failed" and self.run.retryable
        if self.run.status != "queued" and not can_retry:
            return None
        self.run.status = "running"
        return self._claim_context()

    def analysis_status(self, analysis_run_id: str) -> str:
        assert analysis_run_id == self.run.id
        return self.run.status

    def save_analysis_run(
        self,
        project_id: str,
        run_id: str,
        status: str = "pending",
        model: str | None = None,
        step: str | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.saved.append(
            {
                "project_id": project_id,
                "run_id": run_id,
                "status": status,
                "step": step,
                "error_code": error_code,
                "retryable": retryable,
            }
        )
        self.run.status = status
        self.run.step = step or self.run.step
        if error_code is not None:
            self.run.error_code = error_code
        if retryable is not None:
            self.run.retryable = retryable


class StubProjectRepository:
    """Returns a VersionInput for the claimed body version (no stored file:
    file resolution is stubbed at the version-input helper boundary)."""

    def __init__(self, body_version_id: str) -> None:
        self.body_version_id = body_version_id

    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ):
        if kind != "report_body":
            return None
        if version_id is not None and version_id != self.body_version_id:
            return None
        if stage not in (None, "1차"):
            return None
        from app.domain.models import VersionInput

        return VersionInput(
            version_id=self.body_version_id,
            document_id="doc_body_1",
            project_id=project_id,
            kind="report_body",
            stage="1차",
            uri=None,
            sha256="a" * 64,
            mime_type="application/pdf",
        )


class RecordingWorkerOrchestrator:
    """Duck-typed ProofreadingOrchestrator recording run_proofreading kwargs."""

    def __init__(self, review_repo, project_repo=None, run_error: Exception | None = None):
        self.review_repo = review_repo
        self.project_repo = project_repo
        self.pdf_parser = None
        self.run_error = run_error
        self.calls: list[dict[str, Any]] = []

    async def run_proofreading(self, **kwargs) -> OrchestratorResult:
        self.calls.append(kwargs)
        if self.run_error is not None:
            raise self.run_error
        self.review_repo.save_analysis_run(
            project_id=kwargs["project_id"],
            run_id=kwargs["analysis_run_id"],
            status="completed",
            step="proofreading",
        )
        return OrchestratorResult(
            project_id=kwargs["project_id"],
            analysis_run_id=kwargs["analysis_run_id"],
            status="completed",
            pages_parsed=1,
            objects_resolved=0,
            references_resolved=0,
            candidates=[],
            evidences=[],
            objects=[],
            plates=[],
            drawings=[],
            summary={},
            warnings=["stub warning surfaced from proofreading"],
        )


def _stub_version_resolution(monkeypatch):
    """Stub the shared version input resolution so worker unit tests avoid
    PDF parsing; the real resolution is exercised at assembly level."""
    from app.domain.document_structure import ParsedPage

    page = ParsedPage(
        page_id="ver_body_01_p1",
        physical_page=1,
        printed_page=1,
        header="",
        raw_text="stub",
        normalized_text="stub",
    )

    async def _stub(project_repository, project_id, primary_body_version, primary_stage, primary_pdf_path, pdf_parser):
        return {"1차": [page]}, {"1차": primary_body_version.version_id}

    monkeypatch.setattr(
        "app.jobs.worker.resolve_body_versions_for_alignment", _stub
    )


@pytest.fixture
def stub_version_resolution(monkeypatch):
    _stub_version_resolution(monkeypatch)


# ---------------------------------------------------------------------------
# Worker core: claim-conditional execution
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.anyio


async def test_analysis_worker_executes_queued_run_and_returns_completed(stub_version_resolution):
    repo = FakeAnalysisRunRepository()
    orch = RecordingWorkerOrchestrator(
        review_repo=repo,
        project_repo=StubProjectRepository(repo.body_version_id),
    )

    outcome = await _run_analysis_worker("run_abc123", orch)

    assert outcome["status"] == "completed"
    assert outcome["executed"] is True
    assert outcome["analysis_run_id"] == "run_abc123"
    assert outcome["candidates_count"] == 0
    assert repo.run.status == "completed"

    assert len(orch.calls) == 1
    call = orch.calls[0]
    assert call["analysis_run_id"] == "run_abc123"
    assert call["body_version_id"] == "ver_body_01"
    assert call["project_id"] == "p1"
    assert call["enable_vlm"] is False
    assert call["enable_ai_review"] is False
    assert call["version_pages"]["1차"]
    assert call["version_ids"] == {"1차": "ver_body_01"}


@pytest.mark.parametrize(
    "pre_status",
    ["running", "completed", "cancelled", "failed"],
)
async def test_analysis_worker_second_attempt_does_not_re_execute(
    pre_status, stub_version_resolution
):
    """The claim CAS protects the run: a second worker on an already
    running/completed/failed(non-retryable) run does not re-execute."""
    repo = FakeAnalysisRunRepository()
    repo.run.status = pre_status
    if pre_status == "failed":
        repo.run.retryable = False
    orch = RecordingWorkerOrchestrator(
        review_repo=repo,
        project_repo=StubProjectRepository(repo.body_version_id),
    )

    outcome = await _run_analysis_worker("run_abc123", orch)

    assert outcome["executed"] is False
    assert outcome["status"] == pre_status
    assert orch.calls == []


async def test_analysis_worker_retryable_failed_run_can_be_reclaimed(stub_version_resolution):
    """A failed+retryable run can be claimed again and completed (mirrors the
    ingest retry contract)."""
    repo = FakeAnalysisRunRepository()
    repo.run.status = "failed"
    repo.run.retryable = True
    orch = RecordingWorkerOrchestrator(
        review_repo=repo,
        project_repo=StubProjectRepository(repo.body_version_id),
    )

    outcome = await _run_analysis_worker("run_abc123", orch)

    assert outcome["executed"] is True
    assert outcome["status"] == "completed"
    assert len(orch.calls) == 1


async def test_analysis_worker_deterministic_failure_fails_closed_with_input_error(
    stub_version_resolution,
):
    repo = FakeAnalysisRunRepository()
    orch = RecordingWorkerOrchestrator(
        review_repo=repo,
        project_repo=StubProjectRepository(repo.body_version_id),
        run_error=ValueError("body produced zero parsed pages"),
    )

    outcome = await _run_analysis_worker("run_abc123", orch)

    assert outcome["status"] == "failed"
    assert outcome["executed"] is True
    assert outcome["error_code"] == "input_error"
    assert outcome["retryable"] is False
    assert repo.run.status == "failed"
    assert repo.run.error_code == "input_error"
    assert repo.run.retryable is False


async def test_analysis_worker_unknown_failure_marked_retryable_api_error_style(
    stub_version_resolution,
):
    repo = FakeAnalysisRunRepository()
    orch = RecordingWorkerOrchestrator(
        review_repo=repo,
        project_repo=StubProjectRepository(repo.body_version_id),
        run_error=RuntimeError("unexpected infrastructure failure"),
    )

    outcome = await _run_analysis_worker("run_abc123", orch)

    assert outcome["status"] == "failed"
    assert outcome["error_code"] == "analysis_error"
    assert outcome["retryable"] is True
    assert repo.run.status == "failed"
    assert repo.run.error_code == "analysis_error"
    assert repo.run.retryable is True


async def test_analysis_worker_preserves_specific_failure_already_recorded_by_orchestrator(
    stub_version_resolution,
):
    """The orchestrator already persists deterministic failures with specific
    error codes (Gate G: ZERO_PAGES_PARSED, BODY_PDF_NOT_PROVIDED, ...); the
    worker must never overwrite those with a generic code."""

    class FailingAfterRecordingOrchestrator(RecordingWorkerOrchestrator):
        async def run_proofreading(self, **kwargs):
            self.calls.append(kwargs)
            repo.save_analysis_run(
                project_id="p1",
                run_id="run_abc123",
                status="failed",
                step="ingest",
                error_code="ZERO_PAGES_PARSED",
            )
            raise ValueError("Body document produced zero parsed pages")

    repo = FakeAnalysisRunRepository()
    orch = FailingAfterRecordingOrchestrator(
        review_repo=repo,
        project_repo=StubProjectRepository(repo.body_version_id),
    )

    outcome = await _run_analysis_worker("run_abc123", orch)

    assert repo.run.status == "failed"
    assert repo.run.error_code == "ZERO_PAGES_PARSED"
    assert outcome["status"] == "failed"
    assert outcome["executed"] is True
    assert outcome["preserved"] is True


async def test_analysis_worker_fails_closed_when_claimed_run_has_no_body_version_id(
    stub_version_resolution,
):
    class _EmptyClaimRepo(FakeAnalysisRunRepository):
        def claim_analysis(self, analysis_run_id):
            self.run.status = "running"
            return {"project_id": "p1"}

    repo = _EmptyClaimRepo()
    orch = RecordingWorkerOrchestrator(review_repo=repo)

    outcome = await _run_analysis_worker("run_abc123", orch)

    assert outcome["status"] == "failed"
    assert outcome["error_code"] == "input_error"
    assert orch.calls == []


async def test_analysis_worker_surfaces_proofreading_warnings_in_outcome(
    stub_version_resolution,
):
    repo = FakeAnalysisRunRepository()
    orch = RecordingWorkerOrchestrator(
        review_repo=repo,
        project_repo=StubProjectRepository(repo.body_version_id),
    )

    outcome = await _run_analysis_worker("run_abc123", orch)

    assert outcome["warnings"] == ["stub warning surfaced from proofreading"]


# ---------------------------------------------------------------------------
# RQ entry point: run_analysis_worker raises RetryableAnalysisError only for
# retryable failures (mirror execute_ingest_job)
# ---------------------------------------------------------------------------


class _FakeDriver:
    def close(self) -> None:
        pass


def test_worker_entry_point_raises_after_persisting_a_retryable_failure(
    monkeypatch,
):
    repo = FakeAnalysisRunRepository()

    class _FailingOrchestrator(RecordingWorkerOrchestrator):
        async def run_proofreading(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError("unexpected infrastructure failure")

    _stub_version_resolution(monkeypatch)
    monkeypatch.setattr(
        "app.jobs.worker.create_driver", lambda: _FakeDriver()
    )
    monkeypatch.setattr(
        "app.jobs.worker.build_proofreading_orchestrator",
        lambda driver: _FailingOrchestrator(
            review_repo=repo,
            project_repo=StubProjectRepository(repo.body_version_id),
        ),
    )

    with pytest.raises(RetryableAnalysisError):
        run_analysis_worker("run_abc123")

    assert repo.run.status == "failed"
    assert repo.run.error_code == "analysis_error"
    assert repo.run.retryable is True


def test_worker_entry_point_returns_outcome_for_deterministic_failure(monkeypatch):
    repo = FakeAnalysisRunRepository()

    class _DeterministicOrchestrator(RecordingWorkerOrchestrator):
        async def run_proofreading(self, **kwargs):
            raise ValueError("body produced zero pages")

    _stub_version_resolution(monkeypatch)
    monkeypatch.setattr("app.jobs.worker.create_driver", lambda: _FakeDriver())
    monkeypatch.setattr(
        "app.jobs.worker.build_proofreading_orchestrator",
        lambda driver: _DeterministicOrchestrator(
            review_repo=repo,
            project_repo=StubProjectRepository(repo.body_version_id),
        ),
    )

    outcome = run_analysis_worker("run_abc123")

    assert outcome["status"] == "failed"
    assert outcome["error_code"] == "input_error"
    assert outcome["retryable"] is False


# ---------------------------------------------------------------------------
# Queue: enqueue_proofreading stable job id + dedupe
# ---------------------------------------------------------------------------


class FakeJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, FakeJob] = {}
        self.enqueue_calls = 0

    def fetch_job(self, job_id: str):
        return self.jobs.get(job_id)

    def enqueue(self, function_name: str, analysis_run_id: str, **kwargs):
        self.enqueue_calls += 1
        assert function_name == "app.jobs.worker.run_analysis_worker"
        assert kwargs["job_id"] == f"proofreading-{analysis_run_id}"
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

    def enqueue(self, function_name: str, analysis_run_id: str, **kwargs):
        job = FakeJob(kwargs["job_id"])
        self.jobs[job.id] = job
        raise DuplicateJobError(job.id)


def test_enqueue_proofreading_uses_a_stable_job_id_and_deduplicates():
    queue = FakeQueue()

    first = enqueue_proofreading("run-1", queue=queue)
    second = enqueue_proofreading("run-1", queue=queue)

    assert first == "proofreading-run-1"
    assert second == first
    assert queue.enqueue_calls == 1
    validate_job_id(first)


def test_enqueue_proofreading_recovers_when_another_request_wins_the_enqueue_race():
    queue = RacingQueue()

    job_id = enqueue_proofreading("run-1", queue=queue)

    assert job_id == "proofreading-run-1"


@pytest.mark.parametrize("invalid_id", ["", "  ", "run:1", "run/1"])
def test_enqueue_proofreading_rejects_an_invalid_analysis_run_id(invalid_id):
    with pytest.raises(ValueError):
        enqueue_proofreading(invalid_id, queue=FakeQueue())