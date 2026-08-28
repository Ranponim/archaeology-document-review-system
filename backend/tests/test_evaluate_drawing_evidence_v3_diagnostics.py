from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "evaluate_drawing_evidence_v3.py"
SPEC = importlib.util.spec_from_file_location(
    "evaluate_drawing_evidence_v3_diagnostics", SCRIPT_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_resolution_rows_preserves_auto_gate_diagnostics(tmp_path):
    source = SimpleNamespace(
        source_asset_id="asset-1",
        source_path="본문 도면/1지점/source.ai",
        evidence=(),
    )
    candidate = SimpleNamespace(
        candidate_id="candidate-35",
        publication_kind="drawing",
        number="35",
        evidence=(),
        hard_contradiction=False,
    )
    decision = SimpleNamespace(
        verdict="match",
        confidence=0.98,
        summary="visual match",
        cited_support_ids=("ev:filename",),
    )
    result = SimpleNamespace(
        source_asset_id="asset-1",
        status="REVIEW_REQUIRED",
        candidates=(candidate,),
        selected_candidate_id="candidate-35",
        decision=decision,
        diagnostics={
            "auto_gate_reason": "weak_support_only",
            "cited_support_ids": ["ev:filename"],
            "cited_support_families": ["weak_filename_semantic"],
            "cited_nonweak_count": 0,
            "cited_contradiction_ids": [],
        },
    )
    resolution = SimpleNamespace(source_results=(result,))

    row = MODULE.resolution_rows(tmp_path, [source], resolution)[0]

    assert row["auto_gate_reason"] == "weak_support_only"
    assert row["cited_support_ids"] == ["ev:filename"]
    assert row["cited_support_families"] == ["weak_filename_semantic"]
    assert row["cited_nonweak_count"] == 0
    assert row["cited_contradiction_ids"] == []
