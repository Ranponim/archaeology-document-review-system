from pathlib import Path
import pytest
from app.services.pdf_parser import PDFParser
from app.services.page_aligner import PageAligner
from app.services.rule_engine import RuleEngine
from app.domain.canonical_models import ArchaeologyObjectData, PlateData, DrawingData
from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.services.plate_parser import PlateIndex


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
    assert all(c.status == "pending_review" for c in candidates)


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
    assert all(c.status == "pending_review" for c in candidates)


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
    assert all(c.status == "pending_review" for c in result.candidates)


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


# =============================================================================
# Task 10: Object & Evidence Consistency Engine Tests
# =============================================================================

def test_numeric_unit_normalization_and_dimension_consistency():
    engine = RuleEngine()
    
    # Unit normalization checks
    d_275cm = engine.normalize_dimension_unit("275cm")
    d_245m = engine.normalize_dimension_unit("2.45m")
    d_275m = engine.normalize_dimension_unit("2.75m")
    d_127cm = engine.normalize_dimension_unit("12.7cm")
    d_127_nounit = engine.normalize_dimension_unit("12.7")
    d_150cm = engine.normalize_dimension_unit("15.0cm")
    d_15kg = engine.normalize_dimension_unit("1.5kg")
    d_1500g = engine.normalize_dimension_unit("1500g")
    d_120mm = engine.normalize_dimension_unit("120mm")
    
    # Normalized base unit values
    assert d_275cm.normalized_value == pytest.approx(275.0)
    assert d_275cm.base_unit == "cm"
    
    assert d_245m.normalized_value == pytest.approx(245.0)
    assert d_245m.base_unit == "cm"
    
    assert d_275m.normalized_value == pytest.approx(275.0)
    assert d_275m.base_unit == "cm"
    
    assert d_127cm.normalized_value == pytest.approx(12.7)
    assert d_127_nounit.normalized_value == pytest.approx(12.7)
    assert d_127_nounit.base_unit is None
    
    assert d_15kg.normalized_value == pytest.approx(1500.0)
    assert d_15kg.base_unit == "g"
    
    assert d_1500g.normalized_value == pytest.approx(1500.0)
    assert d_1500g.base_unit == "g"
    
    assert d_120mm.normalized_value == pytest.approx(12.0)
    assert d_120mm.base_unit == "cm"
    
    # Consistency comparisons:
    # 275cm vs 2.45m -> Conflicts (275 != 245)
    assert not engine.are_dimensions_consistent("275cm", "2.45m")
    
    # 275cm vs 2.75m -> Matches (275 == 275)
    assert engine.are_dimensions_consistent("275cm", "2.75m")
    
    # 12.7cm vs 12.7 (omitted unit) -> Matches
    assert engine.are_dimensions_consistent("12.7cm", "12.7")
    
    # 12.7cm vs 15.0cm -> Conflicts
    assert not engine.are_dimensions_consistent("12.7cm", "15.0cm")
    
    # 1.5kg vs 1500g -> Matches
    assert engine.are_dimensions_consistent("1.5kg", "1500g")
    
    # 1.5kg vs 1.2kg -> Conflicts
    assert not engine.are_dimensions_consistent("1.5kg", "1.2kg")


def test_dimension_conflict_detection_across_evidences():
    engine = RuleEngine()
    obj = ArchaeologyObjectData(
        object_id="obj_cist_6",
        site="1지점",
        period="청동기시대",
        type="석관묘",
        number="6호",
        canonical_name="1지점 청동기시대 6호 석관묘",
    )
    
    # Evidences with conflicting length: 275cm vs 2.45m
    ev1 = EvidenceData(
        id="ev_dim_1",
        value="길이 275cm, 너비 120cm, 깊이 45cm",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        source_sha256="hash1",
        kind="text_claim",
    )
    ev2 = EvidenceData(
        id="ev_dim_2",
        value="길이 2.45m, 너비 120cm, 깊이 45cm",
        document_version_id="ver_2",
        page_id="ver_2_p111",
        source_sha256="hash2",
        kind="text_claim",
    )
    
    candidates = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev1, ev2],
    )
    
    dim_conflicts = [c for c in candidates if c.rule_category == "numeric_value"]
    assert len(dim_conflicts) == 1
    cand = dim_conflicts[0]
    assert cand.status == "pending_review"
    assert cand.archaeology_object_id == "obj_cist_6"
    assert "275" in (cand.original_text or "") or "275" in (cand.proposed_text or "")
    assert "2.45" in (cand.proposed_text or "") or "2.45" in (cand.original_text or "")
    assert ev1 in cand.evidences and ev2 in cand.evidences
    
    # Now compare with consistent evidence (275cm vs 2.75m): should produce NO numeric conflict
    ev3 = EvidenceData(
        id="ev_dim_3",
        value="길이 2.75m, 너비 120cm, 깊이 45cm",
        document_version_id="ver_3",
        page_id="ver_3_p126",
        source_sha256="hash3",
        kind="text_claim",
    )
    candidates_match = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev1, ev3],
    )
    dim_conflicts_match = [c for c in candidates_match if c.rule_category == "numeric_value"]
    assert len(dim_conflicts_match) == 0


