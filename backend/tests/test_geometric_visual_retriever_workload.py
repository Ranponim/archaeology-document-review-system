from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image

from app.services.geometric_visual_retriever import GeometricVisualRetriever


def test_candidate_workload_is_bounded_without_capping_panel_features(tmp_path: Path):
    candidate_path = tmp_path / "candidate.png"
    image = Image.effect_noise((640, 480), 64).convert("RGB")
    image.save(candidate_path)

    retriever = GeometricVisualRetriever(
        candidate_max_edge=320,
        sift_nfeatures=64,
    )

    candidate_gray = retriever._candidate_grayscale(image)
    assert max(candidate_gray.shape) == 320

    panel_features = retriever._features_image(image)
    candidate_features = retriever._features_path(candidate_path)

    assert panel_features is not None
    assert candidate_features is not None
    assert len(panel_features[0]) > 64
    assert len(candidate_features[0]) <= 64
    assert len(candidate_features[1]) <= 64


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"candidate_max_edge": 0}, "candidate_max_edge must be positive"),
        ({"sift_nfeatures": 0}, "sift_nfeatures must be positive"),
    ],
)
def test_candidate_workload_limits_reject_non_positive_values(kwargs, message):
    with pytest.raises(ValueError, match=message):
        GeometricVisualRetriever(**kwargs)


def test_hybrid_local_runner_exposes_candidate_workload_flags():
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
    assert "geometric-candidate-max-edge" in result.stdout
    assert "geometric-sift-nfeatures" in result.stdout
