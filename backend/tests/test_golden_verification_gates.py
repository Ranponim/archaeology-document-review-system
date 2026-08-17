from dataclasses import replace
import json
from pathlib import Path
from typing import Any
import pytest
import yaml

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    PlateData,
    PlatePanelData,
    ReferenceData,
    ResolutionStatus,
)
from app.domain.document_structure import CaptionData, ParsedPage, TextBlockData
from app.domain.review_models import (
    CorrectionCandidateData,
    EvidenceData,
)
from app.graph.canonical_repository import CanonicalRepository
from app.graph.review_repository import ReviewRepository
from app.services.ai_review_service import AIReviewService
from app.services.asset_cache import AssetHashCache
from app.services.asset_matcher import AssetMatcher, ResolutionResult, resolve_reference
from app.services.object_resolver import ObjectResolver
from app.services.pdf_parser import PDFParser
from app.services.plate_parser import PlateIndex, PlateParser
from app.services.proofreading_orchestrator import (
    OrchestratorResult,
    ProofreadingOrchestrator,
)
from app.services.rule_engine import RuleEngine
from app.services.vlm_review_service import VLMReviewResult, VLMReviewService


GOLDEN_DATASET_PATH = Path(__file__).parent / "fixtures" / "golden" / "golden_dataset.yaml"
PLATE_45_PDF = Path(__file__).parent / "fixtures" / "golden" / "plate_45_fixture.pdf"


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


class MockMultimodalClient:
    def __init__(self, responses: dict[str, dict[str, Any]] | None = None):
        self.responses = responses or {}
        self.call_count = 0

    async def analyze_multimodal(self, prompt: str, image_bytes: bytes, mime_type: str) -> dict:
        self.call_count += 1
        for key, resp in self.responses.items():
            if key in prompt:
                return resp
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "status": "SUPPORTED",
                            "observations": {"feature_number": "45"},
                            "supported_claims": ["1지점 6호 석관묘 완형 노출"],
                            "contradicted_claims": [],
                            "unobservable_claims": [],
                            "confidence": 0.95,
                            "rationale": "표찰 및 유구 구조 일치",
                        })
                    }
                }
            ],
            "usage": {"prompt_tokens": 300, "completion_tokens": 60},
        }


