"""Task 7 tests: graph-backed ObjectEvidenceBundle queries (Gate B).

- CanonicalRepository.get_object_evidence_bundle() consumes real relationships
  (MENTIONS / HAS_BLOCK|HAS_CAPTION / HAS_PAGE / REFERENCES / RESOLVES_TO /
  DEPICTS / ABOUT / SUPPORTED_BY / EXTRACTED_FROM / FROM_VERSION) via Cypher
  traversal — the bundle is built from DB rows, never from a parallel
  in-memory structure.
- RuleEngine consumes the graph-derived bundle (check_object_bundle_consistency)
  and produces candidates referencing bundle-sourced EvidenceData (Gate D).
- Orchestrator feeds the graph bundle to RuleEngine when graph evidence exists
  and degrades explicitly (with a recorded warning) otherwise.
"""
from typing import Any, Callable
import os
import uuid

import pytest
from neo4j import GraphDatabase

from app.domain.document_structure import ParsedPage, TextBlockData
from app.domain.evidence_bundle import ObjectEvidenceBundle
from app.domain.review_models import EvidenceData
from app.graph.canonical_repository import CanonicalRepository
from app.graph.review_repository import ReviewRepository
from app.services.proofreading_orchestrator import ProofreadingOrchestrator
from app.services.rule_engine import RuleEngine


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


class ScriptedFakeNeo4jDriver:
    """Fake driver returning per-query-shaped records in registration order."""

    def __init__(self):
        self.queries: list[dict[str, Any]] = []
        self._responses: list[tuple[Callable[[str], bool], list[dict[str, Any]]]] = []

    def respond(self, marker: str, records: list[dict[str, Any]]) -> "ScriptedFakeNeo4jDriver":
        self._responses.append((lambda q, m=marker: m in q, records))
        return self

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        for predicate, records in self._responses:
            if predicate(query):
                return [FakeNeo4jRecord(r) for r in records], None, None
        return [], None, None


def _claim(
    ev_id: str,
    text: str,
    kind: str = "text_claim",
    sha: str = "sha256_body",
    version_id: str = "ver_1",
    page_id: str = "ver_1_p1",
    **kwargs: Any,
) -> EvidenceData:
    props: dict[str, Any] = {
        "id": ev_id,
        "kind": kind,
        "source_sha256": sha,
        "document_version_id": version_id,
        "page_id": page_id,
        "value": text,
        "method": "graph_mention",
        "confidence": 1.0,
    }
    props.update(kwargs)
    return EvidenceData(**props)


def test_rule_engine_bundle_detects_numeric_conflict_from_bundle_evidence():
    engine = RuleEngine(header_patterns=[])
    bundle = ObjectEvidenceBundle(
        object_id="obj_d",
        canonical_name="1지점 청동기시대 1호 주거지",
        text_claims=[
            _claim("db_claim_275cm", "규모는 길이 275cm이다"),
            _claim("db_claim_245m", "평면조사에서는 길이 2.45m로 기록되었다"),
        ],
    )

    cands = engine.check_object_bundle_consistency(bundle, plates=[], drawings=[])

    numeric = [c for c in cands if c.rule_category == "numeric_value"]
    assert len(numeric) == 1
    assert {ev.id for ev in numeric[0].evidences} == {
        "db_claim_275cm",
        "db_claim_245m",
    }
    assert numeric[0].evidence_list == [          bundle.text_claims[0],
        bundle.text_claims[1],
    ]


def test_rule_engine_bundle_equivalent_values_produce_no_conflict():
    engine = RuleEngine(header_patterns=[])
    bundle = ObjectEvidenceBundle(
        object_id="obj_eq",
        canonical_name="1지점 청동기시대 1호 주거지",
        text_claims=[
            _claim("db_eq_1", "길이 275cm"),
            _claim("db_eq_2", "길이 2.75m"),
        ],
    )

    candidates = engine.check_object_bundle_consistency(bundle, plates=[], drawings=[])

    assert [c for c in candidates if c.rule_category == "numeric_value"] == []


def test_rule_engine_bundle_detects_blank_reference_from_bundle_evidence():
    engine = RuleEngine(header_patterns=[])
    bundle = ObjectEvidenceBundle(
        object_id="obj_blank",
        canonical_name="2지점 2호 토광묘",
        text_claims=[
            _claim("db_blank_ref", "2지점 2호 토광묘(도면 : , 도판 : ) 조사를 진행하였다."),
        ],
    )

    candidates = engine.check_object_bundle_consistency(bundle, plates=[], drawings=[])

    ref_cands = [c for c in candidates if c.rule_category == "figure_plate_table_photo_ref"]
    assert len(ref_cands) == 1
    assert ref_cands[0].evidence.id == "db_blank_ref"


