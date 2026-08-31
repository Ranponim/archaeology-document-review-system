from app.domain.canonical_models import EvidenceLevel
from app.domain.drawing_evidence import (
    ContextFact,
    DrawingCandidateEvidence,
    DrawingCandidateResult,
    DrawingEvidenceResolution,
)
from app.graph.drawing_evidence_repository import DrawingEvidenceRepository


class CaptureDriver:
    def __init__(self):
        self.calls = []

    def execute_query(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return ([{"saved": 1}], None, None)


def test_v2_persists_kind_consensus_mention_and_tie_breaker_metadata():
    candidate = DrawingCandidateResult(
        candidate_id="drawing-candidate:c1:a3:illustration:3",
        reference_corpus_id="c1",
        source_asset_id="a3",
        source_sha256="sha-a3",
        candidate_number="3",
        status="verified",
        evidence_level=EvidenceLevel.DERIVED_VERIFIED,
        resolver_version="drawing-evidence-v2",
        score=0.92,
        runner_up_score=0.4,
        margin=0.52,
        evidence_families=("spatial_signature", "map_signature"),
        publication_kind="illustration",
        tie_breaker_classes=("filename",),
    )
    evidence = DrawingCandidateEvidence(
        id="e1",
        candidate_id=candidate.candidate_id,
        family="map_signature",
        method="exact_map_type",
        value="항공지도",
        normalized_value="항공지도",
        score=0.22,
        source_node_id="mention-3",
        publication_kind="illustration",
        mention_context_id="mention-3",
        consensus_status="consensus",
        tie_breaker_class="semantic",
    )
    fact = ContextFact(
        kind="map_type",
        value="항공지도",
        normalized_value="항공지도",
        source_kind="body",
        source_node_id="mention-3",
        publication_kind="illustration",
        mention_context_id="mention-3",
        consensus_status="consensus",
        tie_breaker_class="semantic",
    )
    resolution = DrawingEvidenceResolution(
        candidates=(candidate,), evidence=(evidence,), context_facts=(fact,)
    )

    driver = CaptureDriver()
    DrawingEvidenceRepository(driver).save_resolution("p1", "c1", resolution)

    candidate_args = next(kwargs for query, kwargs in driver.calls if "DRAWING_EVIDENCE_CANDIDATES" in query)
    assert candidate_args["candidates"][0]["publication_kind"] == "illustration"
    assert candidate_args["candidates"][0]["tie_breaker_classes"] == ["filename"]

    fact_args = next(kwargs for query, kwargs in driver.calls if "DRAWING_EVIDENCE_FACTS" in query)
    assert fact_args["facts"][0]["publication_kind"] == "illustration"
    assert fact_args["facts"][0]["mention_context_id"] == "mention-3"
    assert fact_args["facts"][0]["consensus_status"] == "consensus"

    evidence_args = next(kwargs for query, kwargs in driver.calls if "DRAWING_EVIDENCE_ITEMS" in query)
    assert evidence_args["evidence"][0]["publication_kind"] == "illustration"
    assert evidence_args["evidence"][0]["tie_breaker_class"] == "semantic"

    target_args = next(kwargs for query, kwargs in driver.calls if "DRAWING_EVIDENCE_TARGETS" in query)
    assert target_args["verified"][0]["publication_kind"] == "illustration"
