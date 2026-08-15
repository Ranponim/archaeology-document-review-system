import concurrent.futures
import hashlib
import os
from pathlib import Path
import time
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

    # 5. Verify race-condition-safe concurrent writes
    def _concurrent_write(worker_id: int):
        cache.store_result(
            image_hash=computed_hash,
            prompt="ocr_plate",
            result={"plate_number": "85", "site_name": "2지점 2호 토광묘", "worker": worker_id}
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_concurrent_write, i) for i in range(16)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    # Cached result is valid JSON and no stray .tmp files left behind
    final_cached = cache.get_cached_result(computed_hash, prompt="ocr_plate")
    assert final_cached is not None
    assert final_cached["plate_number"] == "85"
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0

    # 6. Verify stats method
    stats = cache.get_cache_stats()
    assert stats["file_count"] == 1
    assert stats["total_size_bytes"] > 0

    # 7. Verify cleanup method
    old_file = tmp_path / "old_image_hash_dummy.json"
    old_file.write_text('{"plate_number": "old"}', encoding="utf-8")
    old_mtime = time.time() - (35 * 86400)
    os.utime(old_file, (old_mtime, old_mtime))

    stats_before_cleanup = cache.get_cache_stats()
    assert stats_before_cleanup["file_count"] == 2

    # Clean up files older than 30 days
    deleted_count = cache.cleanup(max_age_days=30)
    assert deleted_count == 1
    assert not old_file.exists()

    # Recent cache entry still remains
    assert cache.get_cached_result(computed_hash, prompt="ocr_plate") is not None

    stats_after_cleanup = cache.get_cache_stats()
    assert stats_after_cleanup["file_count"] == 1
    assert stats_after_cleanup["total_size_bytes"] > 0


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
    
    # 1. A drawing number that exists in the repo files (e.g., Drawing 1 in 환경 도면)
    result_drawing = matcher.match_reference(
        ref_type="drawing",
        number="1",
        context={}
    )
    assert isinstance(result_drawing, MatchedAssetResult)
    assert result_drawing.status == "exact"
    assert result_drawing.matched_path is not None
    assert "도면1" in result_drawing.matched_path.name

    # 2. A plate number that exists in the repo files (e.g., Plate 10 has multiple candidates, Plate 116 is exact)
    result_plate_multi = matcher.match_reference(
        ref_type="plate",
        number="10",
        context={}
    )
    assert isinstance(result_plate_multi, MatchedAssetResult)
    assert result_plate_multi.status == "multiple"
    assert len(result_plate_multi.candidate_paths) > 1

    result_plate_exact = matcher.match_reference(
        ref_type="plate",
        number="116",
        context={}
    )
    assert isinstance(result_plate_exact, MatchedAssetResult)
    assert result_plate_exact.status == "exact"
    assert result_plate_exact.matched_path is not None

    # 3. A completely nonexistent reference (should return 'missing')
    result_missing = matcher.match_reference(
        ref_type="drawing",
        number="99999",
        context={}
    )
    assert isinstance(result_missing, MatchedAssetResult)
    assert result_missing.status == "missing"
    assert result_missing.matched_path is None
    assert result_missing.candidate_paths == []

    # 4. Context with blank caption triggers semantic_review
    result_blank = matcher.match_reference(
        ref_type="drawing",
        number="1",
        context={"text": "출토유물 (도면 : , 도판 : )"}
    )
    assert isinstance(result_blank, MatchedAssetResult)
    assert result_blank.status == "semantic_review"
    assert result_blank.matched_path is not None


def test_asset_matcher_all_file_extensions(tmp_path):
    drawings_dir = tmp_path / "drawings"
    plates_dir = tmp_path / "plates"
    drawings_dir.mkdir()
    plates_dir.mkdir()

    drawing_exts = [".ai", ".AI", ".eps", ".EPS", ".pdf", ".PDF", ".dwg", ".DWG", ".dxf", ".DXF"]
    for idx, ext in enumerate(drawing_exts, start=1):
        (drawings_dir / f"도면_{idx}{ext}").write_bytes(f"drawing_{idx}".encode("utf-8"))

    plate_exts = [".jpg", ".JPG", ".jpeg", ".JPEG", ".png", ".PNG", ".tiff", ".TIFF", ".webp", ".WEBP"]
    for idx, ext in enumerate(plate_exts, start=1):
        (plates_dir / f"도판_{idx}{ext}").write_bytes(f"plate_{idx}".encode("utf-8"))

    matcher = AssetMatcher(drawings_dir=drawings_dir, plates_dir=plates_dir)
    summary = matcher.get_index_summary()
    assert summary["drawing_files_count"] == len(drawing_exts)
    assert summary["plate_files_count"] == len(plate_exts)

    # Test matching for each format
    for idx in range(1, len(drawing_exts) + 1):
        res = matcher.match_reference("drawing", str(idx))
        assert res.status == "exact"
        assert res.matched_path is not None

    for idx in range(1, len(plate_exts) + 1):
        res = matcher.match_reference("plate", str(idx))
        assert res.status == "exact"
        assert res.matched_path is not None


def test_asset_matcher_blank_caption_bracket_styles():
    blank_texts = [
        "출토유물 【도면】",
        "출토유물 【 도판 】",
        "출토유물 【도면  】",
        "출토유물 【도면 : , 도판 : 】",
        "출토유물 [도면]",
        "출토유물 [ 도판 ]",
        "출토유물 [도면 : , 도판 : ]",
        "출토유물 (도면)",
        "출토유물 (도판)",
        "출토유물 (도면, 도판)",
        "출토유물 (도면 : , 도판 : )",
        "출토유물 <도면>",
        "출토유물 < 도판 >",
        "출토유물 <도면 : , 도판 : >",
        "출토유물 〈도면〉",
        "출토유물 《도판》",
        "도면 :",
        "도판 :",
        "도면: ",
        "도판:",
        "도면 : , 도판 :",
    ]
    for text in blank_texts:
        assert AssetMatcher._is_blank_caption_text(text), f"Failed to detect blank caption in: {text}"

    non_blank_texts = [
        "출토유물 (도면 57, 도판 85)",
        "출토유물 【도면 57】",
        "출토유물 [도판 85]",
        "출토유물 <도면 1>",
        "1. 조사지역의 위치 및 환경",
        "도면 57",
        "도판 85",
    ]
    for text in non_blank_texts:
        assert not AssetMatcher._is_blank_caption_text(text), f"False positive blank caption in: {text}"


def test_asset_matcher_bracket_styles_in_filenames(tmp_path):
    drawings_dir = tmp_path / "drawings"
    plates_dir = tmp_path / "plates"
    drawings_dir.mkdir()
    plates_dir.mkdir()

    (drawings_dir / "[도면] 50_A.ai").write_bytes(b"cand1")
    (plates_dir / "<도판> 60_A.jpg").write_bytes(b"cand2")

    matcher = AssetMatcher(drawings_dir=drawings_dir, plates_dir=plates_dir)

    res_drawing = matcher.match_reference("drawing", "50")
    assert res_drawing.status == "semantic_review"
    assert res_drawing.matched_path == drawings_dir / "[도면] 50_A.ai"

    res_plate = matcher.match_reference("plate", "60")
    assert res_plate.status == "semantic_review"
    assert res_plate.matched_path == plates_dir / "<도판> 60_A.jpg"

