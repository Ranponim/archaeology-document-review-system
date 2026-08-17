"""Visual asset delivery routes (review §10 / Phase P0-D).

Render routes serve actual image bytes keyed by graph node id; metadata routes
return the JSON contract with a relative `imageUrl` pointing at the render
route — never a server filesystem path (anti-pattern #15). A node with no
render/asset fails closed with 404 / evidence_incomplete.
"""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from app.api.schemas import VisualAssetMetadata
from app.graph.asset_repository import AssetRepository
from app.services.visual_asset_service import (
    VisualAssetIncompleteError,
    VisualAssetNotFoundError,
    VisualAssetService,
)

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])


def get_visual_asset_service(request: Request) -> VisualAssetService:
    svc = getattr(request.app.state, "visual_asset_service", None)
    if svc is None:
        repo = getattr(request.app.state, "asset_repository", None)
        if repo is None:
            driver = getattr(request.app.state, "neo4j_driver", None)
            repo = AssetRepository(driver)
        svc = VisualAssetService(asset_repo=repo)
        request.app.state.visual_asset_service = svc
    return svc


def _render_response(data: dict) -> Response:
    return Response(content=data["bytes"], media_type=data["content_type"])


# ---------------------------------------------------------------------------
# Body pages
# ---------------------------------------------------------------------------


@router.get("/pages/{page_id}/render")
async def render_page(
    page_id: str,
    service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> Response:
    data = await run_in_threadpool(service.get_page_render, page_id)
    return _render_response(data)


@router.get("/pages/{page_id}/metadata", response_model=VisualAssetMetadata)
async def page_metadata(
    page_id: str,
    service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> Any:
    return await run_in_threadpool(service.get_page_metadata, page_id)


# ---------------------------------------------------------------------------
# Plates
# ---------------------------------------------------------------------------


@router.get("/plates/{plate_id}/render")
async def render_plate(
    plate_id: str,
    service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> Response:
    data = await run_in_threadpool(service.get_plate_render, plate_id)
    return _render_response(data)


@router.get("/plates/{plate_id}/metadata", response_model=VisualAssetMetadata)
async def plate_metadata(
    plate_id: str,
    service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> Any:
    return await run_in_threadpool(service.get_plate_metadata, plate_id)


# ---------------------------------------------------------------------------
# Plate panels
# ---------------------------------------------------------------------------


@router.get("/plate-panels/{panel_id}/render")
async def render_plate_panel(
    panel_id: str,
    service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> Response:
    data = await run_in_threadpool(service.get_plate_panel_render, panel_id)
    return _render_response(data)


@router.get("/plate-panels/{panel_id}/metadata", response_model=VisualAssetMetadata)
async def plate_panel_metadata(
    panel_id: str,
    service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> Any:
    return await run_in_threadpool(service.get_plate_panel_metadata, panel_id)


# ---------------------------------------------------------------------------
# Drawings
# ---------------------------------------------------------------------------


@router.get("/drawings/{drawing_id}/render")
async def render_drawing(
    drawing_id: str,
    service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> Response:
    data = await run_in_threadpool(service.get_drawing_render, drawing_id)
    return _render_response(data)


@router.get("/drawings/{drawing_id}/metadata", response_model=VisualAssetMetadata)
async def drawing_metadata(
    drawing_id: str,
    service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> Any:
    return await run_in_threadpool(service.get_drawing_metadata, drawing_id)


# ---------------------------------------------------------------------------
# Drawing regions
# ---------------------------------------------------------------------------


@router.get("/drawing-regions/{region_id}/render")
async def render_drawing_region(
    region_id: str,
    service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> Response:
    data = await run_in_threadpool(service.get_drawing_region_render, region_id)
    return _render_response(data)


@router.get("/drawing-regions/{region_id}/metadata", response_model=VisualAssetMetadata)
async def drawing_region_metadata(
    region_id: str,
    service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> Any:
    return await run_in_threadpool(service.get_drawing_region_metadata, region_id)
