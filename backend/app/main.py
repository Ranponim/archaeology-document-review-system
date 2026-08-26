from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.assets import router as assets_router
from app.api.project_structure import router as project_structure_router
from app.api.projects import AnalysisRunRetryConflict, ServerOperationError
from app.api.projects import router as projects_router
from app.api.reference_corpora import router as reference_corpora_router
from app.api.repository_compat import (
    VisualBundleReviewCompatibilityRepository,
    adapt_project_repository,
    adapt_review_repository,
    adapt_visual_asset_service,
)
from app.api.review_round_runs import router as review_round_runs_router
from app.api.reviews import CandidateNotFoundError
from app.api.reviews import router as reviews_router
from app.api.run_diagnostics import router as run_diagnostics_router
from app.config import (
    get_drawing_evidence_resolver_version,
    get_drawing_evidence_v3_auto_promote,
)
from app.graph.client import create_driver
from app.graph.drawing_evidence_repository_v3 import DrawingEvidenceRepositoryV3
from app.graph.production_review_repository import ProductionReviewRepository
from app.graph.project_repository import (
    AnalysisRunNotFoundError,
    DocumentVersionNotFoundError,
    ProjectNotFoundError,
    ReviewRoundNotFoundError,
)
from app.graph.project_structure_repository import ProjectStructureRepository
from app.graph.reference_corpus_repository import ReferenceCorpusRepository
from app.graph.review_project_repository import ReviewProjectRepository
from app.graph.schema import ensure_schema
from app.graph.source_asset_repository import SourceAssetRepository
from app.jobs.queue import enqueue_ingest, enqueue_proofreading
from app.services.adobe_conversion_client import build_adobe_conversion_client
from app.services.drawing_evidence_corpus_service import EvidenceGraphReferenceCorpusService
from app.services.file_store import FileStore
from app.services.orchestrator_factory import build_proofreading_orchestrator
from app.services.project_structure_service import ProjectStructureService
from app.services.reference_canonicalizer import ReferenceCanonicalizer
from app.services.reference_corpus_service import ReferenceCorpusNotFoundError
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
    project_structure_service=None,
    reference_corpus_service=None,
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
                app.state.review_repository = ProductionReviewRepository(driver)
        if getattr(app.state, "orchestrator", None) is None:
            driver = getattr(app.state, "neo4j_driver", None)
            if driver is not None:
                app.state.orchestrator = build_proofreading_orchestrator(driver)
        if getattr(app.state, "project_structure_service", None) is None:
            driver = getattr(app.state, "neo4j_driver", None)
            if driver is not None:
                app.state.project_structure_service = ProjectStructureService(
                    ProjectStructureRepository(driver),
                    app.state.file_store,
                )
        if getattr(app.state, "reference_corpus_service", None) is None:
            driver = getattr(app.state, "neo4j_driver", None)
            if driver is not None:
                source_repository = SourceAssetRepository(driver)
                drawing_repository = DrawingEvidenceRepositoryV3(driver)
                app.state.drawing_evidence_repository = drawing_repository
                project_repo = app.state.project_repository
                if not hasattr(project_repo, "resolve_version_input"):
                    project_repo = ReviewProjectRepository(driver)
                app.state.reference_corpus_service = EvidenceGraphReferenceCorpusService(
                    ReferenceCorpusRepository(driver),
                    build_adobe_conversion_client(),
                    ReferenceCanonicalizer(),
                    source_asset_repository=source_repository,
                    drawing_evidence_repository=drawing_repository,
                    drawing_evidence_resolver_version=get_drawing_evidence_resolver_version(),
                    drawing_evidence_v3_auto_promote=get_drawing_evidence_v3_auto_promote(),
                    project_repository=project_repo,
                )
        yield
        driver = getattr(app.state, "neo4j_driver", None)
        if driver is not None:
            driver.close()

    application = FastAPI(lifespan=lifespan)
    application.state.file_store = file_store if file_store is not None else FileStore()
    application.state.project_repository = adapt_project_repository(project_repository)
    injected_visual_service = adapt_visual_asset_service(visual_asset_service)
    adapted_review_repository = adapt_review_repository(review_repository)
    if adapted_review_repository is None and injected_visual_service is not None:
        adapted_review_repository = VisualBundleReviewCompatibilityRepository(
            injected_visual_service
        )
    application.state.review_repository = adapted_review_repository
    application.state.orchestrator = orchestrator
    application.state.ingest_enqueuer = ingest_enqueuer or enqueue_ingest
    application.state.run_enqueuer = run_enqueuer or enqueue_proofreading
    application.state.asset_repository = asset_repository
    application.state.visual_asset_service = injected_visual_service
    application.state.project_structure_service = project_structure_service
    application.state.reference_corpus_service = reference_corpus_service
    application.state.drawing_evidence_repository = None

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
    async def missing_document_version(request: Request, _error: DocumentVersionNotFoundError):
        return _error_response(request, 404)

    @application.exception_handler(CandidateNotFoundError)
    async def missing_candidate(request: Request, _error: CandidateNotFoundError):
        return _error_response(request, 404)

    @application.exception_handler(ReviewRoundNotFoundError)
    async def missing_review_round(request: Request, _error: ReviewRoundNotFoundError):
        return _error_response(request, 404)

    @application.exception_handler(ReferenceCorpusNotFoundError)
    async def missing_reference_corpus(request: Request, _error: ReferenceCorpusNotFoundError):
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
    async def incomplete_visual_asset(request: Request, _error: VisualAssetIncompleteError):
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
    application.include_router(reference_corpora_router)
    application.include_router(project_structure_router)
    application.include_router(review_round_runs_router)
    application.include_router(reviews_router)
    application.include_router(run_diagnostics_router)
    application.include_router(assets_router)

    frontend_dir = static_dir or Path(__file__).resolve().parents[1] / "static"
    if frontend_dir.is_dir():
        application.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return application


app = create_app()
