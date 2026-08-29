from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.evaluate_drawing_evidence_v3 import _weak_only_support


def _result_with_weak_support(*, families: list[str]):
    weak_evidence = SimpleNamespace(id="weak-1", weak=True)
    decision = SimpleNamespace(cited_support_ids=("weak-1",))
    candidate = SimpleNamespace(evidence=(weak_evidence,))
    return SimpleNamespace(
        decision=decision,
        candidates=(candidate,),
        diagnostics={"cited_support_families": families},
    )


def test_validated_visual_support_is_not_filename_only():
    result = _result_with_weak_support(
        families=["visual_signature", "weak_filename_semantic"]
    )

    assert _weak_only_support(result) is False


def test_weak_support_without_visual_remains_filename_only():
    result = _result_with_weak_support(families=["weak_filename_semantic"])

    assert _weak_only_support(result) is True
