from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


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


def test_hybrid_profile_rejects_pool_larger_than_baseline_top_k(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "source"
    source_root.mkdir()
    baseline_json = tmp_path / "baseline.json"
    baseline_json.write_text(
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
