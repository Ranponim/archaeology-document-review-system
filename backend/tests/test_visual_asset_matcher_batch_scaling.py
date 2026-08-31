from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import app.services.visual_asset_matcher as visual_asset_matcher
from app.services.visual_asset_matcher import VisualAssetMatcher


def test_match_panels_avoids_scalar_similarity_loop_for_production_batch(
    tmp_path,
    monkeypatch,
):
    """Batch matching must not do one Python byte loop per panel/candidate pair.

    The real plate acceptance contains 2,750 safely segmented panels and 1,032
    JPG candidates. A scalar _similarity call for every pair is not a practical
    production execution path, even when candidate decoding and PDF opening are
    cached.
    """

    candidate_a = tmp_path / "a.jpg"
    candidate_b = tmp_path / "b.jpg"
    candidate_a.write_bytes(b"a")
    candidate_b.write_bytes(b"b")

    zero = bytes([0]) * 1024
    full = bytes([255]) * 1024
    matcher = VisualAssetMatcher(minimum_score=0.97, minimum_margin=0.03)

    monkeypatch.setattr(
        matcher,
        "_candidate_fingerprints_path",
        lambda path: (zero,) if Path(path) == candidate_a else (full,),
    )
    monkeypatch.setattr(
        matcher,
        "_panel_fingerprint",
        lambda pdf_path, physical_page, bbox: zero,
    )

    def scalar_similarity_must_not_run(left: bytes, right: bytes) -> float:
        raise AssertionError("production batch fell back to scalar similarity")

    monkeypatch.setattr(matcher, "_similarity", scalar_similarity_must_not_run)

    matches = matcher.match_panels(
        panels=[
            visual_asset_matcher.VisualPanelRequest(
                panel_id="panel-v1",
                pdf_path="plate-v1.pdf",
                physical_page=1,
                bbox=(0.0, 0.0, 1.0, 1.0),
            ),
            visual_asset_matcher.VisualPanelRequest(
                panel_id="panel-v2",
                pdf_path="plate-v2.pdf",
                physical_page=1,
                bbox=(0.0, 0.0, 1.0, 1.0),
            ),
        ],
        candidates=[
            (SimpleNamespace(id="a"), candidate_a),
            (SimpleNamespace(id="b"), candidate_b),
        ],
    )

    assert set(matches) == {"panel-v1", "panel-v2"}
    assert {match.source_asset_id for match in matches.values()} == {"a"}
