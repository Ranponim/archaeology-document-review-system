import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.config import DATA_ROOT
from app.graph.canonical_repository import CanonicalRepository
from app.graph.client import create_driver
from app.graph.project_repository import DocumentVersionNotFoundError, ProjectRepository
from app.graph.review_repository import ReviewRepository
from app.jobs.ingest import (
    ConversionError,
    ExtractionMetadata,
    Extractor,
    IngestContext,
    IngestRepository,
    ingest_document,
    run_ingest_job as run_kind_ingest_job,
)
from app.jobs.run_inputs import resolve_body_versions_for_alignment
from app.services.orchestrator_factory import build_proofreading_orchestrator

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
            render_dir = None
            if "plate" in kind:
                render_dir = (
                    self._data_root
                    / "derived"
                    / "plate_renders"
                    / context.document_version_id
                )
            run_kind_ingest_job(
                project_id=proj_id,
                version_id=context.document_version_id,
                kind=kind,
                file_path=source,
                canonical_repo=self._canonical_repo,
                review_repo=self._review_repo,
                analysis_run_id=context.analysis_run_id,
                render_dir=render_dir,
            )
        except Exception as error:
            logger.error(
                "Canonical graph ingestion failed for document %s: %s",
                context.document_version_id,
                error,
            )
            raise ConversionError(
                f"Canonical graph ingestion failed: {error}"
            ) from error

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


class RetryableAnalysisError(RuntimeError):
    """Signals RQ to run its configured retry policy after state is persisted."""


def _normalize_analysis_failure(error: Exception) -> tuple[str, bool]:
    if isinstance(error, (DocumentVersionNotFoundError, FileNotFoundError, ValueError)):
        return "input_error", False
    return "analysis_error", True


def _record_analysis_failure(
    review_repo: ReviewRepository,
    project_id: str,
    analysis_run_id: str,
    error: Exception,
) -> dict:
    code, retryable = _normalize_analysis_failure(error)
    try:
        current = review_repo.analysis_status(analysis_run_id)
    except Exception:  # noqa: BLE001 - node may be absent; fail closed below
        current = None
    if current == "failed":
        return {
            "analysis_run_id": analysis_run_id,
            "project_id": project_id,
            "status": "failed",
            "executed": True,
            "error_code": None,
            "retryable": False,
            "preserved": True,
        }
    review_repo.save_analysis_run(
        project_id=project_id,
        run_id=analysis_run_id,
        status="failed",
        step="proofreading",
        error_code=code,
        retryable=retryable,
    )
    return {
        "analysis_run_id": analysis_run_id,
        "project_id": project_id,
        "status": "failed",
        "executed": True,
        "error_code": code,
        "retryable": retryable,
        "preserved": False,
    }


async def _run_analysis_worker(analysis_run_id: str, orchestrator: Any) -> dict:
    """Claim-execute payload of the canonical proofreading worker.

    Claims the queued AnalysisRun first (status CAS: queued -> running; only
    one worker wins). Resolution of version inputs + version_pages/version_ids
    shares the Task 11 helper. The orchestrator itself persists
    completed/failed statuses via save_analysis_run; this function only
    records a generic failure when the orchestrator did not already fail the
    run with a more specific error_code.
    """
    review_repo = getattr(orchestrator, "review_repo", None)
    if review_repo is None:
        raise RuntimeError(
            "analysis worker requires an orchestrator with a review repository"
        )
    claim = review_repo.claim_analysis(analysis_run_id)
    if claim is None:
        return {
            "analysis_run_id": analysis_run_id,
            "status": review_repo.analysis_status(analysis_run_id),
            "executed": False,
        }

    project_id = claim.get("project_id")
    body_version_id = claim.get("body_version_id")
    try:
        if not body_version_id:
            raise ValueError("Queued AnalysisRun has no bodyVersionId")
        version_stage = claim.get("version_stage") or "1차"
        project_repo = getattr(orchestrator, "project_repo", None)
        primary_version = None
        if project_repo is not None:
            primary_version = project_repo.resolve_version_input(
                project_id, "report_body", version_stage, body_version_id
            )
        if primary_version is None:
            raise DocumentVersionNotFoundError(
                f"DocumentVersion '{body_version_id}' not found for project '{project_id}'"
            )
        version_pages, version_ids = await resolve_body_versions_for_alignment(
            project_repository=project_repo,
            project_id=project_id,
            primary_body_version=primary_version,
            primary_stage=version_stage,
            primary_pdf_path=claim.get("body_pdf_path"),
            pdf_parser=getattr(orchestrator, "pdf_parser", None),
        )
        result = await orchestrator.run_proofreading(
            project_id=project_id,
            body_version_id=body_version_id,
            plate_version_id=claim.get("plate_version_id"),
            drawing_version_id=claim.get("drawing_version_id"),
            body_pdf_path=claim.get("body_pdf_path"),
            plate_pdf_path=claim.get("plate_pdf_path"),
            drawing_pdf_path=claim.get("drawing_pdf_path"),
            enable_vlm=claim.get("enable_vlm", True),
            enable_ai_review=claim.get("enable_ai_review", True),
            version_stage=version_stage,
            analysis_run_id=analysis_run_id,
            version_pages=version_pages,
            version_ids=version_ids,
        )
    except Exception as error:  # noqa: BLE001 - job boundary; normalize
        return _record_analysis_failure(review_repo, project_id, analysis_run_id, error)

    return {
        "analysis_run_id": analysis_run_id,
        "project_id": project_id,
        "status": result.status,
        "executed": True,
        "pages_parsed": result.pages_parsed,
        "objects_resolved": result.objects_resolved,
        "references_resolved": result.references_resolved,
        "candidates_count": len(result.candidates),
        "errors": list(result.errors),
        "warnings": list(result.warnings),
    }


def run_analysis_worker(analysis_run_id: str) -> dict:
    """RQ entry point for canonical proofreading.

    The worker uses the same complete factory assembly as the app (anti-pattern
    #14) and raises RetryableAnalysisError for retryable failures so RQ's
    configured retry policy re-executes the job after state is persisted.
    """
    driver = create_driver()
    try:
        outcome = asyncio.run(
            _run_analysis_worker(
                analysis_run_id, build_proofreading_orchestrator(driver)
            )
        )
    finally:
        driver.close()
    if outcome.get("status") == "failed" and outcome.get("retryable"):
        raise RetryableAnalysisError(outcome.get("error_code") or "analysis_error")
    return outcome
