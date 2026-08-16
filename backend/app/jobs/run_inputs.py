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