def test_rule_engine_bundle_visual_and_version_evidence_feed_the_same_checks():
    engine = RuleEngine(header_patterns=[])
    bundle = ObjectEvidenceBundle(
        object_id="obj_v",
        canonical_name="1지점 청동기시대 6호 석관묘",
        plate_claims=[_claim("db_plate", "길이 300cm", kind="plate_caption")],
        visual_observations=[_claim("db_vlm", "길이 300cm", kind="vlm_observation")],
        text_claims=[_claim("db_text", "길이 3.00m")],
    )

    candidates = engine.check_object_bundle_consistency(bundle, plates=[], drawings=[])

    assert [c for c in candidates if c.rule_category == "numeric_value"] == []


def test_get_object_evidence_bundle_empty_when_object_missing():
    driver = ScriptedFakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    bundle = repo.get_object_evidence_bundle("obj_missing")

    assert bundle.object_id == "obj_missing"
    assert bundle.canonical_name == ""
    assert bundle.has_graph_evidence() is False
    assert "MATCH (obj:ArchaeologyObject {id: $object_id})" in driver.queries[0]["query"]
    assert driver.queries[0]["kwargs"]["object_id"] == "obj_missing"
    assert driver.queries[0]["kwargs"].get("database_") == "test_db"


def test_get_object_evidence_bundle_driver_none_returns_empty_bundle():
    repo = CanonicalRepository(driver=None)
    bundle = repo.get_object_evidence_bundle("obj_x")
    assert bundle.object_id == "obj_x"
    assert bundle.has_graph_evidence() is False


def test_get_object_evidence_bundle_traversal_cypher_semantics():
    driver = (
        ScriptedFakeNeo4jDriver()
        .respond("RETURN properties(obj) AS obj", [{"obj": {"canonical_name": "O"}}])
    )
    repo = CanonicalRepository(driver=driver, database="test_db")

    repo.get_object_evidence_bundle("obj_t")

    all_cypher = "\n".join(q["query"] for q in driver.queries)
    assert "[:MENTIONS]->(obj:ArchaeologyObject {id: $object_id})" in all_cypher
    assert "(page:Page)-[:HAS_BLOCK|HAS_CAPTION]->(source)" in all_cypher
    assert "(version:DocumentVersion)-[:HAS_PAGE]->(page)" in all_cypher
    assert "[:REFERENCES]->(ref:Reference)" in all_cypher
    assert "RESOLVES_TO" in all_cypher
    assert "[:DEPICTS]->(obj:ArchaeologyObject" in all_cypher
    assert "[:ABOUT]->(obj:ArchaeologyObject" in all_cypher
    assert "[:SUPPORTED_BY]->(ev:Evidence)" in all_cypher
    assert "[:EXTRACTED_FROM]->(page:Page)" in all_cypher
    assert "[:FROM_VERSION]->(version:DocumentVersion)" in all_cypher


def test_get_object_evidence_bundle_builds_text_claims_from_db_rows():
    driver = (
        ScriptedFakeNeo4jDriver()
        .respond(
            "RETURN properties(obj) AS obj",
            [{"obj": {"canonical_name": "1지점 청동기시대 1호 주거지"}}],
        )
        .respond(
            "[:MENTIONS]->(obj:ArchaeologyObject",
            [
                {
                    "source": {
                        "id": "g_b1",
                        "text": "규모는 길이 275cm이다",
                        "block_type": "paragraph",
                        "bbox": [1.0, 2.0, 3.0, 4.0],
                    },
                    "page": {"id": "ver_g_p1", "physical_page": 1},
                    "version": {"id": "ver_g", "stage": "1차", "sha256": "sha256_g"},
                },
                {
                    "source": {"id": "g_b2", "text": "길이 2.45m로 기록되었다"},
                    "page": {"id": "ver_g_p1", "physical_page": 1},
                    "version": {"id": "ver_g", "stage": "1차", "sha256": "sha256_g"},
                },
            ],
        )
    )
    repo = CanonicalRepository(driver=driver, database="test_db")

    bundle = repo.get_object_evidence_bundle("obj_t")

    assert bundle.canonical_name == "1지점 청동기시대 1호 주거지"
    assert len(bundle.text_claims) == 2
    claim1 = bundle.text_claims[0]
    assert claim1.id == "ev_claim_obj_t_g_b1"
    assert claim1.kind == "text_claim"
    assert claim1.value == "규모는 길이 275cm이다"
    assert claim1.source_sha256 == "sha256_g"
    assert claim1.document_version_id == "ver_g"
    assert claim1.page_id == "ver_g_p1"
    assert claim1.bbox == (1.0, 2.0, 3.0, 4.0)
    assert bundle.text_claims[1].value == "길이 2.45m로 기록되었다"


