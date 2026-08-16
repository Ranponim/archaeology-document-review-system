import json
from pathlib import Path
import pytest
from app.domain.canonical_models import (
    DrawingData,
    DrawingRegionData,
    PlateData,
    PlatePanelData,
    ReferenceData,
    ResolutionStatus,
)
from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.services.asset_cache import AssetHashCache
from app.services.asset_matcher import AssetMatcher, ResolutionResult
from app.services.image_processor import ImageProcessor
from app.services.vlm_review_service import VLMReviewService
from app.services.asset_review_pipeline import (
    AssetReviewPipeline,
    AssetPipelineSummary,
    MAX_VLM_CANDIDATES,
)


def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").is_dir() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("Could not find repository root containing src/ directory")


REPO_ROOT = _find_repo_root()
SRC_DRAWINGS = REPO_ROOT / "src/본문 도면"
SRC_PLATES = REPO_ROOT / "src/도판(사진들)"
SRC_ENV = REPO_ROOT / "src/환경 도면"


class MockOpenRouterMultimodalClient:
    def __init__(self, mock_response: dict | None = None):
        self.call_count = 0
        self.calls: list[dict] = []
        self.mock_response = mock_response

    async def analyze_multimodal(self, prompt: str, image_bytes: bytes, mime_type: str) -> dict:
        self.call_count += 1
        self.calls.append({"prompt": prompt, "image_bytes": image_bytes, "mime_type": mime_type})
        if self.mock_response is not None:
            return self.mock_response
        import re
        match = re.search(r"유구 번호\(예:\s*'([^']*)'\)", prompt)
        feature = match.group(1) if match else "2호 토광묘"
        feat_num_match = re.search(r"(\d+)", feature)
        feat_num = feat_num_match.group(1) if feat_num_match else "2"
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "status": "SUPPORTED",
                            "observations": {
                                "site_label": f"논산 산노리 2지점 {feature}",
                                "feature_number": feat_num,
                                "site_point": "2지점",
                                "orientation": "N-74-E",
                            },
                            "supported_claims": [f"{feature} 일치"],
                            "confidence": 0.98,
                            "rationale": "VLM OCR verified matching site and feature",
                        })
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 400,
                "completion_tokens": 80,
            },
        }


class SequenceMockOpenRouterClient:
    def __init__(self, responses: list[dict]):
        self.call_count = 0
        self.calls: list[dict] = []
        self.responses = responses

    async def analyze_multimodal(self, prompt: str, image_bytes: bytes, mime_type: str) -> dict:
        idx = self.call_count
        self.call_count += 1
        self.calls.append({"prompt": prompt, "image_bytes": image_bytes, "mime_type": mime_type})
        if idx < len(self.responses):
            return self.responses[idx]
        return self.responses[-1]


def _build_mock_response(label_detected: str, site_point: str, feature_number: str, rationale: str = "") -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "label_detected": label_detected,
                        "feature_number": feature_number,
                        "site_point": site_point,
                        "compass_north": "N-74-E",
                        "match_confidence": 0.95,
                        "rationale": rationale or f"VLM result for {label_detected}",
                    })
                }
            }
        ],
        "usage": {
            "prompt_tokens": 350,
            "completion_tokens": 70,
        },
    }


@pytest.mark.anyio
async def test_asset_review_pipeline_calls_vlm_for_ambiguous_cases(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path)
    matcher = AssetMatcher(SRC_DRAWINGS, SRC_PLATES, SRC_ENV)
    mock_client = MockOpenRouterMultimodalClient()
    vlm_service = VLMReviewService(client=mock_client, cache=cache, model="openai/gpt-5.6-luna")

    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=vlm_service, cache=cache)

    # 10 sample references from 2nd/3rd proofreading drafts (drawings 57-60, plates 85-90)
    sample_references = [
        {"type": "drawing", "number": "57", "context": {"site": "2지점", "feature": "2호 토광묘"}},
        {"type": "drawing", "number": "58", "context": {"site": "2지점", "feature": "5~8호 토광묘"}},
        {"type": "drawing", "number": "59", "context": {"site": "2지점", "feature": "9~12호 토광묘"}},
        {"type": "drawing", "number": "60", "context": {"site": "2지점", "feature": "13~16호 토광묘"}},
        {"type": "plate", "number": "85", "context": {"site": "2지점", "feature": "2호 토광묘"}},
        {"type": "plate", "number": "86", "context": {"site": "2지점", "feature": "3호 토광묘"}},
        {"type": "plate", "number": "87", "context": {"site": "2지점", "feature": "3호 토광묘 출토유물"}},
        {"type": "plate", "number": "88", "context": {"site": "2지점", "feature": "4호 토광묘"}},
        {"type": "plate", "number": "89", "context": {"site": "2지점", "feature": "5호 토광묘"}},
        {"type": "plate", "number": "90", "context": {"site": "2지점", "feature": "6호 토광묘"}},
    ]

    summary = await pipeline.review_references(sample_references)

    assert isinstance(summary, AssetPipelineSummary)
    assert summary.total_references == 10

    # 7 ambiguous cases (drawing 57, plates 85, 86, 87, 88, 89, 90) called VLM and were resolved to exact
    assert mock_client.call_count == 7
    assert summary.status_counts["exact"] == 7
    assert summary.status_counts["missing"] == 3
    assert summary.status_counts["multiple"] == 0
    assert summary.status_counts["semantic_review"] == 0


