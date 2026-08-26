from pathlib import Path

import pymupdf

from app.services.drawing_visual_extractor import DrawingVisualExtractor


def _make_tiny_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=200, height=200)
    page.insert_text((20, 30), "drawing 52")
    page.draw_rect(pymupdf.Rect(40, 40, 160, 160))
    document.save(str(path))
    document.close()
    return path


def test_render_source_and_crop_body_region(tmp_path):
    source_path = _make_tiny_pdf(tmp_path / "sample.ai")
    output_dir = tmp_path / "rendered"
    extractor = DrawingVisualExtractor(render_scale=2.0)

    source = extractor.render_source(
        source_path,
        output_dir,
        source_asset_id="asset-1",
        source_sha256="source-sha",
    )
    crop = extractor.crop_body_region(
        source_path,
        output_dir,
        region_id="body:drawing:52",
        page_number=1,
        bbox=(30.0, 30.0, 170.0, 170.0),
        source_sha256="body-sha",
    )

    assert Path(source.image_path).exists()
    assert source.page == 1
    assert source.bbox is None
    assert source.source_sha256 == "source-sha"
    assert Path(crop.image_path).exists()
    assert crop.page == 1
    assert crop.bbox == (30.0, 30.0, 170.0, 170.0)
    assert crop.source_sha256 == "body-sha"


def test_crop_body_region_rejects_empty_clip(tmp_path):
    source_path = _make_tiny_pdf(tmp_path / "sample.ai")
    extractor = DrawingVisualExtractor()

    try:
        extractor.crop_body_region(
            source_path,
            tmp_path / "rendered",
            region_id="body:drawing:52",
            page_number=1,
            bbox=(250.0, 250.0, 300.0, 300.0),
            source_sha256="body-sha",
        )
    except ValueError as exc:
        assert "empty" in str(exc).lower() or "bbox" in str(exc).lower()
    else:
        raise AssertionError("empty body crop must fail closed")
