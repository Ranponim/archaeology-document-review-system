from types import SimpleNamespace

import pytest

from app.domain.models import VersionInput
from app.domain.reference_corpus import ReferenceCorpusData, ReferenceCorpusStatus
from app.jobs import worker
from app.services.drawing_parser import DrawingIndex
from app.services.plate_parser import PlateIndex


class FakeReviewRepository:
    def claim_analysis(self, analysis_run_id):
        return {
            "project_id": "p1",
            "review_round_id": "round-corpus",
            "body_version_id": "stale-body",
            "plate_version_id": "stale-plate",
            "drawing_version_id": "stale-drawing",
            "enable_vlm": False,
            "enable_ai_review": False,
        }

    def analysis_status(self, analysis_run_id):
        return "running"

    def save_analysis_run(self, **kwargs):
        pass


class FakeProjectRepository:
    def get_review_round(self, project_id, round_id):
        assert (project_id, round_id) == ("p1", "round-corpus")
        return SimpleNamespace(
            id="round-corpus",
            project_id="p1",
            sequence=2,
            body_version_id="body-v2",
            reference_corpus_id="corpus-2",
            plate_version_id=None,
            drawing_version_id=None,
        )

    def get_reference_corpus(self, project_id, corpus_id):
        assert (project_id, corpus_id) == ("p1", "corpus-2")
        return ReferenceCorpusData(
            id="corpus-2",
            project_id="p1",
            revision=2,
            status=ReferenceCorpusStatus.READY,
        )

    def resolve_version_input(self, project_id, kind, stage=None, version_id=None):
        assert project_id == "p1"
        assert stage is None
        if kind == "report_body" and version_id == "body-v2":
            return VersionInput(
                version_id="body-v2",
                document_id="doc-body",
                project_id="p1",
                kind="report_body",
                stage="source",
                uri="body-v2.pdf",
                sha256="body-sha",
                mime_type="application/pdf",
            )
        return None


class FakeOrchestrator:
    def __init__(self):
        self.review_repo = FakeReviewRepository()
        self.project_repo = FakeProjectRepository()
        self.canonical_repo = object()
        self.pdf_parser = object()
        self.plate_parser = object()
        self.drawing_parser = object()
        self.calls = []

    async def run_proofreading(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            status="completed",
            pages_parsed=1,
            objects_resolved=0,
            references_resolved=0,
            candidates=[],
            errors=[],
            warnings=[],
        )


@pytest.mark.anyio
async def test_worker_uses_selected_corpus_graph_and_never_legacy_visual_pdf_resolvers(monkeypatch):
    orchestrator = FakeOrchestrator()

    async def fake_body_alignment(**kwargs):
        assert kwargs["primary_body_version"].version_id == "body-v2"
        assert kwargs["review_round_id"] == "round-corpus"
        return ({"current": []}, {"current": "body-v2"})

    async def fake_corpus_indexes(**kwargs):
        assert kwargs["project_id"] == "p1"
        assert kwargs["reference_corpus_id"] == "corpus-2"
        return PlateIndex(), DrawingIndex()

    async def forbidden_legacy(*args, **kwargs):
        raise AssertionError("corpus mode must not call legacy visual PDF resolver")

    monkeypatch.setattr(worker, "resolve_body_versions_for_alignment", fake_body_alignment)
    monkeypatch.setattr(worker, "resolve_reference_corpus_indexes_for_run", fake_corpus_indexes)
    monkeypatch.setattr(worker, "resolve_plate_index_for_run", forbidden_legacy)
    monkeypatch.setattr(worker, "resolve_drawing_index_for_run", forbidden_legacy)

    result = await worker._run_analysis_worker("run-corpus", orchestrator)

    assert result["status"] == "completed"
    assert len(orchestrator.calls) == 1
    call = orchestrator.calls[0]
    assert call["body_version_id"] == "body-v2"
    assert call["plate_version_id"] is None
    assert call["drawing_version_id"] is None
    assert isinstance(call["plate_index"], PlateIndex)
    assert isinstance(call["drawing_index"], DrawingIndex)
