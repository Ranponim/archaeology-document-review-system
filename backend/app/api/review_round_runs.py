from collections.abc import Callable
from typing import Annotated, Any
import uuid

from fastapi import APIRouter, Depends, Request, status
from starlette.concurrency import run_in_threadpool

from app.api.projects import (
    ProjectRepositoryPort,
    ServerOperationError,
    _run_repository,
    get_project_repository,
)
from app.api.review_run_contract import ReviewRoundRunTriggerRequest
from app.api.schemas import RunTriggerResponse
from app.graph.review_repository import ReviewRepository
from app.services.review_round_execution import resolve_review_round_inputs


router = APIRouter(prefix="/api/v1/projects", tags=["reviews"])


def get_review_repository(request: Request) -> Any:
    repo = getattr(request.app.state, "review_repository", None)
    if repo is None:
        driver = getattr(request.app.state, "neo4j_driver", None)
        if driver is not None:
            repo = ReviewRepository(driver)
            request.app.state.review_repository = repo
    return repo


def get_run_enqueuer(request: Request) -> Callable[[str], str]:
    return request.app.state.run_enqueuer


@router.post(
    "/{project_id}/runs",
    response_model=RunTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_review_round_run(
    project_id: str,
    payload: ReviewRoundRunTriggerRequest,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    review_repository: Annotated[Any, Depends(get_review_repository)],
    run_enqueuer: Annotated[Callable[[str], str], Depends(get_run_enqueuer)],
) -> RunTriggerResponse:
    """Queue one proofreading run from one graph-resident ReviewRound.

    The ReviewRound is the sole authority for the body, plate/photo and drawing
    DocumentVersions. The public production route deliberately accepts no
    direct version ids, server file paths or human stage labels.
    """
    warnings: list[str] = []
    review_round_id = payload.review_round_id

    if review_round_id:
        resolved = await _run_repository(
            resolve_review_round_inputs,
            project_repository,
            project_id,
            review_round_id,
        )
        body_version = resolved.body
        plate_version = resolved.plate
        drawing_version = resolved.drawing
        version_stage = resolved.compatibility_stage
        if payload.body_version_id or payload.plate_version_id or payload.drawing_version_id:
            warnings.append(
                "reviewRoundId is authoritative; direct body/plate/drawing version ids were ignored"
            )
    else:
        from app.api.reviews import _resolve_version_for_kind

        body_version = await _resolve_version_for_kind(
            project_repository,
            project_id,
            "report_body",
            payload.body_version_id,
            required=True,
        )
        plate_version = await _resolve_version_for_kind(
            project_repository,
            project_id,
            "plate_book",
            payload.plate_version_id,
            required=False,
        )
        drawing_version = await _resolve_version_for_kind(
            project_repository,
            project_id,
            "drawing_book",
            payload.drawing_version_id,
            required=False,
        )
        version_stage = payload.version_stage
        warnings.append(
            "legacy direct-version run path used; create/select a ReviewRound for canonical execution"
        )

    if review_repository is None:
        raise ServerOperationError("Review repository not configured")

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    await run_in_threadpool(
        review_repository.create_analysis_run,
        project_id=project_id,
        run_id=run_id,
        review_round_id=review_round_id,
        body_version_id=body_version.version_id,
        plate_version_id=(plate_version.version_id if plate_version is not None else None),
        drawing_version_id=(drawing_version.version_id if drawing_version is not None else None),
        body_pdf_path=payload.body_pdf_path,
        plate_pdf_path=payload.plate_pdf_path,
        drawing_pdf_path=payload.drawing_pdf_path,
        enable_vlm=payload.enable_vlm,
        enable_ai_review=payload.enable_ai_review,
        version_stage=version_stage,
    )

    try:
        await run_in_threadpool(run_enqueuer, run_id)
    except ValueError:
        raise
    except Exception:  # Redis/RQ internals stay private at the API boundary.
        try:
            await run_in_threadpool(
                review_repository.save_analysis_run,
                project_id=project_id,
                run_id=run_id,
                status="failed",
                step="analysis",
                error_code="queue_error",
                retryable=True,
            )
        except Exception:
            pass
        raise ServerOperationError from None

    return RunTriggerResponse(
        run_id=run_id,
        project_id=project_id,
        review_round_id=review_round_id,
        status="queued",
        warnings=warnings,
    )
