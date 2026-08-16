"""Task 6 tests: persist (asset)-[:DEPICTS]->(ArchaeologyObject) links.

ArchaeologyObject is the semantic join key between textual mentions
(TextBlock/Caption-[:MENTIONS]->ArchaeologyObject, Task 2) and visual assets
(Plate/PlatePanel/Drawing/DrawingRegion-[:DEPICTS]->ArchaeologyObject).

Covered here:
- Deterministic caption/title matching (canonical_name, 지점/유구/유물 identifiers).
- Ambiguity safety: a caption that merely contains a number must NOT create an
  edge; non-unique identifiers must not be guessed.
- Cypher shape: MERGE (asset)-[:DEPICTS]->(obj), direction asset -> object.
- Orchestrator ordering: plates/drawings/objects are persisted BEFORE DEPICTS.
- Real Neo4j verification with scoped ids (skipped when unavailable).
"""
from typing import Any
import os
import uuid

import pytest
from neo4j import GraphDatabase

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    DrawingRegionData,
    PlateData,
    PlatePanelData,
)
from app.domain.document_structure import ParsedPage, TextBlockData
from app.graph.canonical_repository import CanonicalRepository, compute_depicts_links
from app.graph.review_repository import ReviewRepository
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


def _object(
    object_id: str = "obj_1",
    point: str = "1지점",
    period: str = "청동기시대",
    number: str = "6호",
    type_: str = "석관묘",
) -> ArchaeologyObjectData:
    return ArchaeologyObjectData(
        object_id=object_id,
        site=point,
        point=point,
        period=period,
        type=type_,
        number=number,
        canonical_name=" ".join(p for p in [point, period, number, type_] if p),
    )


def _plate(plate_id: str = "plate_1", title: str = "") -> PlateData:
    return PlateData(
        plate_id=plate_id,
        number="45",
        physical_page=1,
        title=title,
        raw_identifier="【도판 45】",
    )


def _drawing(drawing_id: str = "drawing_1", title: str = "") -> DrawingData:
    return DrawingData(
        drawing_id=drawing_id,
        number="30",
        physical_page=2,
        title=title,
        raw_identifier="【도면 30】",
    )


# ---------------------------------------------------------------------------
# Deterministic matching logic (pure function)
# ---------------------------------------------------------------------------


def test_compute_depicts_links_matches_full_canonical_name():
    """Plate title equal to the object canonical_name creates exactly one link."""
    obj = _object()
    plate = _plate(title="1지점 청동기시대 6호 석관묘")

    links, ambiguous = compute_depicts_links(plates=[plate], objects=[obj])

    assert ambiguous == []
    assert len(links) == 1
    assert links[0].asset_label == "Plate"
    assert links[0].asset_id == "plate_1"
    assert links[0].object_id == "obj_1"


def test_compute_depicts_links_matches_point_number_type_identifiers():
    """Title with 지점+유구/유물 identifiers (no period) still links deterministically."""
    obj = _object()
    plate = _plate(title="1지점 6호 석관묘 전경")

    links, ambiguous = compute_depicts_links(plates=[plate], objects=[obj])

    assert ambiguous == []
    assert len(links) == 1
    assert links[0].object_id == "obj_1"


def test_compute_depicts_links_matches_unique_number_type_identifier():
    """Title with only 유구/유물 identifier links when that identifier is unique."""
    obj = _object()
    plate = _plate(title="6호 석관묘 실측")

    links, ambiguous = compute_depicts_links(plates=[plate], objects=[obj])

    assert ambiguous == []
    assert len(links) == 1
    assert links[0].object_id == "obj_1"


def test_compute_depicts_links_number_type_shared_across_points_is_ambiguous():
    """'6호 석관묘' with two objects in different 지점 must NOT be guessed."""
    obj_a = _object(object_id="obj_a", point="1지점")
    obj_b = _object(object_id="obj_b", point="2지점")
    plate = _plate(title="6호 석관묘")

    links, ambiguous = compute_depicts_links(plates=[plate], objects=[obj_a, obj_b])

    assert links == []
    assert ambiguous == [("Plate", "plate_1")]


