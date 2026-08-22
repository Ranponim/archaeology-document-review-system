from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.graph.graph_review_repository import (
    GraphObjectReference,
    GraphReferenceResolution,
    GraphVisualNode,
)
from app.services.graph_rules import (
    CorpusIntegrityError,
    GraphBodyRegion,
    GraphRuleEngine,
    GraphRuleFinding,
)


class FakeGraphReviewRepository:
    def __init__(self):
        self.integrity = SimpleNamespace(ok=True, errors=())
        self.references: dict[str, list[GraphObjectReference]] = {}
        self.visuals: dict[str, list[GraphVisualNode]] = {}
        self.resolutions: dict[tuple[str, str], GraphReferenceResolution] = {}
        self.saved: list[tuple[str, str, str, str]] = []

    def validate_corpus_integrity(self, project_id, corpus_id):
        return self.integrity

    def references_for_object(self, project_id, object_id):
        return list(self.references.get(object_id, []))

    def visuals_for_object(self, project_id, corpus_id, object_id):
        return list(self.visuals.get(object_id, []))

    def resolve_reference(self, project_id, corpus_id, reference_type, number):
        return self.resolutions.get(
            (reference_type, number),
            GraphReferenceResolution(
                status="MISSING",
                reference_type=reference_type,
                number=number,
                reference_corpus_id=corpus_id,
                target_ids=(),
            ),
        )

    def save_resolution_evidence(
        self, project_id, corpus_id, analysis_run_id, reference_id, resolution
    ):
        self.saved.append((corpus_id, analysis_run_id, reference_id, resolution.status))
        return f"evidence:{corpus_id}:{analysis_run_id}:{reference_id}"


def _plate(corpus: str, number: str) -> GraphVisualNode:
    return GraphVisualNode(
        id=f"plate:{corpus}:{number}",
        label="Plate",
        number=number,
        title=f"도판 {number}",
        reference_corpus_id=corpus,
    )


def _drawing_region(corpus: str, number: str = "30") -> GraphVisualNode:
    return GraphVisualNode(
        id=f"region:{corpus}:{number}",
        label="DrawingRegion",
        number=number,
        title="북쪽 단면 방향 확인 필요",
        reference_corpus_id=corpus,
    )


def _ref(number: str, ref_type: str = "plate") -> GraphObjectReference:
    return GraphObjectReference(
        id=f"ref-{ref_type}-{number}",
        reference_type=ref_type,
        number=number,
        raw_text=f"도판 {number}" if ref_type == "plate" else f"도면 {number}",
        source_block_id="b1",
    )


def _run(engine: GraphRuleEngine, regions=None):
    return engine.run(
        project_id="p1",
        reference_corpus_id="c1",
        analysis_run_id="run-1",
        archaeology_object_ids=["obj-6"],
        body_regions_by_object={"obj-6": list(regions or [])},
    )


def test_finding_model_keeps_graph_identity_and_ai_flag_explicit():
    finding = GraphRuleFinding(
        rule_code="VISUAL_REFERENCE_MISSING",
        severity="high",
        source_block_id="b1",
        archaeology_object_id="obj-6",
        reference_corpus_id="c1",
        canonical_target_ids=("plate:c1:45",),
        original_text="6호 석관묘",
        proposed_text="(도판 45)",
        rationale="graph proof",
        evidence_ids=("ev-1",),
    )
    assert finding.reference_corpus_id == "c1"
    assert finding.requires_ai is False


def test_l1_integrity_error_stops_review_instead_of_becoming_candidate():
    repo = FakeGraphReviewRepository()
    repo.integrity = SimpleNamespace(ok=False, errors=("CORPUS_NOT_READY",))
    engine = GraphRuleEngine(repo)

    with pytest.raises(CorpusIntegrityError) as error:
        _run(engine)

    assert error.value.error_codes == ("CORPUS_NOT_READY",)


def test_l2_missing_target_is_deterministic_and_persists_scoped_evidence():
    repo = FakeGraphReviewRepository()
    repo.references["obj-6"] = [_ref("999")]
    repo.resolutions[("plate", "999")] = GraphReferenceResolution(
        status="MISSING",
        reference_type="plate",
        number="999",
        reference_corpus_id="c1",
        target_ids=(),
    )
    engine = GraphRuleEngine(repo)

    findings = _run(engine)

    finding = next(item for item in findings if item.rule_code == "VISUAL_REFERENCE_MISSING_TARGET")
    assert finding.proposed_text is None
    assert finding.requires_ai is False
    assert repo.saved == [("c1", "run-1", "ref-plate-999", "MISSING")]
    assert finding.evidence_ids == ("evidence:c1:run-1:ref-plate-999",)