@pytest.mark.anyio
async def test_asset_review_pipeline_without_vlm(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path)
    matcher = AssetMatcher(SRC_DRAWINGS, SRC_PLATES, SRC_ENV)
    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=None, cache=cache)

    sample_references = [
        {"type": "drawing", "number": "57", "context": {"site": "2지점", "feature": "2호 토광묘"}},
        {"type": "drawing", "number": "58", "context": {"site": "2지점", "feature": "5~8호 토광묘"}},
        {"type": "plate", "number": "85", "context": {"site": "2지점", "feature": "2호 토광묘"}},
        {"type": "plate", "number": "86", "context": {"site": "2지점", "feature": "3호 토광묘"}},
    ]

    summary = await pipeline.review_references(sample_references)

    assert summary.total_references == 4
    assert summary.status_counts["exact"] == 0
    assert summary.status_counts["semantic_review"] == 1
    assert summary.status_counts["missing"] == 1
    assert summary.status_counts["multiple"] == 2


@pytest.mark.anyio
async def test_asset_review_pipeline_iterates_multiple_candidates_until_match(tmp_path):
    drawings_dir = tmp_path / "drawings"
    plates_dir = tmp_path / "plates"
    drawings_dir.mkdir()
    plates_dir.mkdir()

    # Create 3 candidate files for Plate 10
    cand1 = plates_dir / "도판 10_A.jpg"
    cand2 = plates_dir / "도판 10_B.jpg"
    cand3 = plates_dir / "도판 10_C.jpg"
    cand1.write_bytes(b"unique_cand_1_bytes")
    cand2.write_bytes(b"unique_cand_2_bytes")
    cand3.write_bytes(b"unique_cand_3_bytes")

    # Mock responses: candidate 1 mismatches, candidate 2 matches, candidate 3 should not be called
    responses = [
        _build_mock_response(
            label_detected="논산 산노리 1지점 99호 토광묘",
            site_point="1지점",
            feature_number="99호",
            rationale="Candidate 1 does not match",
        ),
        _build_mock_response(
            label_detected="논산 산노리 2지점 10호 토광묘",
            site_point="2지점",
            feature_number="10호",
            rationale="Candidate 2 verified as exact match for Plate 10",
        ),
        _build_mock_response(
            label_detected="논산 산노리 2지점 10호 토광묘",
            site_point="2지점",
            feature_number="10호",
            rationale="Candidate 3 should not be called",
        ),
    ]

    mock_client = SequenceMockOpenRouterClient(responses)
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    vlm_service = VLMReviewService(client=mock_client, cache=cache)
    matcher = AssetMatcher(drawings_dir=drawings_dir, plates_dir=plates_dir)
    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=vlm_service, cache=cache)

    references = [
        {"type": "plate", "number": "10", "context": {"site": "2지점", "feature": "10호 토광묘"}}
    ]

    summary = await pipeline.review_references(references)

    # VLM was called 2 times (candidate 1 failed, candidate 2 succeeded, broke early)
    assert mock_client.call_count == 2
    assert summary.total_references == 1
    assert summary.status_counts["exact"] == 1
    assert summary.status_counts["multiple"] == 0

    res = summary.results[0]
    assert res.status == "exact"
    assert res.matched_path == cand2
    assert "Candidate 2 verified as exact match" in res.rationale


