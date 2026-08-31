import hashlib
from pathlib import Path
from unittest.mock import patch
import pytest

try:
    import pymupdf  # type: ignore
    HAS_PYMUPDF = True
except ImportError:
    try:
        import fitz as pymupdf  # type: ignore
        HAS_PYMUPDF = True
    except ImportError:
        HAS_PYMUPDF = False

from app.domain.canonical_models import PlateData, PlatePanelData
from app.services.plate_parser import PlateBookResult, PlateIndex, PlateParser


def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").is_dir() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("Could not find repository root containing src/ directory")


REPO_ROOT = _find_repo_root()
REAL_PLATE_PDF_3 = (
    REPO_ROOT
    / "src/완성까지 가던 교정본들/11.21-3차 교정/11.21-115집 논산 산노리 산17-1번지 유적-도판-3차 교정.pdf"
)
GOLDEN_FIXTURE = Path(__file__).parent / "fixtures/golden/plate_45_fixture.pdf"


def test_physical_page_not_equal_plate_number_separation():
    assert GOLDEN_FIXTURE.is_file(), f"Golden fixture missing at {GOLDEN_FIXTURE}"
    parser = PlateParser()
    result = parser.parse(GOLDEN_FIXTURE)

    assert isinstance(result, PlateIndex)
    assert len(result) >= 4

    plate45 = result.get_plate("45")
    assert plate45 is not None
    assert plate45.number == "45"
    assert plate45.physical_page == 47  # Invariant: physical_page (47) != plate_number ("45")
    assert plate45.raw_identifier == "【도판 45】"
    assert plate45.title == "1지점 청동기시대 6호 석관묘"


def test_explicit_identifier_patterns():
    parser = PlateParser()

    cases = [
        ("【도판 45】 1지점 청동기시대 6호 석관묘", "【도판 45】", "45", "1지점 청동기시대 6호 석관묘"),
        ("【도판  45】 1지점 청동기시대 6호 석관묘", "【도판  45】", "45", "1지점 청동기시대 6호 석관묘"),
        ("【도판 45 】 1지점 청동기시대 6호 석관묘", "【도판 45 】", "45", "1지점 청동기시대 6호 석관묘"),
        ("[도판 45] 1지점 청동기시대 6호 석관묘", "[도판 45]", "45", "1지점 청동기시대 6호 석관묘"),
        ("[ 도판 45 ] 1지점 청동기시대 6호 석관묘", "[ 도판 45 ]", "45", "1지점 청동기시대 6호 석관묘"),
        ("〈도판 45〉 1지점 청동기시대 6호 석관묘", "〈도판 45〉", "45", "1지점 청동기시대 6호 석관묘"),
        ("<도판 45> 1지점 청동기시대 6호 석관묘", "<도판 45>", "45", "1지점 청동기시대 6호 석관묘"),
        ("〔도판 45〕 1지점 청동기시대 6호 석관묘", "〔도판 45〕", "45", "1지점 청동기시대 6호 석관묘"),
        ("《도판 45》 1지점 청동기시대 6호 석관묘", "《도판 45》", "45", "1지점 청동기시대 6호 석관묘"),
        ("도판 45 1지점 청동기시대 6호 석관묘", "도판 45", "45", "1지점 청동기시대 6호 석관묘"),
    ]

    for line, expected_raw, expected_num, expected_title in cases:
        parsed = parser.parse_text_header(line)
        assert parsed is not None, f"Failed to parse line: {line}"
        raw_id, num, title, _ = parsed
        assert raw_id == expected_raw
        assert num == expected_num
        assert title == expected_title


def test_title_extraction_with_and_without_panels():
    parser = PlateParser()

    # Case 1: Title with circled panels after dash
    parsed1 = parser.parse_text_header(
        "【도판 45】 1지점 청동기시대 6호 석관묘 - ① 조사 전  ② 조사 중  ③ 토층 A-A'  ④ 동벽 세부  ⑤ 유물 출토 상태"
    )
    assert parsed1 is not None
    _, num1, title1, panel_text1 = parsed1
    assert num1 == "45"
    assert title1 == "1지점 청동기시대 6호 석관묘"
    assert "① 조사 전" in panel_text1

    # Case 2: Standalone title without panels
    parsed2 = parser.parse_text_header("【도판 181】 자문위원회의 개최 모습 1")
    assert parsed2 is not None
    _, num2, title2, panel_text2 = parsed2
    assert num2 == "181"
    assert title2 == "자문위원회의 개최 모습 1"
    assert panel_text2 == ""

    # Case 3: Title with artifact numbers
    parsed3 = parser.parse_text_header("【도판 47】 1지점 청동기시대 6호 석관묘 출토유물 30~32")
    assert parsed3 is not None
    _, num3, title3, panel_text3 = parsed3
    assert num3 == "47"
    assert title3 == "1지점 청동기시대 6호 석관묘 출토유물 30~32"
    assert panel_text3 == ""