def test_feature_type_inconsistency_across_evidences():
    engine = RuleEngine()
    obj = ArchaeologyObjectData(
        object_id="obj_cist_6",
        site="1지점",
        period="청동기시대",
        type="석관묘",
        number="6호",
        canonical_name="1지점 청동기시대 6호 석관묘",
    )
    
    # Evidence claiming 석관묘 vs 토광묘
    ev1 = EvidenceData(
        id="ev_t_1",
        value="6호 석관묘는 구릉 정상부에 위치한다.",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        source_sha256="hash1",
        kind="text_claim",
    )
    ev2 = EvidenceData(
        id="ev_t_2",
        value="6호 토광묘는 구릉 사면에 위치한다.",
        document_version_id="ver_2",
        page_id="ver_2_p111",
        source_sha256="hash2",
        kind="text_claim",
    )
    
    candidates = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev1, ev2],
    )
    
    type_conflicts = [c for c in candidates if c.rule_category == "feature_or_artifact_id"]
    assert len(type_conflicts) >= 1
    cand = type_conflicts[0]
    assert cand.status == "pending_review"
    assert cand.archaeology_object_id == "obj_cist_6"
    assert "석관묘" in (cand.original_text or "") or "석관묘" in (cand.proposed_text or "")
    assert "토광묘" in (cand.proposed_text or "") or "토광묘" in (cand.original_text or "")


def test_period_inconsistency_across_evidences():
    engine = RuleEngine()
    obj = ArchaeologyObjectData(
        object_id="obj_cist_6",
        site="1지점",
        period="청동기시대",
        type="석관묘",
        number="6호",
        canonical_name="1지점 청동기시대 6호 석관묘",
    )
    
    # Period mismatch: 청동기시대 vs 조선시대
    ev1 = EvidenceData(
        id="ev_p_1",
        value="청동기시대 6호 석관묘",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        source_sha256="hash1",
        kind="text_claim",
    )
    ev2 = EvidenceData(
        id="ev_p_2",
        value="조선시대 6호 석관묘",
        document_version_id="ver_2",
        page_id="ver_2_p111",
        source_sha256="hash2",
        kind="text_claim",
    )
    
    candidates = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev1, ev2],
    )
    
    period_conflicts = [c for c in candidates if c.rule_category == "direction_period_term"]
    assert len(period_conflicts) >= 1
    cand = period_conflicts[0]
    assert cand.status == "pending_review"
    assert cand.archaeology_object_id == "obj_cist_6"
    assert "청동기시대" in (cand.original_text or "") or "청동기시대" in (cand.proposed_text or "")
    assert "조선시대" in (cand.proposed_text or "") or "조선시대" in (cand.original_text or "")
    
    # Normalized period match: "청동기" vs "청동기시대" -> Consistent
    ev3 = EvidenceData(
        id="ev_p_3",
        value="청동기 6호 석관묘",
        document_version_id="ver_3",
        page_id="ver_3_p126",
        source_sha256="hash3",
        kind="text_claim",
    )
    candidates_match = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev1, ev3],
    )
    period_conflicts_match = [c for c in candidates_match if c.rule_category == "direction_period_term" and "시대" in (c.original_text or "")]
    assert len(period_conflicts_match) == 0