def test_get_object_evidence_bundle_builds_reference_evidences_from_db_rows():
    driver = (
        ScriptedFakeNeo4jDriver()
        .respond("RETURN properties(obj) AS obj", [{"obj": {"canonical_name": "O"}}])
        .respond(
            "[:REFERENCES]->(ref:Reference)",
            [
                {
                    "source": {"id": "g_b1", "text": "도판 : 45"},
                    "ref": {
                        "id": "ref_g_b1_plate_45",
                        "ref_type": "plate",
                        "number": "45",
                        "raw_text": "도판 : 45",
                        "source_block_id": "g_b1",
                        "bbox": [5.0, 6.0, 7.0, 8.0],
                        "physical_page": 1,
                    },
                    "page": {"id": "ver_g_p1"},
                    "version": {"id": "ver_g", "sha256": "sha256_g"},
                }
            ],
        )
    )
    repo = CanonicalRepository(driver=driver, database="test_db")

    bundle = repo.get_object_evidence_bundle("obj_r")

    assert len(bundle.references) == 1
    ev = bundle.references[0]
    assert ev.kind == "reference"
    assert ev.value == {"ref_type": "plate", "number": "45", "raw_text": "도판 : 45"}
    assert ev.source_sha256 == "sha256_g"
    assert ev.document_version_id == "ver_g"
    assert ev.page_id == "ver_g_p1"
    assert ev.bbox == (5.0, 6.0, 7.0, 8.0)


def test_get_object_evidence_bundle_builds_plate_and_drawing_claims_from_assets():
    rows = [
        {
            "asset_label": "Plate",
            "asset": {
                "id": "plate_45",
                "number": "45",
                "title": "1지점 청동기시대 1호 주거지",
                "raw_identifier": "【도판 45】",
                "source_sha256": "sha256_plate",
                "document_version_id": "ver_plate",
                "physical_page": 47,
                "bbox": [10.0, 10.0, 20.0, 20.0],
            },
            "ref": {"id": "ref_x"},
            "page": None,
            "version": None,
        },
        {
            "asset_label": "Drawing",
            "asset": {
                "id": "drawing_30",
                "number": "30",
                "title": "1지점 1호 주거지 실측",
                "raw_identifier": "【도면 30】",
                "source_sha256": "sha256_draw",
                "document_version_id": "ver_drawing",
                "physical_page": 12,
            },
            "ref": None,
            "page": None,
            "version": None,
        },
    ]
    driver = (
        ScriptedFakeNeo4jDriver()
        .respond("RETURN properties(obj) AS obj", [{"obj": {"canonical_name": "O"}}])
        .respond("[:DEPICTS]->(obj:ArchaeologyObject", rows)
    )
    repo = CanonicalRepository(driver=driver, database="test_db")

    bundle = repo.get_object_evidence_bundle("obj_p")

    assert len(bundle.plate_claims) == 1
    plate_ev = bundle.plate_claims[0]
    assert plate_ev.kind == "plate_caption"
    assert plate_ev.value == {
        "label": "Plate",
        "plate_number": "45",
        "title": "1지점 청동기시대 1호 주거지",
        "raw_identifier": "【도판 45】",
    }
    assert plate_ev.source_sha256 == "sha256_plate"
    assert plate_ev.document_version_id == "ver_plate"
    assert plate_ev.page_id == "ver_plate_p47"
    assert plate_ev.bbox == (10.0, 10.0, 20.0, 20.0)

    assert len(bundle.drawing_claims) == 1
    draw_ev = bundle.drawing_claims[0]
    assert draw_ev.kind == "drawing_caption"
    assert draw_ev.document_version_id == "ver_drawing"


def test_get_object_evidence_bundle_gathers_candidate_supported_evidence():
    rows = [
        {
            "cand": {"id": "cand_x"},
            "ev": {
                "id": "ev_vlm_obj_v",
                "kind": "vlm_observation",
                "source_sha256": "sha256_plate",
                "document_version_id": "ver_v",
                "page_id": "ver_v_p47",
                "value": '{"observation": "석관묘 확인"}',
                "confidence": 0.8,
            },
            "page": {"id": "ver_v_p47"},
            "version": {"id": "ver_v", "sha256": "sha256_v"},
        },
        {
            "cand": {"id": "cand_y"},
            "ev": {
                "id": "ev_ver_obj_v",
                "kind": "version_change",
                "source_sha256": "sha256_v",
                "document_version_id": "ver_v",
                "page_id": "ver_v_p47",
                "value": "수정",
            },
            "page": {"id": "ver_v_p47"},
            "version": {"id": "ver_v", "sha256": "sha256_v"},
        },
    ]
    driver = (
        ScriptedFakeNeo4jDriver()
        .respond("RETURN properties(obj) AS obj", [{"obj": {"canonical_name": "O"}}])
        .respond("[:SUPPORTED_BY]->(ev:Evidence)", rows)
    )
    repo = CanonicalRepository(driver=driver, database="test_db")

    bundle = repo.get_object_evidence_bundle("obj_v")

    assert len(bundle.visual_observations) == 1
    vlm = bundle.visual_observations[0]
    assert vlm.id == "ev_vlm_obj_v"
    assert vlm.kind == "vlm_observation"
    assert vlm.value == {"observation": "석관묘 확인"}
    assert len(bundle.version_claims) == 1
    assert bundle.version_claims[0].kind == "version_change"
    assert bundle.version_claims[0].value == "수정"


