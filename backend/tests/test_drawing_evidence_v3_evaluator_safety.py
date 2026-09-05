from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.evaluate_drawing_evidence_v3 import resolution_rows


def _resolution_with_weak_support(*, families: list[str]):
    weak_evidence = SimpleNamespace(id="weak-1", weak=True)
    candidate = SimpleNamespace(
        candidate_id="candidate-35",
        publication_kind="drawing",
        number="35",
        evidence=(weak_evidence,),
        hard_contradiction=False,
    )
    decision = SimpleNamespace(
        candidate_id="candidate-35",
        verdict="match",
        confidence=0.98,
        summary="visual match",
        cited_support_ids=("weak-1",),
    )
    result = SimpleNamespace(
        source_asset_id="source-1",
        status="AUTO_VERIFIED",
        selected_candidate_id="candidate-35",
        candidates=(candidate,),
        decision=decision,
        diagnostics={
            "auto_gate_reason": "auto_verified",
            "cited_support_ids": ["weak-1"],
            "cited_visual_support_ids": ["visual-1"] if "visual_signature" in families else [],
            "cited_support_families": families,
            "cited_nonweak_count": 1 if "visual_signature" in families else 0,
            "cited_contradiction_ids": [],
        },
    )
    source = SimpleNamespace(
        source_asset_id="source-1",
        source_path="drawing.ai",
        evidence=(),
    )
    return source, SimpleNamespace(source_results=(result,))


def _filename_only_promoted(*, families: list[str]) -> bool:
    source, resolution = _resolution_with_weak_support(families=families)
    rows = resolution_rows(Path("."), [source], resolution)
    return rows[0]["filename_only_promoted"]


def test_validated_visual_support_is_not_filename_only():
    assert _filename_only_promoted(
        families=["visual_signature", "weak_filename_semantic"]
    ) is False


def test_weak_support_without_visual_remains_filename_only():
    assert _filename_only_promoted(families=["weak_filename_semantic"]) is True
