from typing import Any
import pytest

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    DrawingRegionData,
    PlateData,
    PlatePanelData,
    ReferenceData,
)
from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.graph.canonical_repository import CanonicalRepository
from app.graph.review_repository import ReviewRepository
from app.graph.schema import CONSTRAINTS, INDEXES, ensure_schema


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


def test_schema_constraints_and_indexes_declarations():
    constraint_labels = [label for _, label in CONSTRAINTS]
    required_constraint_labels = [
        "Reference",
        "Plate",
        "PlatePanel",
        "Drawing",
        "DrawingRegion",
        "ArchaeologyObject",
        "OriginalAsset",
        "ReviewDecision",
        "AnalysisRun",
        "Project",
        "Document",
        "DocumentVersion",
        "Page",
        "TextBlock",
        "Caption",
        "CorrectionCandidate",
        "Evidence",
    ]
    for label in required_constraint_labels:
        assert label in constraint_labels, f"Missing constraint for {label}"

    index_specs = [(label, props) for _, label, props in INDEXES]
    assert ("Plate", ("number",)) in index_specs
    assert ("Drawing", ("number",)) in index_specs
    assert ("DrawingRegion", ("number",)) in index_specs
    assert ("ArchaeologyObject", ("canonical_name",)) in index_specs
    assert ("Reference", ("ref_type", "number")) in index_specs
    assert ("Evidence", ("kind",)) in index_specs
    assert ("DocumentVersion", ("sha256",)) in index_specs
    assert ("CorrectionCandidate", ("rule_category",)) in index_specs


def test_ensure_schema_executes_constraints_and_indexes_on_driver():
    driver = FakeNeo4jDriver()
    ensure_schema(driver, database="test_db")
    assert len(driver.queries) == len(CONSTRAINTS) + len(INDEXES)

    for q in driver.queries:
        assert q["kwargs"].get("database_") == "test_db"
        query_text = q["query"]
        assert "CREATE CONSTRAINT" in query_text or "CREATE INDEX" in query_text


def test_save_references_creates_nodes_and_links_to_source_blocks():
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    refs = [
        ReferenceData(
            ref_type="plate",
            number="45",
            source_block_id="p105_b1",
            raw_text="도판 : 45",
            source_sha256="doc_hash_1",
            bbox=(10.0, 20.0, 100.0, 30.0),
            physical_page=12,
        ),
        ReferenceData(
            ref_type="drawing",
            number="16",
            source_block_id="p105_c1",
            raw_text="도면 : 16",
            source_sha256="doc_hash_1",
            bbox=(15.0, 25.0, 110.0, 35.0),
            physical_page=12,
        ),
    ]

    repo.save_references(refs)

    assert len(driver.queries) == 1
    query_info = driver.queries[0]
    cypher = query_info["query"]
    kwargs = query_info["kwargs"]

    assert "MERGE (ref:Reference {id: r.id})" in cypher
    assert "[:REFERENCES]->(ref)" in cypher
    assert kwargs.get("database_") == "test_db"
    assert len(kwargs["references"]) == 2
    assert kwargs["references"][0]["number"] == "45"
    assert kwargs["references"][0]["ref_type"] == "plate"
    assert kwargs["references"][0]["source_block_id"] == "p105_b1"
    assert kwargs["references"][1]["number"] == "16"
    assert kwargs["references"][1]["ref_type"] == "drawing"


def test_save_plates_and_panels():
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    panel = PlatePanelData(
        panel_id="panel_45_1",
        plate_id="plate_45",
        panel_index=1,
        caption="① 전경",
        bbox=(10.0, 20.0, 200.0, 300.0),
        physical_page=47,
        render_uri="file:///storage/plate_45_1.jpg",
        source_sha256="hash_p1",
    )
    plate = PlateData(
        plate_id="plate_45",
        number="45",
        physical_page=47,
        title="1지점 청동기시대 6호 석관묘",
        bbox=(10.0, 20.0, 500.0, 700.0),
        source_sha256="plate_doc_hash",
        document_version_id="ver_plates_1",
        panels=[panel],
        raw_identifier="【도판 45】",
    )

    repo.save_plates([plate])

    assert len(driver.queries) >= 1
    full_cypher = " ".join(q["query"] for q in driver.queries)
    assert "Plate" in full_cypher
    assert "PlatePanel" in full_cypher
    assert "HAS_PANEL" in full_cypher

    plate_params = driver.queries[0]["kwargs"].get("plates", [])
    assert len(plate_params) == 1
    assert plate_params[0]["id"] == "plate_45"
    assert plate_params[0]["number"] == "45"
    assert plate_params[0]["physical_page"] == 47


