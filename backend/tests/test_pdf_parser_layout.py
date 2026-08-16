import hashlib
from pathlib import Path
from unittest.mock import patch
import pytest

from app.domain.canonical_models import ReferenceData
from app.domain.document_structure import ParsedPage, TextBlockData, CaptionData
from app.services.pdf_parser import PDFParser


def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").is_dir() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("Could not find repository root containing src/ directory")


REPO_ROOT = _find_repo_root()
SRC_PDF_1 = REPO_ROOT / "src/완성까지 가던 교정본들/11.8-본문-1차 교정/11.8-115집 논산 산노리 산17-1번지 유적-본문-1차 교정.pdf"
SRC_PDF_2 = REPO_ROOT / "src/완성까지 가던 교정본들/11.19-2차 교정/11.19-115집 논산 산노리 산17-1번지 유적-본문-2차 교정.pdf"
SRC_PDF_3 = REPO_ROOT / "src/완성까지 가던 교정본들/11.21-3차 교정/11.21-115집 논산 산노리 산17-1번지 유적-본문-3차 교정.pdf"


def test_pdf_parser_extracts_bounding_boxes_and_sha256():
    parser = PDFParser()
    pages = parser.parse_page_range(SRC_PDF_1, start_page=105, end_page=105)
    assert len(pages) == 1
    page = pages[0]
    
    # Verify SHA-256 hash
    with open(SRC_PDF_1, "rb") as f:
        expected_sha = hashlib.sha256(f.read()).hexdigest()
    assert page.source_sha256 == expected_sha
    
    # Verify bounding boxes exist on text blocks
    assert len(page.text_blocks) > 0
    non_null_bboxes = [b for b in page.text_blocks if b.bbox is not None]
    assert len(non_null_bboxes) == len(page.text_blocks)
    
    for block in page.text_blocks:
        assert isinstance(block.bbox, tuple)
        assert len(block.bbox) == 4
        x0, y0, x1, y1 = block.bbox
        assert x0 <= x1
        assert y0 <= y1
        assert block.source_sha256 == expected_sha
        
    # Verify captions carry bbox and sha256
    assert len(page.captions) > 0
    for caption in page.captions:
        assert caption.bbox is not None
        assert isinstance(caption.bbox, tuple)
        assert len(caption.bbox) == 4
        assert caption.source_sha256 == expected_sha


def test_pdf_parser_extract_single_reference():
    parser = PDFParser()
    
    # 1. Single plate reference
    cap_plate = parser._extract_caption(
        "① 유물(도판 : 45)",
        caption_id="p1_c1",
        bbox=(10.0, 20.0, 100.0, 30.0),
        source_sha256="fake_sha",
        physical_page=1,
    )
    assert cap_plate is not None
    assert cap_plate.drawing_number is None
    assert cap_plate.plate_number == "45"
    assert cap_plate.is_blank_reference is False
    assert len(cap_plate.references) == 1
    ref = cap_plate.references[0]
    assert isinstance(ref, ReferenceData)
    assert ref.ref_type == "plate"
    assert ref.number == "45"
    assert ref.source_block_id == "p1_c1"
    assert ref.source_sha256 == "fake_sha"
    assert ref.bbox == (10.0, 20.0, 100.0, 30.0)
    assert ref.physical_page == 1

    # 2. Single drawing reference
    cap_draw = parser._extract_caption(
        "① 2호 토광묘(도면 : 57)",
        caption_id="p1_c2",
        bbox=(15.0, 25.0, 105.0, 35.0),
        source_sha256="fake_sha",
        physical_page=1,
    )
    assert cap_draw is not None
    assert cap_draw.drawing_number == "57"
    assert cap_draw.plate_number is None
    assert cap_draw.is_blank_reference is False
    assert len(cap_draw.references) == 1
    ref_d = cap_draw.references[0]
    assert ref_d.ref_type == "drawing"
    assert ref_d.number == "57"
    assert ref_d.source_block_id == "p1_c2"


def test_pdf_parser_extract_middle_dot_references():
    parser = PDFParser()
    
    # Standard middle dot U+00B7 (·)
    cap_dot1 = parser._extract_caption(
        "① 유구(도판 : 45·46)",
        caption_id="p1_c1",
        source_sha256="hash1",
        physical_page=5,
    )
    assert cap_dot1 is not None
    assert cap_dot1.plate_number in ["45", "45·46"]
    assert len(cap_dot1.references) == 2
    assert [r.number for r in cap_dot1.references] == ["45", "46"]
    assert all(r.ref_type == "plate" for r in cap_dot1.references)

    # Korean middle dot U+318D (ㆍ)
    cap_dot2 = parser._extract_caption(
        "① 유구(도판 : 45ㆍ46)",
        caption_id="p1_c2",
        source_sha256="hash1",
        physical_page=5,
    )
    assert cap_dot2 is not None
    assert len(cap_dot2.references) == 2
    assert [r.number for r in cap_dot2.references] == ["45", "46"]
    assert all(r.ref_type == "plate" for r in cap_dot2.references)


