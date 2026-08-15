from pathlib import Path
import pytest
from app.services.pdf_parser import PDFParser
from app.domain.document_structure import ParsedPage, TextBlockData, CaptionData


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


def test_pdf_parser_parses_page_range():
    parser = PDFParser()
    pages = parser.parse_page_range(SRC_PDF_1, start_page=105, end_page=114)
    assert len(pages) == 10
    
    first_page = pages[0]
    assert isinstance(first_page, ParsedPage)
    assert first_page.physical_page == 105
    assert first_page.printed_page == 101
    assert "백제문화유산연구원" in first_page.header
    assert len(first_page.text_blocks) > 0
    assert first_page.normalized_text != ""
    assert "2호 토광묘" in first_page.normalized_text


def test_pdf_parser_extracts_captions_and_blank_references():
    parser = PDFParser()
    pages_1 = parser.parse_page_range(SRC_PDF_1, start_page=105, end_page=105)
    pages_2 = parser.parse_page_range(SRC_PDF_2, start_page=111, end_page=111)
    
    p1 = pages_1[0]
    p2 = pages_2[0]
    
    # Check 1차 blank reference parsing
    assert any(c.is_blank_reference for c in p1.captions)
    
    # Check 2차 filled reference parsing (drawing 57, plate 85/86)
    ref_captions = [c for c in p2.captions if not c.is_blank_reference]
    assert len(ref_captions) > 0
    assert any(c.drawing_number == "57" for c in ref_captions)
    assert any(c.plate_number in ["85", "86"] for c in ref_captions)


def test_pdf_parser_handles_all_three_sample_ranges():
    parser = PDFParser()
    p1 = parser.parse_page_range(SRC_PDF_1, 105, 114)
    p2 = parser.parse_page_range(SRC_PDF_2, 111, 120)
    p3 = parser.parse_page_range(SRC_PDF_3, 126, 135)
    
    assert len(p1) == 10
    assert len(p2) == 10
    assert len(p3) == 10
    
    for i in range(10):
        assert p1[i].printed_page == 101 + i
        assert p2[i].printed_page == 102 + i
        assert p3[i].printed_page == 102 + i
