"""Task 9 tests: real panel regions and the render-crop visual flow.

`PlatePanelData.bbox` must represent the actual photo/panel region of a plate
page — never the bbox of a circled label (`①`, `②`, ...). The required path is:

    Plate PDF page -> high-resolution page render -> panel segmentation
    -> PlatePanel.bbox / render_uri -> crop -> VLM observation

When a panel region cannot be safely isolated the parser marks the panel
`bbox_status="insufficient"` (bbox=None, no render_uri) and the VLM path must
return insufficient evidence instead of sending unrelated page content.

The synthetic plate book used here is built with PyMuPDF (the `korea` base-14
CJK font renders the Korean header text) and mirrors the real golden plate
fixture layout: a header line with the 【도판 N】 identifier and panel captions,
embedded photos, and panel badges drawn INSIDE the photos. Expected panel
bboxes are therefore the embedded image rectangles (normalized to the page),
never the label words.
"""
import hashlib
import io
import os
from pathlib import Path
import uuid

import pytest

try:
    import pymupdf  # type: ignore
    HAS_PYMUPDF = True
except ImportError:
    try:
        import fitz as pymupdf  # type: ignore
        HAS_PYMUPDF = True
    except ImportError:
        HAS_PYMUPDF = False

from PIL import Image

from app.domain.canonical_models import PlateData, PlatePanelData, ReferenceData, ResolutionStatus
from app.domain.review_models import EvidenceData
from app.services.asset_matcher import AssetMatcher, ResolutionResult
from app.services.asset_review_pipeline import AssetReviewPipeline
from app.services.image_processor import ImageProcessor
from app.services.plate_parser import PlateParser
from app.services.vlm_review_service import VLMReviewResult

pytestmark = pytest.mark.anyio


def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").is_dir() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("Could not find repository root containing src/ directory")


REPO_ROOT = _find_repo_root()
GOLDEN_FIXTURE = Path(__file__).parent / "fixtures/golden/plate_45_fixture.pdf"
SYNTHETIC_PANEL_TOLERANCE = 0.005


def _png_bytes(size: tuple[int, int], rgb: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="PNG")
    return buf.getvalue()


