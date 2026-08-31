from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.services.geometric_visual_retriever import GeometricVisualRetriever


def _feature_rich_image() -> Image.Image:
    image = Image.new("RGB", (640, 480), "white")
    draw = ImageDraw.Draw(image)
    for x in range(20, 620, 35):
        draw.line((x, 10, x, 470), fill=(40 + x % 160,) * 3, width=3)
    for y in range(20, 460, 31):
        draw.line((10, y, 630, y), fill=(50 + y % 150,) * 3, width=2)
    for index in range(15):
        x = 30 + (index * 37) % 520
        y = 35 + (index * 53) % 360
        draw.ellipse(
            (x, y, x + 45, y + 38),
            outline=(20 + index * 10,) * 3,
            width=4,
        )
    return image


def test_matcher_backend_defaults_to_bf():
    retriever = GeometricVisualRetriever()

    assert retriever.matcher_backend == "bf"
    assert retriever.flann_fallback_count == 0


def test_flann_backend_recovers_transformed_candidate(tmp_path: Path):
    candidate = _feature_rich_image()
    candidate_path = tmp_path / "candidate.jpg"
    candidate.save(candidate_path, quality=96)
    panel = candidate.crop((70, 55, 585, 425)).rotate(
        5,
        expand=True,
        fillcolor="white",
    )
    panel = panel.resize((430, 320), Image.Resampling.LANCZOS)

    retriever = GeometricVisualRetriever(
        matcher_backend="flann",
        candidate_max_edge=640,
        sift_nfeatures=4000,
    )
    ranked = retriever.rank(
        panel_image=panel,
        candidates=[(SimpleNamespace(id="candidate"), candidate_path)],
        top_k=1,
    )

    assert ranked
    assert ranked[0].source_asset_id == "candidate"
    assert ranked[0].inliers >= retriever.minimum_inliers
    assert retriever.flann_fallback_count == 0


def test_unknown_matcher_backend_is_rejected():
    with pytest.raises(ValueError, match="matcher_backend must be 'bf' or 'flann'"):
        GeometricVisualRetriever(matcher_backend="annoy")


def test_flann_error_falls_back_to_bf_and_is_counted():
    retriever = GeometricVisualRetriever(matcher_backend="flann")

    class BrokenMatcher:
        def knnMatch(self, *_args, **_kwargs):
            raise cv2.error("forced flann failure")

    retriever._matcher = BrokenMatcher()
    query = np.random.default_rng(7).random((8, 128), dtype=np.float32)
    train = np.random.default_rng(8).random((12, 128), dtype=np.float32)

    pairs = retriever._knn_match(query, train)

    assert len(pairs) == len(query)
    assert retriever.flann_fallback_count == 1


def test_hybrid_local_runner_exposes_matcher_backend_flag():
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
    assert "geometric-matcher" in result.stdout
