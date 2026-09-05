from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pymupdf
from PIL import Image, ImageDraw

from app.services.visual_asset_matcher import VisualAssetMatcher


def _write_feature_rich_source(path: Path) -> None:
    image = Image.new("RGB", (480, 360), "white")
    draw = ImageDraw.Draw(image)

    for x in range(20, 460, 40):
        draw.line((x, 15, x, 345), fill=(35 + (x % 120),) * 3, width=3)
    for y in range(20, 350, 45):
        draw.line((15, y, 465, y), fill=(55 + (y % 100),) * 3, width=2)

    shapes = [
        (35, 35, 115, 105),
        (145, 55, 235, 150),
        (275, 30, 440, 115),
        (55, 185, 180, 320),
        (215, 175, 320, 300),
        (345, 165, 455, 330),
    ]
    for index, box in enumerate(shapes):
        shade = 25 + index * 28
        if index % 2:
            draw.ellipse(box, outline=(shade,) * 3, width=7)
            inner = tuple(value + 12 for value in box)
            draw.ellipse(inner, outline=(220 - index * 15,) * 3, width=3)
        else:
            draw.rectangle(box, outline=(shade,) * 3, width=7)
            draw.line((box[0], box[1], box[2], box[3]), fill=(90,) * 3, width=4)
            draw.line((box[0], box[3], box[2], box[1]), fill=(160,) * 3, width=4)

    draw.polygon([(250, 130), (300, 145), (330, 125), (355, 155), (285, 165)], outline=(20, 20, 20), width=5)
    image.save(path, format="JPEG", quality=96, subsampling=0)


def _write_distractor(path: Path) -> None:
    image = Image.new("RGB", (480, 360), "white")
    draw = ImageDraw.Draw(image)
    for index in range(12):
        y = 15 + index * 28
        draw.rectangle((20, y, 460, y + 12), fill=(30 + index * 12,) * 3)
    draw.ellipse((160, 90, 320, 270), outline=(10, 10, 10), width=12)
    image.save(path, format="JPEG", quality=96, subsampling=0)


def _write_transformed_pdf(source: Path, pdf_path: Path) -> tuple[float, float, float, float]:
    with Image.open(source) as image:
        image.load()
        # Publication-like transformation: off-centre crop, rotation and resize.
        panel = image.crop((48, 42, 438, 325))
        panel = panel.rotate(
            7.0,
            resample=Image.Resampling.BICUBIC,
            expand=True,
            fillcolor="white",
        )
        panel = panel.resize((318, 236), Image.Resampling.LANCZOS)
        payload = BytesIO()
        panel.save(payload, format="PNG")

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=360, height=300)
        rect = pymupdf.Rect(21, 24, 339, 260)
        page.insert_image(rect, stream=payload.getvalue())
        doc.save(str(pdf_path))
    finally:
        doc.close()

    return (
        21 / 360,
        24 / 300,
        339 / 360,
        260 / 300,
    )


def test_match_panel_recovers_transformed_source_with_geometric_fallback(tmp_path):
    source = tmp_path / "source.jpg"
    distractor = tmp_path / "distractor.jpg"
    pdf_path = tmp_path / "plate.pdf"
    _write_feature_rich_source(source)
    _write_distractor(distractor)
    bbox = _write_transformed_pdf(source, pdf_path)

    matcher = VisualAssetMatcher(minimum_score=0.97, minimum_margin=0.03)
    match = matcher.match_panel(
        pdf_path=pdf_path,
        physical_page=1,
        bbox=bbox,
        candidates=[
            (SimpleNamespace(id="source"), source),
            (SimpleNamespace(id="distractor"), distractor),
        ],
    )

    assert match is not None
    assert match.source_asset_id == "source"
    assert match.method == "sift_ransac"
