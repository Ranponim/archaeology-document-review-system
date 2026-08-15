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


def test_rule_engine_default_header_noise_patterns():
    engine = RuleEngine()
    # Default patterns should match Baekje and common archaeology report headers
    assert engine._is_header_noise('105 | 백제문화유산연구원')
    assert engine._is_header_noise('문화유적 보고서 | 106')
    assert engine._is_header_noise('12 | 국립문화재연구원')
    assert engine._is_header_noise('학술조사보고서 | 45')
    assert engine._is_header_noise('백제문화유산연구원')
    assert engine._is_header_noise('학술조사')
    assert engine._is_header_noise('10 | 발굴조사보고서')
    assert engine._is_header_noise('지표조사보고서 | 20')
    assert engine._is_header_noise('30 | 시굴조사')
    assert engine._is_header_noise('문화유산')
    assert engine._is_header_noise('발굴조사')
    assert engine._is_header_noise('지표조사')
    assert engine._is_header_noise('시굴조사')
    assert engine._is_header_noise('보고서')
    assert engine._is_header_noise('연구원')
    
    # Normal body lines should not be considered header noise
    assert not engine._is_header_noise('1. 조사지역의 위치 및 환경')
    assert not engine._is_header_noise('본 유적은 논산시 노성면 산노리에 위치한다.')
    assert not engine._is_header_noise('도면 57, 도판 85')


def test_rule_engine_custom_header_patterns():
    custom_patterns = [r'^\d+\s*\|\s*한국고고학연구소$', r'^특수발굴조사단$']
    engine = RuleEngine(header_patterns=custom_patterns)
    
    assert engine._header_patterns == custom_patterns
    assert engine._is_header_noise('123 | 한국고고학연구소')
    assert engine._is_header_noise('특수발굴조사단')
    
    # Baekje header should NOT match when custom patterns are explicitly provided
    assert not engine._is_header_noise('105 | 백제문화유산연구원')


def test_rule_engine_comprehensive_feature_id_patterns():
    engine = RuleEngine()
    feature_types = [
        "토광묘", "주거지", "수혈유구", "수혈", "함정유구", "함정",
        "석관묘", "석곽묘", "석실묘", "지석묘", "고분", "적석총",
        "분구묘", "옹관묘", "가마", "가마터", "건물지", "우물",
        "구", "배수로", "패총", "목관묘", "유구", "유물"
    ]
    for idx, ftype in enumerate(feature_types, start=1):
        text = f"{idx}호 {ftype}"
        assert engine.FEATURE_ID_PATTERN.search(text) is not None, f"Failed to match: {text}"
        category = engine._classify_rule_category(None, f"{idx}호 {ftype} 발견")
        assert category == "feature_or_artifact_id", f"Category mismatch for {ftype}"

