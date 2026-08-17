"""Shared proofreading job-input resolution.

ReviewRound runs compare the current body with its immediate predecessor via
ReviewRound PRECEDES. Legacy injected/direct-version workers retain the old
1차/2차/3차/final comparison behavior only for backward compatibility.
"""
from pathlib import Path
import re

from starlette.concurrency import run_in_threadpool

from app.config import DATA_ROOT
from app.domain.document_structure import ParsedPage
from app.domain.models import VersionInput
from app.graph.project_repository import DocumentVersionNotFoundError
from app.graph.review_project_repository import ReviewProjectRepository
from app.services.drawing_parser import DrawingIndex
from app.services.plate_parser import PlateIndex


_ROUND_STAGE_RE = re.compile(r"^(\d+)차$")
_LEGACY_BODY_STAGES = ("1차", "2차", "3차", "final")


def body_stages_for_round(primary_stage: str) -> tuple[str, ...]:
    """Legacy compatibility helper; ReviewRound execution must not call this."""
    match = _ROUND_STAGE_RE.match(str(primary_stage).strip())
    if not match:
        return (primary_stage,)
    sequence = int(match.group(1))
    if sequence <= 1:
        return ("1차",)
    return (f"{sequence - 1}차", f"{sequence}차")


def resolve_stored_pdf_path(version: VersionInput) -> Path | None:
    if not version.uri:
        return None
    candidate = DATA_ROOT / version.uri
    if candidate.is_file():
        return candidate
    if Path(version.uri).is_file():
        return Path(version.uri)
    return None


async def resolve_round_body_versions_for_alignment(
    *,
    project_repository,
    project_id: str,
    current_body: VersionInput,
    previous_body: VersionInput | None,
    current_pdf_path: str | None,
    pdf_parser,
) -> tuple[dict[str, list[ParsedPage]], dict[str, str]]:
    """Parse an explicit ReviewRound body pair without stage-based lookup.

    `previous_body` and `current_body` are already canonical VersionInputs
    resolved from ReviewRound relationships. Semantic keys are deliberately
    `previous`/`current`; they are labels for alignment only, never identity.
    """
    del project_repository  # explicit inputs are the authority; no lookup here
    version_pages: dict[str, list[ParsedPage]] = {}
    version_ids: dict[str, str] = {}

    versions: list[tuple[str, VersionInput | None]] = [
        ("previous", previous_body),
        ("current", current_body),
    ]
    for role, version in versions:
        if version is None:
            continue
        if role == "current" and current_pdf_path:
            pdf_path = Path(current_pdf_path)
        else:
            pdf_path = resolve_stored_pdf_path(version)
        if pdf_path is None or not pdf_path.is_file():
            raise DocumentVersionNotFoundError(
                f"Stored PDF for {role} body version '{version.version_id}' "
                f"not found for project '{project_id}'"
            )
        pages = await run_in_threadpool(
            pdf_parser.parse_pdf,
            pdf_path,
            version_id=version.version_id,
        )
        if not pages:
            raise ValueError(
                f"Body version '{version.version_id}' ({role}) produced zero parsed pages"
            )
        version_pages[role] = pages
        version_ids[role] = version.version_id

    if "current" not in version_ids:
        raise DocumentVersionNotFoundError(
            f"Current body version '{current_body.version_id}' was not resolved"
        )
    return version_pages, version_ids


async def resolve_plate_index_for_run(canonical_repo, project_repo, plate_version_id, plate_pdf_path, plate_parser) -> PlateIndex:
    if not plate_version_id:
        return PlateIndex()
    if canonical_repo is not None:
        index = canonical_repo.get_plate_index_for_version(plate_version_id)
        if index is not None and len(index) > 0:
            return index
    pdf_path = _resolve_asset_pdf_path(project_repo, plate_version_id, plate_pdf_path)
    if pdf_path is not None and plate_parser is not None:
        index = await run_in_threadpool(plate_parser.parse, pdf_path, document_version_id=plate_version_id)
        if len(index) > 0:
            return index
    raise ValueError(
        f"Selected plate version '{plate_version_id}' resolved to an empty canonical index "
        "(no HAS_PLATE graph data and no parseable stored PDF)"
    )