def test_get_object_evidence_bundle_raises_when_db_provenance_missing():
    driver = (
        ScriptedFakeNeo4jDriver()
        .respond("RETURN properties(obj) AS obj", [{"obj": {"canonical_name": "O"}}])
        .respond(
            "[:MENTIONS]->(obj:ArchaeologyObject",
            [
                {
                    "source": {"id": "g_b1", "text": "길이 275cm"},
                    "page": {"id": "ver_g_p1"},
                    "version": None,
                }
            ],
        )
    )
    repo = CanonicalRepository(driver=driver, database="test_db")

    with pytest.raises(ValueError, match="source_sha256 is required"):
        repo.get_object_evidence_bundle("obj_bad")


def _gate_d_page() -> ParsedPage:
    return ParsedPage(
        page_id="ver_gd_p1",
        physical_page=1,
        printed_page=1,
        header="",
        raw_text=(
            "1지점 청동기시대 1호 주거지 규모는 길이 275cm이다. "
            "1지점 청동기시대 1호 주거지 평면조사에서는 길이 2.45m로 기록되었다."
        ),
        normalized_text=(
            "1지점 청동기시대 1호 주거지 규모는 길이 275cm이다. "
            "1지점 청동기시대 1호 주거지 평면조사에서는 길이 2.45m로 기록되었다."
        ),
        text_blocks=[
            TextBlockData(
                block_id="p1_b1",
                text="1지점 청동기시대 1호 주거지 규모는 길이 275cm이다.",
                normalized_text="1지점 청동기시대 1호 주거지 규모는 길이 275cm이다.",
                block_type="paragraph",
                order=1,
                source_sha256="sha256_gd",
            ),
            TextBlockData(
                block_id="p1_b2",
                text="1지점 청동기시대 1호 주거지 평면조사에서는 길이 2.45m로 기록되었다.",
                normalized_text="1지점 청동기시대 1호 주거지 평면조사에서는 길이 2.45m로 기록되었다.",
                block_type="paragraph",
                order=2,
                source_sha256="sha256_gd",
            ),
        ],
        captions=[],
        source_sha256="sha256_gd",
    )


def _graph_bundle_rows() -> list[dict[str, Any]]:
    return [
            {"obj": {"canonical_name": "1지점 청동기시대 1호 주거지"}},
            {
            "source": {"id": "g_b1", "text": "규모는 길이 275cm이다"},
            "page": {"id": "ver_g_p1", "physical_page": 1},
            "version": {"id": "ver_g", "stage": "1차", "sha256": "sha256_g"},
        },
        {
            "source": {"id": "g_b2", "text": "길이 2.45m로 기록되었다"},
            "page": {"id": "ver_g_p1", "physical_page": 1},
            "version": {"id": "ver_g", "stage": "1차", "sha256": "sha256_g"},
        },
    ]


@pytest.mark.anyio
async def test_orchestrator_feeds_graph_bundle_to_rule_engine():
    """Gate B: with a DB bundle available, RuleEngine must consume graph rows
    (evidence ids built from graph block ids), not the in-memory lists."""
    driver = ScriptedFakeNeo4jDriver()
    driver.respond("RETURN properties(obj) AS obj", [{"obj": {"canonical_name": "1지점 청동기시대 1호 주거지"}}])
    driver.respond("[:MENTIONS]->(obj:ArchaeologyObject", _graph_bundle_rows()[1:])
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_graph_bundle",
        body_version_id="ver_g",
        body_pages=[_gate_d_page()],
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    numeric = [c for c in result.candidates if c.rule_category == "numeric_value"]
    assert len(numeric) >= 1
    for cand in numeric:
        ev_ids = {ev.id for ev in cand.evidences}
        assert ev_ids, "candidate must reference bundle-sourced evidences"
        assert all(ev_id.endswith("_g_b1") or ev_id.endswith("_g_b2") for ev_id in ev_ids), ev_ids
        assert all(ev.source_sha256 for ev in cand.evidences)
    assert not any("DEGRADED" in w for w in result.warnings), result.warnings


