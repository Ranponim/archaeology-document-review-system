from pathlib import Path
from typing import Any
import pytest

from app.domain.canonical_models import ReferenceData
from app.domain.document_structure import (
    CaptionData,
    ParsedPage,
    TextBlockData,
    make_block_id,
    make_caption_id,
    make_page_id,
    make_reference_id,
)
from app.graph.canonical_repository import CanonicalRepository
from app.graph.review_repository import ReviewRepository
from app.services.pdf_parser import PDFParser


class FakeNeo4jDriver:
    def __init__(self, records_to_return: list[dict[str, Any]] | None = None):
        self.queries: list[dict[str, Any]] = []
        self.records_to_return = records_to_return or []

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        return self.records_to_return, None, None


def test_canonical_id_helper_functions():
    # 1. Page ID
    assert make_page_id("ver_2026", 10) == "ver_2026_p10"
    assert make_page_id("doc_v1", 1) == "doc_v1_p1"

    # 2. Block ID
    assert make_block_id("ver_2026", 10, 3) == "ver_2026_p10_b3"
    assert make_block_id("doc_v1", 1, 1) == "doc_v1_p1_b1"

    # 3. Caption ID
    assert make_caption_id("ver_2026", 10, 2) == "ver_2026_p10_c2"
    assert make_caption_id("doc_v1", 1, 1) == "doc_v1_p1_c1"

    # 4. Reference ID (cleans numbers and formats predictably)
    assert (
        make_reference_id("ver_2026_p10_b3", "plate", "45")
        == "ref_ver_2026_p10_b3_plate_45"
    )
    assert (
        make_reference_id("ver_2026_p10_c2", "drawing", "12~15")
        == "ref_ver_2026_p10_c2_drawing_12_15"
    )
    assert (
        make_reference_id("doc_v1_p1_b1", "plate", "2·3ㆍ4")
        == "ref_doc_v1_p1_b1_plate_2_3_4"
    )


def test_pdf_parser_generates_unified_ids_with_version_id(tmp_path: Path):
    parser = PDFParser()

    # Test parser internal caption extraction with custom version_id
    lines = [
        "1호 석관묘 본문 (도면 : 12, 도판 : 45)",
        "도면 : 13 , 도판 : 46",
    ]
    captions = parser._extract_captions(
        lines, physical_page=5, version_id="ver_custom_body"
    )
    assert len(captions) == 2
    assert captions[0].caption_id == "ver_custom_body_p5_c1"
    assert captions[1].caption_id == "ver_custom_body_p5_c2"
    assert captions[0].references[0].source_block_id == "ver_custom_body_p5_c1"
    assert captions[0].references[1].source_block_id == "ver_custom_body_p5_c1"

    # Test parser reference extraction with block_id
    block_id = make_block_id("ver_custom_body", 5, 2)
    refs = parser._extract_references(
        "본문 내용입니다 (도판 : 77).",
        source_block_id=block_id,
        physical_page=5,
    )
    assert len(refs) == 1
    assert refs[0].source_block_id == "ver_custom_body_p5_b2"
    assert refs[0].ref_type == "plate"
    assert refs[0].number == "77"


def test_review_repository_page_to_param_preserves_node_ids():
    repo = ReviewRepository(driver=None)

    block = TextBlockData(
        block_id="ver_test_p12_b1",
        text="본문 텍스트",
        normalized_text="본문 텍스트",
        order=1,
    )
    caption = CaptionData(
        caption_id="ver_test_p12_c1",
        raw_text="도판 1. 전경",
        plate_number="1",
    )
    page = ParsedPage(
        physical_page=12,
        printed_page=10,
        header="머리말",
        raw_text="본문 텍스트\n도판 1. 전경",
        normalized_text="본문 텍스트 도판 1. 전경",
        text_blocks=[block],
        captions=[caption],
        page_id="ver_test_p12",
    )

    page_param = repo._page_to_param(version_id="ver_test", page=page)

    # Must preserve exact ID without double prefixing
    assert page_param["id"] == "ver_test_p12"
    assert page_param["blocks"][0]["id"] == "ver_test_p12_b1"
    assert page_param["captions"][0]["id"] == "ver_test_p12_c1"


def test_canonical_repository_reference_id_matching():
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    ref = ReferenceData(
        ref_type="plate",
        number="22~28",
        source_block_id="ver_alpha_p105_b4",
        raw_text="도판 : 22~28",
        physical_page=105,
    )

    ref_id = repo._reference_id(ref)
    assert ref_id == "ref_ver_alpha_p105_b4_plate_22_28"

    repo.save_references([ref])
    assert len(driver.queries) == 1
    cypher = driver.queries[0]["query"]
    params = driver.queries[0]["kwargs"]["references"]

    assert "MERGE (ref:Reference {id: r.id})" in cypher
    assert "OPTIONAL MATCH (b:TextBlock {id: r.source_block_id})" in cypher
    assert "OPTIONAL MATCH (c:Caption {id: r.source_block_id})" in cypher
    assert params[0]["id"] == "ref_ver_alpha_p105_b4_plate_22_28"
    assert params[0]["source_block_id"] == "ver_alpha_p105_b4"


def test_cross_component_canonical_id_harmony():
    """Verify that Parser -> ReviewRepo -> CanonicalRepo all share the exact same IDs for graph traversal."""
    version_id = "project1_v1"
    physical_page = 42

    page_id = make_page_id(version_id, physical_page)
    block_id = make_block_id(version_id, physical_page, 1)
    caption_id = make_caption_id(version_id, physical_page, 1)

    ref_from_block = ReferenceData(
        ref_type="plate",
        number="5",
        source_block_id=block_id,
        physical_page=physical_page,
    )
    ref_from_caption = ReferenceData(
        ref_type="drawing",
        number="12",
        source_block_id=caption_id,
        physical_page=physical_page,
    )

    block = TextBlockData(
        block_id=block_id,
        text="도판 5 참조",
        normalized_text="도판 5 참조",
        order=1,
        references=[ref_from_block],
    )
    caption = CaptionData(
        caption_id=caption_id,
        raw_text="도면 12 유구도",
        drawing_number="12",
        references=[ref_from_caption],
    )

    page = ParsedPage(
        physical_page=physical_page,
        printed_page=40,
        header="조사",
        raw_text="...",
        normalized_text="...",
        text_blocks=[block],
        captions=[caption],
        page_id=page_id,
    )

    review_repo = ReviewRepository(driver=None)
    page_param = review_repo._page_to_param(version_id=version_id, page=page)

    canonical_repo = CanonicalRepository(driver=None)
    block_ref_id = canonical_repo._reference_id(ref_from_block)
    caption_ref_id = canonical_repo._reference_id(ref_from_caption)

    # TextBlock ID matches source_block_id in reference
    assert page_param["blocks"][0]["id"] == block_id
    assert ref_from_block.source_block_id == page_param["blocks"][0]["id"]
    assert block_ref_id == f"ref_{block_id}_plate_5"

    # Caption ID matches source_block_id in reference
    assert page_param["captions"][0]["id"] == caption_id
    assert ref_from_caption.source_block_id == page_param["captions"][0]["id"]
    assert caption_ref_id == f"ref_{caption_id}_drawing_12"