def test_save_drawings_and_regions():
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    region = DrawingRegionData(
        region_id="reg_16_1",
        drawing_id="drawing_16",
        number="16-1",
        title="평면도",
        bbox=(50.0, 60.0, 400.0, 400.0),
        physical_page=18,
        render_uri="file:///storage/reg_16_1.png",
        source_sha256="draw_hash_1",
    )
    drawing = DrawingData(
        drawing_id="drawing_16",
        number="16",
        physical_page=18,
        title="1지점 6호 석관묘 실측도",
        bbox=(20.0, 30.0, 550.0, 750.0),
        source_sha256="draw_doc_hash",
        document_version_id="ver_draw_1",
        regions=[region],
        raw_identifier="【도면 16】",
    )

    repo.save_drawings([drawing])

    assert len(driver.queries) >= 1
    full_cypher = " ".join(q["query"] for q in driver.queries)
    assert "Drawing" in full_cypher
    assert "DrawingRegion" in full_cypher
    assert "HAS_REGION" in full_cypher

    drawing_params = driver.queries[0]["kwargs"].get("drawings", [])
    assert len(drawing_params) == 1
    assert drawing_params[0]["id"] == "drawing_16"
    assert drawing_params[0]["number"] == "16"


def test_link_reference_to_target():
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    repo.link_reference_to_target(
        reference_id="ref_p105_b1_plate_45",
        target_label="Plate",
        target_id="plate_45",
    )

    assert len(driver.queries) == 1
    q = driver.queries[0]
    cypher = q["query"]
    kwargs = q["kwargs"]

    assert "MATCH (ref:Reference {id: $reference_id})" in cypher
    assert "MATCH (target:Plate {id: $target_id})" in cypher
    assert "MERGE (ref)-[:RESOLVES_TO]->(target)" in cypher
    assert kwargs["reference_id"] == "ref_p105_b1_plate_45"
    assert kwargs["target_id"] == "plate_45"


def test_link_reference_to_target_validates_label():
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    with pytest.raises(ValueError, match="Invalid target label"):
        repo.link_reference_to_target(
            reference_id="ref_1",
            target_label="MaliciousLabel; DROP TABLE;",
            target_id="target_1",
        )


def test_save_archaeology_objects():
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    obj = ArchaeologyObjectData(
        object_id="obj_site1_bronze_stone_cist_6",
        site="1지점",
        point="1지점",
        period="청동기시대",
        type="석관묘",
        number="6호",
        canonical_name="1지점 청동기시대 6호 석관묘",
        source_block_ids=["p105_b1"],
        source_sha256="doc_hash_1",
    )

    repo.save_archaeology_objects([obj])

    assert len(driver.queries) == 1
    q = driver.queries[0]
    assert "ArchaeologyObject" in q["query"]
    assert "MENTIONS" in q["query"]
    params = q["kwargs"]["objects"]
    assert len(params) == 1
    assert params[0]["id"] == "obj_site1_bronze_stone_cist_6"
    assert params[0]["canonical_name"] == "1지점 청동기시대 6호 석관묘"


def test_get_canonical_evidence_path():
    fake_record = {
        "ref_props": {
            "id": "ref_p105_b1_plate_45",
            "ref_type": "plate",
            "number": "45",
            "raw_text": "도판 : 45",
            "physical_page": 12,
        },
        "target_label": "Plate",
        "target_props": {
            "id": "plate_45",
            "number": "45",
            "physical_page": 47,
            "title": "1지점 청동기시대 6호 석관묘",
            "raw_identifier": "【도판 45】",
        },
        "source_props": {
            "id": "p105_b1",
            "text": "1지점 청동기시대 6호 석관묘 도판 : 45",
        },
        "page_props": {
            "id": "ver_1_p12",
            "physical_page": 12,
            "printed_page": 10,
        },
        "panels": [
            {
                "id": "panel_45_1",
                "caption": "① 전경",
                "panel_index": 1,
            }
        ],
        "regions": [],
        "objects": [
            {
                "id": "obj_6",
                "canonical_name": "1지점 청동기시대 6호 석관묘",
            }
        ],
    }

    driver = FakeNeo4jDriver(records_to_return=[fake_record])
    repo = CanonicalRepository(driver=driver, database="test_db")

    path = repo.get_canonical_evidence_path(reference_id="ref_p105_b1_plate_45")

    assert len(driver.queries) == 1
    assert "MATCH (ref:Reference {id: $reference_id})" in driver.queries[0]["query"]
    assert path["reference"]["number"] == "45"
    assert path["target"]["label"] == "Plate"
    assert path["target"]["properties"]["title"] == "1지점 청동기시대 6호 석관묘"
    assert path["source"]["id"] == "p105_b1"
    assert path["page"]["physical_page"] == 12
    assert len(path["panels"]) == 1
    assert len(path["objects"]) == 1


def test_review_repository_extensions():
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    repo.save_analysis_run(
        project_id="proj_1",
        run_id="run_123",
        status="running",
        model="google/gemini-2.5-flash",
    )
    assert any("AnalysisRun" in q["query"] for q in driver.queries)

    repo.save_review_decision(
        decision_id="dec_1",
        candidate_id="cand_1",
        decision_status="accepted",
        note="Approved by archaeologist",
        reviewer="expert_1",
    )
    assert any("ReviewDecision" in q["query"] for q in driver.queries)
