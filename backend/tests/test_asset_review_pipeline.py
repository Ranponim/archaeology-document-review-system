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


@pytest.mark.anyio
async def test_asset_review_pipeline_reproduces_sample_baseline(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path)
    matcher = AssetMatcher(SRC_DRAWINGS, SRC_PLATES, SRC_ENV)
    vlm_service = VLMReviewService(client=None, cache=cache, model="openai/gpt-5.6-luna")
    
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
    assert summary.status_counts["exact"] == 3
    assert summary.status_counts["multiple"] == 4
    assert summary.status_counts["missing"] == 1
    assert summary.status_counts["semantic_review"] == 2