@pytest.mark.anyio
async def test_rewired_orchestrator_degrades_explicitly_when_graph_has_no_evidence():
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        allow_degraded_mode=True,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_deg",
        body_version_id="ver_deg",
        body_pages=[_gate_d_page()],
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    numeric = [c for c in result.candidates if c.rule_category == "numeric_value"]
    assert numeric, "in-memory fallback must still find the Gate-D conflict"
    all_ev_ids = {ev.id for c in numeric for ev in c.evidences}
    assert any("p1_b" in e for e in all_ev_ids)
    assert any("DEGRADED" in w for w in result.warnings), (
        "degradation must be explicit and recorded, never silent"
    )


@pytest.mark.anyio
async def test_production_mode_fails_closed_when_graph_db_unavailable():
    """Review P0-2: with allow_degraded_mode=False (production default), a
    missing canonical repository fails the run closed with
    GRAPH_EVIDENCE_UNAVAILABLE — never a silent in-memory fallback."""
    driver = FakeNeo4jDriver()
    review_repo = ReviewRepository(driver=driver, database="test_db")
    orchestrator = ProofreadingOrchestrator(
        canonical_repo=None,
        review_repo=review_repo,
    )

    with pytest.raises(RuntimeError, match="GRAPH_EVIDENCE_UNAVAILABLE"):
        await orchestrator.run_proofreading(
            project_id="proj_fail_closed",
            body_version_id="ver_g",
            body_pages=[_gate_d_page()],
            enable_vlm=False,
            enable_ai_review=False,
        )

    failed_saves = [
        q["kwargs"]
        for q in driver.queries
        if q["kwargs"].get("status") == "failed"
        and q["kwargs"].get("error_code") == "GRAPH_EVIDENCE_UNAVAILABLE"
    ]
    assert failed_saves, "the run must be persisted as failed with GRAPH_EVIDENCE_UNAVAILABLE"


@pytest.mark.anyio
async def test_production_mode_fails_closed_when_bundle_query_raises():
    """Review P0-2: a graph DB error during bundle retrieval fails the run
    closed in production mode (never a silent in-memory fallback)."""

    class _RaisingDriver(FakeNeo4jDriver):
        def execute_query(self, query: str, **kwargs):
            self.queries.append({"query": query, "kwargs": kwargs})
            if "RETURN properties(obj) AS obj" in query:
                raise RuntimeError("Database connection lost")
            return [], None, None

    driver = _RaisingDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")
    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )

    with pytest.raises(RuntimeError, match="GRAPH_EVIDENCE_UNAVAILABLE"):
        await orchestrator.run_proofreading(
            project_id="proj_fail_closed_raise",
            body_version_id="ver_g",
            body_pages=[_gate_d_page()],
            enable_vlm=False,
            enable_ai_review=False,
        )

    failed_saves = [
        q["kwargs"]
        for q in driver.queries
        if q["kwargs"].get("status") == "failed"
        and q["kwargs"].get("error_code") == "GRAPH_EVIDENCE_UNAVAILABLE"
    ]
    assert failed_saves, "the run must be persisted as failed with GRAPH_EVIDENCE_UNAVAILABLE"


@pytest.mark.anyio
async def test_production_mode_marks_object_unresolved_when_bundle_missing():
    """Review P0-2: a required object graph bundle missing in production mode
    marks the object unresolved/manual_review with a persisted reason and does
    NOT produce a candidate from in-memory lists (anti-pattern #6)."""
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")
    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_unresolved",
        body_version_id="ver_g",
        body_pages=[_gate_d_page()],
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert result.candidates == [], "no candidate may be produced from in-memory lists"
    assert result.unresolved, "the object must be marked unresolved"
    assert result.unresolved[0]["reason_code"] == "GRAPH_EVIDENCE_UNAVAILABLE"
    assert result.summary["unresolved_objects"] == 1

    unresolved_saves = [
        q for q in driver.queries if "unresolvedObjects" in q["query"]
    ]
    assert unresolved_saves, "the unresolved reason must be persisted, never silently skipped"
    entry = unresolved_saves[0]["kwargs"]["entry"]
    assert entry["object_id"] == result.unresolved[0]["object_id"]
    assert entry["reason_code"] == "GRAPH_EVIDENCE_UNAVAILABLE"