@pytest.fixture(scope="session")
def golden_benchmark() -> dict[str, Any]:
    assert GOLDEN_DATASET_PATH.is_file(), f"Golden dataset fixture not found: {GOLDEN_DATASET_PATH}"
    with open(GOLDEN_DATASET_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "benchmark_cases" in data, "golden_dataset.yaml must contain benchmark_cases"
    return data


# =============================================================================
# Fixture & Dataset Integrity Checks
# =============================================================================

def test_golden_dataset_structure_and_completeness(golden_benchmark):
    """Verify golden dataset metadata, version lock, and full 10-case coverage."""
    assert golden_benchmark["version"] == "1.0-locked"
    cases = golden_benchmark["benchmark_cases"]
    assert len(cases) == 10, f"Expected exactly 10 golden benchmark cases, found {len(cases)}"

    case_ids = [c["case_id"] for c in cases]
    expected_ids = [f"GT_CASE_{i:03d}" for i in range(1, 11)]
    assert case_ids == expected_ids

    # Case 6 is marked as legacy invalid mapping corrected to canonical
    case_6 = next(c for c in cases if c["case_id"] == "GT_CASE_006")
    assert case_6["ground_truth_status"] == "INVALID_GROUND_TRUTH_MAPPING"
    assert "4. 조사 후_45.JPG" in case_6["forbidden_link_filename"]

    # All other 9 cases are valid ground truth
    other_cases = [c for c in cases if c["case_id"] != "GT_CASE_006"]
    for c in other_cases:
        assert c["ground_truth_status"] == "VALID_GROUND_TRUTH"


# =============================================================================
# Gate 1: Zero False Canonical Mappings (E_false_canonical = 0)
# =============================================================================

def test_gate_1_zero_false_canonical_mappings_across_all_cases(tmp_path, golden_benchmark):
    """Gate 1: Assert zero false canonical mappings (E_false_canonical = 0)

    across all golden benchmark cases. Precision must be 1.0. Decoys must never match.
    """
    cases = golden_benchmark["benchmark_cases"]

    # Setup decoy files on disk
    plates_dir = tmp_path / "plates"
    drawings_dir = tmp_path / "drawings"
    plates_dir.mkdir()
    drawings_dir.mkdir()

    # Create Plate Index with canonical publication plates
    plates_by_number: dict[str, PlateData] = {}
    for p_num in range(1, 100):
        s_num = str(p_num)
        plates_by_number[s_num] = PlateData(
            plate_id=f"plate_{s_num}",
            number=s_num,
            physical_page=p_num + 2,
            title=f"도판 {s_num} 유구/유물",
            raw_identifier=f"【도판 {s_num}】",
            source_sha256=f"hash_plate_{s_num}",
            source_kind="plate_pdf",
        )

    plate_index = PlateIndex(
        plates_by_number=plates_by_number,
        plates=list(plates_by_number.values()),
    )

    # Populate decoy files from all benchmark cases into plates_dir and drawings_dir
    for c in cases:
        for decoy in c.get("decoy_filenames", []):
            if decoy.endswith((".jpg", ".JPG", ".png", ".PNG")):
                (plates_dir / decoy).write_bytes(b"decoy plate bytes")
            else:
                (drawings_dir / decoy).write_bytes(b"decoy drawing bytes")
        if "forbidden_link_filename" in c:
            (plates_dir / c["forbidden_link_filename"]).write_bytes(b"forbidden trap bytes")

    matcher = AssetMatcher(
        drawings_dir=drawings_dir,
        plates_dir=plates_dir,
        plate_index=plate_index,
    )

    false_canonical_mappings_count = 0
    total_resolutions_tested = 0

    # Test all reference cases (Cases 1, 2, 3, 6)
    for c in cases:
        ref_spec = c.get("reference")
        if not ref_spec:
            continue

        ref_type = ref_spec["type"]
        expected_numbers = ref_spec.get("expected_numbers", [ref_spec.get("number")])

        for exp_num in expected_numbers:
            ref = ReferenceData(
                ref_type=ref_type,
                number=exp_num,
                raw_text=c.get("body_text", f"도판 {exp_num}"),
            )
            res = matcher.resolve_reference(ref)
            total_resolutions_tested += 1

            if ref_type == "plate":
                if exp_num in plates_by_number:
                    # Must resolve strictly to expected canonical plate
                    if res.status != ResolutionStatus.RESOLVED:
                        false_canonical_mappings_count += 1
                    if res.target is None or res.target.number != exp_num:
                        false_canonical_mappings_count += 1
                    # Invariant: Decoys and trap filenames must NEVER be in identity evidence
                    for decoy in c.get("decoy_filenames", []):
                        if decoy in str(res.target) or any(decoy in ev for ev in res.identity_evidence):
                            false_canonical_mappings_count += 1
                    if "forbidden_link_filename" in c:
                        forbidden = c["forbidden_link_filename"]
                        if forbidden in str(res.target) or any(forbidden in ev for ev in res.identity_evidence):
                            false_canonical_mappings_count += 1

    # Test missing reference safety (Plate 91)
    missing_ref = ReferenceData(ref_type="plate", number="9999", raw_text="도판 9999")
    missing_res = matcher.resolve_reference(missing_ref)
    total_resolutions_tested += 1
    if missing_res.status not in (ResolutionStatus.MISSING, ResolutionStatus.UNRESOLVED) or missing_res.target is not None:
        false_canonical_mappings_count += 1

    # Gate 1 Metric Assertions
    assert total_resolutions_tested >= 10
    assert false_canonical_mappings_count == 0, f"Gate 1 Failed: E_false_canonical = {false_canonical_mappings_count}, expected 0"
    canonical_precision = (total_resolutions_tested - false_canonical_mappings_count) / total_resolutions_tested
    assert canonical_precision == 1.0, f"Gate 1 Failed: Precision = {canonical_precision}, expected 1.0"


# =============================================================================
# Gate 2: Case 6 Regression Pass Gate
# =============================================================================

def test_gate_2_case_6_regression_with_trap_and_decoy_exclusion(tmp_path, golden_benchmark):
    """Gate 2: Case 6 Regression Gate

    Resolves Reference(plate, 45) canonically to Plate 45 (【도판 45】).
    Strictly excludes '4. 조사 후_45.JPG' and all ambiguous decoys.
    Missing reference (Plate 91) resolves to MISSING/UNRESOLVED with target None.
    """
    case6 = next(c for c in golden_benchmark["benchmark_cases"] if c["case_id"] == "GT_CASE_006")

    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()
    forbidden = case6["forbidden_link_filename"]
    (plates_dir / forbidden).write_bytes(b"forbidden jpeg content")
    for decoy in case6["ambiguous_filenames"]:
        (plates_dir / decoy).write_bytes(b"ambiguous jpeg content")
    for decoy in case6["missing_reference"]["decoy_filenames"]:
        (plates_dir / decoy).write_bytes(b"missing decoy jpeg content")

    plate_45 = PlateData(
        plate_id="plate_45",
        number=case6["reference"]["number"],
        physical_page=case6["physical_page"],
        title=case6["plate_title"],
        raw_identifier=case6["plate_explicit_identifier"],
        source_sha256="canonical_plate_hash_45",
        source_kind="plate_pdf",
    )
    plate_index = PlateIndex(
        plates_by_number={"45": plate_45},
        plates=[plate_45],
    )

    matcher = AssetMatcher(
        drawings_dir=tmp_path / "drawings",
        plates_dir=plates_dir,
        plate_index=plate_index,
    )

    # 1. Resolve Plate 45
    ref_45 = ReferenceData(ref_type="plate", number="45", raw_text="도판 : 45ㆍ46")
    res_45 = matcher.resolve_reference(ref_45)

    assert res_45.status == ResolutionStatus.RESOLVED
    assert res_45.target is not None
    assert res_45.target.number == "45"
    assert res_45.target.physical_page == 47
    assert res_45.target.title == "1지점 청동기시대 6호 석관묘"
    assert res_45.target.raw_identifier == "【도판 45】"

    # Strict inviolable exclusion of forbidden filename
    assert forbidden not in str(res_45.target)
    assert all(forbidden not in ev for ev in res_45.identity_evidence)
    for decoy in case6["ambiguous_filenames"]:
        assert decoy not in str(res_45.target)
        assert all(decoy not in ev for ev in res_45.identity_evidence)

    # 2. Resolve missing reference 91 (with decoys on disk)
    ref_91 = ReferenceData(ref_type="plate", number="91", raw_text="도판 : 91")
    res_91 = matcher.resolve_reference(ref_91)
    assert res_91.status in (ResolutionStatus.MISSING, ResolutionStatus.UNRESOLVED)
    assert res_91.target is None
    assert len(res_91.identity_evidence) == 0

    # 3. Real golden PDF parsing if available
    if PLATE_45_PDF.is_file():
        parser = PlateParser()
        parsed_index = parser.parse(PLATE_45_PDF)
        assert "45" in parsed_index
        plate_45_pdf = parsed_index.get_plate("45")
        assert plate_45_pdf is not None
        assert plate_45_pdf.number == "45"
        assert plate_45_pdf.physical_page == 47
        assert plate_45_pdf.title == "1지점 청동기시대 6호 석관묘"

        res_pdf = resolve_reference(ref_45, plate_index=parsed_index)
        assert res_pdf.status == ResolutionStatus.RESOLVED
        assert res_pdf.target == plate_45_pdf
        assert forbidden not in res_pdf.identity_evidence


# =============================================================================
# Gate 3: Unit Normalization Consistency Check Gate
# =============================================================================

def test_gate_3_unit_normalization_dimension_conflict_detection(golden_benchmark):
    """Gate 3: Unit Normalization Consistency Check Gate

    275cm vs 2.45m conflict (different values) -> raises numeric_value candidate in pending_review.
    275cm vs 2.75m match (same values in different units) -> no conflict.
    1.5kg vs 1500g match -> no conflict.
    """
    case7 = next(c for c in golden_benchmark["benchmark_cases"] if c["case_id"] == "GT_CASE_007")
    engine = RuleEngine()

    obj = ArchaeologyObjectData(
        object_id="obj_cist_6",
        site="1지점",
        period="청동기시대",
        type="석관묘",
        number="6호",
        canonical_name="1지점 청동기시대 6호 석관묘",
    )

    # Unit Normalization checks
    d_275cm = engine.normalize_dimension_unit("275cm")
    d_245m = engine.normalize_dimension_unit("2.45m")
    d_275m = engine.normalize_dimension_unit("2.75m")
    d_15kg = engine.normalize_dimension_unit("1.5kg")
    d_1500g = engine.normalize_dimension_unit("1500g")
    d_120mm = engine.normalize_dimension_unit("120mm")

    assert d_275cm.normalized_value == pytest.approx(275.0)
    assert d_275cm.base_unit == "cm"
    assert d_245m.normalized_value == pytest.approx(245.0)
    assert d_245m.base_unit == "cm"
    assert d_275m.normalized_value == pytest.approx(275.0)
    assert d_275m.base_unit == "cm"
    assert d_15kg.normalized_value == pytest.approx(1500.0)
    assert d_15kg.base_unit == "g"
    assert d_1500g.normalized_value == pytest.approx(1500.0)
    assert d_1500g.base_unit == "g"
    assert d_120mm.normalized_value == pytest.approx(12.0)
    assert d_120mm.base_unit == "cm"

    # Dimension consistency checks
    assert not engine.are_dimensions_consistent("275cm", "2.45m")
    assert engine.are_dimensions_consistent("275cm", "2.75m")
    assert engine.are_dimensions_consistent("1.5kg", "1500g")
    assert engine.are_dimensions_consistent("120mm", "12.0cm")

    # Conflict pair test (275cm vs 2.45m)
    ev_conflict_1 = EvidenceData(
        id="ev_dim_275cm",
        value="길이 275cm, 너비 120cm, 깊이 45cm",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        source_sha256="sha_v1",
        kind="text_claim",
    )
    ev_conflict_2 = EvidenceData(
        id="ev_dim_245m",
        value="길이 2.45m, 너비 120cm, 깊이 45cm",
        document_version_id="ver_2",
        page_id="ver_2_p111",
        source_sha256="sha_v2",
        kind="text_claim",
    )

    candidates_conflict = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev_conflict_1, ev_conflict_2],
    )
    dim_conflicts = [c for c in candidates_conflict if c.rule_category == "numeric_value"]
    assert len(dim_conflicts) == 1
    cand = dim_conflicts[0]
    assert cand.status == "pending_review"
    assert cand.archaeology_object_id == "obj_cist_6"
    assert "275" in (cand.original_text or "") or "275" in (cand.proposed_text or "")
    assert "2.45" in (cand.proposed_text or "") or "2.45" in (cand.original_text or "")
    assert ev_conflict_1 in cand.evidences and ev_conflict_2 in cand.evidences

    # Match pair test (275cm vs 2.75m) -> Zero numeric conflicts
    ev_match_3 = EvidenceData(
        id="ev_dim_275m",
        value="길이 2.75m, 너비 120cm, 깊이 45cm",
        document_version_id="ver_3",
        page_id="ver_3_p126",
        source_sha256="sha_v3",
        kind="text_claim",
    )
    candidates_match = engine.check_object_consistency(
        archaeology_object=obj,
        evidences=[ev_conflict_1, ev_match_3],
    )
    dim_matches = [c for c in candidates_match if c.rule_category == "numeric_value"]
    assert len(dim_matches) == 0


