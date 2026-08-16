"""Task 14 - Gate F decision semantics (TDD).

Candidate generation status (pending_review) stays separate from append-only
expert ReviewDecision records with exactly four values: accepted | rejected |
modified | deferred. layout_noise remains a rule classification only - it is
never a decision value (anti-pattern #11).
"""
from typing import Any
import os
import pytest

from app.domain.review_models import ReviewDecisionValue
from app.graph.review_repository import (
    ReviewRepository,
    compute_latest_decision,
    compute_review_metrics,
)


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


def _candidate_with_decisions(cand_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": cand_id,
        "candidate_id": cand_id,
        "rule_category": "numeric_value",
        "category": "numeric_value",
        "status": "pending_review",
        "decisions": decisions,
    }


def test_rule_engine_candidates_start_pending_review():
    from app.domain.canonical_models import ArchaeologyObjectData
    from app.domain.review_models import EvidenceData
    from app.services.rule_engine import RuleEngine

    engine = RuleEngine()
    obj = ArchaeologyObjectData(
        object_id="obj_t14_rule",
        site="1지점",
        canonical_name="6호 석관묘",
    )
    ev = EvidenceData(
        id="ev_t14_blank",
        value="① 유구(도면 : , 도판 : )",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        source_sha256="hash1",
        kind="text_claim",
    )
    candidates = engine.check_object_consistency(archaeology_object=obj, evidences=[ev])
    assert len(candidates) >= 1
    assert all(c.status == "pending_review" for c in candidates)


@pytest.mark.anyio
async def test_ai_review_candidates_start_pending_review_even_model_claims_confirmed():
    import json

    from app.domain.canonical_models import ArchaeologyObjectData
    from app.domain.review_models import EvidenceData
    from app.services.ai_review_service import AIReviewService

    obj = ArchaeologyObjectData(
        object_id="obj_t14_1",
        site="1지점",
        canonical_name="1지점 14호 토광묘",
    )
    ev = EvidenceData(
        id="ev_t14_1",
        value="해발 63.4m",
        document_version_id="ver_1",
        page_id="ver_1_p50",
        source_sha256="sha256_hash",
        kind="text_claim",
    )

    class MockClient:
        async def analyze_text_discrepancy(self, prompt: str, context: dict) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "candidates": [
                                    {
                                        "category": "numeric_value",
                                        "original_text": "해발 63.4m",
                                        "proposed_text": "해발 63.8m",
                                        "status": "confirmed",
                                        "change_type": "modified",
                                        "rationale": "등고선 고도 불일치",
                                        "cited_evidence_ids": ["ev_t14_1"],
                                    }
                                ]
                            })
                        }
                    }
                ],
                "usage": {},
            }

    service = AIReviewService(client=MockClient(), model="openai/gpt-5.6-luna")
    candidates = await service.review_object_evidence(archaeology_object=obj, evidences=[ev])
    assert len(candidates) == 1
    assert candidates[0].status == "pending_review"


@pytest.mark.anyio
async def test_vlm_asset_pipeline_candidates_start_pending_review(tmp_path):
    from app.domain.canonical_models import ReferenceData, ResolutionStatus
    from app.services.asset_cache import AssetHashCache
    from app.services.asset_matcher import ResolutionResult
    from app.services.asset_review_pipeline import AssetReviewPipeline
    from app.services.vlm_review_service import VLMReviewService

    class NoopVLM(VLMReviewService):
        async def review(self, *args, **kwargs):
            raise AssertionError("VLM must not run for the unresolved path")

    pipeline = AssetReviewPipeline(
        vlm_service=NoopVLM(client=None, cache=AssetHashCache(cache_dir=tmp_path / "vlm_cache")),
        cache=AssetHashCache(cache_dir=tmp_path / "asset_cache"),
    )
    reference = ReferenceData(
        ref_type="plate",
        number="45",
        source_block_id="p47_b1",
        raw_text="【도판 45】",
        source_sha256="sha256_ref",
        physical_page=47,
    )
    candidates = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=ResolutionResult(
            status=ResolutionStatus.UNRESOLVED, target=None, identity_source="unresolved"
        ),
    )
    assert len(candidates) == 1
    assert candidates[0].status == "pending_review"


