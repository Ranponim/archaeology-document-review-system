"""Pytest collection helpers for portable CI.

Several legacy integration-style test modules intentionally exercise the user's
local archaeology source tree under ``<repo>/src``. That fixture directory is
not committed to GitHub, so importing those modules in CI used to fail during
collection before their tests could decide whether the assets were available.

When the local fixture tree exists, nothing is skipped. When it is absent (as
on GitHub Actions), only the modules that unconditionally require that tree are
ignored. The hermetic backend suite and the real-Neo4j remediation suite remain
fully runnable in CI.
"""
from pathlib import Path


_LOCAL_ASSET_MODULES = {
    "test_artifact_visual_comparison.py",
    "test_asset_matcher.py",
    "test_asset_review_pipeline.py",
    "test_page_aligner.py",
    "test_panel_render_flow.py",
    "test_pdf_parser.py",
    "test_pdf_parser_layout.py",
    "test_plate_parser.py",
    "test_review_pipeline_e2e.py",
    "test_rule_engine.py",
}


def pytest_ignore_collect(collection_path: Path, config):  # noqa: ARG001
    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / "src").is_dir():
        return None
    if Path(str(collection_path)).name in _LOCAL_ASSET_MODULES:
        return True
    return None