async def resolve_drawing_index_for_run(canonical_repo, project_repo, drawing_version_id, drawing_pdf_path, drawing_parser) -> DrawingIndex:
    if not drawing_version_id:
        return DrawingIndex()
    if canonical_repo is not None:
        index = canonical_repo.get_drawing_index_for_version(drawing_version_id)
        if index is not None and len(index) > 0:
            return index
    pdf_path = _resolve_asset_pdf_path(project_repo, drawing_version_id, drawing_pdf_path)
    if pdf_path is not None and drawing_parser is not None:
        index = await run_in_threadpool(drawing_parser.parse, pdf_path, document_version_id=drawing_version_id)
        if len(index) > 0:
            return index
    raise ValueError(
        f"Selected drawing version '{drawing_version_id}' resolved to an empty canonical index "
        "(no HAS_DRAWING graph data and no parseable stored PDF)"
    )


def _resolve_asset_pdf_path(project_repo, version_id: str, request_pdf_path: str | None) -> Path | None:
    if request_pdf_path:
        candidate = Path(request_pdf_path)
        if candidate.is_file():
            return candidate
    if project_repo is not None:
        version = project_repo.get_document_version_by_id(version_id)
        if version is not None:
            return resolve_stored_pdf_path(version)
    return None


async def resolve_body_versions_for_alignment(
    project_repository,
    project_id: str,
    primary_body_version: VersionInput,
    primary_stage: str,
    primary_pdf_path: str | None,
    pdf_parser,
    review_round_id: str | None = None,
) -> tuple[dict[str, list[ParsedPage]], dict[str, str]]:
    if review_round_id is not None:
        current_round = await run_in_threadpool(
            project_repository.get_review_round,
            project_id,
            review_round_id,
        )
        if current_round is None:
            raise DocumentVersionNotFoundError(
                f"ReviewRound '{review_round_id}' not found for project '{project_id}'"
            )
        previous_round = await run_in_threadpool(
            project_repository.get_previous_review_round,
            project_id,
            review_round_id,
        )
        previous_body: VersionInput | None = None
        if previous_round is not None and previous_round.body_version_id:
            previous_body = await run_in_threadpool(
                project_repository.resolve_version_input,
                project_id,
                "report_body",
                None,
                previous_round.body_version_id,
            )
            if previous_body is None:
                raise DocumentVersionNotFoundError(
                    f"Predecessor ReviewRound '{previous_round.id}' points to missing "
                    f"body version '{previous_round.body_version_id}'"
                )
        return await resolve_round_body_versions_for_alignment(
            project_repository=project_repository,
            project_id=project_id,
            current_body=primary_body_version,
            previous_body=previous_body,
            current_pdf_path=primary_pdf_path,
            pdf_parser=pdf_parser,
        )

    # Legacy queued jobs only: retain historical stage-based discovery.
    version_pages: dict[str, list[ParsedPage]] = {}
    version_ids: dict[str, str] = {}
    seen_version_ids: set[str] = set()
    stages = _LEGACY_BODY_STAGES

    for stage in stages:
        if stage == primary_stage:
            stage_version = primary_body_version
        else:
            stage_version = await run_in_threadpool(
                project_repository.resolve_version_input,
                project_id,
                "report_body",
                stage,
            )
        if stage_version is None:
            continue
        if stage_version.version_id in seen_version_ids:
            continue
        seen_version_ids.add(stage_version.version_id)

        if stage == primary_stage and primary_pdf_path:
            stage_pdf_path = Path(primary_pdf_path)
        else:
            stage_pdf_path = resolve_stored_pdf_path(stage_version)
        if stage_pdf_path is None or not stage_pdf_path.is_file():
            raise DocumentVersionNotFoundError(
                f"Stored PDF for body version '{stage_version.version_id}' "
                f"(legacy stage '{stage}') not found for project '{project_id}'"
            )
        pages = await run_in_threadpool(
            pdf_parser.parse_pdf, stage_pdf_path, version_id=stage_version.version_id
        )
        if not pages:
            raise ValueError(
                f"Body version '{stage_version.version_id}' (legacy stage '{stage}') produced zero parsed pages"
            )
        version_pages[stage] = pages
        version_ids[stage] = stage_version.version_id

    if primary_body_version.version_id not in seen_version_ids:
        raise DocumentVersionNotFoundError(
            f"Primary body version '{primary_body_version.version_id}' was not resolved for stage '{primary_stage}'"
        )
    return version_pages, version_ids