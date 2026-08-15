import uuid
from collections.abc import Callable
from typing import Annotated
from fastapi import APIRouter, Depends, Request, status
from starlette.concurrency import run_in_threadpool

from app.api.projects import (
    ProjectRepositoryPort,
    ServerOperationError,
    _run_repository,
    get_project_repository,
)
from app.api.schemas import (
    AIAnalyzeRequest,
    AIAnalyzeResponse,
    CandidateListResponse,
    CandidateResponse,
)
from app.jobs.queue import enqueue_ai_analysis

router = APIRouter(prefix="/api/projects", tags=["ai_analysis"])


def get_ai_enqueuer(request: Request) -> Callable[[str, str, str], str]:
    return request.app.state.ai_enqueuer


@router.post(
    "/{project_id}/analyze",
    response_model=AIAnalyzeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_ai_analysis(
    project_id: str,
    payload: AIAnalyzeRequest,
    repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    ai_enqueuer: Annotated[Callable[[str, str, str], str], Depends(get_ai_enqueuer)],
) -> AIAnalyzeResponse:
    # Ensure project exists
    await _run_repository(repository.get_project, project_id)

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        await run_in_threadpool(ai_enqueuer, run_id, project_id, payload.model)
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - sanitize queue error
        raise ServerOperationError from None

    return AIAnalyzeResponse(
        analysis_run_id=run_id,
        status="queued",
        model=payload.model,
    )


@router.get(
    "/{project_id}/candidates",
    response_model=CandidateListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_candidates(
    project_id: str,
    repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> CandidateListResponse:
    # Ensure project exists
    await _run_repository(repository.get_project, project_id)

    # TODO: Query Neo4j ReviewRepository once candidates are persisted.
    return CandidateListResponse(
        project_id=project_id,
        total=0,
        candidates=[],
    )
