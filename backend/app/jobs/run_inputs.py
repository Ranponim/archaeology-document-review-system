"""Shared proofreading job-input resolution (plan Task 12).

Task 11 resolved body versions inside the sync HTTP route; Task 12 moves the
whole resolution onto the RQ worker. This module is the single shared
implementation so the worker (and any future caller) resolves one-format
inputs identically: real DocumentVersions from the graph, real stored PDFs,
real version-bound page ids — never fabricated stage-derived ids.
"""
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from app.config import DATA_ROOT
from app.domain.document_structure import ParsedPage
from app.domain.models import VersionInput
from app.graph.project_repository import DocumentVersionNotFoundError
from app.services.drawing_parser import DrawingIndex
from app.services.plate_parser import PlateIndex

BODY_STAGES = ("1차", "2차", "3차", "final")


def resolve_stored_pdf_path(version: VersionInput) -> Path | None:
    if not version.uri:
        return None
    candidate = DATA_ROOT / version.uri
    if candidate.is_file():
        return candidate
    if Path(version.uri).is_file():
        return Path(version.uri)
    return None


async def resolve_plate_index_for_run(
    canonical_repo,
    project_repo,
    plate_version_id: str | None,
    plate_pdf_path: str | None,
    plate_parser,
) -> PlateIndex:
    """Resolve the canonical PlateIndex for a selected plate version.

    Graph-first: reconstruct from (v)-[:HAS_PLATE]->(p:Plate) + HAS_PANEL.
    Fallback: reparse the stored PDF of the selected version. Fail closed
    (raise) when the version was explicitly selected but no canonical index
    resolves — never silently substitute an empty PlateIndex (anti-pattern #5).
    """
    if not plate_version_id:
        return PlateIndex()
    if canonical_repo is not None:
        index = canonical_repo.get_plate_index_for_version(plate_version_id)
        if index is not None and len(index) > 0:
            return index
    pdf_path = _resolve_asset_pdf_path(project_repo, plate_version_id, plate_pdf_path)
    if pdf_path is not None and plate_parser is not None:
        index = await run_in_threadpool(
            plate_parser.parse, pdf_path, document_version_id=plate_version_id
        )
        if len(index) > 0:
            return index
    raise ValueError(
        f"Selected plate version '{plate_version_id}' resolved to an empty "
        "canonical index (no HAS_PLATE graph data and no parseable stored PDF)"
    )


async def resolve_drawing_index_for_run(
    canonical_repo,
    project_repo,
    drawing_version_id: str | None,
    drawing_pdf_path: str | None,
    drawing_parser,
) -> DrawingIndex:
    """Resolve the canonical DrawingIndex for a selected drawing version.

    Graph-first: reconstruct from (v)-[:HAS_DRAWING]->(d:Drawing) + HAS_REGION.
    Fallback: reparse the stored PDF of the selected version. Fail closed
    (raise) when the version was explicitly selected but no canonical index
    resolves — never silently substitute an empty DrawingIndex (anti-pattern #5).
    """
    if not drawing_version_id:
        return DrawingIndex()
    if canonical_repo is not None:
        index = canonical_repo.get_drawing_index_for_version(drawing_version_id)
        if index is not None and len(index) > 0:
            return index
    pdf_path = _resolve_asset_pdf_path(project_repo, drawing_version_id, drawing_pdf_path)
    if pdf_path is not None and drawing_parser is not None:
        index = await run_in_threadpool(
            drawing_parser.parse, pdf_path, document_version_id=drawing_version_id
        )
        if len(index) > 0:
            return index
    raise ValueError(
        f"Selected drawing version '{drawing_version_id}' resolved to an empty "
        "canonical index (no HAS_DRAWING graph data and no parseable stored PDF)"
    )


def _resolve_asset_pdf_path(
    project_repo, version_id: str, request_pdf_path: str | None
) -> Path | None:
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
) -> tuple[dict[str, list[ParsedPage]], dict[str, str]]:
    """Resolve every report_body DocumentVersion by stage, parse its stored
    PDF with the real version id, and build version_pages/version_ids so
    PRECEDES + ALIGNED_TO persist on a real run (Task 8 M1 fold-in). Fail
    closed when a stored body PDF is missing (plan §3 Gate G)."""
    version_pages: dict[str, list[ParsedPage]] = {}
    version_ids: dict[str, str] = {}
    for stage in BODY_STAGES:
        if stage == primary_stage and primary_body_version is not None:
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
        if stage == primary_stage and primary_pdf_path:
            stage_pdf_path = Path(primary_pdf_path)
        else:
            stage_pdf_path = resolve_stored_pdf_path(stage_version)
        if stage_pdf_path is None or not stage_pdf_path.is_file():
            raise DocumentVersionNotFoundError(
                f"Stored PDF for body version '{stage_version.version_id}' "
                f"(stage '{stage}') not found for project '{project_id}'"
            )
        pages = await run_in_threadpool(
            pdf_parser.parse_pdf, stage_pdf_path, version_id=stage_version.version_id
        )
        if not pages:
            raise ValueError(
                f"Body version '{stage_version.version_id}' (stage '{stage}') "
                "produced zero parsed pages"
            )
        version_pages[stage] = pages
        version_ids[stage] = stage_version.version_id
    return version_pages, version_ids