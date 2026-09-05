from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from PIL import Image, ImageDraw

import app.services.visual_asset_matcher as visual_asset_matcher
from app.services.visual_asset_matcher import VisualAssetMatcher


def _write_pattern_jpg(path: Path) -> None:
    image = Image.new("RGB", (200, 140), "black")
    draw = ImageDraw.Draw(image)
    for index, value in enumerate((20, 220, 50, 180, 90)):
        draw.rectangle(
            (index * 40, 0, index * 40 + 39, 139),
            fill=(value, value, value),
        )
    draw.ellipse((55, 20, 145, 120), fill=(130, 130, 130))
    image.save(path, format="JPEG", quality=100, subsampling=0)


def _write_bordered_pattern_jpg(path: Path) -> tuple[int, int, int, int]:
    inner = Image.new("RGB", (160, 112), "black")
    draw = ImageDraw.Draw(inner)
    for index, value in enumerate((20, 220, 50, 180, 90)):
        draw.rectangle(
            (index * 32, 0, index * 32 + 31, 111),
            fill=(value, value, value),
        )
    draw.ellipse((44, 16, 116, 96), fill=(130, 130, 130))

    canvas = Image.new("RGB", (320, 220), "white")
    box = (73, 51, 233, 163)
    canvas.paste(inner, box[:2])
    canvas.save(path, format="JPEG", quality=100, subsampling=0)
    return box


def _write_distractor_jpg(path: Path) -> None:
    image = Image.new("RGB", (200, 140), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 15, 180, 125), fill=(35, 35, 35))
    draw.line((0, 0, 199, 139), fill=(200, 200, 200), width=8)
    image.save(path, format="JPEG", quality=100, subsampling=0)


def _write_pdf_with_center_crop(original_path: Path, pdf_path: Path) -> tuple[float, float, float, float]:
    with Image.open(original_path) as image:
        image.load()
        # The publication used only the central 80% of the original JPG.
        cropped = image.crop((20, 14, 180, 126))
        payload = BytesIO()
        cropped.save(payload, format="PNG")

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=200, height=200)
        rect = pymupdf.Rect(20, 20, 180, 132)
        page.insert_image(rect, stream=payload.getvalue())
        doc.save(str(pdf_path))
    finally:
        doc.close()

    return (0.10, 0.10, 0.90, 0.66)


def _write_pdf_without_source_border(
    original_path: Path,
    pdf_path: Path,
    content_box: tuple[int, int, int, int],
) -> tuple[float, float, float, float]:
    with Image.open(original_path) as image:
        image.load()
        cropped = image.crop(content_box)
        payload = BytesIO()
        cropped.save(payload, format="PNG")

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=200, height=200)
        rect = pymupdf.Rect(20, 20, 180, 132)
        page.insert_image(rect, stream=payload.getvalue())
        doc.save(str(pdf_path))
    finally:
        doc.close()

    return (0.10, 0.10, 0.90, 0.66)


def _stub_scores(monkeypatch, matcher, tmp_path, scored_assets):
    candidates = []
    scores = {}
    for source_asset_id, score in scored_assets:
        path = tmp_path / f"{source_asset_id}.jpg"
        path.write_bytes(b"candidate")
        candidates.append((SimpleNamespace(id=source_asset_id), path))
        scores[path.name.encode()] = score

    monkeypatch.setattr(matcher, "_panel_fingerprint", lambda *_: b"panel")
    monkeypatch.setattr(
        matcher,
        "_candidate_fingerprints_path",
        lambda path: (path.name.encode(),),
    )
    monkeypatch.setattr(
        matcher,
        "_similarity",
        lambda _panel, candidate: scores[candidate],
    )
    return candidates


def test_match_panel_accepts_bounded_center_crop_without_lowering_safety_threshold(tmp_path):
    original = tmp_path / "original.jpg"
    distractor = tmp_path / "distractor.jpg"
    pdf_path = tmp_path / "plate.pdf"
    _write_pattern_jpg(original)
    _write_distractor_jpg(distractor)
    bbox = _write_pdf_with_center_crop(original, pdf_path)

    matcher = VisualAssetMatcher(minimum_score=0.97, minimum_margin=0.03)
    match = matcher.match_panel(
        pdf_path=pdf_path,
        physical_page=1,
        bbox=bbox,
        candidates=[
            (SimpleNamespace(id="original"), original),
            (SimpleNamespace(id="distractor"), distractor),
        ],
    )

    assert match is not None
    assert match.source_asset_id == "original"
    assert match.score >= 0.97


def test_match_panel_trims_light_source_border_without_lowering_safety_threshold(tmp_path):
    original = tmp_path / "bordered-original.jpg"
    distractor = tmp_path / "distractor.jpg"
    pdf_path = tmp_path / "plate.pdf"
    content_box = _write_bordered_pattern_jpg(original)
    _write_distractor_jpg(distractor)
    bbox = _write_pdf_without_source_border(original, pdf_path, content_box)

    matcher = VisualAssetMatcher(minimum_score=0.97, minimum_margin=0.03)
    match = matcher.match_panel(
        pdf_path=pdf_path,
        physical_page=1,
        bbox=bbox,
        candidates=[
            (SimpleNamespace(id="original"), original),
            (SimpleNamespace(id="distractor"), distractor),
        ],
    )

    assert match is not None
    assert match.source_asset_id == "original"
    assert match.score >= 0.97


