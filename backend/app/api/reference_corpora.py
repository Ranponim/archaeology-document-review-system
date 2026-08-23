from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from pydantic import ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.api.schemas import ApiModel
from app.domain.reference_corpus import ReferenceCorpusData
from app.services.file_store import FileStore
from app.services.reference_corpus_service import ReferenceCorpusService


class ReferenceCorpusResponse(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(alias="projectId")
    revision: int
    status: str
    source_set_hash: str = Field(default="", alias="sourceSetHash")
    converter_version: str = Field(default="", alias="converterVersion")
    manifest_schema_version: str = Field(default="", alias="manifestSchemaVersion")
    canonicalizer_version: str = Field(default="", alias="canonicalizerVersion")
    build_identity: str = Field(default="", alias="buildIdentity")
    created_at: str | None = Field(default=None, alias="createdAt")
    ready_at: str | None = Field(default=None, alias="readyAt")
    failure_code: str | None = Field(default=None, alias="failureCode")


class ReferenceCorpusSourceResponse(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    role: str
    original_name: str = Field(alias="originalName")
    relative_path: str = Field(alias="relativePath")
    sha256: str


def _corpus_response(corpus: ReferenceCorpusData) -> ReferenceCorpusResponse:
    failure = corpus.failure_code
    return ReferenceCorpusResponse(
        id=corpus.id,
        projectId=corpus.project_id,
        revision=corpus.revision,
        status=corpus.status.value,
        sourceSetHash=corpus.source_set_hash,
        converterVersion=corpus.converter_version,
        manifestSchemaVersion=corpus.manifest_schema_version,
        canonicalizerVersion=corpus.canonicalizer_version,
        buildIdentity=corpus.build_identity,
        createdAt=corpus.created_at,
        readyAt=corpus.ready_at,
        failureCode=(getattr(failure, "value", failure) if failure is not None else None),
    )


def get_reference_corpus_service(request: Request) -> ReferenceCorpusService:
    return request.app.state.reference_corpus_service


def get_file_store(request: Request) -> FileStore:
    return request.app.state.file_store


def _corpus_upload_mime(content_type: str | None) -> str | None:
    """Treat browser-generic binary MIME as unknown for extension validation.

    INDD and AI files commonly arrive from browsers as application/octet-stream.
    FileStore still validates the filename suffix and chooses its canonical MIME;
    all other explicit MIME values retain the existing strict validation.
    """
    normalized = str(content_type or "").strip().lower()
    return None if normalized in {"", "application/octet-stream"} else content_type


router = APIRouter(prefix="/api/projects/{project_id}/reference-corpora", tags=["reference-corpora"])


@router.post("", response_model=ReferenceCorpusResponse, status_code=status.HTTP_201_CREATED)
async def create_reference_corpus(
    project_id: UUID,
    service: Annotated[ReferenceCorpusService, Depends(get_reference_corpus_service)],
) -> ReferenceCorpusResponse:
    corpus = await run_in_threadpool(service.create, str(project_id))
    return _corpus_response(corpus)


@router.get("", response_model=list[ReferenceCorpusResponse])
async def list_reference_corpora(
    project_id: UUID,
    service: Annotated[ReferenceCorpusService, Depends(get_reference_corpus_service)],
) -> list[ReferenceCorpusResponse]:
    corpora = await run_in_threadpool(service.list, str(project_id))
    return [_corpus_response(item) for item in corpora]


@router.get("/{corpus_id}", response_model=ReferenceCorpusResponse)
async def get_reference_corpus(
    project_id: UUID,
    corpus_id: str,
    service: Annotated[ReferenceCorpusService, Depends(get_reference_corpus_service)],
) -> ReferenceCorpusResponse:
    corpus = await run_in_threadpool(service.get, str(project_id), corpus_id)
    return _corpus_response(corpus)


@router.post(
    "/{corpus_id}/sources",
    response_model=ReferenceCorpusSourceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_reference_corpus_source(
    project_id: UUID,
    corpus_id: str,
    file: Annotated[UploadFile, File()],
    role: Annotated[str, Query()],
    service: Annotated[ReferenceCorpusService, Depends(get_reference_corpus_service)],
    file_store: Annotated[FileStore, Depends(get_file_store)],
    relative_path: Annotated[str | None, Query(alias="relativePath")] = None,
) -> ReferenceCorpusSourceResponse:
    filename = file.filename or ""
    normalized_role = service.validate_source_role(role, filename)
    content = await file.read()
    stored = await run_in_threadpool(
        file_store.store_bytes,
        project_id,
        filename,
        content,
        _corpus_upload_mime(file.content_type),
    )
    asset = await run_in_threadpool(
        service.stage_stored_source,
        str(project_id),
        corpus_id,
        stored,
        normalized_role,
        relative_path=relative_path,
    )
    return ReferenceCorpusSourceResponse(
        id=asset.id,
        role=normalized_role,
        originalName=asset.original_name,
        relativePath=asset.relative_path,
        sha256=asset.sha256,
    )


@router.post(
    "/{corpus_id}/build",
    response_model=ReferenceCorpusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def build_reference_corpus(
    project_id: UUID,
    corpus_id: str,
    service: Annotated[ReferenceCorpusService, Depends(get_reference_corpus_service)],
) -> ReferenceCorpusResponse:
    corpus = await run_in_threadpool(service.build, str(project_id), corpus_id)
    return _corpus_response(corpus)