def test_compute_depicts_links_bare_number_in_caption_creates_no_edge():
    """A caption that merely contains a number must NOT create a DEPICTS edge.

    This is the Case 6 invariant: '4. 조사 후_45.JPG' / '도판 45' is not
    canonical identity for an object merely because it contains '45'.
    """
    obj = _object(number="45호")
    plate = _plate(title="도판 45")
    drawing = _drawing(title="45")

    links, ambiguous = compute_depicts_links(
        plates=[plate], drawings=[drawing], objects=[obj]
    )

    assert links == []
    assert ambiguous == []


def test_compute_depicts_links_period_disambiguates_shared_point_number_type():
    """Full canonical name (with period) links even when another object shares 지점/유구/유물."""
    obj_a = _object(object_id="obj_a", period="청동기시대")
    obj_b = _object(object_id="obj_b", period="조선시대")
    plate = _plate(title="1지점 청동기시대 6호 석관묘")

    links, ambiguous = compute_depicts_links(plates=[plate], objects=[obj_a, obj_b])

    assert ambiguous == []
    assert len(links) == 1
    assert links[0].object_id == "obj_a"


def test_compute_depicts_links_point_number_type_shared_across_periods_is_ambiguous():
    """'1지점 6호 석관묘' without period matches two objects -> no edge."""
    obj_a = _object(object_id="obj_a", period="청동기시대")
    obj_b = _object(object_id="obj_b", period="조선시대")
    plate = _plate(title="1지점 6호 석관묘")

    links, ambiguous = compute_depicts_links(plates=[plate], objects=[obj_a, obj_b])

    assert links == []
    assert ambiguous == [("Plate", "plate_1")]


def test_compute_depicts_links_panels_and_regions():
    """PlatePanel captions and DrawingRegion titles link with their own labels."""
    obj = _object()
    panel = PlatePanelData(
        panel_id="panel_1",
        plate_id="plate_1",
        panel_index=1,
        caption="1지점 청동기시대 6호 석관묘 전경",
    )
    region = DrawingRegionData(
        region_id="region_1",
        drawing_id="drawing_1",
        number="1",
        title="1지점 청동기시대 6호 석관묘 평면",
    )

    links, ambiguous = compute_depicts_links(
        panels=[panel], regions=[region], objects=[obj]
    )

    assert ambiguous == []
    assert len(links) == 2
    by_label = {l.asset_label: l for l in links}
    assert by_label["PlatePanel"].asset_id == "panel_1"
    assert by_label["PlatePanel"].object_id == "obj_1"
    assert by_label["DrawingRegion"].asset_id == "region_1"
    assert by_label["DrawingRegion"].object_id == "obj_1"


def test_compute_depicts_links_nested_panels_and_regions_are_flattened():
    """Panels/regions nested inside PlateData/DrawingData are also considered."""
    obj = _object()
    panel = PlatePanelData(
        panel_id="panel_nested",
        plate_id="plate_1",
        panel_index=1,
        caption="1지점 청동기시대 6호 석관묘",
    )
    plate = _plate(title="")
    plate = PlateData(
        plate_id=plate.plate_id,
        number=plate.number,
        physical_page=plate.physical_page,
        title=plate.title,
        panels=[panel],
    )
    region = DrawingRegionData(
        region_id="region_nested",
        drawing_id="drawing_1",
        number="1",
        title="1지점 청동기시대 6호 석관묘",
    )
    drawing = DrawingData(
        drawing_id="drawing_1",
        number="30",
        physical_page=2,
        title="",
        regions=[region],
    )

    links, ambiguous = compute_depicts_links(
        plates=[plate], drawings=[drawing], objects=[obj]
    )

    assert ambiguous == []
    assert len(links) == 2
    by_label = {l.asset_label: l for l in links}
    assert by_label["PlatePanel"].asset_id == "panel_nested"
    assert by_label["DrawingRegion"].asset_id == "region_nested"


def test_compute_depicts_links_empty_objects_returns_no_links():
    links, ambiguous = compute_depicts_links(plates=[_plate(title="1지점 청동기시대 6호 석관묘")])
    assert links == []
    assert ambiguous == []


