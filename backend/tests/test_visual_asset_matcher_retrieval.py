from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import app.services.visual_asset_matcher as visual_asset_matcher
from app.services.visual_asset_matcher import VisualAssetMatcher


def _request(panel_id: str, pdf_path: str) -> visual_asset_matcher.VisualPanelRequest:
    return visual_asset_matcher.VisualPanelRequest(
        panel_id=panel_id,
        pdf_path=pdf_path,
        physical_page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
    )


def test_rank_panel_candidates_keeps_below_auto_threshold_candidates(tmp_path, monkeypatch):
    candidate_a = tmp_path / "a.jpg"
    candidate_b = tmp_path / "b.jpg"
    candidate_a.write_bytes(b"a")
    candidate_b.write_bytes(b"b")

    panel = bytes([0]) * 1024
    fingerprints = {
        candidate_a: (bytes([10]) * 1024,),
        candidate_b: (bytes([40]) * 1024,),
    }
    matcher = VisualAssetMatcher(minimum_score=0.97, minimum_margin=0.03)
    monkeypatch.setattr(
        matcher,
        "_panel_fingerprint",
        lambda pdf_path, physical_page, bbox: panel,
    )
    monkeypatch.setattr(
        matcher,
        "_candidate_fingerprints_path",
        lambda path: fingerprints[Path(path)],
    )
    candidates = [
        (SimpleNamespace(id="candidate-a"), candidate_a),
        (SimpleNamespace(id="candidate-b"), candidate_b),
    ]

    assert matcher.match_panel(
        pdf_path="plate.pdf",
        physical_page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
        candidates=candidates,
    ) is None

    ranked = matcher.rank_panel_candidates(
        pdf_path="plate.pdf",
        physical_page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
        candidates=candidates,
        limit=2,
    )

    assert [row.source_asset_id for row in ranked] == ["candidate-a", "candidate-b"]
    assert ranked[0].score < 0.97
    assert ranked[0].score > ranked[1].score


def test_rank_panels_reuses_candidate_fingerprints_for_top_k_batch(tmp_path, monkeypatch):
    candidate_a = tmp_path / "a.jpg"
    candidate_b = tmp_path / "b.jpg"
    candidate_a.write_bytes(b"a")
    candidate_b.write_bytes(b"b")

    panel = bytes([0]) * 1024
    fingerprints = {
        candidate_a: (bytes([10]) * 1024,),
        candidate_b: (bytes([40]) * 1024,),
    }
    calls: Counter[Path] = Counter()
    matcher = VisualAssetMatcher(minimum_score=0.97, minimum_margin=0.03)
    monkeypatch.setattr(
        matcher,
        "_panel_fingerprint",
        lambda pdf_path, physical_page, bbox: panel,
    )

    def fake_fingerprints(path: Path) -> tuple[bytes, ...]:
        path = Path(path)
        calls[path] += 1
        return fingerprints[path]

    monkeypatch.setattr(matcher, "_candidate_fingerprints_path", fake_fingerprints)
    candidates = [
        (SimpleNamespace(id="candidate-a"), candidate_a),
        (SimpleNamespace(id="candidate-b"), candidate_b),
    ]

    ranked = matcher.rank_panels(
        panels=[_request("panel-1", "plate-v1.pdf"), _request("panel-2", "plate-v2.pdf")],
        candidates=candidates,
        limit=2,
    )

    assert set(ranked) == {"panel-1", "panel-2"}
    assert all(rows[0].source_asset_id == "candidate-a" for rows in ranked.values())
    assert calls == Counter({candidate_a: 1, candidate_b: 1})
