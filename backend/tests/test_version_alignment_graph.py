"""Task 8 tests: persist version lineage (PRECEDES) and page alignment
(ALIGNED_TO) into the canonical graph.

- ReviewRepository.save_version_precedes() MERGEs
  (v1:DocumentVersion)-[:PRECEDES]->(v2:DocumentVersion) for the ordered
  version list (1차→2차→3차), hard-MATCHing existing DocumentVersion nodes and
  failing closed (raising) when a node is missing (plan §3 Gate G).
- ReviewRepository.save_aligned_pages() MERGEs
  (pageA)-[:ALIGNED_TO {score,status,method,run_id}]->(pageB) for each
  unordered version pair of a row whose status is in the allowed set
  {exact, probable, manual_review}; unmatched rows and rows with fewer than
  two versions produce no edge.
- ProofreadingOrchestrator.persist_version_alignment() runs PageAligner over
  parsed body versions and persists PRECEDES + ALIGNED_TO.
- Real Neo4j verification with scoped ids (skipped when unavailable).
"""
from typing import Any
import os
import uuid

import pytest
from neo4j import GraphDatabase

from app.domain.document_structure import ParsedPage, make_page_id
from app.graph.project_repository import DocumentVersionNotFoundError
from app.graph.review_repository import ReviewRepository
from app.services.page_aligner import AlignedPageRow, AlignmentStatus, PageAligner
from app.services.proofreading_orchestrator import ProofreadingOrchestrator


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


def _make_page(version_id: str, physical_page: int, text: str) -> ParsedPage:
    return ParsedPage(
        page_id=make_page_id(version_id, physical_page),
        physical_page=physical_page,
        printed_page=physical_page,
        header="",
        raw_text=text,
        normalized_text=text,
    )


# ---------------------------------------------------------------------------
# save_version_precedes
# ---------------------------------------------------------------------------


def test_save_version_precedes_merges_precedes_relationships():
    """PRECEDES cypher shape + order: 1차 PRECEDES 2차, 2차 PRECEDES 3차."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    repo.save_version_precedes(
        "proj_align",
        [("v1", "1차"), ("v2", "2차"), ("v3", "3차")],
    )

    assert len(driver.queries) == 1
    q = driver.queries[0]
    cypher = q["query"]
    kwargs = q["kwargs"]

    # Hard MATCH existing DocumentVersion nodes (never MERGE/CREATE them).
    assert "MATCH (v1:DocumentVersion {id: p.from_id})" in cypher
    assert "MATCH (v2:DocumentVersion {id: p.to_id})" in cypher
    assert "MERGE (v1)-[:PRECEDES]->(v2)" in cypher
    assert kwargs.get("database_") == "test_db"
    assert kwargs["pairs"] == [
        {"from_id": "v1", "to_id": "v2"},
        {"from_id": "v2", "to_id": "v3"},
    ]


def test_save_version_precedes_single_version_is_noop():
    """A single version produces no PRECEDES edge and no error."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    repo.save_version_precedes("proj_align", [("v1", "1차")])

    assert driver.queries == []


def test_save_version_precedes_raises_when_version_missing():
    """Fail closed: a missing DocumentVersion node raises (never silently skip)."""
    driver = FakeNeo4jDriver(records_to_return=[{"matched": 1}])
    repo = ReviewRepository(driver=driver, database="test_db")

    with pytest.raises(DocumentVersionNotFoundError):
        repo.save_version_precedes(
            "proj_align",
            [("v1", "1차"), ("v2", "2차"), ("v3", "3차")],
        )


# ---------------------------------------------------------------------------
# save_aligned_pages
# ---------------------------------------------------------------------------