def test_l2_ambiguous_identity_never_delegates_target_choice_to_ai():
    repo = FakeGraphReviewRepository()
    repo.references["obj-6"] = [_ref("45")]
    repo.resolutions[("plate", "45")] = GraphReferenceResolution(
        status="AMBIGUOUS",
        reference_type="plate",
        number="45",
        reference_corpus_id="c1",
        target_ids=("plate:c1:45:a", "plate:c1:45:b"),
    )
    engine = GraphRuleEngine(repo)

    findings = _run(engine)

    finding = next(item for item in findings if item.rule_code == "VISUAL_REFERENCE_AMBIGUOUS")
    assert finding.proposed_text is None
    assert finding.requires_ai is False
    assert finding.canonical_target_ids == ("plate:c1:45:a", "plate:c1:45:b")


def test_l3_missing_reference_proposes_only_unique_target_and_location():
    repo = FakeGraphReviewRepository()
    repo.visuals["obj-6"] = [_plate("c1", "45")]
    engine = GraphRuleEngine(repo)

    findings = _run(
        engine,
        [GraphBodyRegion(source_block_id="b1", text="6호 석관묘를 설명한다.")],
    )

    finding = next(item for item in findings if item.rule_code == "VISUAL_REFERENCE_MISSING")
    assert finding.proposed_text == "(도판 45)"
    assert finding.canonical_target_ids == ("plate:c1:45",)


def test_l3_blank_placeholder_fill_uses_unique_graph_target():
    repo = FakeGraphReviewRepository()
    repo.visuals["obj-6"] = [_plate("c1", "45")]
    engine = GraphRuleEngine(repo)

    findings = _run(
        engine,
        [GraphBodyRegion(source_block_id="b1", text="6호 석관묘 (도면: , 도판: )")],
    )

    finding = next(item for item in findings if item.rule_code == "VISUAL_REFERENCE_BLANK_FILL")
    assert finding.original_text == "(도면: , 도판: )"
    assert finding.proposed_text == "(도면: , 도판: 45)"


def test_l3_wrong_target_replacement_requires_one_proven_correct_target():
    repo = FakeGraphReviewRepository()
    repo.visuals["obj-6"] = [_plate("c1", "45")]
    repo.references["obj-6"] = [_ref("44")]
    repo.resolutions[("plate", "44")] = GraphReferenceResolution(
        status="RESOLVED",
        reference_type="plate",
        number="44",
        reference_corpus_id="c1",
        target_ids=("plate:c1:44",),
    )
    engine = GraphRuleEngine(repo)

    findings = _run(engine)

    finding = next(item for item in findings if item.rule_code == "VISUAL_REFERENCE_WRONG_TARGET")
    assert finding.original_text == "도판 44"
    assert finding.proposed_text == "도판 45"


def test_l3_multiple_targets_or_locations_never_get_auto_proposal():
    repo = FakeGraphReviewRepository()
    repo.visuals["obj-6"] = [_plate("c1", "45"), _plate("c1", "46")]
    engine = GraphRuleEngine(repo)
    findings = _run(
        engine,
        [GraphBodyRegion(source_block_id="b1", text="첫 위치")],
    )
    ambiguous = next(item for item in findings if item.rule_code == "VISUAL_REFERENCE_AMBIGUOUS")
    assert ambiguous.proposed_text is None

    repo.visuals["obj-6"] = [_plate("c1", "45")]
    findings = _run(
        engine,
        [
            GraphBodyRegion(source_block_id="b1", text="첫 위치"),
            GraphBodyRegion(source_block_id="b2", text="둘째 위치"),
        ],
    )
    location = next(item for item in findings if item.rule_code == "VISUAL_REFERENCE_LOCATION_AMBIGUOUS")
    assert location.proposed_text is None


def test_l4_semantic_escalation_is_the_only_ai_required_layer():
    repo = FakeGraphReviewRepository()
    repo.visuals["obj-6"] = [_drawing_region("c1")]
    engine = GraphRuleEngine(repo)

    findings = _run(
        engine,
        [
            GraphBodyRegion(
                source_block_id="b1",
                text="북쪽 단면 방향이 일치한다.",
                semantic_topics=("orientation",),
            )
        ],
    )

    finding = next(item for item in findings if item.rule_code == "SEMANTIC_REVIEW_REQUIRED")
    assert finding.requires_ai is True
    assert finding.proposed_text is None
    assert all(
        item.requires_ai is False
        for item in findings
        if item.rule_code != "SEMANTIC_REVIEW_REQUIRED"
    )
