from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.domain.canonical_models import ArchaeologyObjectData
from app.domain.document_structure import ParsedPage, TextBlockData
from app.domain.models import VersionInput
from app.domain.reference_corpus import ReferenceCorpusData, ReferenceCorpusStatus
from app.graph.graph_review_repository import (
    GraphObjectReference,
    GraphReferenceResolution,
    GraphVisualNode,
)
from app.jobs import worker
from app.services.graph_rules import GraphRuleEngine
from app.services.optional_graph_review import OptionalGraphReviewDispatcher
from app.services.optional_review_orchestrator import OptionalGraphFirstReviewRoundOrchestrator
from app.services.plate_parser import PlateIndex
from app.services.drawing_parser import DrawingIndex


@dataclass
class _Round:
    id: str = "round-graph"
    project_id: str = "p1"
    sequence: int = 1
    body_version_id: str = "body-v1"
    reference_corpus_id: str = "corpus-1"
    plate_version_id: str | None = None
    drawing_version_id: str | None = None


class _ReviewRepository:
    def __init__(self):
        self.saved_candidates = []
        self.saved_evidences = []
        self.status = "queued"

    def claim_analysis(self, analysis_run_id):
        assert analysis_run_id == "run-graph"
        self.status = "running"
        return {
            "project_id": "p1",
            "review_round_id": "round-graph",
            "body_version_id": "stale-body",
            "plate_version_id": "stale-plate",
            "drawing_version_id": "stale-drawing",
            "enable_ai_review": False,
            "enable_vlm": False,
        }

    def analysis_status(self, analysis_run_id):
        return self.status

    def save_analysis_run(self, **kwargs):
        self.status = kwargs.get("status", self.status)

    def save_pages_and_blocks(self, **kwargs):
        return None

    def save_evidences(self, evidences):
        self.saved_evidences.extend(evidences)

    def save_candidates(self, **kwargs):
        self.saved_candidates.extend(kwargs["candidates"])


class _ProjectRepository:
    def get_review_round(self, project_id, round_id):
        assert (project_id, round_id) == ("p1", "round-graph")
        return _Round()

    def get_reference_corpus(self, project_id, corpus_id):
        assert (project_id, corpus_id) == ("p1", "corpus-1")
        return ReferenceCorpusData(
            id="corpus-1",
            project_id="p1",
            revision=1,
            status=ReferenceCorpusStatus.READY,
        )

    def resolve_version_input(self, project_id, kind, stage=None, version_id=None):
        if (project_id, kind, version_id) != ("p1", "report_body", "body-v1"):
            return None
        return VersionInput(
            version_id="body-v1",
            document_id="doc-body",
            project_id="p1",
            kind="report_body",
            stage="source",
            uri="body.pdf",
            sha256="body-sha",
            mime_type="application/pdf",
        )


class _ObjectResolver:
    def resolve_mentions(self, *, blocks, captions, project_id):
        assert project_id == "p1"
        return [
            SimpleNamespace(
                object_data=ArchaeologyObjectData(
                    object_id="obj-6",
                    project_id="p1",
                    site="site",
                    point="1지점",
                    type="석관묘",
                    number="6호",
                    canonical_name="1지점 6호 석관묘",
                    source_block_ids=["b1"],
                )
            )
        ]


class _CanonicalRepository:
    def save_archaeology_objects(self, *, objects, project_id):
        assert project_id == "p1"
        assert [item.object_id for item in objects] == ["obj-6"]

    def save_references(self, references):
        return None


class _CorpusObjectLinker:
    def link(self, project_id, corpus_id, objects):
        assert (project_id, corpus_id) == ("p1", "corpus-1")
        assert [item.object_id for item in objects] == ["obj-6"]
        return SimpleNamespace(created=[], ambiguous=[], unmatched=[])


