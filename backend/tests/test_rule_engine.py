from pathlib import Path
import pytest
from app.services.pdf_parser import PDFParser
from app.services.page_aligner import PageAligner
from app.services.rule_engine import RuleEngine
from app.domain.review_models import CorrectionCandidateData


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


def test_rule_engine_detects_drawing_plate_reference_diffs():
    parser = PDFParser()
    p1 = parser.parse_page_range(SRC_PDF_1, 105, 105)[0]
    p2 = parser.parse_page_range(SRC_PDF_2, 111, 111)[0]
    
    engine = RuleEngine()
    candidates = engine.compare_pages(p1, p2, stage_from="1차", stage_to="2차")
    
    # Should detect drawing/plate reference filling
    ref_cands = [c for c in candidates if c.rule_category == "figure_plate_table_photo_ref"]
    assert len(ref_cands) > 0
    assert any("57" in (c.proposed_text or "") for c in ref_cands)


def test_rule_engine_detects_spacing_and_arrow_rules():
    parser = PDFParser()
    p2 = parser.parse_page_range(SRC_PDF_2, 111, 111)[0]
    p3 = parser.parse_page_range(SRC_PDF_3, 126, 126)[0]
    
    engine = RuleEngine()
    candidates = engine.compare_pages(p2, p3, stage_from="2차", stage_to="3차")
    
    spacing_cands = [c for c in candidates if c.rule_category == "annotation_resolution"]
    assert len(spacing_cands) > 0
    # Arrow spacing rule test
    assert any("→" in (c.proposed_text or "") for c in spacing_cands)


def test_rule_engine_runs_across_sample_alignment_rows():
    parser = PDFParser()
    p1 = parser.parse_page_range(SRC_PDF_1, 105, 114)
    p2 = parser.parse_page_range(SRC_PDF_2, 111, 120)
    p3 = parser.parse_page_range(SRC_PDF_3, 126, 135)
    
    aligner = PageAligner()
    rows = aligner.align_parallel_ranges({"1차": p1, "2차": p2, "3차": p3})
    
    engine = RuleEngine()
    result = engine.analyze_alignment_rows(rows)
    
    assert len(result.candidates) > 50
    assert result.summary["total"] == len(result.candidates)
    assert "figure_plate_table_photo_ref" in result.summary["rule"]
    assert "annotation_resolution" in result.summary["rule"]
