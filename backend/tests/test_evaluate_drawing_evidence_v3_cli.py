from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "evaluate_drawing_evidence_v3.py"
SPEC = importlib.util.spec_from_file_location("evaluate_drawing_evidence_v3", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _required_args(tmp_path: Path) -> list[str]:
    return [
        "--source-root",
        str(tmp_path / "src"),
        "--gold",
        str(tmp_path / "gold.json"),
        "--output-json",
        str(tmp_path / "result.json"),
        "--output-report",
        str(tmp_path / "result.md"),
        "--live-codex",
    ]


def test_live_acceptance_cli_accepts_single_source_smoke_limit(tmp_path):
    args = MODULE.build_parser().parse_args(_required_args(tmp_path) + ["--limit", "1"])

    assert args.limit == 1


def test_discover_limited_ai_files_slices_without_reordering(monkeypatch, tmp_path):
    paths = [tmp_path / "c.ai", tmp_path / "a.ai", tmp_path / "b.ai"]
    monkeypatch.setattr(MODULE, "discover_ai_files", lambda _root: list(paths))

    assert MODULE.discover_limited_ai_files(tmp_path, limit=2) == paths[:2]
    assert MODULE.discover_limited_ai_files(tmp_path, limit=None) == paths


@pytest.mark.parametrize("limit", [0, -1])
def test_discover_limited_ai_files_rejects_non_positive_limit(monkeypatch, tmp_path, limit):
    monkeypatch.setattr(MODULE, "discover_ai_files", lambda _root: [])

    with pytest.raises(ValueError, match="limit must be positive"):
        MODULE.discover_limited_ai_files(tmp_path, limit=limit)
