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

    The ReviewRound is the sole authority for body, plate/photo, and drawing
    DocumentVersions. The public route has no direct-version, file-path, or
    stage fallback.
    """
    resolved = await _run_repository(
        resolve_review_round_inputs,
        project_repository,
        project_id,
        payload.review_round_id,
    )

    if review_repository is None:
        raise ServerOperationError("Review repository not configured")

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    await run_in_threadpool(
        review_repository.create_analysis_run,
        project_id=project_id,
        run_id=run_id,
        review_round_id=resolved.review_round.id,
        body_version_id=resolved.body.version_id,
        plate_version_id=(resolved.plate.version_id if resolved.plate is not None else None),
        drawing_version_id=(resolved.drawing.version_id if resolved.drawing is not None else None),
        body_pdf_path=None,
        plate_pdf_path=None,
        drawing_pdf_path=None,
        enable_vlm=payload.enable_vlm,
        enable_ai_review=payload.enable_ai_review,
        version_stage=resolved.compatibility_stage,
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
        review_round_id=resolved.review_round.id,
        status="queued",
        warnings=[],
    )
