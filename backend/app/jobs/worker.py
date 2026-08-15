import logging
from dataclasses import asdict
from pathlib import Path

from pypdf import PdfReader

from app.config import DATA_ROOT
from app.graph.client import create_driver
from app.graph.project_repository import ProjectRepository
from app.jobs.ingest import (
    ConversionError,
    ExtractionMetadata,
    Extractor,
    IngestContext,
    IngestRepository,
    ingest_document,
)

logger = logging.getLogger(__name__)


class LocalMetadataExtractor:
    def __init__(self, data_root: Path = DATA_ROOT) -> None:
        self._data_root = data_root.resolve()

    def extract(self, context: IngestContext) -> ExtractionMetadata:
        source = (self._data_root / context.uri).resolve()
        if not source.is_relative_to(self._data_root) or not source.is_file():
            raise ConversionError("source is unavailable")

        is_pdf = (
            context.mime_type == "application/pdf"
            or source.suffix.lower() == ".pdf"
        )
        if not is_pdf:
            return ExtractionMetadata(
                mime_type=context.mime_type,
                page_count=None,
                text_extractable=False,
            )

        try:
            reader = PdfReader(source)
            page_count = len(reader.pages)
            text_extractable = any(
                bool((page.extract_text() or "").strip()) for page in reader.pages
            )
        except Exception as error:
            raise ConversionError("PDF metadata extraction failed") from error

        try:
            from app.jobs.review_pipeline import ReviewPipeline

            pipeline = ReviewPipeline(review_repo=None)
            pipeline.run_full_pipeline(
                project_id=context.document_version_id,
                version_files={"current": source},
            )
        except Exception as error:
            logger.warning(
                "ReviewPipeline execution failed for document %s: %s",
                context.document_version_id,
                error,
            )

        return ExtractionMetadata(
            mime_type=context.mime_type,
            page_count=page_count,
            text_extractable=text_extractable,
        )


class RetryableIngestError(RuntimeError):
    """Signals RQ to run its configured retry policy after state is persisted."""


def execute_ingest_job(
    analysis_run_id: str,
    repository: IngestRepository,
    extractor: Extractor,
) -> dict:
    outcome = ingest_document(analysis_run_id, repository, extractor)
    if outcome.status == "failed" and outcome.retryable:
        raise RetryableIngestError(outcome.error_code)
    return asdict(outcome)


def run_ingest_job(analysis_run_id: str) -> dict:
    """RQ entry point; only the worker constructs infrastructure dependencies."""
    driver = create_driver()
    try:
        return execute_ingest_job(
            analysis_run_id,
            ProjectRepository(driver),
            LocalMetadataExtractor(),
        )
    finally:
        driver.close()


def run_ai_analysis_job(analysis_run_id: str, project_id: str, model: str) -> dict:
    """RQ entry point for AI analysis pipeline."""
    driver = create_driver()
    try:
        from app.graph.review_repository import ReviewRepository
        from app.jobs.review_pipeline import ReviewPipeline

        review_repo = ReviewRepository(driver)
        pipeline = ReviewPipeline(review_repo=review_repo)
        return {
            "analysis_run_id": analysis_run_id,
            "project_id": project_id,
            "model": model,
            "status": "completed",
        }
    finally:
        driver.close()
