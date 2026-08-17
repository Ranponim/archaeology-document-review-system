from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.schemas import (
    AnalysisRunResponse,
    DocumentResponse,
    DocumentVersionResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectResponse,
    RetryAnalysisRunResponse,
    UploadResponse,
)
from app.domain.models import (
    Document,
    DocumentVersion,
    Project,
    StoredFile,
    VersionInput,
)
from app.domain.review_round import ReviewRound
from app.graph.project_repository import (
    AnalysisRunNotFoundError,
    DocumentVersionNotFoundError,
    ProjectNotFoundError,
    ReviewRoundNotFoundError,
)
from app.services.file_store import FileStore


class ServerOperationError(RuntimeError):
    """A sanitized marker for an unexpected storage or repository failure."""


class AnalysisRunRetryConflict(RuntimeError):
    """The requested run is terminal and not eligible for retry."""


class ProjectRepositoryPort(Protocol):
    def create_project(self, name: str, internal_code: str | None) -> Project: ...

    def list_projects(self) -> list[Project]: ...

    def get_project(self, project_id: str) -> dict: ...

    def get_project_documents(self, project_id: str) -> list[Document]: ...

    def get_document_versions(self, document_id: str) -> list[DocumentVersion]: ...

    def get_document_version_by_id(self, version_id: str) -> DocumentVersion | None: ...

    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ) -> VersionInput | None: ...

    def add_document_version(
        self,
        project_id: str,
        stored: StoredFile,
        stage: str = "source",
        kind: str = "report_body",
        title: str | None = None,
    ) -> DocumentVersion: ...

    def create_document_with_version(
        self,
        project_id: str,
        stored: StoredFile,
        stage: str = "source",
        kind: str = "report_body",
        title: str | None = None,
    ) -> tuple[Document, DocumentVersion]: ...

    def fail_ingest(self, analysis_run_id: str, code: str, retryable: bool) -> bool: ...

    def prepare_ingest_retry(self, project_id: str, analysis_run_id: str) -> str: ...

    def create_review_round(
        self,
        project_id: str,
        body_version_id: str | None = None,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        notes: str | None = None,
    ) -> ReviewRound: ...

    def list_review_rounds(self, project_id: str) -> list[ReviewRound]: ...

    def get_review_round(
        self, project_id: str, round_id: str
    ) -> ReviewRound | None: ...

    def approve_review_round(
        self, project_id: str, round_id: str
    ) -> ReviewRound: ...



def get_file_store(request: Request) -> FileStore:
    return request.app.state.file_store


def get_project_repository(request: Request) -> ProjectRepositoryPort:
    return request.app.state.project_repository


def get_ingest_enqueuer(request: Request) -> Callable[[str], str]:
    return request.app.state.ingest_enqueuer


router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _run_repository(operation, *args):
    try:
        return await run_in_threadpool(operation, *args)
    except ProjectNotFoundError:
        raise
    except AnalysisRunNotFoundError:
        raise
    except ReviewRoundNotFoundError:
        raise
    except Exception:  # noqa: BLE001 - sanitize adapter failures at the API boundary
        raise ServerOperationError from None


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> list[ProjectResponse]:
    projects = await _run_repository(repository.list_projects)
    return [
        ProjectResponse(
            id=project.id,
            name=project.name,
            internal_code=project.internal_code,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
        for project in projects
    ]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> ProjectResponse:
    project = await _run_repository(
        repository.create_project,
        payload.name,
        payload.internal_code,
    )
    return ProjectResponse(
        id=project.id,
        name=project.name,
        internal_code=project.internal_code,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.post(
    "/{project_id}/documents",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    project_id: UUID,
    file: Annotated[UploadFile, File()],
    repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    file_store: Annotated[FileStore, Depends(get_file_store)],
    ingest_enqueuer: Annotated[Callable[[str], str], Depends(get_ingest_enqueuer)],
    stage: Annotated[str, Query(pattern=r"^(source|final|[1-9][0-9]*차)$")] = "source",
    kind: Annotated[str, Query()] = "report_body",
) -> UploadResponse:
    normalized_project_id = str(project_id)
    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise ValueError("Publication document uploads must be PDF")
    # Validate project existence before accepting original bytes. The write
    # transaction repeats the MATCH so a concurrent deletion still fails closed.
    await _run_repository(repository.get_project, normalized_project_id)
    try:
        stored = await file_store.store_upload(project_id, file)
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - sanitize storage failures at the API boundary
        raise ServerOperationError from None
    version = await _run_repository(
        repository.add_document_version,
        normalized_project_id,
        stored,
        stage,
        kind,
    )
    try:
        await run_in_threadpool(ingest_enqueuer, version.analysis_run_id)
    except Exception:  # noqa: BLE001 - Redis details stay private
        try:
            await _run_repository(
                repository.fail_ingest,
                version.analysis_run_id,
                "api_error",
                True,
            )
        except ServerOperationError:
            pass
        raise ServerOperationError from None
    return UploadResponse(
        document_version_id=version.id,
        analysis_run_id=version.analysis_run_id,
    )


@router.post(
    "/{project_id}/analysis-runs/{analysis_run_id}/retry",
    response_model=RetryAnalysisRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_analysis_run(
    project_id: UUID,
    analysis_run_id: UUID,
    repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    ingest_enqueuer: Annotated[Callable[[str], str], Depends(get_ingest_enqueuer)],
) -> RetryAnalysisRunResponse:
    normalized_run_id = str(analysis_run_id)
    run_status = await _run_repository(
        repository.prepare_ingest_retry,
        str(project_id),
        normalized_run_id,
    )
    if run_status not in {"queued", "running"}:
        raise AnalysisRunRetryConflict

    if run_status == "queued":
        try:
            await run_in_threadpool(ingest_enqueuer, normalized_run_id)
        except Exception:  # noqa: BLE001 - Redis details stay private
            try:
                await _run_repository(
                    repository.fail_ingest,
                    normalized_run_id,
                    "api_error",
                    True,
                )
            except ServerOperationError:
                pass
            raise ServerOperationError from None

    return RetryAnalysisRunResponse(
        analysis_run_id=normalized_run_id,
        status=run_status,
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: UUID,
    repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> ProjectDetailResponse:
    snapshot = await _run_repository(repository.get_project, str(project_id))
    project = snapshot["project"]
    documents = snapshot.get("documents", [])
    versions = snapshot["document_versions"]
    runs = snapshot["analysis_runs"]
    return ProjectDetailResponse(
        id=project.id,
        name=project.name,
        internal_code=project.internal_code,
        created_at=project.created_at,
        updated_at=project.updated_at,
        documents=[
            DocumentResponse(
                id=doc.id,
                project_id=doc.project_id,
                kind=doc.kind,
                title=doc.title,
            )
            for doc in documents
        ],
        document_versions=[
            DocumentVersionResponse(
                id=version.id,
                document_id=version.document_id,
                original_name=version.original_name,
                mime_type=version.mime_type,
                size_bytes=version.size_bytes,
                stage=version.stage,
            )
            for version in versions
        ],
        analysis_runs=[AnalysisRunResponse(**run) for run in runs],
    )
