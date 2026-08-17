from types import SimpleNamespace

import pytest

from app.domain.models import VersionInput
from app.jobs import worker


class FakeReviewRepository:
    def __init__(self):
        self.saved = []

    def claim_analysis(self, analysis_run_id):
        return {
            "project_id": "p1",
            "review_round_id": "round_4",
            # Snapshot fields are deliberately stale/wrong. ReviewRound is authority.
            "body_version_id": "stale_body",
            "plate_version_id": None,
            "drawing_version_id": None,
            "version_stage": "4차",
            "enable_vlm": False,
            "enable_ai_review": False,
        }

    def analysis_status(self, analysis_run_id):
        return "running"

    def save_analysis_run(self, **kwargs):
        self.saved.append(kwargs)


class FakeProjectRepository:
    def get_review_round(self, project_id, round_id):
        assert project_id == "p1"
        assert round_id == "round_4"
        return SimpleNamespace(
            id="round_4",
            project_id="p1",
            sequence=4,
            body_version_id="body_v3",
            plate_version_id=None,
            drawing_version_id=None,
        )

    def resolve_version_input(self, project_id, kind, stage=None, version_id=None):
        # Canonical ReviewRound resolution must never require stage == round sequence.
        assert project_id == "p1"
        assert stage is None
        if kind == "report_body" and version_id == "body_v3":
            return VersionInput(
                version_id="body_v3",
                document_id="doc_body",
                project_id="p1",
                kind="report_body",
                stage="3차",
                uri="body-v3.pdf",
                sha256="bodysha",
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
async def test_worker_re_resolves_review_round_and_allows_reused_body_version(monkeypatch):
    orch = FakeOrchestrator()

    async def fake_body_alignment(**kwargs):
        assert kwargs["primary_body_version"].version_id == "body_v3"
        assert kwargs["primary_stage"] == "4차"
        return ({"4차": []}, {"4차": "body_v3"})

    async def fake_plate_index(**kwargs):
        assert kwargs["plate_version_id"] is None
        return None

    async def fake_drawing_index(**kwargs):
        assert kwargs["drawing_version_id"] is None
        return None

    monkeypatch.setattr(worker, "resolve_body_versions_for_alignment", fake_body_alignment)
    monkeypatch.setattr(worker, "resolve_plate_index_for_run", fake_plate_index)
    monkeypatch.setattr(worker, "resolve_drawing_index_for_run", fake_drawing_index)

    result = await worker._run_analysis_worker("run_round_4", orch)

    assert result["status"] == "completed"
    assert len(orch.calls) == 1
    call = orch.calls[0]
    assert call["body_version_id"] == "body_v3"
    assert call["version_stage"] == "4차"
