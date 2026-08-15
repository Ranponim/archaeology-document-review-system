import json
from pathlib import Path
import pytest
from app.services.asset_cache import AssetHashCache
from app.services.asset_matcher import AssetMatcher
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
        self.mock_response = mock_response or {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "label_detected": "논산 산노리 2지점 2호 토광묘",
                            "feature_number": "2",
                            "site_point": "2지점",
                            "compass_north": "N-74-E",
                            "match_confidence": 0.98,
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

    async def analyze_multimodal(self, prompt: str, image_bytes: bytes, mime_type: str) -> dict:
        self.call_count += 1
        self.calls.append({"prompt": prompt, "image_bytes": image_bytes, "mime_type": mime_type})
        return self.mock_response


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