@pytest.mark.anyio
async def test_asset_review_pipeline_no_match_keeps_original_status(tmp_path):
    drawings_dir = tmp_path / "drawings"
    plates_dir = tmp_path / "plates"
    drawings_dir.mkdir()
    plates_dir.mkdir()

    # Create 3 candidate files for Plate 20
    cand1 = plates_dir / "도판 20_A.jpg"
    cand2 = plates_dir / "도판 20_B.jpg"
    cand3 = plates_dir / "도판 20_C.jpg"
    cand1.write_bytes(b"cand_20_1")
    cand2.write_bytes(b"cand_20_2")
    cand3.write_bytes(b"cand_20_3")

    # All 3 candidates return mismatch
    responses = [
        _build_mock_response("미확인 유구 1", "3지점", "1호"),
        _build_mock_response("미확인 유구 2", "3지점", "2호"),
        _build_mock_response("미확인 유구 3", "3지점", "3호"),
    ]

    mock_client = SequenceMockOpenRouterClient(responses)
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    vlm_service = VLMReviewService(client=mock_client, cache=cache)
    matcher = AssetMatcher(drawings_dir=drawings_dir, plates_dir=plates_dir)
    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=vlm_service, cache=cache)

    references = [
        {"type": "plate", "number": "20", "context": {"site": "2지점", "feature": "20호 토광묘"}}
    ]

    summary = await pipeline.review_references(references)

    # All 3 candidates checked, none matched
    assert mock_client.call_count == 3
    assert summary.status_counts["multiple"] == 1
    assert summary.status_counts["exact"] == 0
    assert summary.results[0].status == "multiple"
    assert summary.results[0].matched_path is None


@pytest.mark.anyio
async def test_asset_review_pipeline_respects_max_vlm_candidates_limit(tmp_path):
    drawings_dir = tmp_path / "drawings"
    plates_dir = tmp_path / "plates"
    drawings_dir.mkdir()
    plates_dir.mkdir()

    # Create 8 candidate files for Plate 30
    for i in range(1, 9):
        cand = plates_dir / f"도판 30_{i}.jpg"
        cand.write_bytes(f"cand_30_{i}_bytes".encode("utf-8"))

    # All candidates return mismatch
    responses = [
        _build_mock_response(f"오답 유구 {i}", "3지점", f"{i}호")
        for i in range(1, 9)
    ]

    mock_client = SequenceMockOpenRouterClient(responses)
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    vlm_service = VLMReviewService(client=mock_client, cache=cache)
    matcher = AssetMatcher(drawings_dir=drawings_dir, plates_dir=plates_dir)
    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=vlm_service, cache=cache)

    references = [
        {"type": "plate", "number": "30", "context": {"site": "2지점", "feature": "30호 토광묘"}}
    ]

    summary = await pipeline.review_references(references)

    # Must only call VLM for the first MAX_VLM_CANDIDATES (5) candidates, ignoring the remaining 3
    assert MAX_VLM_CANDIDATES == 5
    assert mock_client.call_count == 5
    assert summary.status_counts["multiple"] == 1
    assert summary.status_counts["exact"] == 0
    assert summary.results[0].status == "multiple"


@pytest.mark.anyio
async def test_asset_review_pipeline_semantic_review_resolved_by_second_candidate(tmp_path):
    drawings_dir = tmp_path / "drawings"
    plates_dir = tmp_path / "plates"
    drawings_dir.mkdir()
    plates_dir.mkdir()

    # Create 2 candidate files with blank caption bracket in filename causing semantic_review
    cand1 = drawings_dir / "【도면 】 40_A.ai"
    cand2 = drawings_dir / "【도면 】 40_B.ai"
    cand1.write_bytes(b"draw_40_1")
    cand2.write_bytes(b"draw_40_2")

    responses = [
        _build_mock_response("논산 산노리 1지점 5호 토광묘", "1지점", "5호"),
        _build_mock_response("논산 산노리 2지점 40호 토광묘", "2지점", "40호", rationale="Resolved blank caption drawing 40"),
    ]

    mock_client = SequenceMockOpenRouterClient(responses)
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    vlm_service = VLMReviewService(client=mock_client, cache=cache)
    matcher = AssetMatcher(drawings_dir=drawings_dir, plates_dir=plates_dir)
    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=vlm_service, cache=cache)

    references = [
        {"type": "drawing", "number": "40", "context": {"site": "2지점", "feature": "40호 토광묘"}}
    ]

    summary = await pipeline.review_references(references)

    assert mock_client.call_count == 2
    assert summary.status_counts["exact"] == 1
    assert summary.status_counts["semantic_review"] == 0
    assert summary.results[0].status == "exact"
    assert summary.results[0].matched_path == cand2
    assert "Resolved blank caption drawing 40" in summary.results[0].rationale


