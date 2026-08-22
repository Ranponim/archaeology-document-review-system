from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.domain.models import DocumentVersion
from app.main import create_app
from app.services.file_store import FileStore


class FakeRepository:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.writes = 0

    def get_project(self, project_id: str):
        if project_id != self.project_id:
            raise KeyError(project_id)
        return {"project": object(), "documents": [], "document_versions": [], "analysis_runs": []}

    def add_document_version(self, project_id, stored, stage="source", kind="report_body", title=None):
        self.writes += 1
        return DocumentVersion(
            id=str(uuid4()),
            document_id=str(uuid4()),
            analysis_run_id=str(uuid4()),
            uri=stored.uri,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type=stored.mime_type,
            original_name=stored.original_name,
            stage=stage,
        )

    def fail_ingest(self, analysis_run_id, code, retryable):
        return True


def test_new_plate_and_drawing_pdf_document_uploads_are_rejected_before_graph_write(tmp_path):
    project_id = str(uuid4())
    repository = FakeRepository(project_id)
    app = create_app(
        file_store=FileStore(tmp_path),
        project_repository=repository,
        ingest_enqueuer=lambda run_id: f"ingest-{run_id}",
    )

    with TestClient(app) as client:
        for kind in ("plate_book", "drawing_book", "plate_pdf", "drawing_pdf"):
            response = client.post(
                f"/api/projects/{project_id}/documents?stage=source&kind={kind}",
                files={"file": (f"{kind}.pdf", b"%PDF", "application/pdf")},
            )
            assert response.status_code in {400, 422}

    assert repository.writes == 0


def test_body_pdf_document_upload_remains_allowed(tmp_path):
    project_id = str(uuid4())
    repository = FakeRepository(project_id)
    app = create_app(
        file_store=FileStore(tmp_path),
        project_repository=repository,
        ingest_enqueuer=lambda run_id: f"ingest-{run_id}",
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project_id}/documents?stage=source&kind=report_body",
            files={"file": ("body.pdf", b"%PDF", "application/pdf")},
        )

    assert response.status_code == 202
    assert repository.writes == 1
