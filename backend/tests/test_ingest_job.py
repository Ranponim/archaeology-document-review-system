from dataclasses import dataclass

import pytest
from rq.exceptions import DuplicateJobError
from rq.job import validate_job_id

from pypdf import PdfWriter

from app.jobs.ingest import (
    ApiError,
    CachedExtraction,
    ConversionError,
    ExtractionMetadata,
    IngestContext,
    InputError,
    RateLimitedError,
    ingest_document,
)
from app.jobs.queue import enqueue_ingest
from app.jobs.worker import (
    LocalMetadataExtractor,
    RetryableIngestError,
    execute_ingest_job,
)


@dataclass
class RunState:
    id: str
    status: str = "queued"
    step: str = "ingest"
    error_code: str | None = None
    retryable: bool = False


class FakeIngestRepository:
    def __init__(self) -> None:
        self.run = RunState("run-1")
        self.context = IngestContext(
            analysis_run_id="run-1",
            document_version_id="version-1",
            uri="incoming/project/hash/a.pdf",
            sha256="a" * 64,
            mime_type="application/pdf",
        )
        self.cached: CachedExtraction | None = None
        self.saved_metadata: ExtractionMetadata | None = None
        self.reused_from: str | None = None

    def claim_ingest(self, analysis_run_id: str):
        assert analysis_run_id == self.run.id
        can_retry = self.run.status == "failed" and self.run.retryable
        if self.run.status != "queued" and not can_retry:
            return None
        self.run.status = "running"
        return self.context

    def analysis_status(self, analysis_run_id: str) -> str:
        assert analysis_run_id == self.run.id
        return self.run.status

    def find_cached_extraction(self, sha256: str, excluding_version_id: str):
        assert sha256 == self.context.sha256
        assert excluding_version_id == self.context.document_version_id
        return self.cached

    def complete_ingest(
        self,
        analysis_run_id: str,
        metadata: ExtractionMetadata,
        reused_from_version_id: str | None,
    ) -> bool:
        if self.run.status != "running":
            return False
        self.saved_metadata = metadata
        self.reused_from = reused_from_version_id
        self.run.status = "completed"
        return True

    def fail_ingest(self, analysis_run_id: str, code: str, retryable: bool) -> bool:
        if self.run.status != "running":
            return False
        self.run.status = "failed"
        self.run.error_code = code
        self.run.retryable = retryable
        return True


class FakeExtractor:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.calls = 0
        self.result = result or ExtractionMetadata(
            mime_type="application/pdf",
            page_count=12,
            text_extractable=True,
        )
        self.error = error

    def extract(self, context: IngestContext) -> ExtractionMetadata:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class CancellingExtractor(FakeExtractor):
    def __init__(self, repository: FakeIngestRepository) -> None:
        super().__init__()
        self.repository = repository

    def extract(self, context: IngestContext) -> ExtractionMetadata:
        result = super().extract(context)
        self.repository.run.status = "cancelled"
        return result


def test_ingest_job_marks_completed_and_is_idempotent():
    repository = FakeIngestRepository()
    extractor = FakeExtractor()

    first = ingest_document(repository.run.id, repository, extractor)
    second = ingest_document(repository.run.id, repository, extractor)

    assert first.status == "completed"
    assert second.status == "completed"
    assert repository.run.status == "completed"
    assert extractor.calls == 1
    assert repository.saved_metadata == ExtractionMetadata(
        mime_type="application/pdf",
        page_count=12,
        text_extractable=True,
    )


def test_cancelled_ingest_never_calls_extractor():
    repository = FakeIngestRepository()
    repository.run.status = "cancelled"
    extractor = FakeExtractor()

    outcome = ingest_document(repository.run.id, repository, extractor)

    assert outcome.status == "cancelled"
    assert extractor.calls == 0


def test_cancellation_during_extraction_cannot_be_overwritten_by_completion():
    repository = FakeIngestRepository()
    extractor = CancellingExtractor(repository)

    outcome = ingest_document(repository.run.id, repository, extractor)

    assert outcome.status == "cancelled"
    assert repository.run.status == "cancelled"


def test_ingest_reuses_completed_extraction_for_same_content_hash():
    repository = FakeIngestRepository()
    repository.cached = CachedExtraction(
        document_version_id="version-original",
        metadata=ExtractionMetadata(
            mime_type="application/pdf",
            page_count=27,
            text_extractable=False,
        ),
    )
    extractor = FakeExtractor()

    outcome = ingest_document(repository.run.id, repository, extractor)

    assert outcome.status == "completed"
    assert extractor.calls == 0
    assert repository.saved_metadata == repository.cached.metadata
    assert repository.reused_from == "version-original"


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (InputError("invalid source"), "input_error"),
        (ConversionError("private filename.pdf"), "conversion_error"),
    ],
)
def test_input_and_conversion_failures_are_normalized_and_not_retryable(
    error, expected_code
):
    repository = FakeIngestRepository()
    extractor = FakeExtractor(error=error)

    outcome = ingest_document(repository.run.id, repository, extractor)

    assert outcome.status == "failed"
    assert outcome.error_code == expected_code
    assert outcome.retryable is False
    assert repository.run.error_code == expected_code
    assert repository.run.retryable is False