@pytest.mark.anyio
async def test_production_mode_produces_candidate_from_graph_evidence():
    """Review P0-2: production mode (allow_degraded_mode=False) with a valid
    graph bundle produces the candidate from graph evidence and records no
    unresolved objects."""
    driver = ScriptedFakeNeo4jDriver()
    driver.respond(
        "RETURN properties(obj) AS obj",
        [{"obj": {"canonical_name": "1지점 청동기시대 1호 주거지"}}],
    )
    driver.respond("[:MENTIONS]->(obj:ArchaeologyObject", _graph_bundle_rows()[1:])
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")
    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_prod_graph",
        body_version_id="ver_g",
        body_pages=[_gate_d_page()],
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    numeric = [c for c in result.candidates if c.rule_category == "numeric_value"]
    assert numeric, "production mode must produce the candidate from graph evidence"
    assert result.unresolved == []
    assert not any("DEGRADED" in w for w in result.warnings)


@pytest.mark.anyio
async def test_kill_switch_relationship_deletion_changes_analysis_outcome():
    """Review P0-2 / Test B (unit): deleting a load-bearing graph relationship
    (simulated by an empty bundle on the second run) must change the analysis
    OUTCOME — the candidate produced from graph evidence is NOT produced and
    the object becomes unresolved with a persisted reason. A node-count-only
    assertion is insufficient; the candidate outcome must change."""
    # Run 1: valid graph evidence -> production mode produces the numeric candidate
    driver = ScriptedFakeNeo4jDriver()
    driver.respond(
        "RETURN properties(obj) AS obj",
        [{"obj": {"canonical_name": "1지점 청동기시대 1호 주거지"}}],
    )
    driver.respond("[:MENTIONS]->(obj:ArchaeologyObject", _graph_bundle_rows()[1:])
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")
    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_kill_switch",
        body_version_id="ver_g",
        body_pages=[_gate_d_page()],
        enable_vlm=False,
        enable_ai_review=False,
    )
    assert result.status == "completed"
    numeric = [c for c in result.candidates if c.rule_category == "numeric_value"]
    assert numeric, "run 1 must produce the numeric candidate from graph evidence"
    assert result.unresolved == []

    # Run 2: the load-bearing MENTIONS relationship is gone -> empty bundle
    empty_driver = FakeNeo4jDriver()
    canonical_repo2 = CanonicalRepository(driver=empty_driver, database="test_db")
    review_repo2 = ReviewRepository(driver=empty_driver, database="test_db")
    orchestrator2 = ProofreadingOrchestrator(
        canonical_repo=canonical_repo2,
        review_repo=review_repo2,
    )
    result2 = await orchestrator2.run_proofreading(
        project_id="proj_kill_switch",
        body_version_id="ver_g",
        body_pages=[_gate_d_page()],
        enable_vlm=False,
        enable_ai_review=False,
    )
    assert result2.status == "completed"
    numeric2 = [c for c in result2.candidates if c.rule_category == "numeric_value"]
    assert numeric2 == [], (
        "run 2 must NOT produce the candidate after the relationship is deleted"
    )
    assert result2.unresolved, "the object must be marked unresolved with a persisted reason"
    assert result2.unresolved[0]["reason_code"] == "GRAPH_EVIDENCE_UNAVAILABLE"
    assert result2.summary["unresolved_objects"] == 1

    unresolved_saves = [
        q for q in empty_driver.queries if "unresolvedObjects" in q["query"]
    ]
    assert unresolved_saves, "the unresolved reason must be persisted, never silently skipped"
    entry = unresolved_saves[0]["kwargs"]["entry"]
    assert entry["object_id"] == result2.unresolved[0]["object_id"]
    assert entry["reason_code"] == "GRAPH_EVIDENCE_UNAVAILABLE"


def _real_driver():
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