def test_match_panels_fails_closed_when_two_panels_in_same_revision_select_same_source(monkeypatch):
    request_type = visual_asset_matcher.VisualPanelRequest
    matcher = VisualAssetMatcher()
    requests = [
        request_type(
            panel_id="panel-a",
            uniqueness_scope_id="pdf-a",
            pdf_path="plate.pdf",
            physical_page=1,
            bbox=(0.0, 0.0, 0.5, 0.5),
        ),
        request_type(
            panel_id="panel-b",
            uniqueness_scope_id="pdf-a",
            pdf_path="plate.pdf",
            physical_page=1,
            bbox=(0.5, 0.0, 1.0, 0.5),
        ),
    ]

    monkeypatch.setattr(
        matcher,
        "match_panel",
        lambda **_: visual_asset_matcher.VisualAssetMatch(
            source_asset_id="same-photo",
            score=0.99,
        ),
    )

    matches = matcher.match_panels(panels=requests, candidates=[])

    assert matches == {}


# Regression from the 2,750-panel acceptance: reuse across revisions is valid.
def test_match_panels_allows_same_source_across_revision_scopes(monkeypatch):
    request_type = visual_asset_matcher.VisualPanelRequest
    matcher = VisualAssetMatcher()
    requests = [
        request_type(
            panel_id="rev-a-panel",
            uniqueness_scope_id="pdf-a",
            pdf_path="a.pdf",
            physical_page=1,
            bbox=(0.0, 0.0, 0.5, 0.5),
        ),
        request_type(
            panel_id="rev-b-panel",
            uniqueness_scope_id="pdf-b",
            pdf_path="b.pdf",
            physical_page=1,
            bbox=(0.0, 0.0, 0.5, 0.5),
        ),
    ]

    monkeypatch.setattr(
        matcher,
        "match_panel",
        lambda **_: visual_asset_matcher.VisualAssetMatch(
            source_asset_id="same-photo",
            score=0.99,
        ),
    )

    matches = matcher.match_panels(panels=requests, candidates=[])

    assert set(matches) == {"rev-a-panel", "rev-b-panel"}


def test_assessment_preserves_ranked_candidates_below_score(monkeypatch, tmp_path):
    matcher = VisualAssetMatcher(minimum_score=0.97, minimum_margin=0.03)
    candidates = _stub_scores(
        monkeypatch,
        matcher,
        tmp_path,
        [("candidate-a", 0.95), ("candidate-b", 0.91), ("candidate-c", 0.80)],
    )

    assessment = matcher.assess_panel(
        pdf_path=tmp_path / "plate.pdf",
        physical_page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
        candidates=candidates,
        top_k=5,
    )

    assert assessment.status == "BELOW_SCORE"
    assert assessment.best_score == pytest.approx(0.95)
    assert assessment.margin == pytest.approx(0.04)
    assert [item.source_asset_id for item in assessment.candidates] == [
        "candidate-a",
        "candidate-b",
        "candidate-c",
    ]
    assert assessment.match is None


def test_assessment_preserves_ambiguous_runner_up(monkeypatch, tmp_path):
    matcher = VisualAssetMatcher(minimum_score=0.97, minimum_margin=0.03)
    candidates = _stub_scores(
        monkeypatch,
        matcher,
        tmp_path,
        [("candidate-a", 0.98), ("candidate-b", 0.97), ("candidate-c", 0.70)],
    )

    assessment = matcher.assess_panel(
        pdf_path=tmp_path / "plate.pdf",
        physical_page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
        candidates=candidates,
        top_k=2,
    )

    assert assessment.status == "AMBIGUOUS_MARGIN"
    assert assessment.best_score == pytest.approx(0.98)
    assert assessment.margin == pytest.approx(0.01)
    assert [item.source_asset_id for item in assessment.candidates] == [
        "candidate-a",
        "candidate-b",
    ]
    assert assessment.match is None


def test_assessment_keeps_verified_match_and_ranking(monkeypatch, tmp_path):
    matcher = VisualAssetMatcher(minimum_score=0.97, minimum_margin=0.03)
    candidates = _stub_scores(
        monkeypatch,
        matcher,
        tmp_path,
        [("candidate-a", 0.99), ("candidate-b", 0.90)],
    )

    assessment = matcher.assess_panel(
        pdf_path=tmp_path / "plate.pdf",
        physical_page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
        candidates=candidates,
    )

    assert assessment.status == "VERIFIED"
    assert assessment.match is not None
    assert assessment.match.source_asset_id == "candidate-a"
    assert assessment.best_score == pytest.approx(0.99)
    assert assessment.margin == pytest.approx(0.09)
