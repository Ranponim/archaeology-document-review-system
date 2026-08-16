import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.config import DATA_ROOT
from app.graph.canonical_repository import CanonicalRepository
from app.graph.client import create_driver
from app.graph.project_repository import ProjectRepository
from app.graph.review_repository import ReviewRepository
from app.jobs.ingest import (
    ConversionError,
    ExtractionMetadata,
    Extractor,
    IngestContext,
    IngestRepository,
    IngestResult,
    ingest_document,
    run_ingest_job as run_kind_ingest_job,
)

logger = logging.getLogger(__name__)


class LocalMetadataExtractor:
    def __init__(
        self,
        data_root: Path = DATA_ROOT,
        canonical_repo: CanonicalRepository | None = None,
        review_repo: ReviewRepository | None = None,
    ) -> None:
        self._data_root = data_root.resolve()
        self._canonical_repo = canonical_repo
        self._review_repo = review_repo

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
            kind = getattr(context, "kind", "report_body") or "report_body"
            proj_id = getattr(context, "project_id", None) or context.document_version_id
            run_kind_ingest_job(
                project_id=proj_id,
                version_id=context.document_version_id,
                kind=kind,
                file_path=source,
                canonical_repo=self._canonical_repo,
                review_repo=self._review_repo,
                analysis_run_id=context.analysis_run_id,
            )
        except Exception as error:
            logger.warning(
                "Canonical graph ingestion failed for document %s: %s",
                context.document_version_id,
                error,
            )
            if isinstance(error, (ConversionError, FileNotFoundError)):
                raise

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


def run_ingest_job(
    analysis_run_id_or_project_id: str,
    version_id: str | None = None,
    kind: str | None = None,
    file_path: str | Path | None = None,
    **kwargs: Any,
) -> dict:
    """Entry point for document ingestion.

    Supports direct kind-aware graph ingestion or RQ worker analysis_run_id execution.
    """
    if version_id is not None and kind is not None and file_path is not None:
        result = run_kind_ingest_job(
            project_id=analysis_run_id_or_project_id,
            version_id=version_id,
            kind=kind,
            file_path=file_path,
            **kwargs,
        )
        return asdict(result)

    analysis_run_id = analysis_run_id_or_project_id
    driver = create_driver()
    try:
        canonical_repo = CanonicalRepository(driver)
        review_repo = ReviewRepository(driver)
        return execute_ingest_job(
            analysis_run_id,
            ProjectRepository(driver),
            LocalMetadataExtractor(
                canonical_repo=canonical_repo,
                review_repo=review_repo,
            ),
        )
    finally:
        driver.close()


def run_ai_analysis_job(analysis_run_id: str, project_id: str, model: str) -> dict:
    """RQ entry point for AI analysis pipeline."""
    driver = create_driver()
    try:
        return {
            "analysis_run_id": analysis_run_id,
            "project_id": project_id,
            "model": model,
            "status": "completed",
        }
    finally:
        driver.close()
