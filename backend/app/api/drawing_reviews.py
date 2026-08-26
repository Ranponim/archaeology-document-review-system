from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from starlette.concurrency import run_in_threadpool

from app.api.drawing_review_contract import (
    DrawingReviewCaseResponse,
    DrawingReviewResolveRequest,
    DrawingReviewResolveResponse,
)
from app.api.projects import (
    ProjectRepositoryPort,
    ServerOperationError,
    _run_repository,
    get_project_repository,
)
from app.graph.drawing_evidence_repository_v3 import DrawingEvidenceRepositoryV3


router = APIRouter(prefix="/api/v1/projects", tags=["drawing-reviews"])


def get_drawing_evidence_repository(request: Request) -> Any:
    repo = getattr(request.app.state, "drawing_evidence_repository", None)
    if repo is None:
        driver = getattr(request.app.state, "neo4j_driver", None)
        if driver is not None:
            repo = DrawingEvidenceRepositoryV3(driver)
            request.app.state.drawing_evidence_repository = repo
    return repo


@router.get(
    "/{project_id}/drawing-reviews",
    response_model=list[DrawingReviewCaseResponse],
    status_code=status.HTTP_200_OK,
)
async def list_drawing_reviews(
    project_id: str,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    drawing_repository: Annotated[Any, Depends(get_drawing_evidence_repository)],
) -> list[DrawingReviewCaseResponse]:
    await _run_repository(project_repository.get_project, project_id)
    if drawing_repository is None:
        raise ServerOperationError("Drawing evidence repository not configured")
    rows = await run_in_threadpool(
        drawing_repository.list_v3_review_cases,
        project_id,
    )
    return [DrawingReviewCaseResponse.model_validate(row) for row in rows]


@router.post(
    "/{project_id}/drawing-reviews/{source_asset_id}/resolve",
    response_model=DrawingReviewResolveResponse,
    status_code=status.HTTP_200_OK,
)
async def resolve_drawing_review(
    project_id: str,
    source_asset_id: str,
    payload: DrawingReviewResolveRequest,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    drawing_repository: Annotated[Any, Depends(get_drawing_evidence_repository)],
) -> DrawingReviewResolveResponse:
    await _run_repository(project_repository.get_project, project_id)
    if drawing_repository is None:
        raise ServerOperationError("Drawing evidence repository not configured")
    row = await run_in_threadpool(
        drawing_repository.resolve_v3_review,
        project_id,
        source_asset_id,
        payload.action,
        payload.candidate_id,
        payload.reviewer,
    )
    return DrawingReviewResolveResponse.model_validate(row)