def build_synthetic_plate_pdf(dest: Path) -> Path:
    """Create a 3-page plate-style PDF with deterministic embedded photos.

    Page 1: 【도판 1】 with two photos at (40,80,290,400) and (305,80,555,400);
            labels "(1)" / "(2)" are drawn inside the photos.
    Page 2: 【도판 2】 with NO photo -> region cannot be safely isolated.
    Page 3: 【도판 3】 with one photo but the label sits far outside it.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(
        pymupdf.Rect(40, 80, 290, 400),
        stream=_png_bytes((250, 320), (180, 30, 30)),
    )
    page.insert_image(
        pymupdf.Rect(305, 80, 555, 400),
        stream=_png_bytes((250, 320), (30, 30, 180)),
    )
    page.insert_text(
        (50, 60),
        "【도판 1】 테스트 전경 1) 좌측  2) 우측",
        fontname="korea",
        fontsize=12,
    )
    page.insert_text((110, 300), "(1)", fontsize=16)
    page.insert_text((420, 300), "(2)", fontsize=16)

    text_page = doc.new_page(width=595, height=842)
    text_page.insert_text(
        (50, 60),
        "【도판 2】 텍스트 전용 1) 전경",
        fontname="korea",
        fontsize=12,
    )

    bad_page = doc.new_page(width=595, height=842)
    bad_page.insert_image(
        pymupdf.Rect(40, 80, 290, 400),
        stream=_png_bytes((250, 320), (30, 180, 30)),
    )
    bad_page.insert_text(
        (50, 60),
        "【도판 3】 미배치 표찰 1) 전경",
        fontname="korea",
        fontsize=12,
    )
    bad_page.insert_text((420, 700), "(1)", fontsize=16)

    pdf_path = dest / "synthetic_plate_book.pdf"
    doc.save(pdf_path)
    doc.close()
    return pdf_path


class CapturingVLMService:
    """Duck-typed VLMReviewService recording the exact bytes it receives."""

    def __init__(self) -> None:
        self.calls: list[bytes] = []

    async def verify_plate_photo(
        self,
        image_bytes: bytes,
        expected_feature: str,
        expected_site: str = "",
        claims: list[str] | None = None,
        mime_type: str = "image/jpeg",
    ) -> VLMReviewResult:
        self.calls.append(image_bytes)
        return VLMReviewResult(
            status="SUPPORTED",
            observations={"site_label": "테스트"},
            supported_claims=[f"{expected_feature} 일치"],
            confidence=0.9,
            rationale="mock vlm",
        )


def _page_image_rects(pdf_path: Path, physical_page: int) -> list[tuple[float, float, float, float]]:
    """Normalized (0..1) embedded image rects of a page, used as expectations."""
    doc = pymupdf.open(str(pdf_path))
    try:
        page = doc[physical_page - 1]
        rects: list[tuple[float, float, float, float]] = []
        seen: set[tuple[float, float, float, float]] = set()
        for img in page.get_images(full=True):
            for r in page.get_image_rects(img[0]):
                key = (round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))
                if key in seen:
                    continue
                seen.add(key)
                rects.append(
                    (
                        r.x0 / page.rect.width,
                        r.y0 / page.rect.height,
                        r.x1 / page.rect.width,
                        r.y1 / page.rect.height,
                    )
                )
        return sorted(rects)
    finally:
        doc.close()


def test_synthetic_fixture_is_shape_as_documented(tmp_path):
    pdf = build_synthetic_plate_pdf(tmp_path)
    rects1 = _page_image_rects(pdf, 1)
    assert len(rects1) == 2
    assert rects1[0][2] - rects1[0][0] > 0.35
    assert _page_image_rects(pdf, 2) == []
    assert len(_page_image_rects(pdf, 3)) == 1


def test_plate_parser_renders_page_at_2x_and_panel_bbox_is_embedded_image_rect(tmp_path):
    """The parser renders the full page at >=2x (~1191px wide) and the panel
    bbox is the embedded photo rect in normalized coords — NOT the label bbox."""
    pdf = build_synthetic_plate_pdf(tmp_path)
    parser = PlateParser()

    render_bytes = parser.render_page(pdf, 1)
    assert render_bytes
    with Image.open(io.BytesIO(render_bytes)) as img:
        assert img.width >= 1191, img.size
        assert img.width >= 2 * 595 - 2, img.size
        assert img.height > 2 * 800, img.size

    index = parser.parse(pdf, document_version_id="ver_plate")
    plate1 = index.get_plate("1")
    assert plate1 is not None
    assert len(plate1.panels) == 2

    expected_rects = _page_image_rects(pdf, 1)
    assert len(expected_rects) == 2

    p1, p2 = plate1.panels
    assert p1.bbox_status == "segmented"
    assert p2.bbox_status == "segmented"
    assert p1.bbox is not None and p2.bbox is not None
    for v in (*p1.bbox, *p2.bbox):
        assert 0.0 <= v <= 1.0
    assert p1.bbox[2] - p1.bbox[0] > 0.3
    assert p1.bbox[3] - p1.bbox[1] > 0.3
    assert p2.bbox[2] - p2.bbox[0] > 0.3
    assert p2.bbox[3] - p2.bbox[1] > 0.3
    for got, expected in ((p1.bbox, expected_rects[0]), (p2.bbox, expected_rects[1])):
        for k in range(4):
            assert abs(got[k] - expected[k]) < SYNTHETIC_PANEL_TOLERANCE


def test_panel_without_safely_isolatable_region_is_marked_insufficient(tmp_path):
    pdf = build_synthetic_plate_pdf(tmp_path)
    index = PlateParser().parse(str(pdf), document_version_id="ver_plate")

    plate2 = index.get_plate("2")
    assert plate2 is not None
    assert len(plate2.panels) == 1
    assert plate2.panels[0].bbox is None
    assert plate2.panels[0].bbox_status == "insufficient"
    assert plate2.panels[0].render_uri is None

    plate3 = index.get_plate("3")
    assert plate3 is not None
    assert plate3.panels[0].bbox is None
    assert plate3.panels[0].bbox_status == "insufficient"


async def test_insufficient_panel_never_reaches_vlm_and_crop_path_refuses(tmp_path):
    """Regions that cannot be isolated must produce insufficient evidence —
    the page render must never be sent as if it were the panel photo."""
    pdf = build_synthetic_plate_pdf(tmp_path)
    index = PlateParser().parse(str(pdf), document_version_id="ver_plate")
    panel = index.get_plate("3").panels[0]
    assert panel.bbox is None
    assert panel.bbox_status == "insufficient"

    page_render = PlateParser.render_page(pdf, 3)
    assert ImageProcessor.crop_region(page_render, (0.4, 0.4, 0.4, 0.4)) == b""

    resolution = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        target=panel,
        identity_source="plate_pdf",
        identity_evidence=["【도판 3】"],
    )
    reference = ReferenceData(
        ref_type="plate",
        number="3",
        source_block_id="p3_b1",
        raw_text="도판 3",
        source_sha256=panel.source_sha256,
        physical_page=3,
    )
    vlm = CapturingVLMService()
    from app.services.asset_cache import AssetHashCache
    pipeline = AssetReviewPipeline(
        matcher=AssetMatcher(plates_dir=tmp_path / "plates"),
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    candidates = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=vlm,
        image_bytes=page_render,
        expected_feature="테스트",
        document_version_id="ver_plate",
        page_id="ver_plate_p3",
    )

    assert len(candidates) == 1
    assert vlm.calls == [], "VLM must never receive unresolved/insufficient content"
    assert candidates[0].confidence == 0.0
    assert candidates[0].evidence is None


async def test_asset_review_pipeline_crops_highres_page_render_to_panel_for_vlm(tmp_path):
    """The VLM request must receive the cropped panel region of the page
    render (via ImageProcessor.crop_region), never the whole page."""
    pdf = build_synthetic_plate_pdf(tmp_path)
    panel = PlateParser().parse(str(pdf), document_version_id="ver_plate").get_plate("1").panels[0]
    assert panel.bbox is not None
    assert panel.bbox_status == "segmented"

    page_render = PlateParser.render_page(pdf, 1)

    resolution = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        target=panel,
        identity_source="plate_pdf",
        identity_evidence=["【도판 1】"],
    )
    reference = ReferenceData(
        ref_type="plate",
        number="1",
        source_block_id="p1_b1",
        raw_text="도판 1",
        source_sha256=panel.source_sha256,
        physical_page=1,
    )
    vlm = CapturingVLMService()
    from app.services.asset_cache import AssetHashCache
    pipeline = AssetReviewPipeline(
        matcher=AssetMatcher(plates_dir=tmp_path / "plates"),
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    candidates = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=vlm,
        image_bytes=page_render,
        expected_feature="테스트 전경",
        expected_site="1지점",
        document_version_id="ver_plate",
        page_id="ver_plate_p1",
    )

    assert len(vlm.calls) == 1
    expected_crop = ImageProcessor.crop_region(page_render, panel.bbox)
    assert vlm.calls[0] == expected_crop
    assert vlm.calls[0] != ImageProcessor.prepare_for_vlm(page_render), (
        "VLM must receive the panel crop, not the whole page render"
    )
    assert ImageProcessor.is_valid_image(vlm.calls[0])
    assert len(candidates) == 1
    ev = candidates[0].evidence
    assert ev is not None and ev.kind == "vlm_observation"
    assert ev.bbox == panel.bbox


def test_parser_persists_page_render_with_provenance_under_derived_dir(tmp_path):
    """render_uri points to a written page render under the derived dir; the
    panel source_sha256 is the original plate PDF byte hash."""
    pdf = build_synthetic_plate_pdf(tmp_path)
    expected_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    render_dir = tmp_path / "derived" / "plate_renders"
    index = PlateParser().parse(str(pdf), document_version_id="ver_p", render_dir=render_dir)

    panel1 = index.get_plate("1").panels[0]
    assert panel1.bbox_status == "segmented"
    assert panel1.render_uri is not None
    uri = Path(panel1.render_uri)
    assert uri.is_absolute()
    assert uri.parent == render_dir
    assert uri.is_file()
    assert ImageProcessor.is_valid_image(uri.read_bytes())
    assert panel1.source_sha256 == expected_sha

    written = sorted(render_dir.iterdir())
    assert len(written) == 3, [p.name for p in written]
    assert any(p.name.startswith("ver_p_p") and p.name.endswith(".png") for p in written)
    for p in written:
        assert ImageProcessor.is_valid_image(p.read_bytes())


def test_golden_fixture_panel_bboxes_match_embedded_image_rects_not_label_words():
    """On the real golden plate fixture, each segmented panel bbox is one of
    the page's embedded photo rects (normalized), never the label word bbox."""
    assert GOLDEN_FIXTURE.is_file()
    index = PlateParser().parse(GOLDEN_FIXTURE, document_version_id="ver_plate")

    plate45 = index.get_plate("45")
    assert plate45 is not None
    assert len(plate45.panels) == 5
    panel_bboxes = [p.bbox for p in plate45.panels]
    assert all(b is not None for b in panel_bboxes)

    expected_rects: set[tuple[float, float, float, float]] = set()
    doc = pymupdf.open(str(GOLDEN_FIXTURE))
    try:
        page = doc[46]
        for img in page.get_images(full=True):
            for r in page.get_image_rects(img[0]):
                if r.width < 2 or r.height < 2:
                    continue
                expected_rects.add(
                    (
                        round(r.x0 / page.rect.width, 4),
                        round(r.y0 / page.rect.height, 4),
                        round(r.x1 / page.rect.width, 4),
                        round(r.y1 / page.rect.height, 4),
                    )
                )
    finally:
        doc.close()
    assert len(expected_rects) == 5

    mapped = {
        (round(b[0], 4), round(b[1], 4), round(b[2], 4), round(b[3], 4))
        for b in panel_bboxes
    }
    assert mapped == expected_rects, "panel bboxes must be the 5 photo rects"
    for b in panel_bboxes:
        assert b[2] - b[0] > 0.1
        assert b[3] - b[1] > 0.1