def test_save_aligned_pages_merges_aligned_to_relationships():
    """ALIGNED_TO relationship shape with score/status/method/run_id."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    p1 = _make_page("v1", 1, "논산 산노리 유적 1호 토광묘 조사 개요")
    p2 = _make_page("v2", 1, "논산 산노리 유적 1호 토광묘 조사 개요")
    row = AlignedPageRow(
        row_id=1,
        pages={"1차": p1, "2차": p2},
        similarity_score=1.0,
        sequence_matcher_ratio=1.0,
        status=AlignmentStatus.EXACT,
    )

    repo.save_aligned_pages(
        [row], {"1차": [p1], "2차": [p2]}, "run_1",
        version_ids={"1차": "v1", "2차": "v2"},
    )

    assert len(driver.queries) == 1
    q = driver.queries[0]
    cypher = q["query"]
    kwargs = q["kwargs"]

    assert "MATCH (a:Page {id: e.from_id})" in cypher
    assert "MATCH (b:Page {id: e.to_id})" in cypher
    assert (
        "MERGE (a)-[:ALIGNED_TO {score: e.score, status: e.status, "
        "method: e.method, run_id: e.run_id}]->(b)" in cypher
    )
    assert kwargs.get("database_") == "test_db"
    assert kwargs["edges"] == [
        {
            "from_id": "v1_p1",
            "to_id": "v2_p1",
            "score": 1.0,
            "status": "exact",
            "method": "dtw_weighted",
            "run_id": "run_1",
            "row_id": 1,
        }
    ]


def test_save_aligned_pages_skips_unmatched_rows():
    """Unmatched rows produce no ALIGNED_TO edge."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    p1 = _make_page("v1", 1, "text")
    p2 = _make_page("v2", 1, "text")
    row = AlignedPageRow(
        row_id=1,
        pages={"1차": p1, "2차": p2},
        similarity_score=0.0,
        sequence_matcher_ratio=0.0,
        status=AlignmentStatus.UNMATCHED,
    )

    repo.save_aligned_pages(
        [row], {"1차": [p1], "2차": [p2]}, "run_1",
        version_ids={"1차": "v1", "2차": "v2"},
    )

    assert driver.queries == []


def test_save_aligned_pages_skips_rows_with_single_version():
    """A row with fewer than two versions produces no ALIGNED_TO edge."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    p1 = _make_page("v1", 1, "text")
    row = AlignedPageRow(
        row_id=1,
        pages={"1차": p1},
        similarity_score=1.0,
        sequence_matcher_ratio=1.0,
        status=AlignmentStatus.EXACT,
    )

    repo.save_aligned_pages(
        [row], {"1차": [p1]}, "run_1",
        version_ids={"1차": "v1"},
    )

    assert driver.queries == []


def test_save_aligned_pages_status_mapping():
    """AlignmentStatus enum maps to the allowed string set."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    p1 = _make_page("v1", 1, "text")
    p2 = _make_page("v2", 1, "text")
    row = AlignedPageRow(
        row_id=1,
        pages={"1차": p1, "2차": p2},
        similarity_score=0.7,
        sequence_matcher_ratio=0.7,
        status=AlignmentStatus.PROBABLE,
    )

    repo.save_aligned_pages(
        [row], {"1차": [p1], "2차": [p2]}, "run_1",
        version_ids={"1차": "v1", "2차": "v2"},
    )

    assert driver.queries[0]["kwargs"]["edges"][0]["status"] == "probable"


