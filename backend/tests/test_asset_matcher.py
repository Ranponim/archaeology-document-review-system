import os
import hashlib
from pathlib import Path
import pytest
from app.services.asset_cache import AssetHashCache
from app.services.asset_matcher import AssetMatcher, MatchedAssetResult


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


def test_asset_hash_cache_computes_sha256_and_caches(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path)
    
    dummy_bytes = b"JPEG_IMAGE_PIXEL_DATA_12345"
    expected_hash = hashlib.sha256(dummy_bytes).hexdigest()
    
    # 1. Compute hash
    computed_hash = cache.compute_bytes_hash(dummy_bytes)
    assert computed_hash == expected_hash
    
    # 2. Check cache miss
    assert cache.get_cached_result(computed_hash, prompt="ocr_plate") is None
    
    # 3. Store result
    cache.store_result(
        image_hash=computed_hash,
        prompt="ocr_plate",
        result={"plate_number": "85", "site_name": "2지점 2호 토광묘"}
    )
    
    # 4. Check cache hit (0 cost)
    cached = cache.get_cached_result(computed_hash, prompt="ocr_plate")
    assert cached is not None
    assert cached["plate_number"] == "85"


def test_asset_matcher_indexes_real_repository_assets():
    matcher = AssetMatcher(
        drawings_dir=SRC_DRAWINGS,
        plates_dir=SRC_PLATES,
        env_dir=SRC_ENV
    )
    
    summary = matcher.get_index_summary()
    assert summary["drawing_files_count"] > 0
    assert summary["plate_files_count"] > 0


def test_asset_matcher_matches_sample_references():
    matcher = AssetMatcher(
        drawings_dir=SRC_DRAWINGS,
        plates_dir=SRC_PLATES,
        env_dir=SRC_ENV
    )
    
    # Reference for Drawing 58, 59, 60 (2지점 토광묘 AI drawing)
    result_58 = matcher.match_reference(
        ref_type="drawing",
        number="58",
        context={"feature": "토광묘", "site_point": "2지점"}
    )
    assert isinstance(result_58, MatchedAssetResult)
    assert result_58.status in ["exact", "multiple", "semantic_review"]
    assert result_58.matched_path is not None or len(result_58.candidate_paths) > 0
