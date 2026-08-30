from __future__ import annotations

import app.services.visual_asset_matcher as visual_asset_matcher
from app.services.visual_asset_matcher import VisualAssetMatcher


def test_identical_geometry_aliases_do_not_create_false_source_collision(monkeypatch):
    matcher = VisualAssetMatcher()
    request_type = visual_asset_matcher.VisualPanelRequest
    requests = [
        request_type(
            panel_id="alias-a",
            uniqueness_scope_id="pdf-revision-a",
            pdf_path="plate.pdf",
            physical_page=109,
            bbox=(0.270985, 0.295455, 0.718802, 0.462963),
        ),
        request_type(
            panel_id="alias-b",
            uniqueness_scope_id="pdf-revision-a",
            pdf_path="plate.pdf",
            physical_page=109,
            bbox=(0.270985, 0.295455, 0.718802, 0.462963),
        ),
    ]

    monkeypatch.setattr(
        matcher,
        "match_panel",
        lambda **_: visual_asset_matcher.VisualAssetMatch(
            source_asset_id="Links/65 (3).JPG",
            score=0.998380055,
        ),
    )

    matches = matcher.match_panels(panels=requests, candidates=[])

    assert set(matches) == {"alias-a", "alias-b"}
    assert {match.source_asset_id for match in matches.values()} == {"Links/65 (3).JPG"}