def test_real_neo4j_object_evidence_bundle_traversal():
    """Real Neo4j: the full evidence traversal (Gate B) from persisted nodes.

    Scoped ids (bundle_test_*) are deleted afterwards so the shared database is
    never touched outside the test scope.
    """
    driver = _real_driver()
    if driver is None:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    scope = f"bundle_test_{uuid.uuid4().hex[:8]}"
    version_id = f"{scope}_ver"
    page_id = f"{scope}_p1"
    b1_id = f"{scope}_b1"
    b2_id = f"{scope}_b2"
    obj_id = f"{scope}_obj"
    plate_id = f"{scope}_plate45"
    ref_id = f"{scope}_ref"
    cand_id = f"{scope}_cand"
    vlm_ev_id = f"{scope}_vlm_ev"
    ver_ev_id = f"{scope}_ver_ev"
    try:
        driver.execute_query(
            """
            CREATE (v:DocumentVersion {id: $version_id, stage: '1차', sha256: 'sha256_body'})
            CREATE (p:Page {id: $page_id, physical_page: 5, printed_page: 5})
            CREATE (b1:TextBlock {id: $b1_id, text: '규모는 길이 275cm이다', order: 1, block_type: 'paragraph'})
            CREATE (b2:TextBlock {id: $b2_id, text: '길이 2.45m로 기록되었다', order: 2, block_type: 'paragraph'})
            CREATE (obj:ArchaeologyObject {id: $obj_id, canonical_name: '1지점 청동기시대 6호 석관묘',
                    point: '1지점', period: '청동기시대', type: '석관묘', number: '6호'})
            CREATE (ref:Reference {id: $ref_id, ref_type: 'plate', number: '45', raw_text: '도판 : 45',
                    source_block_id: $b1_id, source_sha256: 'sha256_body', physical_page: 5})
            CREATE (plate:Plate {id: $plate_id, number: '45', physical_page: 47,
                    title: '1지점 청동기시대 6호 석관묘', source_sha256: 'sha256_plate',
                    document_version_id: $version_id, raw_identifier: '【도판 45】'})
            CREATE (cand:CorrectionCandidate {id: $cand_id, rule_category: 'numeric_value', status: 'pending_review'})
            CREATE (ev1:Evidence {id: $vlm_ev_id, kind: 'vlm_observation',
                    source_sha256: 'sha256_plate', document_version_id: $version_id, page_id: $page_id,
                    value: '{"observation": "perceived cist"}', confidence: 0.8})
            CREATE (ev2:Evidence {id: $ver_ev_id, kind: 'version_change',
                    source_sha256: 'sha256_body', document_version_id: $version_id, page_id: $page_id,
                    value: 'modified in 2nd pass'})
            CREATE (v)-[:HAS_PAGE]->(p)
            CREATE (p)-[:HAS_BLOCK]->(b1)
            CREATE (p)-[:HAS_BLOCK]->(b2)
            CREATE (b1)-[:MENTIONS]->(obj)
            CREATE (b2)-[:MENTIONS]->(obj)
            CREATE (b1)-[:REFERENCES]->(ref)
            CREATE (ref)-[:RESOLVES_TO]->(plate)
            CREATE (plate)-[:DEPICTS]->(obj)
            CREATE (cand)-[:ABOUT]->(obj)
            CREATE (cand)-[:SUPPORTED_BY]->(ev1)
            CREATE (cand)-[:SUPPORTED_BY]->(ev2)
            CREATE (ev1)-[:EXTRACTED_FROM]->(p)
            CREATE (ev1)-[:FROM_VERSION]->(v)
            CREATE (ev2)-[:EXTRACTED_FROM]->(p)
            CREATE (ev2)-[:FROM_VERSION]->(v)
            """,
            version_id=version_id,
            page_id=page_id,
            b1_id=b1_id,
            b2_id=b2_id,
            obj_id=obj_id,
            ref_id=ref_id,
            plate_id=plate_id,
            cand_id=cand_id,
            vlm_ev_id=vlm_ev_id,
            ver_ev_id=ver_ev_id,
        )
        repo = CanonicalRepository(driver=driver)
        bundle = repo.get_object_evidence_bundle(obj_id)

        assert bundle.object_id == obj_id
        assert bundle.canonical_name == "1지점 청동기시대 6호 석관묘"
        claim_values = {_text(ev.value) for ev in bundle.text_claims}
        assert any("275cm" in v for v in claim_values)
        assert any("2.45m" in v for v in claim_values)
        assert bundle.text_claims[0].source_sha256 == "sha256_body"
        assert len(bundle.references) == 1
        assert bundle.references[0].value.get("number") == "45"
        assert len(bundle.plate_claims) == 1
        assert bundle.plate_claims[0].kind == "plate_caption"
        assert bundle.plate_claims[0].document_version_id == version_id
        assert any(ev.kind == "vlm_observation" for ev in bundle.visual_observations)
        assert any(ev.kind == "version_change" for ev in bundle.version_claims)

        engine = RuleEngine(header_patterns=[])
        candidates = engine.check_object_bundle_consistency(bundle, plates=[], drawings=[])
        assert any(c.rule_category == "numeric_value" for c in candidates)
    finally:
        driver.execute_query(
            "MATCH (n) WHERE n.id STARTS WITH $scope DETACH DELETE n",
            scope=scope,
        )
        driver.close()


def _text(value: Any) -> str:
    return str(value)