def test_save_aligned_pages_three_versions_emits_all_unordered_pairs():
    """Three versions present -> three unordered ALIGNED_TO edges."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    p1 = _make_page("v1", 1, "text")
    p2 = _make_page("v2", 1, "text")
    p3 = _make_page("v3", 1, "text")
    row = AlignedPageRow(
        row_id=1,
        pages={"1차": p1, "2차": p2, "3차": p3},
        similarity_score=1.0,
        sequence_matcher_ratio=1.0,
        status=AlignmentStatus.EXACT,
    )

    repo.save_aligned_pages(
        [row],
        {"1차": [p1], "2차": [p2], "3차": [p3]},
        "run_1",
        version_ids={"1차": "v1", "2차": "v2", "3차": "v3"},
    )

    edges = driver.queries[0]["kwargs"]["edges"]
    assert len(edges) == 3
    pairs = {(e["from_id"], e["to_id"]) for e in edges}
    assert pairs == {("v1_p1", "v2_p1"), ("v1_p1", "v3_p1"), ("v2_p1", "v3_p1")}


# ---------------------------------------------------------------------------
# Orchestrator wiring
# ---------------------------------------------------------------------------


def test_orchestrator_persists_version_alignment():
    """persist_version_alignment runs the aligner and persists PRECEDES + ALIGNED_TO."""
    driver = FakeNeo4jDriver()
    review_repo = ReviewRepository(driver=driver, database="test_db")
    orchestrator = ProofreadingOrchestrator(review_repo=review_repo)

    p1 = _make_page("v1", 1, "논산 산노리 유적 1호 토광묘 조사 개요")
    p2 = _make_page("v2", 1, "논산 산노리 유적 1호 토광묘 조사 개요")

    orchestrator.persist_version_alignment(
        project_id="proj_align",
        version_pages={"1차": [p1], "2차": [p2]},
        version_ids={"1차": "v1", "2차": "v2"},
        run_id="run_align",
    )

    all_cypher = "\n".join(q["query"] for q in driver.queries)
    assert "PRECEDES" in all_cypher
    assert "ALIGNED_TO" in all_cypher


def test_orchestrator_persist_version_alignment_single_version_no_error():
    """A single version persists no ALIGNED_TO rows and does not error."""
    driver = FakeNeo4jDriver()
    review_repo = ReviewRepository(driver=driver, database="test_db")
    orchestrator = ProofreadingOrchestrator(review_repo=review_repo)

    p1 = _make_page("v1", 1, "논산 산노리 유적 1호 토광묘 조사 개요")

    orchestrator.persist_version_alignment(
        project_id="proj_align",
        version_pages={"1차": [p1]},
        version_ids={"1차": "v1"},
        run_id="run_align",
    )

    all_cypher = "\n".join(q["query"] for q in driver.queries)
    assert "ALIGNED_TO" not in all_cypher
    assert "PRECEDES" not in all_cypher


# ---------------------------------------------------------------------------
# Real Neo4j verification (scoped ids, skipped when unavailable)
# ---------------------------------------------------------------------------


def _real_driver():
    """Connect to a real Neo4j using NEO4J_* env vars; None when unavailable."""
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


def test_real_neo4j_version_alignment_graph():
    """Real Neo4j: PRECEDES and ALIGNED_TO persist as real relationships.

    Uses scoped ids (align_test_*) and deletes them afterwards so the shared
    database is never touched outside the test scope.
    """
    driver = _real_driver()
    if driver is None:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    scope = f"align_test_{uuid.uuid4().hex[:8]}"
    v1, v2, v3 = f"{scope}_v1", f"{scope}_v2", f"{scope}_v3"
    p1, p2, p3 = make_page_id(v1, 1), make_page_id(v2, 1), make_page_id(v3, 1)
    try:
        driver.execute_query(
            """
            CREATE (v1:DocumentVersion {id: $v1, stage: '1차'})
            CREATE (v2:DocumentVersion {id: $v2, stage: '2차'})
            CREATE (v3:DocumentVersion {id: $v3, stage: '3차'})
            CREATE (p1:Page {id: $p1, physical_page: 1})
            CREATE (p2:Page {id: $p2, physical_page: 1})
            CREATE (p3:Page {id: $p3, physical_page: 1})
            CREATE (v1)-[:HAS_PAGE]->(p1)
            CREATE (v2)-[:HAS_PAGE]->(p2)
            CREATE (v3)-[:HAS_PAGE]->(p3)
            """,
            v1=v1, v2=v2, v3=v3, p1=p1, p2=p2, p3=p3,
        )
        repo = ReviewRepository(driver=driver)

        # Persist PRECEDES (1차→2차→3차)
        repo.save_version_precedes(
            scope, [(v1, "1차"), (v2, "2차"), (v3, "3차")]
        )

        # Persist ALIGNED_TO across the three versions
        page1 = _make_page(v1, 1, "논산 산노리 유적 1호 토광묘 조사 개요")
        page2 = _make_page(v2, 1, "논산 산노리 유적 1호 토광묘 조사 개요")
        page3 = _make_page(v3, 1, "논산 산노리 유적 1호 토광묘 조사 개요")
        row = AlignedPageRow(
            row_id=1,
            pages={"1차": page1, "2차": page2, "3차": page3},
            similarity_score=1.0,
            sequence_matcher_ratio=1.0,
            status=AlignmentStatus.EXACT,
        )
        repo.save_aligned_pages(
            [row],
            {"1차": [page1], "2차": [page2], "3차": [page3]},
            f"{scope}_run",
            version_ids={"1차": v1, "2차": v2, "3차": v3},
        )

        # PRECEDES exists: 1차→2차 and 2차→3차
        recs, _, _ = driver.execute_query(
            "MATCH (a:DocumentVersion {id: $v1})-[:PRECEDES]->"
            "(b:DocumentVersion {id: $v2}) RETURN count(*) AS c",
            v1=v1, v2=v2,
        )
        assert recs[0]["c"] == 1
        recs2, _, _ = driver.execute_query(
            "MATCH (a:DocumentVersion {id: $v2})-[:PRECEDES]->"
            "(b:DocumentVersion {id: $v3}) RETURN count(*) AS c",
            v2=v2, v3=v3,
        )
        assert recs2[0]["c"] == 1

        # ALIGNED_TO exists between the three pages
        recs3, _, _ = driver.execute_query(
            "MATCH (a:Page {id: $p1})-[:ALIGNED_TO]->(b:Page {id: $p2}) "
            "RETURN count(*) AS c",
            p1=p1, p2=p2,
        )
        assert recs3[0]["c"] == 1
        recs4, _, _ = driver.execute_query(
            "MATCH (a:Page {id: $p1})-[:ALIGNED_TO]->(b:Page {id: $p3}) "
            "RETURN count(*) AS c",
            p1=p1, p3=p3,
        )
        assert recs4[0]["c"] == 1

        # ALIGNED_TO carries the exact property set
        recs5, _, _ = driver.execute_query(
            "MATCH (a:Page {id: $p1})-[r:ALIGNED_TO]->(b:Page {id: $p2}) "
            "RETURN r.status AS status, r.score AS score, "
            "r.method AS method, r.run_id AS run_id",
            p1=p1, p2=p2,
        )
        assert recs5[0]["status"] == "exact"
        assert recs5[0]["score"] == 1.0
        assert recs5[0]["method"] == "dtw_weighted"
        assert recs5[0]["run_id"] == f"{scope}_run"
    finally:
        driver.execute_query(
            "MATCH (n) WHERE n.id STARTS WITH $scope DETACH DELETE n",
            scope=scope,
        )
        driver.close()

# ---------------------------------------------------------------------------
# task-11-review §6 nit: save_aligned_pages must use real version ids
# ---------------------------------------------------------------------------


def test_save_aligned_pages_uses_real_version_id_when_page_has_no_bound_id():
    """A ParsedPage without a bound page_id must fall back to
    make_page_id(real version_id, physical_page) — never the stage name."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    p1 = ParsedPage(
        page_id=None,
        physical_page=1,
        printed_page=1,
        header="",
        raw_text="text",
        normalized_text="text",
    )
    p2 = ParsedPage(
        page_id=None,
        physical_page=1,
        printed_page=1,
        header="",
        raw_text="text",
        normalized_text="text",
    )
    row = AlignedPageRow(
        row_id=1,
        pages={"1차": p1, "2차": p2},
        similarity_score=1.0,
        sequence_matcher_ratio=1.0,
        status=AlignmentStatus.EXACT,
    )

    repo.save_aligned_pages(
        [row],
        {"1차": [p1], "2차": [p2]},
        "run_1",
        version_ids={"1차": "v1", "2차": "v2"},
    )

    edge = driver.queries[0]["kwargs"]["edges"][0]
    assert edge["from_id"] == "v1_p1" == make_page_id("v1", 1)
    assert edge["to_id"] == "v2_p1" == make_page_id("v2", 1)
    assert "1차" not in edge["from_id"]
    assert "2차" not in edge["to_id"]


def test_save_aligned_pages_fails_closed_when_version_id_missing():
    """A stage lacking a real version id must fail closed — never fabricate a
    stage-derived page id."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    p1 = ParsedPage(
        page_id=None,
        physical_page=1,
        printed_page=1,
        header="",
        raw_text="text",
        normalized_text="text",
    )
    row = AlignedPageRow(
        row_id=1,
        pages={"1차": p1},
        similarity_score=1.0,
        sequence_matcher_ratio=1.0,
        status=AlignmentStatus.EXACT,
    )

    with pytest.raises(ValueError, match="version_ids missing entries"):
        repo.save_aligned_pages(
            [row],
            {"1차": [p1]},
            "run_1",
            version_ids={},
        )