def test_review_decision_value_literal_is_exactly_four_values():
    assert set(ReviewDecisionValue.__args__) == {"accepted", "rejected", "modified", "deferred"}


@pytest.mark.parametrize(
    "bad_value",
    ["accept", "reject", "modify", "confirm", "confirmed", "layout_noise", "pending_review", "?()"],
)
def test_save_review_decision_rejects_non_four_value_vocabulary(bad_value: str):
    repo = ReviewRepository(driver=FakeNeo4jDriver(), database="arch_test")
    with pytest.raises(ValueError, match="decision"):
        repo.save_review_decision(
            decision_id="dec_bad_1",
            candidate_id="cand_1",
            decision_status=bad_value,
            reviewer="r1",
        )


def test_save_review_decision_accepts_four_value_vocabulary():
    repo = ReviewRepository(driver=FakeNeo4jDriver(), database="arch_test")
    for value in ("accepted", "rejected", "modified", "deferred"):
        repo.save_review_decision(
            decision_id=f"dec_ok_{value}",
            candidate_id="cand_1",
            decision_status=value,
            reviewer="r1",
        )


def test_save_review_decision_never_mutates_candidate_status():
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="arch_test")

    repo.save_review_decision(
        decision_id="dec_1",
        candidate_id="cand_1",
        decision_status="rejected",
        note="본문 서술이 정확함",
        reviewer="expert_1",
    )

    query = driver.queries[0]["query"]
    assert "SET cand.status" not in query
    assert "cand.status = $candidate_status" not in query
    assert "ReviewDecision" in query
    assert "HAS_DECISION" in query
    assert "SUPERSEDES" in query


def test_save_review_decision_persists_previous_decision_id():
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="arch_test")

    repo.save_review_decision(
        decision_id="dec_2",
        candidate_id="cand_1",
        decision_status="modified",
        reviewer="expert_2",
        previous_decision_id="dec_1",
    )
    query = driver.queries[0]["query"]
    assert "previous_decision_id" in query


def test_latest_decision_helper_returns_most_recent_or_none():
    decisions = [
        {"id": "dec_a", "created_at": "2026-08-17T01:00:00Z", "decision_status": "accepted"},
        {"id": "dec_b", "created_at": "2026-08-17T05:30:00Z", "decision_status": "rejected"},
        {"id": "dec_c", "created_at": "2026-08-17T03:00:00Z", "decision_status": "deferred"},
    ]
    latest = compute_latest_decision(decisions)
    assert latest["id"] == "dec_b"
    assert latest["decision_status"] == "rejected"

    assert compute_latest_decision([]) is None


def test_get_candidate_exposes_latest_decision_and_history():
    fake_record = {
        "candidate": {
            "id": "cand_t14_2",
            "rule_category": "numeric_value",
            "status": "pending_review",
        },
        "obj_id": None,
        "evidences": [],
        "decisions": [
            {"id": "dec_old", "decision_status": "accepted", "created_at": "2026-08-16T00:00:00Z"},
            {"id": "dec_new", "decision_status": "rejected", "created_at": "2026-08-17T00:00:00Z"},
        ],
    }
    driver = FakeNeo4jDriver(records_to_return=[fake_record])
    repo = ReviewRepository(driver=driver, database="arch_test")

    cand = repo.get_candidate("cand_t14_1")
    assert cand is not None
    assert len(cand["decisions"]) == 2
    assert cand["latest_decision"]["id"] == "dec_new"
    assert cand["latest_decision"]["decision_status"] == "rejected"
    assert cand["status"] == "pending_review"


def test_get_candidates_exposes_latest_decision():
    fake_record = {
        "candidate": {"id": "cand_t14_2", "status": "pending_review"},
        "obj_id": None,
        "evidences": [],
        "decisions": [
            {"id": "dec_1", "decision_status": "accepted", "created_at": "2026-08-17T00:00:00Z"},
        ],
    }
    driver = FakeNeo4jDriver(records_to_return=[fake_record])
    repo = ReviewRepository(driver=driver, database="arch_test")

    results = repo.get_candidates("proj_1")
    assert len(results) == 1
    assert results[0]["latest_decision"]["id"] == "dec_1"
    assert len(results[0]["decisions"]) == 1