def test_get_object_evidence_bundle_threads_analysis_run_id_into_reconstructed_claims():
    """Review 5.1 fold-in: graph-traversal claims carry the analysis run id so
    save_candidates cannot clobber it to None on persistence. Candidate-backed
    evidence (stored rows) keeps its ORIGINAL producing run id instead."""
    vlm_row = {
        "cand": {"id": "cand_x", "rule_category": "figure_plate_table_photo_ref"},
        "ev": {
            "id": "ev_vlm_obj_t",
            "kind": "vlm_observation",
            "source_sha256": "sha256_plate",
            "document_version_id": "ver_v",
            "page_id": "ver_v_p47",
            "value": '{"observation": "석관묘 확인"}',
            "confidence": 0.8,
            "analysis_run_id": "run_old",
        },
        "page": {"id": "ver_v_p47"},
        "version": {"id": "ver_v", "sha256": "sha256_v"},
    }
    driver = (
        ScriptedFakeNeo4jDriver()
        .respond("RETURN properties(obj) AS obj", [{"obj": {"canonical_name": "O"}}])
        .respond(
            "[:REFERENCES]->(ref:Reference)",
            [
                {
                    "source": {"id": "g_b1"},
                    "ref": {
                        "id": "ref_g_b1_plate_45",
                        "ref_type": "plate",
                        "number": "45",
                        "source_block_id": "g_b1",
                    },
                    "page": {"id": "ver_g_p1"},
                    "version": {"id": "ver_g", "sha256": "sha256_g"},
                }
            ],
        )
        .respond("[:SUPPORTED_BY]->(ev:Evidence)", [vlm_row])
        .respond(
            "[:DEPICTS]->(obj:ArchaeologyObject",
            [
                {
                    "asset_label": "Plate",
                    "asset": {
                        "id": "plate_45",
                        "number": "45",
                        "title": "1지점 청동기시대 1호 주거지",
                        "source_sha256": "sha256_plate",
                        "document_version_id": "ver_plate",
                        "physical_page": 47,
                    },
                    "ref": None,
                    "page": None,
                    "version": None,
                }
            ],
        )
        .respond(
            "[:MENTIONS]->(obj:ArchaeologyObject",
            [
                {
                    "source": {"id": "g_b1", "text": "규모는 길이 275cm이다"},
                    "page": {"id": "ver_g_p1", "physical_page": 1},
                    "version": {"id": "ver_g", "stage": "1차", "sha256": "sha256_g"},
                }
            ],
        )
    )
    repo = CanonicalRepository(driver=driver, database="test_db")

    bundle = repo.get_object_evidence_bundle("obj_t", analysis_run_id="run_9")

    assert bundle.text_claims[0].analysis_run_id == "run_9"
    assert bundle.references[0].analysis_run_id == "run_9"
    assert bundle.plate_claims[0].analysis_run_id == "run_9"
    assert bundle.visual_observations[0].analysis_run_id == "run_old", (
        "stored candidate-backed evidence keeps its original producing run"
    )


@pytest.mark.anyio
async def test_orchestrator_persists_analysis_run_id_on_graph_sourced_evidence_with_matching_block_ids():
    """Review 5.1 fold-in: when graph block ids equal the in-memory block ids
    (the production collision), save_candidates must NOT clobber the evidence
    analysis_run_id to None."""
    driver = (
        ScriptedFakeNeo4jDriver()
        .respond(
            "RETURN properties(obj) AS obj",
            [{"obj": {"canonical_name": "1지점 청동기시대 1호 주거지"}}],
        )
        .respond(
            "[:MENTIONS]->(obj:ArchaeologyObject",
            [
                {
                    "source": {"id": "p1_b1", "text": "규모는 길이 275cm이다"},
                    "page": {"id": "ver_g_p1", "physical_page": 1},
                    "version": {"id": "ver_g", "stage": "1차", "sha256": "sha256_g"},
                },
                {
                    "source": {"id": "p1_b2", "text": "평면조사에서는 길이 2.45m로 기록되었다"},
                    "page": {"id": "ver_g_p1", "physical_page": 1},
                    "version": {"id": "ver_g", "stage": "1차", "sha256": "sha256_g"},
                },
            ],
        )
    )
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_run_id",
        body_version_id="ver_g",
        body_pages=[_gate_d_page()],
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    numeric = [c for c in result.candidates if c.rule_category == "numeric_value"]
    assert numeric
    assert not any("DEGRADED" in w for w in result.warnings)

    save_candidates_queries = [
        q for q in driver.queries if "MERGE (cand:CorrectionCandidate" in q["query"]
    ]
    assert save_candidates_queries, "save_candidates must run"
    for q in save_candidates_queries:
        for cand in q["kwargs"]["candidates"]:
            assert cand["analysis_run_id"] == result.analysis_run_id
            ev_params = cand["evidences"]
            assert ev_params
            for ev_p in ev_params:
                assert ev_p["analysis_run_id"] == result.analysis_run_id, ev_p["id"]
                assert ev_p["id"].endswith("_p1_b1") or ev_p["id"].endswith("_p1_b2")
