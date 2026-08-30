from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pymupdf
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


def test_match_panels_fails_closed_when_two_panels_select_same_source(monkeypatch):
    request_type = visual_asset_matcher.VisualPanelRequest
    matcher = VisualAssetMatcher()
    requests = [
        request_type(
            panel_id="panel-a",
            pdf_path="plate.pdf",
            physical_page=1,
            bbox=(0.0, 0.0, 0.5, 0.5),
        ),
        request_type(
            panel_id="panel-b",
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
