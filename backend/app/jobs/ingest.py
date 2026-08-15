from dataclasses import dataclass
from typing import Literal, Protocol

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
