from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_hybrid_local_runner_cli_imports_without_real_corpus():
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "evaluate_panel_provenance_hybrid.py"),
            "--help",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "geometric-candidate-pool" in result.stdout
    assert "source-root" in result.stdout