def test_panel_extraction_circled_parenthesized_and_suffixes():
    parser = PlateParser()
    result = parser.parse(GOLDEN_FIXTURE, document_version_id="ver_doc_1")

    # Plate 45 panels
    plate45 = result.get_plate("45")
    assert plate45 is not None
    assert len(plate45.panels) == 5

    p1, p2, p3, p4, p5 = plate45.panels
    assert p1.panel_index == 1
    assert p1.caption == "조사 전"
    assert p1.physical_page == 47
    assert p1.bbox is not None
    assert p1.panel_id == "ver_doc_1_plate_45_panel_1"
    assert p1.plate_id == plate45.plate_id

    assert p2.panel_index == 2
    assert p2.caption == "조사 중"
    assert p3.panel_index == 3
    assert p3.caption == "토층 A-A'"
    assert p4.panel_index == 4
    assert p4.caption == "동벽 세부"
    assert p5.panel_index == 5
    assert p5.caption == "유물 출토 상태"

    # Plate 46 panels
    plate46 = result.get_plate("46")
    assert plate46 is not None
    assert len(plate46.panels) == 2
    assert plate46.panels[0].panel_index == 1
    assert plate46.panels[0].caption == "조사 완료"
    assert plate46.panels[1].panel_index == 2
    assert plate46.panels[1].caption == "조사 후"


def test_panel_extraction_ranges_and_dots():
    parser = PlateParser()

    # Range: ②~⑤
    panels_range = parser.extract_panels_from_caption("① 조사 완료  ②~⑤ 유물 출토 상태")
    assert len(panels_range) == 5
    assert panels_range[1] == "조사 완료"
    assert panels_range[2] == "유물 출토 상태"
    assert panels_range[3] == "유물 출토 상태"
    assert panels_range[4] == "유물 출토 상태"
    assert panels_range[5] == "유물 출토 상태"

    # Dots: ②·③
    panels_dots = parser.extract_panels_from_caption("① 조사 완료  ②·③ 유물 출토 상태  ④ 조사 후")
    assert len(panels_dots) == 4
    assert panels_dots[1] == "조사 완료"
    assert panels_dots[2] == "유물 출토 상태"
    assert panels_dots[3] == "유물 출토 상태"
    assert panels_dots[4] == "조사 후"

    # Parenthesized: (1) (2)
    panels_paren = parser.extract_panels_from_caption("(1) 조사 전  (2) 조사 후")
    assert len(panels_paren) == 2
    assert panels_paren[1] == "조사 전"
    assert panels_paren[2] == "조사 후"

    # Suffix parenthesis: 1) 2)
    panels_suffix = parser.extract_panels_from_caption("1) 남측 전경  2) 북측 전경")
    assert len(panels_suffix) == 2
    assert panels_suffix[1] == "남측 전경"
    assert panels_suffix[2] == "북측 전경"


def test_plate_index_and_dictionary_lookup():
    parser = PlateParser()
    index = parser.parse(GOLDEN_FIXTURE)

    # 1. get_plate lookup
    assert index.get_plate("45") is not None
    assert index.get_plate("999") is None

    # 2. dict subscript lookup
    assert index["45"].number == "45"
    assert "45" in index
    assert "999" not in index
    assert index[0].number in ("45", "46", "47", "48")

    # 3. plates_by_number dictionary
    assert "45" in index.plates_by_number
    assert index.plates_by_number["45"].physical_page == 47

    # 4. get_panel lookup
    panel_1 = index.get_panel("45", 1)
    assert panel_1 is not None
    assert panel_1.caption == "조사 전"
    assert index.get_panel("45", 99) is None
    assert index.get_panel("999", 1) is None

    # 5. Iteration and len
    assert len(index) >= 4
    plate_numbers = [p.number for p in index]
    assert "45" in plate_numbers
    assert "46" in plate_numbers
    assert "47" in plate_numbers
    assert "48" in plate_numbers

    # 6. Alias PlateBookResult is PlateIndex
    assert PlateBookResult is PlateIndex


