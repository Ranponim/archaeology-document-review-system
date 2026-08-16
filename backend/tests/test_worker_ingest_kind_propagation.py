"""kind/project_id propagation across the RQ worker ingest boundary.

Regression guards for task-1-5 review Issues 4.1/4.2/3.4:
- claim_ingest must return the persisted document kind and project id so the
  worker can build Plate/Drawing graphs on the RQ path (previously every
  upload was ingested as report_body).
- The legacy ReviewPipeline must not be invoked from the production ingest
  worker (it persisted unscoped ``doc_ver_pN`` page ids and invented
  ``{uuid}_current`` version ids).
"""
from pathlib import Path
from typing import Any

from pypdf import PdfWriter

from app.graph.project_repository import ProjectRepository
from app.jobs.ingest import IngestContext
from app.jobs.worker import LocalMetadataExtractor
from app.services.drawing_parser import DrawingIndex, DrawingData


class FakeNeo4jRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class FakeNeo4jDriver:
    def __init__(self, records_to_return: list[dict[str, Any]] | None = None):
        self.queries: list[dict[str, Any]] = []
        self.records_to_return = [FakeNeo4jRecord(r) for r in (records_to_return or [])]

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        return self.records_to_return, None, None


CLAIM_RECORD = {
    "analysisRunId": "run-1",
    "documentVersionId": "ver-1",
    "uri": "incoming/proj/drawings.pdf",
    "sha256": "a" * 64,
    "mimeType": "application/pdf",
    "kind": "drawing_book",
    "projectId": "proj-9",
}


def test_claim_ingest_returns_kind_and_project_id():
    driver = FakeNeo4jDriver([CLAIM_RECORD])
    repository = ProjectRepository(driver)

    context = repository.claim_ingest("run-1")

    assert context is not None
    assert context.analysis_run_id == "run-1"
    assert context.document_version_id == "ver-1"
    assert context.uri == CLAIM_RECORD["uri"]
    assert context.sha256 == CLAIM_RECORD["sha256"]
    assert context.mime_type == "application/pdf"
    assert context.kind == "drawing_book"
    assert context.project_id == "proj-9"

    claim_cypher = driver.queries[0]["query"]
    assert "HAS_DOCUMENT" in claim_cypher and "HAS_VERSION" in claim_cypher
    assert "coalesce(document.kind" in claim_cypher
    assert "project.id AS projectId" in claim_cypher


def test_claim_ingest_kind_falls_back_to_report_body_when_document_unknown():
    record = dict(CLAIM_RECORD, kind="report_body", projectId=None)
    driver = FakeNeo4jDriver([record])
    repository = ProjectRepository(driver)

    context = repository.claim_ingest("run-1")

    assert context is not None
    assert context.kind == "report_body"
    assert context.project_id is None


def _pdf_fixture(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "document.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


def test_extractor_passes_kind_and_project_id_into_kind_ingest_job(
    tmp_path: Path, monkeypatch
):
    pdf_path = _pdf_fixture(tmp_path)
    calls: list[dict[str, Any]] = []

    def spy_run_kind_ingest_job(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "app.jobs.worker.run_kind_ingest_job", spy_run_kind_ingest_job
    )

    extractor = LocalMetadataExtractor(data_root=tmp_path)
    context = IngestContext(
        analysis_run_id="run-test",
        document_version_id="version-test",
        uri="document.pdf",
        sha256="b" * 64,
        mime_type="application/pdf",
        kind="plate_book",
        project_id="proj-42",
    )

    metadata = extractor.extract(context)

    assert metadata.page_count == 1
    assert metadata.text_extractable is False
    assert calls == [
        {
            "project_id": "proj-42",
            "version_id": "version-test",
            "kind": "plate_book",
            "file_path": pdf_path,
            "canonical_repo": None,
            "review_repo": None,
            "analysis_run_id": "run-test",
            # Task 9: plate books render pages into the derived dir.
            "render_dir": tmp_path / "derived" / "plate_renders" / "version-test",
        }
    ]


def test_extractor_falls_back_to_version_id_when_project_id_unset(
    tmp_path: Path, monkeypatch
):
    _pdf_fixture(tmp_path)
    calls: list[dict[str, Any]] = []

    def spy_run_kind_ingest_job(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "app.jobs.worker.run_kind_ingest_job", spy_run_kind_ingest_job
    )

    extractor = LocalMetadataExtractor(data_root=tmp_path)
    context = IngestContext(
        analysis_run_id="run-test",
        document_version_id="version-test",
        uri="document.pdf",
        sha256="b" * 64,
        mime_type="application/pdf",
    )

    metadata = extractor.extract(context)

    assert metadata.page_count == 1
    assert calls[0]["kind"] == "report_body"
    assert calls[0]["project_id"] == "version-test"


def test_extractor_carries_drawing_book_kind_end_to_end(tmp_path: Path, monkeypatch):
    """A drawing_book upload on the RQ path must reach the kind-aware ingest
    with its real kind, not the report_body default."""
    pdf_path = _pdf_fixture(tmp_path)
    received: dict[str, Any] = {}

    def spy_run_kind_ingest_job(**kwargs):
        received.update(kwargs)

    monkeypatch.setattr(
        "app.jobs.worker.run_kind_ingest_job", spy_run_kind_ingest_job
    )

    extractor = LocalMetadataExtractor(data_root=tmp_path)
    context = IngestContext(
        analysis_run_id="run-test",
        document_version_id="version-test",
        uri="document.pdf",
        sha256="b" * 64,
        mime_type="application/pdf",
        kind="drawing_book",
        project_id="proj-42",
    )

    metadata = extractor.extract(context)

    assert metadata.page_count == 1
    assert received["kind"] == "drawing_book"
    assert received["file_path"] == pdf_path


def test_extractor_does_not_invoke_legacy_review_pipeline(tmp_path: Path, monkeypatch):
    pdf_path = _pdf_fixture(tmp_path)
    pipeline_calls: list[str] = []

    class SpyReviewPipeline:
        def __init__(self, review_repo=None):
            pipeline_calls.append("constructed")

        def run_full_pipeline(self, project_id, version_files):
            pipeline_calls.append("run_full_pipeline")

    monkeypatch.setattr(
        "app.jobs.review_pipeline.ReviewPipeline", SpyReviewPipeline
    )

    extractor = LocalMetadataExtractor(data_root=tmp_path)
    context = IngestContext(
        analysis_run_id="run-test",
        document_version_id="version-test",
        uri="document.pdf",
        sha256="b" * 64,
        mime_type="application/pdf",
    )

    metadata = extractor.extract(context)

    assert metadata.mime_type == "application/pdf"
    assert metadata.page_count == 1
    assert pipeline_calls == []