import pytest
from app.graph.schema import CONSTRAINTS, ensure_schema
from app.graph.review_repository import ReviewRepository
from app.domain.document_structure import ParsedPage, TextBlockData, CaptionData
from app.domain.review_models import CorrectionCandidateData, EvidenceData


class FakeNeo4jRecord:
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key: str):
        return self._data[key]

    def get(self, key: str, default=None):
        return self._data.get(key, default)


class FakeNeo4jDriver:
    def __init__(self, records_to_return=None):
        self.queries: list[dict] = []
        self.records_to_return = [
            FakeNeo4jRecord(r) for r in (records_to_return or [])
        ]

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        return self.records_to_return, None, None


def test_schema_includes_review_nodes_constraints():
    labels = [label for _, label in CONSTRAINTS]
    assert "Page" in labels
    assert "TextBlock" in labels
    assert "Caption" in labels
    assert "CorrectionCandidate" in labels
    assert "Evidence" in labels


def test_review_repository_builds_cypher_parameters():
    page = ParsedPage(
        physical_page=105,
        printed_page=101,
        header="백제문화유산연구원 | 101",
        raw_text="2호 토광묘",
        normalized_text="2호 토광묘",
        text_blocks=[
            TextBlockData(block_id="p105_b1", text="2호 토광묘", normalized_text="2호 토광묘", order=1)
        ],
        captions=[
            CaptionData(caption_id="p105_c1", raw_text="① 유구(도면 : , 도판 : )", is_blank_reference=True)
        ]
    )
    
    cand = CorrectionCandidateData(
        candidate_id="cand_1",
        rule_category="figure_plate_table_photo_ref",
        change_type="modified",
        status="confirmed",
        original_text="도면 : ",
        proposed_text="도면 : 57",
        evidence=EvidenceData(
            version_from="1차",
            version_to="2차",
            physical_page_from=105,
            physical_page_to=111,
            printed_page_from=101,
            printed_page_to=102,
            rule_name="figure_plate_table_photo_ref",
            rationale="Filled blank drawing reference"
        )
    )
    
    # Verify repository methods exist and produce correct payload structures
    repo = ReviewRepository(driver=None)
    page_param = repo._page_to_param(version_id="ver_1", page=page)
    assert page_param["physical_page"] == 105
    assert page_param["printed_page"] == 101
    assert len(page_param["blocks"]) == 1
    assert len(page_param["captions"]) == 1
    
    cand_param = repo._candidate_to_param(cand)
    assert cand_param["candidate_id"] == "cand_1"
    assert cand_param["rule_category"] == "figure_plate_table_photo_ref"
    assert cand_param["evidence"]["version_from"] == "1차"


def test_create_analysis_run_links_run_to_selected_versions():
    """P0-5: create_analysis_run must create (run)-[:ANALYZES]->(body),
    (run)-[:USES_PLATE]->(plate), (run)-[:USES_DRAWING]->(drawing) so the
    selected body/plate/drawing versions are inspectable from the run graph."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    repo.create_analysis_run(
        project_id="p1",
        run_id="run_1",
        body_version_id="ver_body_3",
        plate_version_id="ver_plate_3",
        drawing_version_id="ver_draw_3",
        version_stage="3차",
    )

    assert len(driver.queries) == 1
    q = driver.queries[0]
    cypher = q["query"]
    kwargs = q["kwargs"]

    assert "MERGE (proj)-[:HAS_RUN]->(run)" in cypher
    assert "MERGE (run)-[:ANALYZES]->(body)" in cypher
    assert "MERGE (run)-[:USES_PLATE]->(plate)" in cypher
    assert "MERGE (run)-[:USES_DRAWING]->(drawing)" in cypher
    assert kwargs["body_version_id"] == "ver_body_3"
    assert kwargs["plate_version_id"] == "ver_plate_3"
    assert kwargs["drawing_version_id"] == "ver_draw_3"
    assert kwargs["version_stage"] == "3차"


def test_create_analysis_run_skips_missing_optional_versions():
    """P0-5: a run without plate/drawing versions still links ANALYZES to the
    body version and never fabricates USES_* edges."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    repo.create_analysis_run(
        project_id="p1",
        run_id="run_2",
        body_version_id="ver_body_1",
        version_stage="1차",
    )

    cypher = driver.queries[0]["query"]
    assert "MERGE (run)-[:ANALYZES]->(body)" in cypher
    assert "USES_PLATE" in cypher
    assert "USES_DRAWING" in cypher
    assert driver.queries[0]["kwargs"]["plate_version_id"] is None
    assert driver.queries[0]["kwargs"]["drawing_version_id"] is None