# ---------------------------------------------------------------------------
# CanonicalRepository persistence (FakeDriver records Cypher)
# ---------------------------------------------------------------------------


def test_link_visual_assets_to_objects_merges_depicts_asset_to_object():
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    obj = _object()
    plate = _plate(title="1지점 청동기시대 6호 석관묘")

    repo.link_visual_assets_to_objects(plates=[plate], objects=[obj])

    assert len(driver.queries) == 1
    q = driver.queries[0]
    cypher = q["query"]
    kwargs = q["kwargs"]

    # Direction must be (asset)-[:DEPICTS]->(obj), never the reverse
    assert "MERGE (asset)-[:DEPICTS]->(obj)" in cypher
    assert "MERGE (obj)-[:DEPICTS]->(asset)" not in cypher
    assert "MATCH (asset:Plate {id: l.asset_id})" in cypher
    assert "MATCH (obj:ArchaeologyObject {id: l.object_id})" in cypher
    assert kwargs.get("database_") == "test_db"
    assert len(kwargs["links"]) == 1
    assert kwargs["links"][0] == {"asset_id": "plate_1", "object_id": "obj_1"}


def test_link_visual_assets_to_objects_marks_ambiguous_assets_semantic_review():
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    obj_a = _object(object_id="obj_a", point="1지점")
    obj_b = _object(object_id="obj_b", point="2지점")
    plate = _plate(title="6호 석관묘")

    repo.link_visual_assets_to_objects(plates=[plate], objects=[obj_a, obj_b])

    assert len(driver.queries) == 1
    q = driver.queries[0]
    cypher = q["query"]
    kwargs = q["kwargs"]

    # No DEPICTS edge for the ambiguous asset; it is flagged for semantic review
    assert "DEPICTS" not in cypher
    assert "SET asset.depicts_status = 'semantic_review'" in cypher
    assert kwargs["assets"] == [{"asset_id": "plate_1"}]


def test_link_visual_assets_to_objects_no_matches_executes_nothing():
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    obj = _object()
    plate = _plate(title="도판 45")

    repo.link_visual_assets_to_objects(plates=[plate], objects=[obj])

    assert driver.queries == []


def test_link_visual_assets_to_objects_without_driver_is_noop():
    repo = CanonicalRepository(driver=None)
    obj = _object()
    plate = _plate(title="1지점 청동기시대 6호 석관묘")
    repo.link_visual_assets_to_objects(plates=[plate], objects=[obj])  # must not raise