def test_plate_parser_real_plate_book_pdf_sample_pages():
    if not REAL_PLATE_PDF_3.is_file():
        pytest.skip(f"Real sample PDF not found at {REAL_PLATE_PDF_3}")

    parser = PlateParser()
    # Parse physical pages 45 to 50
    plates = parser.parse_page_range(REAL_PLATE_PDF_3, start_page=45, end_page=50)

    assert len(plates) >= 5
    plate_dict = {p.number: p for p in plates}

    # Physical page 47 is 도판 45
    plate45 = plate_dict.get("45")
    assert plate45 is not None
    assert plate45.physical_page == 47
    assert plate45.number == "45"
    assert "6호 석관묘" in plate45.title
    assert len(plate45.panels) == 5
    assert plate45.panels[0].caption == "조사 전"
    assert plate45.panels[1].caption == "조사 중"
    assert plate45.panels[2].caption == "토층 A-A'"
    assert plate45.panels[3].caption == "동벽 세부"
    assert plate45.panels[4].caption == "유물 출토 상태"

    # All panels have non-null bboxes from the page
    for panel in plate45.panels:
        assert panel.bbox is not None
        assert isinstance(panel.bbox, tuple)
        assert len(panel.bbox) == 4

    # SHA256 provenance
    with open(REAL_PLATE_PDF_3, "rb") as f:
        expected_sha = hashlib.sha256(f.read()).hexdigest()
    assert plate45.source_sha256 == expected_sha


def test_real_plate_parser_recovers_continuation_caption_panel():
    if not REAL_PLATE_PDF_3.is_file():
        pytest.skip(f"Real sample PDF not found at {REAL_PLATE_PDF_3}")

    plates = PlateParser().parse_page_range(REAL_PLATE_PDF_3, start_page=59, end_page=59)

    assert len(plates) == 1
    assert plates[0].number == "57"
    assert len(plates[0].panels) == 6
    assert all(panel.bbox is not None for panel in plates[0].panels)


def test_plate_parser_pypdf_fallback():
    parser = PlateParser()

    with patch("app.services.plate_parser.HAS_PYMUPDF", False):
        result = parser.parse(GOLDEN_FIXTURE)
        assert len(result) >= 4
        plate45 = result.get_plate("45")
        assert plate45 is not None
        assert plate45.number == "45"
        assert plate45.physical_page == 47
        assert plate45.title == "1지점 청동기시대 6호 석관묘"
        assert len(plate45.panels) == 5


def test_plate_parser_edge_cases():
    parser = PlateParser()

    # Empty and non-matching lines
    assert parser.parse_text_header("") is None
    assert parser.parse_text_header("문화유적 보고서 | 45") is None
    assert parser.extract_panels_from_caption("") == {}
    assert parser.parse_panel_token("") == []

    # Bracket variations with trailing colons / slashes
    res = parser.parse_text_header("【도판 10-1】 유구 전경 : ① 동측 전경")
    assert res is not None
    assert res[1] == "10-1"
    assert res[2] == "유구 전경"
    assert "① 동측 전경" in res[3]

    # Index methods on missing plate
    index = PlateIndex()
    assert len(index) == 0
    assert index.get_plate("1") is None
    assert index.get_panel("1", 1) is None
    assert "1" not in index


def test_segment_page_panels_uses_reading_order_when_badges_are_rasterized():
    class Rect:
        def __init__(self, x0, y0, x1, y1):
            self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1

        @property
        def width(self):
            return self.x1 - self.x0

        @property
        def height(self):
            return self.y1 - self.y0

    class Page:
        rect = Rect(0, 0, 100, 100)

        def get_images(self, full=True):
            return [(1,), (2,)]

        def get_image_rects(self, xref):
            return {
                1: [Rect(0, 0, 100, 40)],
                2: [Rect(0, 45, 100, 85)],
            }[xref]

    result = PlateParser.segment_page_panels(
        Page(),
        label_bboxes={2: (90, 75, 95, 80)},
        expected_indices={1, 2},
    )

    assert set(result) == {1, 2}
    assert result[1][1] < result[2][1]
