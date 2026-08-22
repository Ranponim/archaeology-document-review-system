from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.canonical_models import ArchaeologyObjectData
from app.domain.document_structure import ParsedPage, TextBlockData
from app.services.graph_first_review_round_orchestrator import GraphFirstReviewRoundOrchestrator
from app.services.graph_rules import GraphRuleFinding
from app.services.optional_graph_review import OptionalReviewOutcome
from app.services.optional_review_orchestrator import OptionalGraphFirstReviewRoundOrchestrator


class FakeObjectResolver:
    def resolve_mentions(self, *, blocks, captions, project_id):
        assert project_id == "p1"
        return [
            SimpleNamespace(
                object_data=ArchaeologyObjectData(
                    object_id="obj-6",
                    site="site",
                    point="1지점",
                    type="석관묘",
                    number="6호",
                    canonical_name="1지점 6호 석관묘",
                    source_block_ids=["b1"],
                    project_id="p1",
                )
            )
        ]


class FakeCanonicalRepository:
    def __init__(self):
        self.calls = []

    def save_archaeology_objects(self, *, objects, project_id):
        self.calls.append(("save_objects", project_id, [item.object_id for item in objects]))

    def save_references(self, references):
        self.calls.append(("save_references", len(references)))

    def link_visual_assets_to_objects(self, **kwargs):
        raise AssertionError("corpus mode must not use legacy global DEPICTS linker")

    def get_object_evidence_bundle(self, *args, **kwargs):
        raise AssertionError("corpus mode must not use legacy object evidence bundle rules")


class FakeStrictRuleEngine:
    def check_object_bundle_consistency(self, *args, **kwargs):
        raise AssertionError("corpus mode must not run legacy StrictRuleEngine")


class FakeCorpusObjectLinker:
    def __init__(self, events):
        self.events = events

    def link(self, project_id, corpus_id, objects):
        self.events.append(("link", project_id, corpus_id, tuple(o.object_id for o in objects)))
        return SimpleNamespace(created=[], ambiguous=[])


class FakeGraphRuleEngine:
    def __init__(self, events, *, include_semantic=False):
        self.events = events
        self.include_semantic = include_semantic

    def run(self, **kwargs):
        self.events.append(("graph_rules", kwargs["reference_corpus_id"]))
        assert kwargs["project_id"] == "p1"
        assert kwargs["analysis_run_id"] == "run-1"
        assert kwargs["archaeology_object_ids"] == ["obj-6"]
        assert kwargs["body_regions_by_object"]["obj-6"][0].source_block_id == "b1"
        findings = [
            GraphRuleFinding(
                rule_code="VISUAL_REFERENCE_MISSING",
                severity="high",
                source_block_id="b1",
                archaeology_object_id="obj-6",
                reference_corpus_id="corpus-1",
                canonical_target_ids=("plate:corpus-1:45",),
                original_text="1지점 6호 석관묘 설명",
                proposed_text="(도판 45)",
                rationale="selected corpus graph proof",
                evidence_ids=("resolution:1",),
            )
        ]
        if self.include_semantic:
            findings.append(
                GraphRuleFinding(
                    rule_code="SEMANTIC_REVIEW_REQUIRED",
                    severity="medium",
                    source_block_id="b1",
                    archaeology_object_id="obj-6",
                    reference_corpus_id="corpus-1",
                    canonical_target_ids=("region:corpus-1:30",),
                    original_text="북쪽 단면 방향이 일치한다.",
                    proposed_text=None,
                    rationale="orientation requires semantic review",
                    evidence_ids=("semantic:1",),
                    requires_ai=True,
                )
            )
        return findings


class FakeOptionalDispatcher:
    def __init__(self, *, warnings=None):
        self.calls = []
        self._warnings = list(warnings or [])

    @staticmethod
    def _context_key(finding):
        return f"{finding.rule_code}:{finding.source_block_id or ''}"

    async def review(self, **kwargs):
        self.calls.append(kwargs)
        return OptionalReviewOutcome(findings=[], warnings=list(self._warnings))


def _page():
    return ParsedPage(
        physical_page=1,
        printed_page=1,
        header="",
        raw_text="1지점 6호 석관묘 설명",
        normalized_text="1지점 6호 석관묘 설명",
        text_blocks=[
            TextBlockData(
                block_id="b1",
                text="1지점 6호 석관묘 설명",
                normalized_text="1지점 6호 석관묘 설명",
                order=1,
                block_type="paragraph",
                source_sha256="body-sha",
            )
        ],
        captions=[],
        source_sha256="body-sha",
    )


