from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from starlette.concurrency import run_in_threadpool

from app.api.projects import ProjectRepositoryPort, _run_repository, get_project_repository
from app.graph.project_repository import AnalysisRunNotFoundError


router = APIRouter(prefix="/api/v1/projects", tags=["runs"])


def get_review_repository(request: Request) -> Any:
    return getattr(request.app.state, "review_repository", None)


@router.get(
    "/{project_id}/runs/{run_id}",
    status_code=status.HTTP_200_OK,
)
async def get_analysis_run_detail(
    project_id: str,
    run_id: str,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    review_repository: Annotated[Any, Depends(get_review_repository)],
) -> dict[str, Any]:
    await _run_repository(project_repository.get_project, project_id)
    if review_repository is None or not hasattr(review_repository, "get_analysis_run"):
        raise AnalysisRunNotFoundError(run_id)
    run = await run_in_threadpool(
        review_repository.get_analysis_run,
        project_id,
        run_id,
    )
    if not run:
        raise AnalysisRunNotFoundError(run_id)
    return run