def test_api_failure_is_normalized_and_marked_retryable():
    repository = FakeIngestRepository()
    extractor = FakeExtractor(error=ApiError("secret remote response"))

    outcome = ingest_document(repository.run.id, repository, extractor)

    assert outcome.status == "failed"
    assert outcome.error_code == "api_error"
    assert outcome.retryable is True
    assert repository.run.error_code == "api_error"
    assert repository.run.retryable is True


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (RateLimitedError("temporary"), "rate_limited"),
        (RuntimeError("unexpected infrastructure failure"), "api_error"),
    ],
)
def test_temporary_and_unknown_failures_are_safe_to_retry(error, expected_code):
    repository = FakeIngestRepository()
    extractor = FakeExtractor(error=error)

    outcome = ingest_document(repository.run.id, repository, extractor)

    assert outcome.status == "failed"
    assert outcome.error_code == expected_code
    assert outcome.retryable is True


def test_retryable_failure_can_be_claimed_again_and_completed():
    repository = FakeIngestRepository()
    extractor = FakeExtractor(error=ApiError("temporary"))

    first = ingest_document(repository.run.id, repository, extractor)
    extractor.error = None
    second = ingest_document(repository.run.id, repository, extractor)

    assert first.status == "failed"
    assert first.retryable is True
    assert second.status == "completed"
    assert extractor.calls == 2


def test_worker_entry_point_raises_after_persisting_a_retryable_failure():
    repository = FakeIngestRepository()
    extractor = FakeExtractor(error=ApiError("temporary"))

    with pytest.raises(RetryableIngestError):
        execute_ingest_job(repository.run.id, repository, extractor)

    assert repository.run.status == "failed"
    assert repository.run.error_code == "api_error"
    assert repository.run.retryable is True


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
        assert function_name == "app.jobs.worker.run_ingest_job"
        assert kwargs["job_id"] == f"ingest-{analysis_run_id}"
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


def test_enqueue_ingest_uses_a_stable_job_id_and_deduplicates():
    queue = FakeQueue()

    first = enqueue_ingest("run-1", queue=queue)
    second = enqueue_ingest("run-1", queue=queue)

    assert first == "ingest-run-1"
    assert second == first
    assert queue.enqueue_calls == 1
    validate_job_id(first)


def test_enqueue_ingest_recovers_when_another_request_wins_the_enqueue_race():
    queue = RacingQueue()

    job_id = enqueue_ingest("run-1", queue=queue)

    assert job_id == "ingest-run-1"


@pytest.mark.parametrize("invalid_id", ["", "  ", "run:1", "run/1"])
def test_enqueue_ingest_rejects_an_invalid_analysis_run_id(invalid_id):
    with pytest.raises(ValueError):
        enqueue_ingest(invalid_id, queue=FakeQueue())


def test_local_metadata_extractor_no_longer_invokes_legacy_review_pipeline(
    tmp_path, monkeypatch
):
    """The production ingest worker must not run the legacy ReviewPipeline:
    it persisted unscoped ``doc_ver_pN`` page ids and invented per-version
    ids that collide across projects (task-1-5 review Issue 3.4)."""
    pdf_path = tmp_path / "document.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    pipeline_calls = []

    class SpyReviewPipeline:
        def __init__(self, review_repo=None):
            pipeline_calls.append("constructed")

        def run_full_pipeline(self, project_id, version_files):
            pipeline_calls.append("run_full_pipeline")

    monkeypatch.setattr("app.jobs.review_pipeline.ReviewPipeline", SpyReviewPipeline)

    extractor = LocalMetadataExtractor(data_root=tmp_path)
    context = IngestContext(
        analysis_run_id="run-test",
        document_version_id="version-test",
        uri="document.pdf",
        sha256="b" * 64,
        mime_type="application/pdf",
    )

    metadata = extractor.extract(context)

    assert metadata.mime_type == "application/pdf"
    assert metadata.page_count == 1
    assert pipeline_calls == []


def test_local_metadata_extractor_skips_review_pipeline_for_non_pdf(tmp_path, monkeypatch):
    text_file = tmp_path / "notes.txt"
    text_file.write_text("hello world", encoding="utf-8")

    pipeline_calls = []

    class SpyReviewPipeline:
        def __init__(self, review_repo=None):
            pass

        def run_full_pipeline(self, project_id, version_files):
            pipeline_calls.append(project_id)

    monkeypatch.setattr("app.jobs.review_pipeline.ReviewPipeline", SpyReviewPipeline)

    extractor = LocalMetadataExtractor(data_root=tmp_path)
    context = IngestContext(
        analysis_run_id="run-test",
        document_version_id="version-test",
        uri="notes.txt",
        sha256="c" * 64,
        mime_type="text/plain",
    )

    metadata = extractor.extract(context)

    assert metadata.mime_type == "text/plain"
    assert metadata.page_count is None
    assert metadata.text_extractable is False
    assert len(pipeline_calls) == 0


def test_local_metadata_extractor_handles_review_pipeline_failure_gracefully(tmp_path, monkeypatch):
    pdf_path = tmp_path / "failing.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    class FailingReviewPipeline:
        def __init__(self, review_repo=None):
            pass

        def run_full_pipeline(self, project_id, version_files):
            raise RuntimeError("Pipeline crashed unexpectedly")

    monkeypatch.setattr("app.jobs.review_pipeline.ReviewPipeline", FailingReviewPipeline)

    extractor = LocalMetadataExtractor(data_root=tmp_path)
    context = IngestContext(
        analysis_run_id="run-test",
        document_version_id="version-test",
        uri="failing.pdf",
        sha256="d" * 64,
        mime_type="application/pdf",
    )

    # Should not raise an exception even if ReviewPipeline fails
    metadata = extractor.extract(context)

    assert metadata.mime_type == "application/pdf"
    assert metadata.page_count == 1