def test_pdf_parser_extract_range_references():
    parser = PDFParser()
    
    # Plate range 22~28
    cap_range_plate = parser._extract_caption(
        "① 유구(도판 : 22~28)",
        caption_id="p2_c1",
        source_sha256="hash2",
        physical_page=10,
    )
    assert cap_range_plate is not None
    assert len(cap_range_plate.references) == 7
    expected_plate_numbers = [str(n) for n in range(22, 29)]
    assert [r.number for r in cap_range_plate.references] == expected_plate_numbers
    assert all(r.ref_type == "plate" for r in cap_range_plate.references)

    # Drawing range 16~22 with dash/tilde
    cap_range_draw = parser._extract_caption(
        "① 유구(도면 : 16~22)",
        caption_id="p2_c2",
        source_sha256="hash2",
        physical_page=10,
    )
    assert cap_range_draw is not None
    assert len(cap_range_draw.references) == 7
    expected_draw_numbers = [str(n) for n in range(16, 23)]
    assert [r.number for r in cap_range_draw.references] == expected_draw_numbers
    assert all(r.ref_type == "drawing" for r in cap_range_draw.references)


def test_pdf_parser_extract_compound_caption_references():
    parser = PDFParser()
    cap = parser._extract_caption(
        "① 유구(도면 : 30, 도판 : 45ㆍ46)",
        caption_id="p3_c1",
        bbox=(50.0, 60.0, 200.0, 80.0),
        source_sha256="hash3",
        physical_page=20,
    )
    assert cap is not None
    assert cap.drawing_number == "30"
    assert cap.plate_number in ["45", "45ㆍ46"]
    assert cap.is_blank_reference is False
    assert len(cap.references) == 3
    
    # 1 drawing ref + 2 plate refs
    drawings = [r for r in cap.references if r.ref_type == "drawing"]
    plates = [r for r in cap.references if r.ref_type == "plate"]
    
    assert len(drawings) == 1
    assert drawings[0].number == "30"
    assert drawings[0].source_block_id == "p3_c1"
    assert drawings[0].bbox == (50.0, 60.0, 200.0, 80.0)
    assert drawings[0].physical_page == 20
    
    assert len(plates) == 2
    assert [p.number for p in plates] == ["45", "46"]
    assert all(p.source_block_id == "p3_c1" for p in plates)
    assert all(p.physical_page == 20 for p in plates)


def test_pdf_parser_extract_blank_and_non_captions():
    parser = PDFParser()
    
    # Blank compound
    c1 = parser._extract_caption("① 유구(도면 : , 도판 : )", caption_id="p1_c1")
    assert c1 is not None
    assert c1.is_blank_reference is True
    assert c1.drawing_number is None
    assert c1.plate_number is None
    assert len(c1.references) == 0

    # Blank drawing only
    c2 = parser._extract_caption("① 2호 토광묘(도면 : )", caption_id="p1_c2")
    assert c2 is not None
    assert c2.is_blank_reference is True
    assert len(c2.references) == 0

    # Blank plate only
    c3 = parser._extract_caption("① 유물(도판 : )", caption_id="p1_c3")
    assert c3 is not None
    assert c3.is_blank_reference is True
    assert len(c3.references) == 0

    # Non-caption text
    c4 = parser._extract_caption("일반적인 본문 설명 문장입니다.", caption_id="p1_c4")
    assert c4 is None


def test_pdf_parser_real_pdf_structured_references_3rd_draft():
    parser = PDFParser()
    # In 3rd draft, page 201 contains ① 유구(도면 : 95, 도판 : 136·137)
    pages = parser.parse_page_range(SRC_PDF_3, start_page=201, end_page=201)
    assert len(pages) == 1
    page = pages[0]
    
    # Find caption with 136·137
    captions = [c for c in page.captions if any(r.number == "137" for r in c.references)]
    assert len(captions) >= 1
    target_cap = captions[0]
    
    ref_numbers = [r.number for r in target_cap.references]
    assert "95" in ref_numbers
    assert "136" in ref_numbers
    assert "137" in ref_numbers
    
    # Verify that text blocks also carry references
    matching_blocks = [b for b in page.text_blocks if any(r.number == "137" for r in b.references)]
    assert len(matching_blocks) >= 1


def test_pdf_parser_parse_pdf_full_and_mode():
    parser = PDFParser()
    # parse_pdf should accept mode argument and return parsed pages
    pages = parser.parse_page_range(SRC_PDF_1, start_page=105, end_page=106, mode="report_body")
    assert len(pages) == 2
    assert all(isinstance(p, ParsedPage) for p in pages)
    assert pages[0].source_sha256 is not None
