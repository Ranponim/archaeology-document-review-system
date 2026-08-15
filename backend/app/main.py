from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.projects import ServerOperationError
from app.api.projects import router as projects_router
from app.graph.client import create_driver
from app.graph.project_repository import ProjectNotFoundError, ProjectRepository
from app.services.file_store import FileStore


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
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.project_repository is None:
            driver = create_driver()
            app.state.neo4j_driver = driver
            app.state.project_repository = ProjectRepository(driver)
        yield
        driver = getattr(app.state, "neo4j_driver", None)
        if driver is not None:
            driver.close()

    application = FastAPI(lifespan=lifespan)
    application.state.file_store = file_store if file_store is not None else FileStore()
    application.state.project_repository = project_repository

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

    @application.exception_handler(ValueError)
    async def invalid_input(request: Request, _error: ValueError):
        return _error_response(request, 400)

    @application.exception_handler(ServerOperationError)
    async def server_operation_error(request: Request, _error: ServerOperationError):
        return _server_error_response(request)

    application.include_router(projects_router)
    return application


app = create_app()