# =============================================================================
# Gate 4: Audit Trail & Provenance Verification Gate
# =============================================================================

@pytest.mark.anyio
async def test_gate_4_audit_trail_and_provenance_verification(golden_benchmark, tmp_path):
    """Gate 4: Audit Trail & Provenance Verification Gate

    - All candidates start strictly in `pending_review` (never accepted/confirmed).
    - Every candidate has complete Evidence -> DocumentVersion -> Page -> source_sha256.
    - Period synonyms normalize deterministically (Case 8).
    - Ambiguous entities remain isolated in `semantic_review` without unsafe merge (Case 9).
    - VLM observation negative safety flags feature number mismatch as CONTRADICTED (Case 10).
    """
    engine = RuleEngine()
    resolver = ObjectResolver()

    # 1. Case 8: Period Synonym Normalization Verification
    case8 = next(c for c in golden_benchmark["benchmark_cases"] if c["case_id"] == "GT_CASE_008")
    for pair in case8["synonym_pairs"]:
        b1 = TextBlockData(
            block_id="b_syn_1",
            text=f"{pair['input_a']} 발굴 조사",
            normalized_text=f"{pair['input_a']} 발굴 조사",
            order=1,
            source_sha256="sha_syn_1",
        )
        b2 = TextBlockData(
            block_id="b_syn_2",
            text=f"{pair['input_b']} 발굴 조사",
            normalized_text=f"{pair['input_b']} 발굴 조사",
            order=2,
            source_sha256="sha_syn_2",
        )
        res = resolver.resolve_mentions(blocks=[b1, b2])
        assert len(res) == 1, f"Failed to merge synonym pair: {pair['input_a']} vs {pair['input_b']}"
        assert res[0].object_data.canonical_name == pair["canonical_name"]
        assert res[0].object_data.period == pair["normalized_period"]

    # 2. Case 9: Ambiguous Entity Safety Verification (2호 토광묘)
    case9 = next(c for c in golden_benchmark["benchmark_cases"] if c["case_id"] == "GT_CASE_009")
    ctx = case9["multi_entity_context"]
    blocks_case9 = [
        TextBlockData(
            block_id=item["block_id"],
            text=item["text"],
            normalized_text=item["text"],
            order=idx,
            source_sha256=f"sha_case9_{idx}",
        )
        for idx, item in enumerate(ctx, start=1)
    ]
    results_case9 = resolver.resolve_mentions(blocks=blocks_case9)
    assert len(results_case9) == 3, "Ambiguous mention must NOT be auto-merged into existing objects"

    ambiguous_res = next(r for r in results_case9 if r.object_data.canonical_name == "2호 토광묘")
    assert ambiguous_res.status == "semantic_review"
    assert ambiguous_res.confidence <= 0.7
    assert ambiguous_res.source_block_ids == ["b_ambiguous_2"]

    # 3. Case 10: VLM Observation Negative Safety Verification
    case10 = next(c for c in golden_benchmark["benchmark_cases"] if c["case_id"] == "GT_CASE_010")
    cache = AssetHashCache(cache_dir=tmp_path)
    mock_payload = {
        "status": "SUPPORTED",  # VLM might claim match based on site name
        "observations": {
            "site_label": case10["test_scenario"]["photo_observation"]["site_label"],
            "feature_number": case10["test_scenario"]["photo_observation"]["feature_number"],
            "object_type": case10["test_scenario"]["photo_observation"]["object_type"],
            "orientation": case10["test_scenario"]["photo_observation"]["orientation"],
        },
        "supported_claims": ["2지점 사진"],
        "contradicted_claims": ["유구 번호 불일치 (기대: 2호 vs 관측: 25호)"],
        "unobservable_claims": [],
        "confidence": 0.88,
        "rationale": "2지점은 일치하나 25호 토광묘로 관측됨",
    }
    mock_client = MockMultimodalClient({"2호": {"choices": [{"message": {"content": json.dumps(mock_payload)}}], "usage": {"prompt_tokens": 300, "completion_tokens": 60}}})
    vlm_service = VLMReviewService(client=mock_client, cache=cache)

    vlm_res = await vlm_service.verify_plate_photo(
        image_bytes=b"CASE10_PHOTO_BYTES",
        expected_feature=case10["test_scenario"]["expected_feature"],
        expected_site=case10["test_scenario"]["expected_site"],
    )
    assert vlm_res.status in case10["test_scenario"]["expected_verdicts"]
    assert vlm_res.status != case10["test_scenario"]["forbidden_verdict"]
    assert vlm_res.is_match == case10["test_scenario"]["expected_is_match"]
    assert vlm_res.observations["feature_number"] == "25"

    # 4. Provenance & Status Invariant Check across generated candidates
    obj = ArchaeologyObjectData(
        object_id="obj_provenance_test",
        site="1지점",
        canonical_name="1지점 청동기시대 6호 석관묘",
    )
    ev_prov = EvidenceData(
        id="ev_prov_1",
        value="길이 275cm (도면 : , 도판 : )",
        document_version_id="ver_prov_1",
        page_id="page_prov_105",
        source_sha256="sha256_prov_source_105",
        kind="text_claim",
    )
    cands = engine.check_object_consistency(archaeology_object=obj, evidences=[ev_prov])
    assert len(cands) >= 1
    for c in cands:
        assert c.status == "pending_review", f"Candidate {c.candidate_id} status must be pending_review"
        assert len(c.evidences) >= 1
        for ev in c.evidences:
            assert ev.source_sha256 is not None and len(ev.source_sha256) > 0
            assert ev.document_version_id is not None
            assert ev.page_id is not None
            assert ev.kind is not None


