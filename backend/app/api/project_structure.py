from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api.project_structure_contract import (
    ProjectStructureChildrenResponse,
    ProjectStructureNode,
    ProjectStructureNodeType,
    ProjectStructureRootResponse,
)
from app.graph.project_structure_repository import ProjectStructureRepository
from app.services.project_structure_service import (
    ProjectStructureService,
    StructureNodeNotFoundError,
)


router = APIRouter(prefix="/api/projects", tags=["project-structure"])


def get_project_structure_service(request: Request) -> ProjectStructureService:
    service = getattr(request.app.state, "project_structure_service", None)
    if service is not None:
        return service
    driver = getattr(request.app.state, "neo4j_driver", None)
    if driver is None:
        raise HTTPException(status_code=503, detail="project_structure_unavailable")
    service = ProjectStructureService(
        ProjectStructureRepository(driver), request.app.state.file_store
    )
    request.app.state.project_structure_service = service
    return service


@router.get("/{project_id}/structure", response_model=ProjectStructureRootResponse)
async def get_project_structure(
    project_id: str,
    service: Annotated[ProjectStructureService, Depends(get_project_structure_service)],
) -> ProjectStructureRootResponse:
    return await run_in_threadpool(service.get_root, project_id)


@router.get(
    "/{project_id}/structure/nodes/{node_type}/{node_id}/children",
    response_model=ProjectStructureChildrenResponse,
)
async def get_project_structure_children(
    project_id: str,
    node_type: ProjectStructureNodeType,
    node_id: str,
    service: Annotated[ProjectStructureService, Depends(get_project_structure_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ProjectStructureChildrenResponse:
    try:
        return await run_in_threadpool(
            service.get_children, project_id, node_type, node_id, offset, limit
        )
    except StructureNodeNotFoundError:
        raise HTTPException(status_code=404, detail="structure_node_not_found") from None


@router.get(
    "/{project_id}/structure/nodes/{node_type}/{node_id}",
    response_model=ProjectStructureNode,
)
async def get_project_structure_node(
    project_id: str,
    node_type: ProjectStructureNodeType,
    node_id: str,
    service: Annotated[ProjectStructureService, Depends(get_project_structure_service)],
) -> ProjectStructureNode:
    try:
        return await run_in_threadpool(service.get_node, project_id, node_type, node_id)
    except StructureNodeNotFoundError:
        raise HTTPException(status_code=404, detail="structure_node_not_found") from None