def test_orientation_inconsistency_across_evidences():
    engine = RuleEngine()
    obj = ArchaeologyObjectData(
        object_id="obj_cist_6",
        site="1지점",
        period="청동기시대",
        type="석관묘",
        number="6호",
        canonical_name="1지점 청동기시대 6호 석관묘",
    )
    
    # Orientation mismatch: N-125°-E vs N-145°-E
    ev1 = EvidenceData(
        id="ev_o_1",
        value="유구의 주축방향은 N-125°-E이다.",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        source_sha256="hash1",
        kind="text_claim",
    )
    ev2 = EvidenceData(
        id="ev_o_2",
        value="유구의 주축방향은 N-145°-E이다.",
        document_version_id="ver_2",
        page_id="ver_2_p111",
        source_sha256="hash2",
        kind="text_claim",
    )
    
    candidates = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev1, ev2],
    )
    
    orient_conflicts = [c for c in candidates if c.rule_category == "direction_period_term"]
    assert len(orient_conflicts) >= 1
    cand = orient_conflicts[0]
    assert cand.status == "pending_review"
    assert cand.archaeology_object_id == "obj_cist_6"
    assert "N-125°-E" in (cand.original_text or "") or "N-125°-E" in (cand.proposed_text or "")
    assert "N-145°-E" in (cand.proposed_text or "") or "N-145°-E" in (cand.original_text or "")
    
    # Orientation format match: N-125°-E vs N-125-E -> Consistent
    ev3 = EvidenceData(
        id="ev_o_3",
        value="유구의 주축방향은 N-125-E이다.",
        document_version_id="ver_3",
        page_id="ver_3_p126",
        source_sha256="hash3",
        kind="text_claim",
    )
    candidates_match = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev1, ev3],
    )
    orient_conflicts_match = [c for c in candidates_match if c.rule_category == "direction_period_term" and "125" in (c.original_text or "")]
    assert len(orient_conflicts_match) == 0


def test_reference_resolution_mismatch_detection():
    engine = RuleEngine()
    obj = ArchaeologyObjectData(
        object_id="obj_cist_6",
        site="1지점",
        period="청동기시대",
        type="석관묘",
        number="6호",
        canonical_name="1지점 청동기시대 6호 석관묘",
    )
    
    # Body claims reference: 도판 45
    ev_ref = EvidenceData(
        id="ev_ref_1",
        kind="reference",
        value="도판 45",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        source_sha256="hash1",
    )
    
    # But Plate 45 is titled "2호 토광묘" (mismatch with 6호 석관묘)
    plate_45 = PlateData(
        plate_id="plate_45",
        number="45",
        physical_page=200,
        title="2호 토광묘",
        source_sha256="plate_hash",
    )
    plate_index = PlateIndex(plates=[plate_45])
    
    candidates = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev_ref],
        plate_index=plate_index,
    )
    
    ref_conflicts = [c for c in candidates if c.rule_category == "figure_plate_table_photo_ref"]
    assert len(ref_conflicts) >= 1
    cand = ref_conflicts[0]
    assert cand.status == "pending_review"
    assert cand.archaeology_object_id == "obj_cist_6"
    assert "도판 45" in (cand.original_text or "")
    assert "2호 토광묘" in (cand.proposed_text or "") or "2호 토광묘" in (cand.evidence.rationale if cand.evidence else "")


def test_blank_reference_detection_generates_pending_review_candidates():
    engine = RuleEngine()
    obj = ArchaeologyObjectData(
        object_id="obj_cist_6",
        site="1지점",
        canonical_name="6호 석관묘",
    )
    
    ev_blank = EvidenceData(
        id="ev_blank_1",
        value="① 유구(도면 : , 도판 : )",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        source_sha256="hash1",
        kind="text_claim",
    )
    
    candidates = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev_blank],
    )
    
    blank_cands = [c for c in candidates if c.rule_category == "figure_plate_table_photo_ref"]
    assert len(blank_cands) >= 1
    for c in blank_cands:
        assert c.status == "pending_review"
        assert c.archaeology_object_id == "obj_cist_6"


def test_all_candidates_strictly_have_pending_review_status():
    engine = RuleEngine()
    obj = ArchaeologyObjectData(
        object_id="obj_pit_2",
        site="1지점",
        period="청동기시대",
        type="석관묘",
        number="2호",
        canonical_name="1지점 청동기시대 2호 석관묘",
    )
    
    ev1 = EvidenceData(
        id="ev_1",
        value="길이 275cm, 토광묘, 조선시대, N-125°-E, (도면 : )",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        source_sha256="hash1",
    )
    ev2 = EvidenceData(
        id="ev_2",
        value="길이 2.45m, 석관묘, 청동기시대, N-145°-E",
        document_version_id="ver_2",
        page_id="ver_2_p111",
        source_sha256="hash2",
    )
    
    candidates = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev1, ev2],
    )
    
    assert len(candidates) > 0
    for cand in candidates:
        assert cand.status == "pending_review", f"Candidate {cand.candidate_id} status is {cand.status}, must be pending_review"
        assert cand.status not in ("confirmed", "accepted")