class _GraphRepository:
    def __init__(self):
        self.saved_resolution_evidence = []

    def validate_corpus_integrity(self, project_id, corpus_id):
        assert (project_id, corpus_id) == ("p1", "corpus-1")
        return SimpleNamespace(ok=True, errors=())

    def references_for_object(self, project_id, object_id):
        assert (project_id, object_id) == ("p1", "obj-6")
        return [
            GraphObjectReference(
                id="ref-wrong",
                reference_type="plate",
                number="44",
                raw_text="도판 44",
                source_block_id="b1",
            ),
            GraphObjectReference(
                id="ref-missing",
                reference_type="drawing",
                number="999",
                raw_text="도면 999",
                source_block_id="b1",
            ),
        ]

    def visuals_for_object(self, project_id, corpus_id, object_id):
        assert (project_id, corpus_id, object_id) == ("p1", "corpus-1", "obj-6")
        return [
            GraphVisualNode(
                id="plate:corpus-1:45",
                label="Plate",
                number="45",
                title="1지점 6호 석관묘",
                reference_corpus_id="corpus-1",
            )
        ]

    def resolve_reference(self, project_id, corpus_id, reference_type, number):
        assert (project_id, corpus_id) == ("p1", "corpus-1")
        if (reference_type, number) == ("plate", "44"):
            return GraphReferenceResolution(
                status="RESOLVED",
                reference_type="plate",
                number="44",
                reference_corpus_id="corpus-1",
                target_ids=("plate:corpus-1:44",),
            )
        return GraphReferenceResolution(
            status="MISSING",
            reference_type=reference_type,
            number=number,
            reference_corpus_id="corpus-1",
            target_ids=(),
        )

    def save_resolution_evidence(
        self, project_id, corpus_id, analysis_run_id, reference_id, resolution
    ):
        row = (project_id, corpus_id, analysis_run_id, reference_id, resolution.status)
        self.saved_resolution_evidence.append(row)
        return f"resolution:{corpus_id}:{analysis_run_id}:{reference_id}"


class _BombReviewer:
    def __init__(self):
        self.calls = 0

    async def review_graph_finding(self, **kwargs):
        self.calls += 1
        raise AssertionError("AI/VLM must not be called when both flags are OFF")


def _page():
    return ParsedPage(
        physical_page=1,
        printed_page=1,
        header="",
        raw_text="1지점 6호 석관묘는 도판 44와 도면 999를 참조한다.",
        normalized_text="1지점 6호 석관묘는 도판 44와 도면 999를 참조한다.",
        text_blocks=[
            TextBlockData(
                block_id="b1",
                text="1지점 6호 석관묘는 도판 44와 도면 999를 참조한다.",
                normalized_text="1지점 6호 석관묘는 도판 44와 도면 999를 참조한다.",
                order=1,
                source_sha256="body-sha",
            )
        ],
        source_sha256="body-sha",
    )


@pytest.mark.anyio
async def test_review_round_to_graph_candidates_is_corpus_authoritative_and_model_free(monkeypatch):
    review_repo = _ReviewRepository()
    project_repo = _ProjectRepository()
    graph_repo = _GraphRepository()
    ai = _BombReviewer()
    vlm = _BombReviewer()
    orchestrator = OptionalGraphFirstReviewRoundOrchestrator(
        project_repo=project_repo,
        review_repo=review_repo,
        canonical_repo=_CanonicalRepository(),
        pdf_parser=object(),
        plate_parser=object(),
        drawing_parser=object(),
        object_resolver=_ObjectResolver(),
        rule_engine=object(),
        corpus_object_linker=_CorpusObjectLinker(),
        graph_rule_engine=GraphRuleEngine(graph_repo),
        optional_review_dispatcher=OptionalGraphReviewDispatcher(
            ai_reviewer=ai,
            vlm_reviewer=vlm,
        ),
        allow_degraded_mode=False,
    )

    async def fake_alignment(**kwargs):
        assert kwargs["review_round_id"] == "round-graph"
        assert kwargs["primary_body_version"].version_id == "body-v1"
        return ({"current": [_page()]}, {"current": "body-v1"})

    async def fake_corpus_indexes(**kwargs):
        assert kwargs["reference_corpus_id"] == "corpus-1"
        return PlateIndex(), DrawingIndex()

    async def forbidden_legacy(*args, **kwargs):
        raise AssertionError("corpus mode must never resolve legacy visual PDFs")

    monkeypatch.setattr(worker, "resolve_body_versions_for_alignment", fake_alignment)
    monkeypatch.setattr(worker, "resolve_reference_corpus_indexes_for_run", fake_corpus_indexes)
    monkeypatch.setattr(worker, "resolve_plate_index_for_run", forbidden_legacy)
    monkeypatch.setattr(worker, "resolve_drawing_index_for_run", forbidden_legacy)

    outcome = await worker._run_analysis_worker("run-graph", orchestrator)

    assert outcome["status"] == "completed"
    assert outcome["candidates_count"] >= 2
    assert ai.calls == 0
    assert vlm.calls == 0
    assert all(item.status == "pending_review" for item in review_repo.saved_candidates)
    codes = {item.evidence.rule_name for item in review_repo.saved_candidates if item.evidence}
    assert "VISUAL_REFERENCE_MISSING_TARGET" in codes
    assert "VISUAL_REFERENCE_WRONG_TARGET" in codes
    assert (
        "p1", "corpus-1", "run-graph", "ref-wrong", "RESOLVED"
    ) in graph_repo.saved_resolution_evidence
    assert (
        "p1", "corpus-1", "run-graph", "ref-missing", "MISSING"
    ) in graph_repo.saved_resolution_evidence
