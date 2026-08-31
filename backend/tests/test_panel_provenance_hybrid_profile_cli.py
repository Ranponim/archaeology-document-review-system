from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import tools.profile_panel_provenance_hybrid as profiler


def test_hybrid_profile_cli_exposes_bounded_sample_contract():
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "profile_panel_provenance_hybrid.py"),
            "--help",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--sample-size" in result.stdout
    assert "--geometric-candidate-pool" in result.stdout
    assert "--output-json" in result.stdout
    assert "100 unresolved panels" in result.stdout


def _write_empty_baseline(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "measurement_head": "baseline-head",
                "elapsed_seconds": 0.0,
                "algorithm": {"top_k": 5},
                "rows": [],
            }
        ),
        encoding="utf-8",
    )


def test_hybrid_profile_rejects_pool_larger_than_baseline_top_k(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "source"
    source_root.mkdir()
    baseline_json = tmp_path / "baseline.json"
    _write_empty_baseline(baseline_json)
    output_json = tmp_path / "profile.json"

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "profile_panel_provenance_hybrid.py"),
            "--source-root",
            str(source_root),
            "--baseline-json",
            str(baseline_json),
            "--geometric-candidate-pool",
            "50",
            "--output-json",
            str(output_json),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "baseline top_k=5" in result.stderr
    assert "regenerate the baseline" in result.stderr
    assert not output_json.exists()


def test_hybrid_profile_reports_candidate_timing_breakdown(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "source"
    source_root.mkdir()
    baseline_json = tmp_path / "baseline.json"
    _write_empty_baseline(baseline_json)
    output_json = tmp_path / "profile.json"

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "profile_panel_provenance_hybrid.py"),
            "--source-root",
            str(source_root),
            "--baseline-json",
            str(baseline_json),
            "--geometric-candidate-pool",
            "5",
            "--output-json",
            str(output_json),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["baseline_top_k"] == 5
    timing = payload["timing"]
    assert timing["candidate_step_count"] == 0
    assert timing["candidate_feature_mean_seconds"] is None
    assert timing["candidate_evidence_mean_seconds"] is None
    assert timing["candidate_feature_cache_hit_count"] == 0
    assert timing["candidate_feature_cache_miss_count"] == 0
    assert timing["candidate_feature_cache_hit_mean_seconds"] is None
    assert timing["candidate_feature_cache_miss_mean_seconds"] is None


def test_hybrid_profile_reports_deep_breakdown_schema(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "source"
    source_root.mkdir()
    baseline_json = tmp_path / "baseline.json"
    _write_empty_baseline(baseline_json)
    output_json = tmp_path / "deep-profile.json"

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "profile_panel_provenance_hybrid.py"),
            "--source-root",
            str(source_root),
            "--baseline-json",
            str(baseline_json),
            "--geometric-candidate-pool",
            "5",
            "--output-json",
            str(output_json),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["sampled_panel_ids"] == []
    assert payload["candidate_image_stats"]["pixel_count_histogram"] == {
        "<=0.5MP": 0,
        "0.5-1MP": 0,
        "1-2MP": 0,
        "2-4MP": 0,
        "4-8MP": 0,
        ">8MP": 0,
    }
    assert payload["candidate_feature_stats"]["descriptor_count_histogram"] == {
        "0": 0,
        "1-250": 0,
        "251-500": 0,
        "501-1000": 0,
        "1001-2000": 0,
        ">2000": 0,
    }
    assert payload["candidate_reuse"]["total_candidate_evaluations"] == 0
    assert payload["candidate_reuse"]["unique_candidate_source_count"] == 0
    assert payload["correlations"]["pixel_count_vs_sift_detect_compute"] is None
    assert payload["correlations"]["descriptor_count_vs_bf_knn_match"] is None
    assert payload["timing"]["candidate_feature_decomposition"]["image_decode"]["total_seconds"] == 0.0
    assert payload["timing"]["candidate_evidence_decomposition"]["bf_knn_match"]["total_seconds"] == 0.0


def test_profiler_keeps_image_decode_separate_from_sift_time(tmp_path: Path):
    candidate_path = tmp_path / "candidate.png"
    Image.effect_noise((256, 256), 64).convert("RGB").save(candidate_path)
    retriever = profiler._ProfiledGeometricVisualRetriever()
    record: dict[str, object] = {}

    started = time.perf_counter()
    features, record = retriever.profile_candidate_features(candidate_path, record)
    total_seconds = time.perf_counter() - started

    assert features is not None
    assert record["image_decode_seconds"] > 0.0
    assert record["sift_detect_compute_seconds"] > 0.0
    measured = (
        record["image_decode_seconds"]
        + record["grayscale_or_preprocess_seconds"]
        + record["sift_detect_compute_seconds"]
    )
    assert measured <= total_seconds * 1.2