def _create_test_image_bytes(width: int = 200, height: int = 200, color: tuple = (255, 0, 0)) -> bytes:
    import io
    from PIL import Image

    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_image_processor_crop_region_valid_bbox():
    import io
    from PIL import Image

    img_bytes = _create_test_image_bytes(width=200, height=200)

    # 1. Absolute coordinates: (10, 20, 110, 120) -> width 100, height 100
    cropped = ImageProcessor.crop_region(img_bytes, bbox=(10, 20, 110, 120))
    assert cropped != b""
    with Image.open(io.BytesIO(cropped)) as img:
        assert img.size == (100, 100)

    # 2. Normalized coordinates: (0.1, 0.1, 0.5, 0.5) on 200x200 -> (20, 20, 100, 100) -> 80x80
    cropped_norm = ImageProcessor.crop_region(img_bytes, bbox=(0.1, 0.1, 0.5, 0.5))
    assert cropped_norm != b""
    with Image.open(io.BytesIO(cropped_norm)) as img:
        assert img.size == (80, 80)


def test_image_processor_crop_region_empty_and_corrupt_rejection():
    # Empty bytes
    assert ImageProcessor.crop_region(b"", bbox=(0, 0, 50, 50)) == b""

    # Corrupted / non-image bytes
    assert ImageProcessor.crop_region(b"not_an_image_payload", bbox=(0, 0, 50, 50)) == b""

    # Inverted / zero area bbox
    img_bytes = _create_test_image_bytes(100, 100)
    assert ImageProcessor.crop_region(img_bytes, bbox=(50, 50, 50, 50)) == b""
    assert ImageProcessor.crop_region(img_bytes, bbox=(80, 80, 20, 20)) == b""


@pytest.mark.anyio
async def test_review_canonical_reference_plate_panel_produces_pending_review_candidate_with_vlm_evidence(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    mock_client = MockOpenRouterMultimodalClient()
    vlm_service = VLMReviewService(client=mock_client, cache=cache)
    matcher = AssetMatcher(drawings_dir=tmp_path / "drawings", plates_dir=tmp_path / "plates")
    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=vlm_service, cache=cache)

    panel = PlatePanelData(
        panel_id="panel_45_1",
        plate_id="plate_45",
        panel_index=1,
        caption="2호 토광묘",
        bbox=(10.0, 10.0, 110.0, 110.0),
        physical_page=47,
        source_sha256="plate_hash_45",
    )
    resolution = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        target=panel,
        identity_source="plate_pdf",
        identity_evidence=["【도판 45】"],
    )
    reference = ReferenceData(
        ref_type="plate",
        number="45",
        source_sha256="doc_hash_45",
        physical_page=10,
        raw_text="도판 45",
    )
    img_bytes = _create_test_image_bytes(200, 200)

    candidates = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=vlm_service,
        image_bytes=img_bytes,
        expected_feature="2호 토광묘",
        expected_site="2지점",
        document_version_id="doc_ver_1",
        page_id="page_47",
    )

    assert len(candidates) == 1
    cand = candidates[0]
    assert isinstance(cand, CorrectionCandidateData)
    assert cand.status == "pending_review"  # Strictly pending_review, no auto-accepted
    assert cand.rule_category == "figure_plate_table_photo_ref"
    assert cand.evidence is not None
    assert isinstance(cand.evidence, EvidenceData)
    assert cand.evidence.kind == "vlm_observation"
    assert cand.evidence.source_sha256 == "plate_hash_45"
    assert cand.evidence.document_version_id == "doc_ver_1"
    assert cand.evidence.page_id == "page_47"
    assert cand.evidence.region_id == "panel_45_1"
    assert cand.evidence.bbox == (10.0, 10.0, 110.0, 110.0)
    assert cand.evidence.confidence > 0.0
    assert mock_client.call_count == 1


@pytest.mark.anyio
async def test_review_canonical_reference_drawing_region(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    mock_client = MockOpenRouterMultimodalClient()
    vlm_service = VLMReviewService(client=mock_client, cache=cache)
    matcher = AssetMatcher(drawings_dir=tmp_path / "drawings", plates_dir=tmp_path / "plates")
    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=vlm_service, cache=cache)

    region = DrawingRegionData(
        region_id="drawing_reg_57",
        drawing_id="drawing_57",
        number="57",
        title="2호 토광묘 실측도",
        bbox=(0.05, 0.05, 0.85, 0.85),
        physical_page=58,
        source_sha256="draw_hash_57",
    )
    resolution = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        target=region,
        identity_source="drawing_pdf",
        identity_evidence=["【도면 57】"],
    )
    reference = ReferenceData(
        ref_type="drawing",
        number="57",
        source_sha256="doc_hash_57",
        physical_page=12,
        raw_text="도면 57",
    )
    img_bytes = _create_test_image_bytes(200, 200)

    candidates = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=vlm_service,
        image_bytes=img_bytes,
        expected_feature="2호 토광묘",
        expected_site="2지점",
        document_version_id="doc_ver_1",
    )

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.status == "pending_review"
    assert cand.evidence is not None
    assert cand.evidence.kind == "vlm_observation"
    assert cand.evidence.source_sha256 == "draw_hash_57"
    assert cand.evidence.region_id == "drawing_reg_57"
    assert cand.evidence.bbox == (0.05, 0.05, 0.85, 0.85)
    assert mock_client.call_count == 1


