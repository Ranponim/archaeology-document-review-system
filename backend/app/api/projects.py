from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.schemas import (
    AnalysisRunResponse,
    DocumentVersionResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectResponse,
    UploadResponse,
)
from app.domain.models import DocumentVersion, Project, StoredFile
from app.services.file_store import FileStore


class ProjectRepositoryPort(Protocol):
    def create_project(self, name: str, internal_code: str | None) -> Project: ...

    def get_project(self, project_id: str) -> dict: ...

    def add_document_version(
        self, project_id: str, stored: StoredFile, stage: str
    ) -> DocumentVersion: ...


def get_file_store(request: Request) -> FileStore:
    return request.app.state.file_store


def get_project_repository(request: Request) -> ProjectRepositoryPort:
    return request.app.state.project_repository


router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> ProjectResponse:
    project = await run_in_threadpool(
        repository.create_project,
        payload.name,
        payload.internal_code,
    )
    return ProjectResponse(
        id=project.id,
        name=project.name,
        internal_code=project.internal_code,
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
    stage: Annotated[Literal["source"], Query()] = "source",
) -> UploadResponse:
    normalized_project_id = str(project_id)
    # Validate project existence before accepting original bytes. The write
    # transaction repeats the MATCH so a concurrent deletion still fails closed.
    await run_in_threadpool(repository.get_project, normalized_project_id)
    stored = await file_store.store_upload(project_id, file)
    version = await run_in_threadpool(
        repository.add_document_version,
        normalized_project_id,
        stored,
        stage,
    )
    return UploadResponse(
        document_version_id=version.id,
        analysis_run_id=version.analysis_run_id,
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: UUID,
    repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> ProjectDetailResponse:
    snapshot = await run_in_threadpool(repository.get_project, str(project_id))
    project = snapshot["project"]
    versions = snapshot["document_versions"]
    runs = snapshot["analysis_runs"]
    return ProjectDetailResponse(
        id=project.id,
        name=project.name,
        internal_code=project.internal_code,
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
