from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.services.geometric_visual_retriever import GeometricVisualEvidence
from app.services.visual_asset_matcher import VisualAssetMatcher


class _AmbiguousGeometricRetriever:
    def rank(self, *, panel_image, candidates, top_k=5):
        del panel_image, candidates, top_k
        return (
            GeometricVisualEvidence(
                source_asset_id="candidate-a",
                score=0.85,
                good_matches=30,
                inliers=24,
                inlier_ratio=0.80,
            ),
            GeometricVisualEvidence(
                source_asset_id="candidate-b",
                score=0.80,
                good_matches=28,
                inliers=22,
                inlier_ratio=0.79,
            ),
        )


def test_geometric_fallback_remains_fail_closed_when_top_two_are_too_close(
    monkeypatch,
    tmp_path: Path,
):
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    first.write_bytes(b"candidate-a")
    second.write_bytes(b"candidate-b")

    matcher = VisualAssetMatcher(
        minimum_score=0.97,
        minimum_margin=0.03,
        geometric_minimum_margin=0.08,
        geometric_retriever=_AmbiguousGeometricRetriever(),
    )
    monkeypatch.setattr(
        matcher,
        "_panel_fingerprint",
        lambda *_args, **_kwargs: bytes([0]) * (32 * 32),
    )
    monkeypatch.setattr(
        matcher,
        "_candidate_fingerprints_path",
        lambda _path: (bytes([16]) * (32 * 32),),
    )
    monkeypatch.setattr(
        matcher,
        "_panel_image",
        lambda *_args, **_kwargs: Image.new("RGB", (128, 128), "white"),
    )

    assessment = matcher.assess_panel(
        pdf_path=tmp_path / "plate.pdf",
        physical_page=1,
        bbox=(0.1, 0.1, 0.9, 0.9),
        candidates=[
            (SimpleNamespace(id="candidate-a"), first),
            (SimpleNamespace(id="candidate-b"), second),
        ],
    )

    assert assessment.status == "BELOW_SCORE"
    assert assessment.match is None
