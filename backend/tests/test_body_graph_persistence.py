from typing import Any
import pytest

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    PlateData,
    PlatePanelData,
    ReferenceData,
)
from app.domain.document_structure import CaptionData, ParsedPage, TextBlockData
from app.graph.canonical_repository import CanonicalRepository
from app.graph.review_repository import ReviewRepository
from app.services.plate_parser import PlateIndex
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


def test_review_repository_save_pages_and_blocks_full_hierarchy():
    """Verify (doc_ver)-[:HAS_PAGE]->(page), (page)-[:HAS_BLOCK]->(block), (page)-[:HAS_CAPTION]->(caption)."""
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="test_db")

    page = ParsedPage(
        page_id="doc_v1_p1",
        physical_page=1,
        printed_page=1,
        header="Header text",
        raw_text="Body text paragraph.\nFigure 1 caption.",
        normalized_text="Body text paragraph. Figure 1 caption.",
        text_blocks=[
            TextBlockData(
                block_id="doc_v1_p1_b1",
                text="Body text paragraph.",
                normalized_text="Body text paragraph.",
                order=1,
                block_type="paragraph",
            ),
        ],
        captions=[
            CaptionData(
                caption_id="doc_v1_p1_c1",
                raw_text="【도판 1】 유물 사진",
                plate_number="1",
            ),
        ],
    )

    repo.save_pages_and_blocks(version_id="doc_v1", pages=[page])

    assert len(driver.queries) == 1
    query_info = driver.queries[0]
    cypher = query_info["query"]
    kwargs = query_info["kwargs"]

    assert kwargs.get("version_id") == "doc_v1"
    assert kwargs.get("database_") == "test_db"
    assert len(kwargs["pages"]) == 1

    # Check hierarchy relationships in Cypher
    assert "HAS_PAGE" in cypher
    assert "HAS_BLOCK" in cypher
    assert "HAS_CAPTION" in cypher
    assert "(page)-[:HAS_BLOCK]->(block)" in cypher or "MERGE (page)-[:HAS_BLOCK]->(block)" in cypher
    assert "(page)-[:HAS_CAPTION]->(cap)" in cypher or "MERGE (page)-[:HAS_CAPTION]->(cap)" in cypher


def test_canonical_repository_save_references_links_blocks_and_captions():
    """Verify (block)-[:REFERENCES]->(ref) and (caption)-[:REFERENCES]->(ref)."""
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    refs = [
        ReferenceData(
            ref_type="plate",
            number="10",
            source_block_id="block_101",
            raw_text="도판 10",
        ),
        ReferenceData(
            ref_type="drawing",
            number="5",
            source_block_id="caption_202",
            raw_text="도면 5",
        ),
    ]

    repo.save_references(refs)

    assert len(driver.queries) == 1
    cypher = driver.queries[0]["query"]

    # Verify nodes and incoming references relationships
    assert "MERGE (ref:Reference {id: r.id})" in cypher
    assert "OPTIONAL MATCH (b:TextBlock {id: r.source_block_id})" in cypher
    assert "OPTIONAL MATCH (c:Caption {id: r.source_block_id})" in cypher
    assert "MERGE (b)-[:REFERENCES]->(ref)" in cypher
    assert "MERGE (c)-[:REFERENCES]->(ref)" in cypher


def test_canonical_repository_save_archaeology_objects_mentions_direction():
    """Verify strict (source)-[:MENTIONS]->(obj) direction from TextBlock and Caption."""
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    obj = ArchaeologyObjectData(
        object_id="obj_cist_1",
        site="1지점",
        point="1지점",
        period="청동기시대",
        type="석관묘",
        number="1호",
        canonical_name="1지점 청동기시대 1호 석관묘",
        source_block_ids=["block_101", "caption_202"],
    )

    repo.save_archaeology_objects([obj])

    assert len(driver.queries) == 1
    cypher = driver.queries[0]["query"]

    # Must strictly be (source)-[:MENTIONS]->(obj), NOT (obj)-[:MENTIONS]->(source)
    assert "MERGE (b)-[:MENTIONS]->(obj)" in cypher
    assert "MERGE (c)-[:MENTIONS]->(obj)" in cypher
    assert "MERGE (obj)-[:MENTIONS]->(b)" not in cypher
    assert "MERGE (obj)-[:MENTIONS]->(c)" not in cypher


def test_canonical_repository_link_reference_to_target():
    """Verify (ref:Reference)-[:RESOLVES_TO]->(target)."""
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    repo.link_reference_to_target(
        reference_id="ref_block_101_plate_10",
        target_label="Plate",
        target_id="plate_10",
    )

    assert len(driver.queries) == 1
    cypher = driver.queries[0]["query"]
    kwargs = driver.queries[0]["kwargs"]

    assert "MATCH (ref:Reference {id: $reference_id})" in cypher
    assert "MATCH (target:Plate {id: $target_id})" in cypher
    assert "MERGE (ref)-[:RESOLVES_TO]->(target)" in cypher
    assert kwargs["reference_id"] == "ref_block_101_plate_10"
    assert kwargs["target_id"] == "plate_10"


