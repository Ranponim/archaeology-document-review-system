from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.reference_corpora import router
from app.domain.reference_corpus import ReferenceCorpusData, ReferenceCorpusStatus
from app.domain.source_assets import OriginalAssetData
from app.services.file_store import FileStore
from app.services.reference_corpus_service import ReferenceCorpusService


class FakeReferenceCorpusService:
    validate_source_role = staticmethod(ReferenceCorpusService.validate_source_role)

    def __init__(self) -> None:
        self.corpus = ReferenceCorpusData(
            id="corpus-1",
            project_id="",
            revision=1,
            status=ReferenceCorpusStatus.STAGING,
        )
        self.staged: list[tuple[str, str]] = []

    def create(self, project_id: str) -> ReferenceCorpusData:
        self.corpus = replace(self.corpus, project_id=project_id)
        return self.corpus

    def get(self, project_id: str, corpus_id: str) -> ReferenceCorpusData:
        if project_id != self.corpus.project_id or corpus_id != self.corpus.id:
            raise LookupError(corpus_id)
        return self.corpus

    def list(self, project_id: str) -> list[ReferenceCorpusData]:
        return [self.corpus] if project_id == self.corpus.project_id else []

    def stage_stored_source(self, project_id, corpus_id, stored, role, *, relative_path=None):
        assert project_id == self.corpus.project_id
        assert corpus_id == self.corpus.id
        self.staged.append((role, stored.original_name))
        return OriginalAssetData(
            id=f"asset-{len(self.staged)}",
            project_id=project_id,
            uri=stored.uri,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type=stored.mime_type,
            original_name=stored.original_name,
            relative_path=relative_path or stored.original_name,
            asset_kind=role,
            source_root_name="reference-corpus",
            import_batch_id=corpus_id,
            parse_status="stored",
            provenance_status="unlinked",
        )

    def build(self, project_id: str, corpus_id: str) -> ReferenceCorpusData:
        assert project_id == self.corpus.project_id
        assert corpus_id == self.corpus.id
        self.corpus = replace(self.corpus, status=ReferenceCorpusStatus.READY)
        return self.corpus


def _client(tmp_path):
    app = FastAPI()
    app.state.file_store = FileStore(tmp_path)
    app.state.reference_corpus_service = FakeReferenceCorpusService()

    @app.exception_handler(ValueError)
    async def invalid_input(_request: Request, _error: ValueError):
        return JSONResponse(status_code=400, content={"code": "input_error"})

    app.include_router(router)
    return TestClient(app), app.state.reference_corpus_service


def test_create_upload_build_list_and_detail_reference_corpus(tmp_path):
    client, service = _client(tmp_path)
    project_id = str(uuid4())

    created = client.post(f"/api/projects/{project_id}/reference-corpora")
    assert created.status_code == 201
    assert created.json()["id"] == "corpus-1"
    assert created.json()["status"] == "staging"

    uploads = [
        ("plate_layout", "plates.indd", b"indd", "application/x-indesign"),
        ("plate_link", "photo.jpg", b"jpeg", "image/jpeg"),
        ("drawing_source", "drawing.ai", b"ai", "application/postscript"),
    ]
    for role, name, content, mime in uploads:
        response = client.post(
            f"/api/projects/{project_id}/reference-corpora/corpus-1/sources?role={role}",
            files={"file": (name, content, mime)},
        )
        assert response.status_code == 202
        assert response.json()["role"] == role

    assert service.staged == [
        ("plate_layout", "plates.indd"),
        ("plate_link", "photo.jpg"),
        ("drawing_source", "drawing.ai"),
    ]

    built = client.post(f"/api/projects/{project_id}/reference-corpora/corpus-1/build")
    assert built.status_code == 202
    assert built.json()["status"] == "ready"

    listing = client.get(f"/api/projects/{project_id}/reference-corpora")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == ["corpus-1"]

    detail = client.get(f"/api/projects/{project_id}/reference-corpora/corpus-1")
    assert detail.status_code == 200
    assert detail.json()["status"] == "ready"


def test_source_role_extension_contract_fails_closed(tmp_path):
    client, _service = _client(tmp_path)
    project_id = str(uuid4())
    assert client.post(f"/api/projects/{project_id}/reference-corpora").status_code == 201

    response = client.post(
        f"/api/projects/{project_id}/reference-corpora/corpus-1/sources?role=drawing_source",
        files={"file": ("not-a-drawing.jpg", b"jpeg", "image/jpeg")},
    )
    assert response.status_code == 400
