from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.projects import AnalysisRunRetryConflict, ServerOperationError
from app.api.projects import router as projects_router
from app.api.assets import router as assets_router
from app.api.reviews import CandidateNotFoundError
from app.api.reviews import router as reviews_router
from app.graph.audited_review_repository import AuditedReviewRepository
from app.graph.client import create_driver
from app.graph.project_repository import (
    AnalysisRunNotFoundError,
    DocumentVersionNotFoundError,
    ProjectNotFoundError,
    ReviewRoundNotFoundError,
)
from app.graph.review_project_repository import ReviewProjectRepository
from app.graph.schema import ensure_schema
from app.jobs.queue import enqueue_ingest, enqueue_proofreading
from app.services.file_store import FileStore
from app.services.orchestrator_factory import build_proofreading_orchestrator
from app.services.visual_asset_service import (
    VisualAssetIncompleteError,
    VisualAssetNotFoundError,
)


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id is None:
        request_id = str(uuid4())
        request.state.request_id = request_id
    return request_id


def _error_response(request: Request, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": "input_error", "request_id": _request_id(request)},
    )


def _server_error_response(request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"code": "server_error", "request_id": _request_id(request)},
    )


def create_app(
    *,
    file_store: FileStore | None = None,
    project_repository=None,
    review_repository=None,
    orchestrator=None,
    ingest_enqueuer=None,
    run_enqueuer=None,
    static_dir: Path | None = None,
    asset_repository=None,
    visual_asset_service=None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.project_repository is None:
            driver = create_driver()
            app.state.neo4j_driver = driver
            app.state.project_repository = ReviewProjectRepository(driver)
            ensure_schema(driver)
        if getattr(app.state, "review_repository", None) is None:
            driver = getattr(app.state, "neo4j_driver", None)
            if driver is not None:
                app.state.review_repository = AuditedReviewRepository(driver)
        if getattr(app.state, "orchestrator", None) is None:
            driver = getattr(app.state, "neo4j_driver", None)
            if driver is not None:
                app.state.orchestrator = build_proofreading_orchestrator(driver)
        yield
        driver = getattr(app.state, "neo4j_driver", None)
        if driver is not None:
            driver.close()

    application = FastAPI(lifespan=lifespan)
    application.state.file_store = file_store if file_store is not None else FileStore()
    application.state.project_repository = project_repository
    application.state.review_repository = review_repository
    application.state.orchestrator = orchestrator
    application.state.ingest_enqueuer = ingest_enqueuer or enqueue_ingest
    application.state.run_enqueuer = run_enqueuer or enqueue_proofreading
    application.state.asset_repository = asset_repository
    application.state.visual_asset_service = visual_asset_service

    @application.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _error: RequestValidationError):
        return _error_response(request, 422)

    @application.exception_handler(ProjectNotFoundError)
    async def missing_project(request: Request, _error: ProjectNotFoundError):
        return _error_response(request, 404)

    @application.exception_handler(DocumentVersionNotFoundError)
    async def missing_document_version(
        request: Request, _error: DocumentVersionNotFoundError
    ):
        return _error_response(request, 404)

    @application.exception_handler(CandidateNotFoundError)
    async def missing_candidate(request: Request, _error: CandidateNotFoundError):
        return _error_response(request, 404)

    @application.exception_handler(ReviewRoundNotFoundError)
    async def missing_review_round(
        request: Request, _error: ReviewRoundNotFoundError
    ):
        return _error_response(request, 404)

    @application.exception_handler(AnalysisRunNotFoundError)
    async def missing_analysis_run(request: Request, _error: AnalysisRunNotFoundError):
        return _error_response(request, 404)

    @application.exception_handler(AnalysisRunRetryConflict)
    async def retry_conflict(request: Request, _error: AnalysisRunRetryConflict):
        return _error_response(request, 409)

    @application.exception_handler(VisualAssetNotFoundError)
    async def missing_visual_asset(request: Request, _error: VisualAssetNotFoundError):
        return _error_response(request, 404)

    @application.exception_handler(VisualAssetIncompleteError)
    async def incomplete_visual_asset(
        request: Request, _error: VisualAssetIncompleteError
    ):
        return JSONResponse(
            status_code=404,
            content={"code": "evidence_incomplete", "request_id": _request_id(request)},
        )

    @application.exception_handler(ValueError)
    async def invalid_input(request: Request, _error: ValueError):
        return _error_response(request, 400)

    @application.exception_handler(ServerOperationError)
    async def server_operation_error(request: Request, _error: ServerOperationError):
        return _server_error_response(request)

    @application.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(projects_router)
    application.include_router(reviews_router)
    application.include_router(assets_router)

    frontend_dir = static_dir or Path(__file__).resolve().parents[1] / "static"
    if frontend_dir.is_dir():
        application.mount(
            "/",
            StaticFiles(directory=frontend_dir, html=True),
            name="frontend",
        )
    return application


app = create_app()
