from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import pypdf

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    PlateData,
    ReferenceData,
)
from app.domain.document_structure import CaptionData, ParsedPage, TextBlockData

ErrorCode = Literal[
    "input_error",
    "conversion_error",
    "api_error",
    "rate_limited",
]


@dataclass(frozen=True, slots=True)
class IngestContext:
    analysis_run_id: str
    document_version_id: str
    uri: str
    sha256: str
    mime_type: str
    kind: str = "report_body"
    project_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionMetadata:
    mime_type: str
    page_count: int | None
    text_extractable: bool


@dataclass(frozen=True, slots=True)
class CachedExtraction:
    document_version_id: str
    metadata: ExtractionMetadata


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    status: Literal["completed", "failed", "cancelled", "running"]
    error_code: ErrorCode | None = None
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class IngestResult:
    project_id: str
    version_id: str
    kind: str
    status: Literal["completed", "failed", "cancelled", "running"]
    pages_count: int = 0
    objects_count: int = 0
    references_count: int = 0
    plates_count: int = 0
    panels_count: int = 0
    drawings_count: int = 0
    regions_count: int = 0
    error_code: ErrorCode | str | None = None
    error_message: str | None = None
    retryable: bool = False


class InputError(ValueError):
    pass


class ConversionError(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


class RateLimitedError(ApiError):
    pass


class IngestRepository(Protocol):
    def claim_ingest(self, analysis_run_id: str) -> IngestContext | None: ...

    def analysis_status(self, analysis_run_id: str) -> str: ...

    def find_cached_extraction(
        self, sha256: str, excluding_version_id: str
    ) -> CachedExtraction | None: ...

    def complete_ingest(
        self,
        analysis_run_id: str,
        metadata: ExtractionMetadata,
        reused_from_version_id: str | None,
    ) -> bool: ...

    def fail_ingest(
        self, analysis_run_id: str, code: ErrorCode, retryable: bool
    ) -> bool: ...


class Extractor(Protocol):
    def extract(self, context: IngestContext) -> ExtractionMetadata: ...


def _outcome_for_existing_status(status: str) -> IngestOutcome:
    if status == "completed":
        return IngestOutcome(status="completed")
    if status == "cancelled":
        return IngestOutcome(status="cancelled")
    if status == "failed":
        return IngestOutcome(status="failed")
    return IngestOutcome(status="running")


def _normalize_error(error: Exception) -> tuple[ErrorCode, bool]:
    if isinstance(error, RateLimitedError):
        return "rate_limited", True
    if isinstance(error, ApiError):
        return "api_error", True
    if isinstance(error, InputError):
        return "input_error", False
    if isinstance(error, ConversionError):
        return "conversion_error", False
    return "api_error", True


def run_ingest_job(
    project_id: str,
    version_id: str,
    kind: str,
    file_path: str | Path,
    *,
    canonical_repo: Any | None = None,
    review_repo: Any | None = None,
    pdf_parser: Any | None = None,
    plate_parser: Any | None = None,
    drawing_parser: Any | None = None,
    object_resolver: Any | None = None,
    analysis_run_id: str | None = None,
    page_range: tuple[int, int] | None = None,
    render_dir: str | Path | None = None,
) -> IngestResult:
    """Kind-aware canonical graph construction during document ingestion.

    Parses uploaded document versions (report_body, plate_book, drawing_book),
    constructs all canonical graph nodes and relationships, and persists them into Neo4j
    with fail-closed error handling.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Document file not found at '{file_path}'")

    # Fail-closed validation for PDF readability
    is_pdf = path.suffix.lower() == ".pdf" or str(kind).endswith("pdf") or "pdf" in str(kind).lower()
    if is_pdf:
        try:
            reader = pypdf.PdfReader(str(path))
            _ = len(reader.pages)
        except Exception as error:
            if isinstance(error, (FileNotFoundError, InputError)):
                raise
            raise ConversionError(f"Corrupt or unreadable PDF '{file_path}': {error}") from error

    try:
        norm_kind = str(kind).strip().lower()

        if norm_kind in ("report_body", "report", "body"):
            from app.services.object_resolver import ObjectResolver
            from app.services.pdf_parser import PDFParser

            parser = pdf_parser or PDFParser()
            resolver = object_resolver or ObjectResolver()

            if page_range:
                pages: list[ParsedPage] = parser.parse_page_range(
                    path,
                    start_page=page_range[0],
                    end_page=page_range[1],
                    version_id=version_id,
                )
            else:
                pages = parser.parse_pdf(path, version_id=version_id)

            # Gate G: a real body file with zero parsed pages must fail
            # closed, not return a normal completed result.
            if not pages:
                if review_repo is not None and analysis_run_id is not None:
                    review_repo.save_analysis_run(
                        project_id=project_id,
                        run_id=analysis_run_id,
                        status="failed",
                        step="ingest",
                        error_code="ZERO_PAGES_PARSED",
                    )
                raise ValueError(
                    f"Body document '{version_id}' produced zero parsed pages"
                )

            if review_repo is not None and pages:
                review_repo.save_pages_and_blocks(version_id=version_id, pages=pages)

            all_references: list[ReferenceData] = []
            for p in pages:
                for b in p.text_blocks:
                    for ref in b.references:
                        all_references.append(ref)
                for c in p.captions:
                    for ref in c.references:
                        all_references.append(ref)

            if canonical_repo is not None and all_references:
                canonical_repo.save_references(all_references)

            all_blocks: list[TextBlockData] = [b for p in pages for b in p.text_blocks]
            all_captions: list[CaptionData] = [c for p in pages for c in p.captions]
            obj_results = resolver.resolve_mentions(
                blocks=all_blocks,
                captions=all_captions,
                project_id=project_id,
            )
            all_objects: list[ArchaeologyObjectData] = [r.object_data for r in obj_results]

            if canonical_repo is not None and all_objects:
                canonical_repo.save_archaeology_objects(all_objects)

            return IngestResult(
                project_id=project_id,
                version_id=version_id,
                kind=kind,
                status="completed",
                pages_count=len(pages),
                objects_count=len(all_objects),
                references_count=len(all_references),
            )

        elif norm_kind in ("plate_book", "plate", "plates"):
            from app.services.plate_parser import PlateIndex, PlateParser

            parser = plate_parser or PlateParser()
            if page_range:
                plates_list = parser.parse_page_range(
                    path,
                    start_page=page_range[0],
                    end_page=page_range[1],
                    document_version_id=version_id,
                    render_dir=render_dir,
                )
                pl_index = PlateIndex(
                    plates_by_number={p.number: p for p in plates_list},
                    plates=plates_list,
                )
            else:
                pl_index = parser.parse(
                    path,
                    document_version_id=version_id,
                    render_dir=render_dir,
                )

            all_plates: list[PlateData] = list(pl_index.plates)
            if canonical_repo is not None and all_plates:
                canonical_repo.save_plates(plates=all_plates)

            total_panels = sum(len(p.panels) for p in all_plates)
            return IngestResult(
                project_id=project_id,
                version_id=version_id,
                kind=kind,
                status="completed",
                plates_count=len(all_plates),
                panels_count=total_panels,
            )

        elif norm_kind in ("drawing_book", "drawing", "drawings"):
            from app.services.drawing_parser import DrawingIndex, DrawingParser

            parser = drawing_parser or DrawingParser()
            if page_range:
                drawings_list = parser.parse_page_range(
                    path,
                    start_page=page_range[0],
                    end_page=page_range[1],
                    document_version_id=version_id,
                )
                dr_index = DrawingIndex(
                    drawings_by_number={d.number: d for d in drawings_list},
                    drawings=drawings_list,
                )
            else:
                dr_index = parser.parse(path, document_version_id=version_id)

            all_drawings: list[DrawingData] = list(dr_index.drawings)
            if canonical_repo is not None and all_drawings:
                canonical_repo.save_drawings(drawings=all_drawings)

            total_regions = sum(len(d.regions) for d in all_drawings)
            return IngestResult(
                project_id=project_id,
                version_id=version_id,
                kind=kind,
                status="completed",
                drawings_count=len(all_drawings),
                regions_count=total_regions,
            )

        else:
            return IngestResult(
                project_id=project_id,
                version_id=version_id,
                kind=kind,
                status="completed",
            )

    except Exception as error:
        if review_repo is not None and analysis_run_id is not None:
            try:
                review_repo.save_analysis_run(
                    project_id=project_id,
                    run_id=analysis_run_id,
                    status="failed",
                    step="ingest",
                )
            except Exception:
                pass
        raise


def ingest_document(
    analysis_run_id: str,
    repository: IngestRepository,
    extractor: Extractor,
) -> IngestOutcome:
    """Claim and ingest one run while preserving terminal-state idempotency."""
    context = repository.claim_ingest(analysis_run_id)
    if context is None:
        return _outcome_for_existing_status(repository.analysis_status(analysis_run_id))

    try:
        cached = repository.find_cached_extraction(
            context.sha256,
            excluding_version_id=context.document_version_id,
        )
        if cached is None:
            metadata = extractor.extract(context)
            reused_from_version_id = None
        else:
            metadata = cached.metadata
            reused_from_version_id = cached.document_version_id

        completed = repository.complete_ingest(
            analysis_run_id,
            metadata,
            reused_from_version_id,
        )
        if not completed:
            return _outcome_for_existing_status(
                repository.analysis_status(analysis_run_id)
            )
        return IngestOutcome(status="completed")
    except Exception as error:  # noqa: BLE001 - normalize failures at job boundary
        code, retryable = _normalize_error(error)
        failed = repository.fail_ingest(analysis_run_id, code, retryable)
        if not failed:
            return _outcome_for_existing_status(
                repository.analysis_status(analysis_run_id)
            )
        return IngestOutcome(
            status="failed",
            error_code=code,
            retryable=retryable,
        )