def _orchestrator(*, events, graph_engine, optional_dispatcher=None):
    return OptionalGraphFirstReviewRoundOrchestrator(
        pdf_parser=object(),
        plate_parser=object(),
        drawing_parser=object(),
        object_resolver=FakeObjectResolver(),
        canonical_repo=FakeCanonicalRepository(),
        rule_engine=FakeStrictRuleEngine(),
        corpus_object_linker=FakeCorpusObjectLinker(events),
        graph_rule_engine=graph_engine,
        optional_review_dispatcher=optional_dispatcher,
        allow_degraded_mode=False,
    )


@pytest.mark.anyio
async def test_corpus_mode_runs_linker_then_graph_rules_and_emits_one_pending_candidate():
    events = []
    orchestrator = _orchestrator(events=events, graph_engine=FakeGraphRuleEngine(events))

    result = await orchestrator.run_proofreading(
        project_id="p1",
        body_version_id="body-v1",
        body_pages=[_page()],
        plate_index=None,
        drawing_index=None,
        analysis_run_id="run-1",
        reference_corpus_id="corpus-1",
        enable_ai_review=False,
        enable_vlm=False,
    )

    assert events == [
        ("link", "p1", "corpus-1", ("obj-6",)),
        ("graph_rules", "corpus-1"),
    ]
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.rule_category == "figure_plate_table_photo_ref"
    assert candidate.status == "pending_review"
    assert candidate.proposed_text == "(도판 45)"
    assert candidate.analysis_run_id == "run-1"
    assert candidate.finding_fingerprint
    assert result.summary["mode"] == "reference_corpus"
    assert result.summary["reference_corpus_id"] == "corpus-1"


@pytest.mark.anyio
async def test_optional_dispatcher_is_not_called_when_both_flags_are_off():
    events = []
    dispatcher = FakeOptionalDispatcher()
    orchestrator = _orchestrator(
        events=events,
        graph_engine=FakeGraphRuleEngine(events, include_semantic=True),
        optional_dispatcher=dispatcher,
    )

    result = await orchestrator.run_proofreading(
        project_id="p1",
        body_version_id="body-v1",
        body_pages=[_page()],
        analysis_run_id="run-1",
        reference_corpus_id="corpus-1",
        enable_ai_review=False,
        enable_vlm=False,
    )

    assert dispatcher.calls == []
    assert len(result.candidates) == 2
    assert result.status == "completed"


@pytest.mark.anyio
async def test_optional_failure_warning_preserves_all_graph_candidates_and_filters_inputs():
    events = []
    dispatcher = FakeOptionalDispatcher(
        warnings=["optional ai review warning: TimeoutError"]
    )
    orchestrator = _orchestrator(
        events=events,
        graph_engine=FakeGraphRuleEngine(events, include_semantic=True),
        optional_dispatcher=dispatcher,
    )

    result = await orchestrator.run_proofreading(
        project_id="p1",
        body_version_id="body-v1",
        body_pages=[_page()],
        analysis_run_id="run-1",
        reference_corpus_id="corpus-1",
        enable_ai_review=True,
        enable_vlm=False,
    )

    assert len(dispatcher.calls) == 1
    call = dispatcher.calls[0]
    assert call["enable_ai_review"] is True
    assert call["enable_vlm"] is False
    assert len(call["findings"]) == 1
    assert call["findings"][0].rule_code == "SEMANTIC_REVIEW_REQUIRED"
    assert len(result.candidates) == 2
    assert result.status == "completed"
    assert result.warnings == ["optional ai review warning: TimeoutError"]
    assert result.summary["optional_review_findings"] == 0
    assert result.summary["optional_review_semantic_inputs"] == 1


def test_production_factory_assembles_graph_first_collaborators(monkeypatch):
    import app.services.orchestrator_factory as factory

    monkeypatch.setattr(factory, "VLMReviewService", lambda: object())
    monkeypatch.setattr(factory, "AIReviewService", lambda: object())
    monkeypatch.delenv("DEVELOPMENT_CANDIDATE_BUDGET", raising=False)
    monkeypatch.delenv("CANDIDATE_BUDGET", raising=False)
    monkeypatch.delenv("REVIEW_MODE", raising=False)

    orchestrator = factory.build_proofreading_orchestrator(object())

    assert isinstance(orchestrator, GraphFirstReviewRoundOrchestrator)
    assert isinstance(orchestrator, OptionalGraphFirstReviewRoundOrchestrator)
    assert orchestrator.graph_rule_engine is not None
    assert orchestrator.corpus_object_linker is not None
    assert orchestrator.optional_review_dispatcher is not None
    assert orchestrator.optional_review_repository is not None
