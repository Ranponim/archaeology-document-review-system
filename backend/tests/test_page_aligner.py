from pathlib import Path
import pytest
from app.services.pdf_parser import PDFParser
from app.services.page_aligner import PageAligner, AlignedPageRow


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


def test_page_aligner_weighted_similarity():
    aligner = PageAligner()
    s1 = "2지점 시대미상 2호 토광묘는 해발 42.80m에 조성되었으며"
    s2 = "2지점 시대미상 2호 토광묘는 해발 42.80m에 조성되었으며"
    assert aligner.calculate_weighted_similarity(s1, s2) == pytest.approx(1.0)
    
    s3 = "완전히 다른 내용의 문장입니다."
    assert aligner.calculate_weighted_similarity(s1, s3) < 0.2


def test_page_aligner_aligns_real_sample_pages():
    parser = PDFParser()
    p1 = parser.parse_page_range(SRC_PDF_1, 105, 114)
    p2 = parser.parse_page_range(SRC_PDF_2, 111, 120)
    p3 = parser.parse_page_range(SRC_PDF_3, 126, 135)
    
    aligner = PageAligner()
    version_dict = {
        "1차": p1,
        "2차": p2,
        "3차": p3
    }
    rows = aligner.align_parallel_ranges(version_dict)
    assert len(rows) == 10
    
    for idx, row in enumerate(rows):
        assert isinstance(row, AlignedPageRow)
        assert row.row_id == idx + 1
        assert "1차" in row.pages
        assert "2차" in row.pages
        assert "3차" in row.pages
        assert row.pages["1차"].physical_page == 105 + idx
        assert row.pages["2차"].physical_page == 111 + idx
        assert row.pages["3차"].physical_page == 126 + idx
        assert row.similarity_score > 0.8
        assert row.sequence_matcher_ratio > 0.9