@pytest.mark.anyio
async def test_review_canonical_reference_rejects_arbitrary_filename_coincidences(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    mock_client = MockOpenRouterMultimodalClient()
    vlm_service = VLMReviewService(client=mock_client, cache=cache)
    matcher = AssetMatcher(drawings_dir=tmp_path / "drawings", plates_dir=tmp_path / "plates")
    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=vlm_service, cache=cache)

    # Missing/unresolved reference or arbitrary string target
    resolution = ResolutionResult(
        status=ResolutionStatus.MISSING,
        target=None,
        identity_source="plate_pdf",
        identity_evidence=[],
    )
    reference = ReferenceData(
        ref_type="plate",
        number="91",
        source_sha256="doc_hash_91",
        physical_page=15,
        raw_text="도판 91",
    )

    candidates = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=vlm_service,
        image_bytes=b"decoy_random_91.jpg_bytes",
    )

    # Invariant: VLM MUST NEVER be called on non-resolved or arbitrary filename matches
    assert mock_client.call_count == 0
    assert len(candidates) == 1
    assert candidates[0].status == "pending_review"
    assert candidates[0].evidence is None or candidates[0].evidence.kind != "vlm_observation"


@pytest.mark.anyio
async def test_review_canonical_reference_handles_empty_or_corrupt_image_gracefully(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    mock_client = MockOpenRouterMultimodalClient()
    vlm_service = VLMReviewService(client=mock_client, cache=cache)
    matcher = AssetMatcher(drawings_dir=tmp_path / "drawings", plates_dir=tmp_path / "plates")
    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=vlm_service, cache=cache)

    panel = PlatePanelData(
        panel_id="panel_corrupt",
        plate_id="plate_99",
        panel_index=1,
        caption="99호",
        bbox=(0, 0, 50, 50),
        source_sha256="sha_99",
    )
    resolution = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        target=panel,
    )
    reference = ReferenceData(
        ref_type="plate",
        number="99",
        source_sha256="sha_99",
    )

    # 1. Empty bytes
    cand_empty = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=vlm_service,
        image_bytes=b"",
    )
    assert len(cand_empty) == 1
    assert cand_empty[0].status == "pending_review"
    assert mock_client.call_count == 0

    # 2. Corrupted bytes
    cand_corrupt = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=vlm_service,
        image_bytes=b"completely_corrupt_bytes",
    )
    assert len(cand_corrupt) == 1
    assert cand_corrupt[0].status == "pending_review"
    assert mock_client.call_count == 0


@pytest.mark.anyio
async def test_review_canonical_reference_never_auto_promotes_to_accepted(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    mock_client = MockOpenRouterMultimodalClient()
    vlm_service = VLMReviewService(client=mock_client, cache=cache)
    matcher = AssetMatcher(drawings_dir=tmp_path / "drawings", plates_dir=tmp_path / "plates")
    pipeline = AssetReviewPipeline(matcher=matcher, vlm_service=vlm_service, cache=cache)

    panel = PlatePanelData(
        panel_id="panel_1",
        plate_id="plate_1",
        panel_index=1,
        caption="1호 토광묘",
        source_sha256="hash_1",
    )
    resolution = ResolutionResult(status=ResolutionStatus.RESOLVED, target=panel)
    reference = ReferenceData(ref_type="plate", number="1", source_sha256="hash_1")
    img_bytes = _create_test_image_bytes(100, 100)

    candidates = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=vlm_service,
        image_bytes=img_bytes,
        expected_feature="1호 토광묘",
    )

    assert len(candidates) == 1
    # Candidate status must strictly be pending_review (never "accepted" or "confirmed")
    assert candidates[0].status == "pending_review"
    assert candidates[0].status != "accepted"
    assert candidates[0].status != "confirmed"