def test_metrics_use_latest_decision_across_history():
    candidates = [
        _candidate_with_decisions(
            "cand_a",
            [
                {"id": "a1", "decision_status": "accepted", "created_at": "2026-08-16T00:00:00Z"},
                {"id": "a2", "decision_status": "rejected", "created_at": "2026-08-17T00:00:00Z"},
            ],
        ),
        _candidate_with_decisions(
            "cand_b",
            [{"id": "b1", "decision_status": "accepted", "created_at": "2026-08-17T00:00:00Z"}],
        ),
        _candidate_with_decisions("cand_c", []),
    ]
    metrics = compute_review_metrics("proj_1", candidates)
    assert metrics["total_candidates"] == 3
    assert metrics["accepted_candidates"] == 1
    assert metrics["rejected_candidates"] == 1
    assert metrics["modified_candidates"] == 0
    assert metrics["deferred_candidates"] == 0
    assert metrics["pending_candidates"] == 1
    assert len(candidates[0]["decisions"]) == 2


def test_metrics_deferred_is_a_distinct_bucket():
    candidates = [
        _candidate_with_decisions(
            "cand_d",
            [{"id": "d1", "decision_status": "deferred", "created_at": "2026-08-17T00:00:00Z"}],
        ),
    ]
    metrics = compute_review_metrics("proj_1", candidates)
    assert metrics["deferred_candidates"] == 1
    assert metrics["accepted_candidates"] == 0
    assert metrics["pending_candidates"] == 0


def test_metrics_never_reads_layout_noise_as_rejection():
    candidates = [
        _candidate_with_decisions(
            "cand_e",
            [{"id": "e1", "decision_status": "rejected", "created_at": "2026-08-17T00:00:00Z"}],
        ),
        _candidate_with_decisions("cand_f", []),
    ]
    metrics = compute_review_metrics("proj_1", candidates)
    assert metrics["rejected_candidates"] == 1
    assert metrics["accepted_candidates"] == 0
    assert metrics["pending_candidates"] == 1


def _real_driver():
    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        return None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return driver
    except Exception:
        return None


def test_real_neo4j_decisions_append_only_and_latest_queryable():
    import time
    import uuid

    driver = _real_driver()
    if driver is None:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    scope = f"dec_test_{uuid.uuid4().hex[:8]}"
    cand_id = f"{scope}_cand"
    dec1, dec2 = f"{scope}_dec1", f"{scope}_dec2"
    try:
        driver.execute_query(
            """
            CREATE (cand:CorrectionCandidate {id: $cand_id, status: 'pending_review', rule_category: 'numeric_value'})
            """,
            cand_id=cand_id,
        )
        time.sleep(0.05)
        repo = ReviewRepository(driver=driver)
        repo.save_review_decision(
            decision_id=dec1, candidate_id=cand_id,
            decision_status="accepted", reviewer="expert_1", note="1차 수용",
        )
        repo.save_review_decision(
            decision_id=dec2, candidate_id=cand_id,
            decision_status="deferred", reviewer="expert_2", note="보류",
        )

        cand = repo.get_candidate(cand_id)
        assert cand is not None
        assert cand["status"] == "pending_review"
        assert {d["id"] for d in cand["decisions"]} == {dec1, dec2}
        assert cand["latest_decision"]["id"] == dec2
        assert cand["latest_decision"]["decision_status"] == "deferred"

        records, _, _ = driver.execute_query(
            """
            MATCH (cand:CorrectionCandidate {id: $cand_id})-[:HAS_DECISION]->(d:ReviewDecision)
            OPTIONAL MATCH (d)-[:SUPERSEDES]->(prev:ReviewDecision)
            RETURN d.id AS id, prev.id AS prev_id
            """,
            cand_id=cand_id,
        )
        rows = {(r["id"], r["prev_id"]) for r in records}
        assert (dec2, dec1) in rows
        assert (dec1, None) in rows
    finally:
        driver.execute_query(
            """
            MATCH (n) WHERE n.id STARTS WITH $scope
            DETACH DELETE n
            """,
            scope=scope,
        )
