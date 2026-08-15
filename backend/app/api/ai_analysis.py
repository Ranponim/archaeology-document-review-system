import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Request, status
from app.api.projects import ProjectRepositoryPort, get_project_repository, _run_repository
from app.api.schemas import (
    AIAnalyzeRequest,
    AIAnalyzeResponse,
    CandidateListResponse,
    CandidateResponse,
)

router = APIRouter(prefix="/api/projects", tags=["ai_analysis"])


@router.post(
    "/{project_id}/analyze",
    response_model=AIAnalyzeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_ai_analysis(
    project_id: str,
    payload: AIAnalyzeRequest,
    repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> AIAnalyzeResponse:
    # Ensure project exists
    await _run_repository(repository.get_project, project_id)

    run_id = f"run_{uuid.uuid4().hex[:12]}"
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

    # Return candidates list
    return CandidateListResponse(
        project_id=project_id,
        total=0,
        candidates=[],
    )