# ---------------------------------------------------------------------------
# Orchestrator wiring: DEPICTS after save_plates/save_drawings/save_archaeology_objects
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_orchestrator_links_depicts_after_persisting_assets_and_objects():
    """DEPICTS merge must execute AFTER plates, drawings, and objects are saved."""
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    page = ParsedPage(
        page_id="doc_v1_p1",
        physical_page=1,
        printed_page=1,
        header="Header",
        raw_text="1지점 청동기시대 1호 석관묘에서 출토되었다.",
        normalized_text="1지점 청동기시대 1호 석관묘에서 출토되었다.",
        text_blocks=[
            TextBlockData(
                block_id="block_101",
                text="1지점 청동기시대 1호 석관묘에서 출토되었다.",
                normalized_text="1지점 청동기시대 1호 석관묘에서 출토되었다.",
                order=1,
                block_type="paragraph",
            )
        ],
        captions=[],
    )

    plate = PlateData(
        plate_id="plate_1",
        number="1",
        physical_page=5,
        title="1지점 청동기시대 1호 석관묘",
        raw_identifier="【도판 1】",
    )
    drawing = DrawingData(
        drawing_id="drawing_1",
        number="1",
        physical_page=6,
        title="1지점 청동기시대 1호 석관묘 실측도",
        raw_identifier="【도면 1】",
    )

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_depicts_order",
        body_version_id="doc_v1",
        body_pages=[page],
        plates=[plate],
        drawings=[drawing],
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert result.objects_resolved == 1

    depicts_idx = -1
    save_plates_idx = -1
    save_drawings_idx = -1
    save_objects_idx = -1

    for idx, q in enumerate(driver.queries):
        cypher = q["query"]
        if "MERGE (asset)-[:DEPICTS]->(obj)" in cypher:
            depicts_idx = idx
        if "MERGE (plate:Plate {id: p.id})" in cypher:
            save_plates_idx = idx
        if "MERGE (drawing:Drawing {id: d.id})" in cypher:
            save_drawings_idx = idx
        if "MERGE (obj:ArchaeologyObject {id: o.id})" in cypher:
            save_objects_idx = idx

    assert depicts_idx != -1, "DEPICTS merge query was not executed"
    assert save_plates_idx != -1, "save_plates query was not executed"
    assert save_drawings_idx != -1, "save_drawings query was not executed"
    assert save_objects_idx != -1, "save_archaeology_objects query was not executed"
    assert save_plates_idx < depicts_idx, (
        f"Ordering violation: save_plates (idx {save_plates_idx}) must precede DEPICTS (idx {depicts_idx})"
    )
    assert save_drawings_idx < depicts_idx, (
        f"Ordering violation: save_drawings (idx {save_drawings_idx}) must precede DEPICTS (idx {depicts_idx})"
    )
    assert save_objects_idx < depicts_idx, (
        f"Ordering violation: save_archaeology_objects (idx {save_objects_idx}) must precede DEPICTS (idx {depicts_idx})"
    )

    # The DEPICTS queries must carry the matched plate and drawing pairs
    depicts_queries = [
        q["query"] for q in driver.queries if "MERGE (asset)-[:DEPICTS]->(obj)" in q["query"]
    ]
    assert any("Plate" in c for c in depicts_queries)
    assert any("Drawing" in c for c in depicts_queries)


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


def test_real_neo4j_depicts_links_with_scoped_ids():
    """Real Neo4j: DEPICTS edges persist and bare-number captions do not link.

    Uses scoped ids (depicts_test_*) and deletes them afterwards so the shared
    database is never touched outside the test scope.
    """
    driver = _real_driver()
    if driver is None:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    scope = f"depicts_test_{uuid.uuid4().hex[:8]}"
    try:
        repo = CanonicalRepository(driver=driver)

        obj = _object(object_id=f"{scope}_obj_1")
        plate = _plate(plate_id=f"{scope}_plate_1", title="1지점 청동기시대 6호 석관묘")
        bare_number_plate = _plate(plate_id=f"{scope}_plate_2", title="도판 45")

        # Ordering guarantee: assets and objects are persisted before linking
        repo.save_plates([plate, bare_number_plate])
        repo.save_archaeology_objects([obj])

        repo.link_visual_assets_to_objects(
            plates=[plate, bare_number_plate], objects=[obj]
        )

        # Deterministic title match -> exactly one DEPICTS edge, asset -> object
        recs, _, _ = driver.execute_query(
            "MATCH (a:Plate {id: $pid})-[:DEPICTS]->(o:ArchaeologyObject {id: $oid}) "
            "RETURN a.id AS aid, o.id AS oid",
            pid=plate.plate_id,
            oid=obj.object_id,
        )
        assert len(recs) == 1
        assert recs[0]["aid"] == plate.plate_id
        assert recs[0]["oid"] == obj.object_id

        # Bare-number caption -> no DEPICTS edge at all
        recs2, _, _ = driver.execute_query(
            "MATCH (a:Plate {id: $pid})-[:DEPICTS]->(o) RETURN count(o) AS c",
            pid=bare_number_plate.plate_id,
        )
        assert recs2[0]["c"] == 0

        # Linked asset carries depicts_status
        recs3, _, _ = driver.execute_query(
            "MATCH (a:Plate {id: $pid}) RETURN a.depicts_status AS status",
            pid=plate.plate_id,
        )
        assert recs3[0]["status"] == "linked"
    finally:
        driver.execute_query(
            "MATCH (n) WHERE n.id STARTS WITH $scope DETACH DELETE n",
            scope=scope,
        )
        driver.close()