def test_real_neo4j_plate_panel_bbox_render_uri_persistence():
    """Real Neo4j (optional): PlatePanel bbox / render_uri / bbox_status are
    actually persisted; scoped plate_test_* ids with cleanup in finally."""
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    from neo4j import GraphDatabase

    try:
        driver = GraphDatabase.driver(
            "bolt://127.0.0.1:7687", auth=("neo4j", password)
        )
        driver.verify_connectivity()
    except Exception:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    from app.graph.canonical_repository import CanonicalRepository

    scope = f"plate_test_{uuid.uuid4().hex[:8]}"
    plate_id = f"{scope}_plate_45"
    panel_id = f"{scope}_plate_45_panel_1"
    version_id = f"{scope}_ver"
    try:
        repo = CanonicalRepository(driver=driver)
        panel = PlatePanelData(
            panel_id=panel_id,
            plate_id=plate_id,
            panel_index=1,
            caption="조사 전",
            bbox=(0.1, 0.1, 0.5, 0.5),
            bbox_status="segmented",
            physical_page=47,
            render_uri=f"file://{scope}/page_047.png",
            source_sha256="sha256_plate_pdf",
        )
        plate = PlateData(
            plate_id=plate_id,
            number="45",
            physical_page=47,
            title="테스트",
            source_sha256="sha256_plate_pdf",
            document_version_id=version_id,
            panels=[panel],
            raw_identifier="【도판 45】",
        )
        repo.save_plates([plate])

        records, _, _ = driver.execute_query(
            "MATCH (p:PlatePanel {id: $panel_id}) RETURN properties(p) AS props",
            panel_id=panel_id,
        )
        assert len(records) == 1
        props = dict(records[0]["props"])
        assert props["bbox"] == [0.1, 0.1, 0.5, 0.5]
        assert props["render_uri"] == f"file://{scope}/page_047.png"
        assert props["bbox_status"] == "segmented"
        assert props["source_sha256"] == "sha256_plate_pdf"

        rel_records, _, _ = driver.execute_query(
            "MATCH (pl:Plate {id: $plate_id})-[:HAS_PANEL]->(p:PlatePanel {id: $panel_id}) "
            "RETURN p.id AS pid",
            plate_id=plate_id,
            panel_id=panel_id,
        )
        assert len(rel_records) == 1
        assert rel_records[0]["pid"] == panel_id
    finally:
        driver.execute_query(
            "MATCH (n) WHERE n.id STARTS WITH $scope DETACH DELETE n",
            scope=scope,
        )
        driver.close()


def test_direct_image_bytes_and_absolute_bbox_still_crop_directly():
    """Regression guard: absolute and normalized panel bboxes on the photo
    itself still crop from the original image bytes (legacy semantics)."""
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (10, 200, 10)).save(buf, format="PNG")
    raw = buf.getvalue()
    assert ImageProcessor.is_valid_image(ImageProcessor.crop_region(raw, (50, 50, 150, 150)))
    assert ImageProcessor.is_valid_image(ImageProcessor.crop_region(raw, (0.25, 0.25, 0.75, 0.75)))