# =============================================================================
# Gate 5: End-to-End Orchestrator Pipeline Verification Gate
# =============================================================================

@pytest.mark.anyio
async def test_gate_5_end_to_end_orchestrator_pipeline_on_golden_dataset(tmp_path, golden_benchmark):
    """Gate 5: End-to-End Orchestrator Pipeline Verification Gate

    Executes ProofreadingOrchestrator over synthetic multi-page document
    integrating all golden cases, asserts 100% completion, zero false canonical
    mappings, pending_review candidate compliance, and full provenance preservation.
    """
    # 1. Build canonical Plate and Drawing indices
    plates_by_number: dict[str, PlateData] = {
        "45": PlateData(
            plate_id="plate_45",
            number="45",
            physical_page=47,
            title="1지점 청동기시대 6호 석관묘",
            raw_identifier="【도판 45】",
            source_sha256="hash_plate_45",
            source_kind="plate_pdf",
        ),
        "46": PlateData(
            plate_id="plate_46",
            number="46",
            physical_page=48,
            title="1지점 청동기시대 6호 석관묘 출토유물",
            raw_identifier="【도판 46】",
            source_sha256="hash_plate_46",
            source_kind="plate_pdf",
        ),
        "81": PlateData(
            plate_id="plate_81",
            number="81",
            physical_page=95,
            title="2지점 조선시대 1호 토광묘",
            raw_identifier="【도판 81】",
            source_sha256="hash_plate_81",
            source_kind="plate_pdf",
        ),
        "82": PlateData(
            plate_id="plate_82",
            number="82",
            physical_page=96,
            title="2지점 조선시대 2호 토광묘",
            raw_identifier="【도판 82】",
            source_sha256="hash_plate_82",
            source_kind="plate_pdf",
        ),
    }
    for p_num in range(22, 29):
        s_num = str(p_num)
        plates_by_number[s_num] = PlateData(
            plate_id=f"plate_{s_num}",
            number=s_num,
            physical_page=p_num + 10,
            title=f"1지점 청동기시대 {p_num - 21}호 석관묘 출토유물",
            raw_identifier=f"【도판 {s_num}】",
            source_sha256=f"hash_plate_{s_num}",
            source_kind="plate_pdf",
        )

    plate_index = PlateIndex(
        plates_by_number=plates_by_number,
        plates=list(plates_by_number.values()),
    )

    drawings_by_number: dict[str, DrawingData] = {
        "30": DrawingData(
            drawing_id="drawing_30",
            number="30",
            physical_page=35,
            title="1지점 청동기시대 6호 석관묘 평단면도",
            raw_identifier="【도면 30】",
            source_sha256="hash_drawing_30",
        ),
        "54": DrawingData(
            drawing_id="drawing_54",
            number="54",
            physical_page=60,
            title="2지점 조선시대 2호 토광묘 평단면도",
            raw_identifier="【도면 54】",
            source_sha256="hash_drawing_54",
        ),
    }

    # 2. Setup mock ParsedPages representing golden draft pages
    parsed_pages = [
        ParsedPage(
            physical_page=105,
            printed_page=101,
            header="백제문화유산연구원 | 101",
            raw_text=(
                "1지점 청동기시대 6호 석관묘는 구릉 정상부에 위치한다.\n"
                "① 유구(도면 : 30, 도판 : 45ㆍ46)\n"
                "규모는 길이 275cm, 너비 120cm, 잔존깊이 45cm이다.\n"
                "1지점 청동기시대 석관묘 1~7호 출토유물(도판 : 22~28)\n"
                "2지점 조선시대 2호 토광묘 ① 유구(도면 : 54, 도판 : 81·82)\n"
                "또한 2호 토광묘 바닥면에서 목탄 흔적이 확인된다(도면 : , 도판 : ).\n"
            ),
            normalized_text=(
                "1지점 청동기시대 6호 석관묘는 구릉 정상부에 위치한다. "
                "① 유구(도면 : 30, 도판 : 45ㆍ46) "
                "규모는 길이 275cm, 너비 120cm, 잔존깊이 45cm이다. "
                "1지점 청동기시대 석관묘 1~7호 출토유물(도판 : 22~28) "
                "2지점 조선시대 2호 토광묘 ① 유구(도면 : 54, 도판 : 81·82) "
                "또한 2호 토광묘 바닥면에서 목탄 흔적이 확인된다(도면 : , 도판 : )."
            ),
            text_blocks=[
                TextBlockData(
                    block_id="p105_b1",
                    text="1지점 청동기시대 6호 석관묘는 구릉 정상부에 위치한다.",
                    normalized_text="1지점 청동기시대 6호 석관묘는 구릉 정상부에 위치한다.",
                    order=1,
                    source_sha256="sha256_p105",
                ),
                TextBlockData(
                    block_id="p105_b2",
                    text="① 유구(도면 : 30, 도판 : 45ㆍ46)",
                    normalized_text="① 유구(도면 : 30, 도판 : 45ㆍ46)",
                    order=2,
                    source_sha256="sha256_p105",
                    references=[
                        ReferenceData(ref_type="drawing", number="30", source_block_id="p105_b2", raw_text="도면 : 30", source_sha256="sha256_p105", physical_page=105),
                        ReferenceData(ref_type="plate", number="45", source_block_id="p105_b2", raw_text="도판 : 45", source_sha256="sha256_p105", physical_page=105),
                        ReferenceData(ref_type="plate", number="46", source_block_id="p105_b2", raw_text="도판 : 46", source_sha256="sha256_p105", physical_page=105),
                    ],
                ),
                TextBlockData(
                    block_id="p105_b3",
                    text="규모는 길이 275cm, 너비 120cm, 잔존깊이 45cm이다.",
                    normalized_text="규모는 길이 275cm, 너비 120cm, 잔존깊이 45cm이다.",
                    order=3,
                    source_sha256="sha256_p105",
                ),
                TextBlockData(
                    block_id="p105_b4",
                    text="1지점 청동기시대 석관묘 1~7호 출토유물(도판 : 22~28)",
                    normalized_text="1지점 청동기시대 석관묘 1~7호 출토유물(도판 : 22~28)",
                    order=4,
                    source_sha256="sha256_p105",
                    references=[
                        ReferenceData(ref_type="plate", number=str(num), source_block_id="p105_b4", raw_text="도판 : 22~28", source_sha256="sha256_p105", physical_page=105)
                        for num in range(22, 29)
                    ],
                ),
                TextBlockData(
                    block_id="p105_b5",
                    text="2지점 조선시대 2호 토광묘 ① 유구(도면 : 54, 도판 : 81·82)",
                    normalized_text="2지점 조선시대 2호 토광묘 ① 유구(도면 : 54, 도판 : 81·82)",
                    order=5,
                    source_sha256="sha256_p105",
                    references=[
                        ReferenceData(ref_type="drawing", number="54", source_block_id="p105_b5", raw_text="도면 : 54", source_sha256="sha256_p105", physical_page=105),
                        ReferenceData(ref_type="plate", number="81", source_block_id="p105_b5", raw_text="도판 : 81", source_sha256="sha256_p105", physical_page=105),
                        ReferenceData(ref_type="plate", number="82", source_block_id="p105_b5", raw_text="도판 : 82", source_sha256="sha256_p105", physical_page=105),
                    ],
                ),
                TextBlockData(
                    block_id="p105_b6",
                    text="또한 2호 토광묘 바닥면에서 목탄 흔적이 확인된다(도면 : , 도판 : ).",
                    normalized_text="또한 2호 토광묘 바닥면에서 목탄 흔적이 확인된다(도면 : , 도판 : ).",
                    order=6,
                    source_sha256="sha256_p105",
                ),
            ],
            captions=[
                CaptionData(
                    caption_id="p105_c1",
                    raw_text="① 유구(도면 : 30, 도판 : 45ㆍ46)",
                    drawing_number="30",
                    plate_number="45",
                    is_blank_reference=False,
                    source_sha256="sha256_p105",
                ),
                CaptionData(
                    caption_id="p105_c2",
                    raw_text="① 유구(도면 : 54, 도판 : 81·82)",
                    drawing_number="54",
                    plate_number="81",
                    is_blank_reference=False,
                    source_sha256="sha256_p105",
                ),
                CaptionData(
                    caption_id="p105_c3",
                    raw_text="출토유물(도판 : 22~28)",
                    plate_number="22",
                    is_blank_reference=False,
                    source_sha256="sha256_p105",
                ),
                CaptionData(
                    caption_id="p105_c4",
                    raw_text="(도면 : , 도판 : )",
                    is_blank_reference=True,
                    source_sha256="sha256_p105",
                ),
            ],
        )
    ]

    # 3. Setup Fake Neo4j Repositories
    fake_driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(fake_driver, database="neo4j")
    review_repo = ReviewRepository(fake_driver, database="neo4j")

    # 4. Setup AssetMatcher with plate_index and on-disk decoy traps
    plates_dir = tmp_path / "plates"
    drawings_dir = tmp_path / "drawings"
    plates_dir.mkdir()
    drawings_dir.mkdir()
    (plates_dir / "4. 조사 후_45.JPG").write_bytes(b"forbidden jpeg")
    (plates_dir / "2. 조사 중_82.JPG").write_bytes(b"decoy jpeg")

    asset_matcher = AssetMatcher(
        drawings_dir=drawings_dir,
        plates_dir=plates_dir,
        plate_index=plate_index,
    )

    # 5. Initialize Orchestrator with components
    orchestrator = ProofreadingOrchestrator(
        plate_parser=PlateParser(),
        object_resolver=ObjectResolver(),
        asset_matcher=asset_matcher,
        rule_engine=RuleEngine(),
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        allow_degraded_mode=True,
    )

    # 6. Execute Orchestration
    result = await orchestrator.run_proofreading(
        project_id="proj_golden_gate_test",
        body_version_id="ver_golden_body_1",
        plate_version_id="ver_golden_plate_1",
        body_pages=parsed_pages,
        plates=list(plates_by_number.values()),
        drawings=list(drawings_by_number.values()),
        enable_vlm=False,
        enable_ai_review=False,
    )

    # 7. Comprehensive Gate 5 Assertions
    assert isinstance(result, OrchestratorResult)
    assert result.status == "completed"
    assert result.pages_parsed == 1
    assert result.objects_resolved >= 2
    assert result.references_resolved >= 3
    assert len(result.evidences) > 0
    assert len(result.candidates) > 0

    # Invariant: 100% of candidates strictly in pending_review
    for cand in result.candidates:
        assert cand.status == "pending_review", f"Candidate {cand.candidate_id} status is {cand.status}, must be pending_review"
        assert cand.status not in ("confirmed", "accepted")
        assert len(cand.evidences) >= 1
        for ev in cand.evidences:
            assert ev.source_sha256 is not None and len(ev.source_sha256) > 0
            assert ev.document_version_id in ("ver_golden_body_1", "ver_golden_plate_1", None)

    # Invariant: Case 6 trap filename NEVER in candidates or target identities
    for cand in result.candidates:
        assert "4. 조사 후_45.JPG" not in (cand.original_text or "")
        assert "4. 조사 후_45.JPG" not in (cand.proposed_text or "")
        if cand.evidence:
            assert "4. 조사 후_45.JPG" not in cand.evidence.rationale

    for plate in result.plates:
        assert "4. 조사 후_45.JPG" not in plate.title
        assert plate.raw_identifier != "4. 조사 후_45.JPG"
