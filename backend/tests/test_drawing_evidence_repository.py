from __future__ import annotations

from app.domain.canonical_models import EvidenceLevel
from app.domain.drawing_evidence import (
    ContextFact,
    DrawingCandidateEvidence,
    DrawingCandidateResult,
    DrawingEvidenceResolution,
)
from app.graph.drawing_evidence_repository import DrawingEvidenceRepository


class _CaptureDriver:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def execute_query(self, query: str, **kwargs):
        self.calls.append((query, kwargs))
        if "BODY_DRAWING_CONTEXT" in query:
            return ([{
                "number": "14",
                "source_id": "caption-14",
                "source_text": "도면 14. 2지점 S1 E1 북동 토층",
                "source_sha256": "body-sha",
                "neighbor_texts": ["2지점 조사", "S1 E1 북동부"],
                "neighbor_ids": ["block-1", "block-2"],
            }], None, None)
        if "DRAWING_EVIDENCE_" in query:
            return ([{"saved": 1}], None, None)
        return ([], None, None)


def _resolution(level: EvidenceLevel) -> DrawingEvidenceResolution:
    candidate = DrawingCandidateResult(
        candidate_id="drawing-candidate:c1:ai14:14",
        reference_corpus_id="c1",
        source_asset_id="ai14",
        source_sha256="ai-sha",
        candidate_number="14",
        status="verified" if level in {EvidenceLevel.DIRECT, EvidenceLevel.DERIVED_VERIFIED} else "candidate",
        evidence_level=level,
        score=0.91,
        runner_up_score=0.4,
        margin=0.51,
        evidence_families=("identity", "semantic_content"),
        evidence_ids=("e1",),
    )
    evidence = DrawingCandidateEvidence(
        id="e1",
        candidate_id=candidate.candidate_id,
        family="semantic_content",
        method="exact_grid",
        value="S1E1",
        normalized_value="S1E1",
        score=0.22,
        source_node_id="caption-14",
        source_sha256="body-sha",
    )
    fact = ContextFact(
        kind="grid",
        value="S1 E1",
        normalized_value="S1E1",
        source_kind="body",
        source_node_id="caption-14",
        source_sha256="body-sha",
    )
    return DrawingEvidenceResolution(candidates=(candidate,), evidence=(evidence,), context_facts=(fact,))


def test_body_context_query_is_project_scoped_and_includes_neighbors():
    driver = _CaptureDriver()
    repository = DrawingEvidenceRepository(driver)

    contexts = repository.list_body_drawing_contexts("p1")

    assert len(contexts) == 1
    assert contexts[0].number == "14"
    assert contexts[0].raw_texts == (
        "도면 14. 2지점 S1 E1 북동 토층",
        "2지점 조사",
        "S1 E1 북동부",
    )
    assert contexts[0].source_node_ids == ("caption-14", "block-1", "block-2")
    query = next(query for query, _ in driver.calls if "BODY_DRAWING_CONTEXT" in query)
    assert "MATCH (p:Project" in query
    assert "HAS_DOCUMENT" in query
    assert "ref.ref_type = 'drawing'" in query


def test_heuristic_candidate_is_persisted_without_target_relation():
    driver = _CaptureDriver()
    repository = DrawingEvidenceRepository(driver)

    repository.save_resolution("p1", "c1", _resolution(EvidenceLevel.HEURISTIC))

    candidate_query = next(query for query, _ in driver.calls if "DRAWING_EVIDENCE_CANDIDATES" in query)
    assert "PROPOSES" in candidate_query
    assert "TARGETS" not in candidate_query
    assert any("DRAWING_EVIDENCE_ITEMS" in query for query, _ in driver.calls)
    assert any("DRAWING_EVIDENCE_FACTS" in query for query, _ in driver.calls)
    assert not any("DRAWING_EVIDENCE_TARGETS" in query for query, _ in driver.calls)


def test_verified_candidate_gets_target_relation():
    driver = _CaptureDriver()
    repository = DrawingEvidenceRepository(driver)

    repository.save_resolution("p1", "c1", _resolution(EvidenceLevel.DERIVED_VERIFIED))

    assert any(
        "DRAWING_EVIDENCE_TARGETS" in query and "TARGETS" in query
        for query, _ in driver.calls
    )
