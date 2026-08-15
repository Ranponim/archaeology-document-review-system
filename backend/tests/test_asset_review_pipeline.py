import json
from pathlib import Path
import pytest
from app.services.asset_cache import AssetHashCache
from app.services.asset_matcher import AssetMatcher
from app.services.vlm_review_service import VLMReviewService
from app.services.asset_review_pipeline import AssetReviewPipeline, AssetPipelineSummary


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
