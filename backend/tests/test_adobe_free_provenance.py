from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pymupdf

from app.domain import canonical_models
from app.domain.source_assets import OriginalAssetData
from app.services.pdf_parser import PDFParser


def _asset(asset_id: str, name: str, sha: str = "sha") -> OriginalAssetData:
    return OriginalAssetData(
        id=asset_id,
        project_id="p1",
        uri=f"incoming/p1/{asset_id}/{name}",
        sha256=sha,
        size_bytes=1,
        mime_type="application/octet-stream",
        original_name=name,
        relative_path=name,
        asset_kind="reference_source",
        source_root_name="reference-corpus",
        import_batch_id="c1",
        parse_status="stored",
        provenance_status="unlinked",
    )


def _write_pdf_like_ai(path: Path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    if text:
        page.insert_text((30, 50), text, fontsize=12)
    doc.save(path)
    doc.close()


def _write_pattern_image(path: Path, variant: int) -> None:
    image = Image.new("RGB", (120, 80), "white")
    draw = ImageDraw.Draw(image)
    if variant == 1:
        draw.rectangle((10, 10, 100, 60), outline="black", width=5)
        draw.line((10, 60, 100, 10), fill="black", width=4)
    else:
        draw.ellipse((15, 10, 105, 70), outline="black", width=5)
        draw.line((15, 40, 105, 40), fill="black", width=4)
    image.save(path, quality=95)


def _write_pdf_with_image(pdf_path: Path, image_path: Path) -> tuple[float, float, float, float]:
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.insert_image(pymupdf.Rect(20, 30, 180, 170), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    # PyMuPDF preserves image aspect ratio inside the requested placement rect.
    # PlateParser uses the actual embedded image rect, so the fixture must too.
    doc = pymupdf.open(pdf_path)
    try:
        page = doc[0]
        xref = page.get_images(full=True)[0][0]
        rect = page.get_image_rects(xref)[0]
        return (
            rect.x0 / page.rect.width,
            rect.y0 / page.rect.height,
            rect.x1 / page.rect.width,
            rect.y1 / page.rect.height,
        )
    finally:
        doc.close()


def test_canonical_models_expose_graded_evidence_metadata():
    assert hasattr(canonical_models, "EvidenceLevel")
    level = canonical_models.EvidenceLevel
    assert [item.value for item in level] == [
        "direct",
        "derived_verified",
        "heuristic",
        "unresolved",
    ]

    ref = canonical_models.ReferenceData(
        ref_type="drawing",
        number="14",
        evidence_level=level.DIRECT,
        evidence_method="body_explicit_identifier",
    )
    assert ref.evidence_level == level.DIRECT
    assert ref.evidence_method == "body_explicit_identifier"


def test_body_reference_parser_accepts_real_src_reference_forms():
    parser = PDFParser()
    refs = parser._extract_references(
        "도면 1과 도면: 2를 비교하고 【도판 3】, 【원색도판 4】 및 도판 : 5를 참조한다."
    )

    pairs = [(ref.ref_type, ref.number) for ref in refs]
    assert pairs == [
        ("drawing", "1"),
        ("drawing", "2"),
        ("plate", "3"),
        ("plate", "4"),
        ("plate", "5"),
    ]
    assert all(ref.evidence_level == canonical_models.EvidenceLevel.DIRECT for ref in refs)
    assert all(ref.evidence_method == "body_explicit_identifier" for ref in refs)


def test_body_reference_parser_preserves_list_range_and_blank_caption_behavior():
    parser = PDFParser()

    refs = parser._extract_references("도면 7-9, 도판 11·12")
    assert [(ref.ref_type, ref.number) for ref in refs] == [
        ("drawing", "7"),
        ("drawing", "8"),
        ("drawing", "9"),
        ("plate", "11"),
        ("plate", "12"),
    ]

    assert parser._extract_references("(도면 : , 도판 : )") == []
    caption = parser._extract_caption("① 유구(도면 : , 도판 : )", caption_id="c1")
    assert caption is not None
    assert caption.is_blank_reference is True


def test_drawing_identity_resolver_prefers_internal_explicit_identifier(tmp_path):
    from app.services.drawing_identity_resolver import DrawingIdentityResolver

    class ExplicitParser:
        def parse(self, _source_path):
            return SimpleNamespace(
                drawings=[
                    canonical_models.DrawingData(
                        drawing_id="legacy-14",
                        number="14",
                        physical_page=1,
                        title="북동 토층",
                        raw_identifier="【도면 14】",
                    )
                ]
            )

    source = tmp_path / "unknown.ai"
    _write_pdf_like_ai(source, "14")
    asset = _asset("ai1", "unknown.ai")

    result = DrawingIdentityResolver(parser=ExplicitParser()).resolve(
        corpus_id="c1", asset=asset, source_path=source
    )

    assert result.unresolved_source_ids == ()
    assert len(result.drawings) == 1
    drawing = result.drawings[0]
    assert drawing.number == "14"
    assert drawing.source_asset_id == "ai1"
    assert drawing.reference_corpus_id == "c1"
    assert drawing.evidence_level == canonical_models.EvidenceLevel.DIRECT
    assert drawing.evidence_method == "pdf_internal_identifier"


def test_drawing_identity_resolver_uses_filename_only_as_heuristic(tmp_path):
    from app.services.drawing_identity_resolver import DrawingIdentityResolver

    source = tmp_path / "도면27. 토층.ai"
    _write_pdf_like_ai(source, "section")
    asset = _asset("ai27", source.name)

    result = DrawingIdentityResolver().resolve(corpus_id="c1", asset=asset, source_path=source)

    assert result.unresolved_source_ids == ()
    assert len(result.drawings) == 1
    drawing = result.drawings[0]
    assert drawing.number == "27"
    assert drawing.evidence_level == canonical_models.EvidenceLevel.HEURISTIC
    assert drawing.evidence_method == "filename_identifier"
    assert drawing.source_asset_id == "ai27"


def test_drawing_identity_resolver_refuses_to_invent_number(tmp_path):
    from app.services.drawing_identity_resolver import DrawingIdentityResolver

    source = tmp_path / "north-section.ai"
    _write_pdf_like_ai(source, "section")
    asset = _asset("ai-unresolved", source.name)

    result = DrawingIdentityResolver().resolve(corpus_id="c1", asset=asset, source_path=source)

    assert result.drawings == ()
    assert result.unresolved_source_ids == ("ai-unresolved",)


def test_visual_asset_matcher_returns_unique_high_confidence_source(tmp_path):
    from app.services.visual_asset_matcher import VisualAssetMatcher

    target = tmp_path / "target.jpg"
    distractor = tmp_path / "distractor.jpg"
    _write_pattern_image(target, 1)
    _write_pattern_image(distractor, 2)
    plate_pdf = tmp_path / "plates.pdf"
    bbox = _write_pdf_with_image(plate_pdf, target)

    match = VisualAssetMatcher().match_panel(
        pdf_path=plate_pdf,
        physical_page=1,
        bbox=bbox,
        candidates=[
            (_asset("photo-target", target.name), target),
            (_asset("photo-other", distractor.name), distractor),
        ],
    )

    assert match is not None
    assert match.source_asset_id == "photo-target"
    assert match.method == "pixel_thumbnail_similarity"
    assert match.score >= 0.97


def test_visual_asset_matcher_refuses_ambiguous_equal_sources(tmp_path):
    from app.services.visual_asset_matcher import VisualAssetMatcher

    target = tmp_path / "target.jpg"
    duplicate = tmp_path / "duplicate.jpg"
    _write_pattern_image(target, 1)
    duplicate.write_bytes(target.read_bytes())
    plate_pdf = tmp_path / "plates.pdf"
    bbox = _write_pdf_with_image(plate_pdf, target)

    match = VisualAssetMatcher().match_panel(
        pdf_path=plate_pdf,
        physical_page=1,
        bbox=bbox,
        candidates=[
            (_asset("photo-a", target.name), target),
            (_asset("photo-b", duplicate.name), duplicate),
        ],
    )

    assert match is None