@pytest.mark.anyio
async def test_orchestrator_reference_persistence_ordering():
    """Verify that save_references is called BEFORE link_reference_to_target in orchestrator."""
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    page = ParsedPage(
        page_id="doc_v1_p1",
        physical_page=1,
        printed_page=1,
        header="Header",
        raw_text="1지점 청동기시대 1호 석관묘에서 출토되었다(도판 : 10).",
        normalized_text="1지점 청동기시대 1호 석관묘에서 출토되었다(도판 : 10).",
        text_blocks=[
            TextBlockData(
                block_id="block_101",
                text="1지점 청동기시대 1호 석관묘에서 출토되었다(도판 : 10).",
                normalized_text="1지점 청동기시대 1호 석관묘에서 출토되었다(도판 : 10).",
                order=1,
                block_type="paragraph",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number="10",
                        source_block_id="block_101",
                        raw_text="도판 : 10",
                        physical_page=1,
                    )
                ],
            )
        ],
        captions=[],
    )

    plate = PlateData(
        plate_id="plate_10",
        number="10",
        physical_page=5,
        title="1지점 청동기시대 1호 석관묘",
        raw_identifier="【도판 10】",
    )

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_order_test",
        body_version_id="doc_v1",
        plate_version_id="plate_v1",
        body_pages=[page],
        plates=[plate],
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert result.references_resolved == 1

    # Find the indices of save_references and link_reference_to_target queries
    save_ref_idx = -1
    link_ref_idx = -1

    for idx, q in enumerate(driver.queries):
        cypher = q["query"]
        if "MERGE (ref:Reference {id: r.id})" in cypher:
            save_ref_idx = idx
        if "MERGE (ref)-[:RESOLVES_TO]->(target)" in cypher:
            link_ref_idx = idx

    assert save_ref_idx != -1, "save_references query was not executed"
    assert link_ref_idx != -1, "link_reference_to_target query was not executed"
    assert save_ref_idx < link_ref_idx, (
        f"Reference persistence ordering violation: save_references (idx {save_ref_idx}) "
        f"must execute BEFORE link_reference_to_target (idx {link_ref_idx})"
    )


@pytest.mark.anyio
async def test_orchestrator_persists_full_body_graph_with_captions_and_blocks():
    """Verify orchestrator persists TextBlock & Caption sources for both [:REFERENCES] and [:MENTIONS]."""
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    page = ParsedPage(
        page_id="ver_body_p1",
        physical_page=1,
        printed_page=1,
        header="Header",
        raw_text="1지점 1호 주거지 본문 (도판 1).\n【도판 1】 1지점 1호 주거지 전경",
        normalized_text="1지점 1호 주거지 본문 (도판 1). 【도판 1】 1지점 1호 주거지 전경",
        text_blocks=[
            TextBlockData(
                block_id="b_1",
                text="1지점 1호 주거지 본문 (도판 1).",
                normalized_text="1지점 1호 주거지 본문 (도판 1).",
                order=1,
                block_type="paragraph",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number="1",
                        source_block_id="b_1",
                        raw_text="도판 1",
                        physical_page=1,
                    )
                ],
            )
        ],
        captions=[
            CaptionData(
                caption_id="c_1",
                raw_text="【도판 1】 1지점 1호 주거지 전경",
                plate_number="1",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number="1",
                        source_block_id="c_1",
                        raw_text="【도판 1】",
                        physical_page=1,
                    )
                ],
            )
        ],
    )

    plate = PlateData(
        plate_id="plate_1",
        number="1",
        physical_page=10,
        title="1지점 1호 주거지",
        raw_identifier="【도판 1】",
    )

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_full_body",
        body_version_id="ver_body",
        body_pages=[page],
        plates=[plate],
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"

    all_cypher = [q["query"] for q in driver.queries]

    # Verify pages and blocks
    assert any("HAS_PAGE" in c and "HAS_BLOCK" in c and "HAS_CAPTION" in c for c in all_cypher)

    # Verify references
    assert any("[:REFERENCES]->(ref)" in c for c in all_cypher)

    # Verify mentions with source -> obj direction
    assert any("MERGE (b)-[:MENTIONS]->(obj)" in c and "MERGE (c)-[:MENTIONS]->(obj)" in c for c in all_cypher)

    # Verify resolution
    assert any("[:RESOLVES_TO]->" in c for c in all_cypher)
