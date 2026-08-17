"""Pytest collection helpers for portable CI and ReviewRound migration."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


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

# These nodeids assert the retired pre-ReviewRound execution contract. They are
# intentionally retained as migration documentation. Replacement coverage lives
# in the ReviewRound authority/unbounded-round tests and real Neo4j integration.
_RETIRED_DIRECT_STAGE_TESTS = {
    "test_reviews_api.py::test_trigger_analysis_run_enqueues_and_returns_202": (
        "legacy direct-version execution expected no deprecation warning; ReviewRound is canonical"
    ),
    "test_production_orchestrator_assembly.py::test_run_trigger_enqueues_only_and_worker_uses_full_production_orchestrator": (
        "legacy direct-version warning assertion predates ReviewRound authority"
    ),
    "test_reviews_api.py::test_trigger_analysis_run_stage_mismatch_returns_404": (
        "human stage labels are compatibility metadata, not canonical ReviewRound identity"
    ),
    "test_version_input_resolution.py::test_run_route_uses_canonical_version_resolution_and_stage_mismatch_failure": (
        "implicit stage-only run resolution was replaced by ReviewRound/exact graph identity"
    ),
}


def pytest_ignore_collect(collection_path: Path, config):  # noqa: ARG001
    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / "src").is_dir():
        return None
    if Path(str(collection_path)).name in _LOCAL_ASSET_MODULES:
        return True
    return None


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    neo4j_configured = bool(os.environ.get("NEO4J_TEST_URI"))
    for item in items:
        nodeid = item.nodeid.replace("\\", "/")

        if not neo4j_configured and "test_project_repository.py::" in nodeid:
            item.add_marker(
                pytest.mark.skip(
                    reason="real Neo4j repository integration runs in the dedicated neo4j-e2e CI job"
                )
            )
            continue

        for suffix, reason in _RETIRED_DIRECT_STAGE_TESTS.items():
            if nodeid.endswith(suffix):
                item.add_marker(pytest.mark.xfail(reason=reason, strict=False))
                break
