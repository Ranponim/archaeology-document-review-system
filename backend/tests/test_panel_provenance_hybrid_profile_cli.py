from __future__ import annotations

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
