"""Phase P0-C tests: complete semantic visual validation.

Review source: docs/superpowers/reviews/2026-08-17-neo4j-frontend-mvp-code-review.md
Phase P0-C (§13), P0-3 (VLM body claims), P0-4 (drawing visual pipeline),
anti-patterns #2/#3/#9/#10/#14, Definition of Done "Photo/Plate" + "Drawing".

Covered:
1. P0-3 — the orchestrator passes body/object claims derived from the graph
   bundle (ObjectEvidenceBundle.text_claims + references) into the VLM, so the
   VLM compares body claims against the actual panel/drawing image — not just
   the asset caption/title.
2. P0-3 — the VLM target is canonically resolved BEFORE the VLM call; a wrong
   or missing canonical mapping stops the VLM call (VLM never establishes
   identity).
3. P0-3 — the VLM result stays pending_review with the structured 4-class
   result (SUPPORTED/PARTIAL/CONTRADICTED/INSUFFICIENT_EVIDENCE), never
   reduced to a vague boolean is_match and never auto-accepted.
4. P0-4 — DrawingParser renders the page and the DrawingRegion bbox equals the
   embedded region rect (mirroring PlateParser Task 9); render_uri is a valid
   image; crop round-trips; the VLM receives the cropped region bytes.
5. P0-4 / anti-pattern #9 — a drawing region that cannot be safely isolated or
   whose render_uri points to a vector source (AI/EPS/DWG/DXF) never reaches
   the VLM; the candidate is conversion_error / INSUFFICIENT_EVIDENCE.
6. P0-C #3 / anti-pattern #14 — the VLM observation Evidence provenance points
   to the actual visual DocumentVersion (plate/drawing), NOT the body version.
7. Real Neo4j (optional): drawing region render + provenance; scoped
   p0c_test_* ids with cleanup.
"""
from typing import Any, Callable
import hashlib
import io
import os
from pathlib import Path
import uuid

import pytest

from PIL import Image

from app.domain.canonical_models import (
    DrawingData,
    DrawingRegionData,
    PlateData,
    PlatePanelData,
    ReferenceData,
    ResolutionStatus,
)
from app.domain.document_structure import ParsedPage, TextBlockData
from app.graph.canonical_repository import CanonicalRepository
from app.graph.review_repository import ReviewRepository
from app.services.asset_cache import AssetHashCache
from app.services.asset_matcher import AssetMatcher, ResolutionResult
from app.services.asset_review_pipeline import AssetReviewPipeline
from app.services.drawing_parser import HAS_PYMUPDF, DrawingParser
from app.services.image_processor import ImageProcessor
from app.services.proofreading_orchestrator import ProofreadingOrchestrator
from app.services.vlm_review_service import VLMReviewResult

pytestmark = pytest.mark.anyio

VLM_STATUSES = {"SUPPORTED", "PARTIAL", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"}


class FakeNeo4jRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class EmptyFakeNeo4jDriver:
    """Fake driver returning no records for every query (no graph evidence)."""

    def __init__(self, events: list[str] | None = None):
        self.queries: list[dict[str, Any]] = []
        self.events = events

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        if self.events is not None:
            self.events.append(query)
        return [], None, None


class QueueFakeNeo4jDriver:
    """Fake driver returning per-query-shaped record batches in FIFO order.

    A marker registered with a single batch repeats that batch on every call;
    a marker registered with multiple batches pops them in order.
    """

    def __init__(self):
        self.queries: list[dict[str, Any]] = []
        self._responses: list[tuple[Callable[[str], bool], list[list[dict[str, Any]]]]] = []

    def respond(self, marker: str, batches: list[list[dict[str, Any]]]) -> "QueueFakeNeo4jDriver":
        self._responses.append((lambda q, m=marker: m in q, batches))
        return self

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        for predicate, batches in self._responses:
            if predicate(query):
                if not batches:
                    return [], None, None
                batch = batches[0] if len(batches) == 1 else batches.pop(0)
                return [FakeNeo4jRecord(r) for r in batch], None, None
        return [], None, None


class CapturingClaimsVLMService:
    """Duck-typed VLMReviewService recording the exact bytes, expected feature,
    expected site, and claims it receives."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def verify_plate_photo(
        self,
        image_bytes: bytes,
        expected_feature: str,
        expected_site: str = "",
        claims: list[str] | None = None,
        mime_type: str = "image/jpeg",
    ) -> VLMReviewResult:
        self.calls.append(
            {
                "image_bytes": image_bytes,
                "expected_feature": expected_feature,
                "expected_site": expected_site,
                "claims": list(claims or []),
            }
        )
        return VLMReviewResult(
            status="SUPPORTED",
            observations={"site_label": expected_site or "테스트"},
            supported_claims=[f"{expected_feature} 일치"],
            confidence=0.9,
            rationale="mock vlm",
        )


class CapturingBytesVLMService:
    """Duck-typed VLMReviewService recording only the exact bytes it receives."""

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
            observations={"site_label": expected_site or "테스트"},
            supported_claims=[f"{expected_feature} 일치"],
            confidence=0.9,
            rationale="mock vlm",
        )


def _png_bytes(size: tuple[int, int], rgb: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="PNG")
    return buf.getvalue()


def _body_page_with_reference(plate_number: str = "45") -> ParsedPage:
    """One page whose block mentions an object and references a plate."""
    return ParsedPage(
        page_id="ver_g_p1",
        physical_page=1,
        printed_page=1,
        header="",
        raw_text=(
            "FULL_DOCUMENT_SECRET_PAGE_TEXT 1지점 청동기시대 1호 주거지 규모는 길이 275cm이다. "
            f"1지점 청동기시대 1호 주거지(도판 : {plate_number}) 조사를 진행하였다."
        ),
        normalized_text=(
            "1지점 청동기시대 1호 주거지 규모는 길이 275cm이다. "
            f"1지점 청동기시대 1호 주거지(도판 : {plate_number}) 조사를 진행하였다."
        ),
        text_blocks=[
            TextBlockData(
                block_id="p1_b1",
                text="1지점 청동기시대 1호 주거지 규모는 길이 275cm이다.",
                normalized_text="1지점 청동기시대 1호 주거지 규모는 길이 275cm이다.",
                block_type="paragraph",
                order=1,
                source_sha256="sha256_g",
            ),
            TextBlockData(
                block_id="p1_b2",
                text=f"1지점 청동기시대 1호 주거지(도판 : {plate_number}) 조사를 진행하였다.",
                normalized_text=f"1지점 청동기시대 1호 주거지(도판 : {plate_number}) 조사를 진행하였다.",
                block_type="paragraph",
                order=2,
                source_sha256="sha256_g",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number=plate_number,
                        source_block_id="p1_b2",
                        raw_text=f"도판 : {plate_number}",
                        source_sha256="sha256_g",
                        physical_page=1,
                    )
                ],
            ),
        ],
        captions=[],
        source_sha256="sha256_g",
    )


def _plate_with_panel(render_uri: str | None = None) -> list[PlateData]:
    panel = PlatePanelData(
        panel_id="plate_45_panel_1",
        plate_id="plate_45",
        panel_index=1,
        caption="1지점 청동기시대 1호 주거지",
        bbox=(0.1, 0.1, 0.5, 0.5),
        bbox_status="segmented",
        physical_page=47,
        render_uri=render_uri,
        source_sha256="sha256_plate",
    )
    return [
        PlateData(
            plate_id="plate_45",
            number="45",
            physical_page=47,
            title="1지점 청동기시대 1호 주거지",
            source_sha256="sha256_plate",
            document_version_id="ver_plate",
            panels=[panel],
            raw_identifier="【도판 45】",
        )
    ]


def _text_claim_row() -> dict[str, Any]:
    return {
        "source": {"id": "g_b1", "text": "규모는 길이 275cm이다"},
        "page": {"id": "ver_g_p1", "physical_page": 1},
        "version": {"id": "ver_g", "stage": "1차", "sha256": "sha256_g"},
    }


def _reference_row() -> dict[str, Any]:
    return {
        "source": {"id": "g_b1", "text": "1지점 청동기시대 1호 주거지(도판 : 45)"},
        "ref": {
            "id": "ref_g_plate_45",
            "ref_type": "plate",
            "number": "45",
            "raw_text": "도판 : 45",
            "source_block_id": "g_b1",
            "source_sha256": "sha256_g",
            "physical_page": 1,
        },
        "page": {"id": "ver_g_p1", "physical_page": 1},
        "version": {"id": "ver_g", "stage": "1차", "sha256": "sha256_g"},
    }


def _bundle_driver_with_text_claims() -> QueueFakeNeo4jDriver:
    """Driver shaped for get_object_evidence_bundle's five targeted queries,
    returning one text claim and one reference evidence."""
    return (
        QueueFakeNeo4jDriver()
        .respond(
            "RETURN properties(obj) AS obj",
            [[{"obj": {"canonical_name": "1지점 청동기시대 1호 주거지"}}]],
        )
        .respond("[:REFERENCES]->(ref:Reference)", [[_reference_row()]])
        .respond("[:MENTIONS]->(obj:ArchaeologyObject", [[_text_claim_row()]])
        .respond("[:DEPICTS]->(obj:ArchaeologyObject", [[]])
        .respond("[:SUPPORTED_BY]->(ev:Evidence)", [[]])
    )


# ---------------------------------------------------------------------------
# P0-3 — VLM compares body claims against the image
# ---------------------------------------------------------------------------


async def test_orchestrator_passes_body_claims_from_graph_bundle_to_vlm(tmp_path):
    """P0-3: the VLM prompt must include body claims derived from graph
    evidence (text_claims + references), not just the plate panel caption."""
    driver = _bundle_driver_with_text_claims()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    render_path = tmp_path / "render.png"
    render_path.write_bytes(_png_bytes((200, 200), (180, 30, 30)))
    vlm = CapturingClaimsVLMService()
    pipeline = AssetReviewPipeline(
        vlm_service=vlm,
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        asset_review_pipeline=pipeline,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_p0c_claims",
        body_version_id="ver_g",
        plate_version_id="ver_plate",
        body_pages=[_body_page_with_reference()],
        plates=_plate_with_panel(render_uri=str(render_path)),
        enable_vlm=True,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert len(vlm.calls) == 1, "VLM must be invoked exactly once for the resolved panel"
    claims = vlm.calls[0]["claims"]
    assert claims, "VLM must receive body claims derived from the graph bundle"
    assert any("규모는 길이 275cm이다" in c for c in claims), (
        f"a text_claim value must reach the VLM, got {claims}"
    )
    assert any("도판 : 45" in c for c in claims), (
        f"a reference raw_text must reach the VLM, got {claims}"
    )


async def test_orchestrator_skips_vlm_when_canonical_mapping_missing(tmp_path):
    """P0-3 / anti-pattern #2: a reference that cannot be canonically resolved
    (missing plate) must stop the VLM call — VLM never establishes identity."""
    driver = EmptyFakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    vlm = CapturingClaimsVLMService()
    pipeline = AssetReviewPipeline(
        vlm_service=vlm,
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        asset_review_pipeline=pipeline,
    )
    # Body page references plate 999 which is NOT in the canonical plate index.
    result = await orchestrator.run_proofreading(
        project_id="proj_p0c_missing",
        body_version_id="ver_g",
        plate_version_id="ver_plate",
        body_pages=[_body_page_with_reference("999")],
        plates=_plate_with_panel(render_uri=str(tmp_path / "render.png")),
        enable_vlm=True,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert vlm.calls == [], "VLM must never be called for an unresolved canonical mapping"
    assert all(c.status == "pending_review" for c in result.candidates), (
        "unresolved references must stay pending_review, never auto-accepted"
    )


async def test_vlm_result_stays_pending_review_with_structured_4_class_result(tmp_path):
    """P0-3 / anti-patterns #10/#11: the VLM candidate stays pending_review and
    the evidence stores the structured 4-class result — never reduced to a
    vague boolean is_match and never auto-accepted."""
    driver = _bundle_driver_with_text_claims()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    render_path = tmp_path / "render.png"
    render_path.write_bytes(_png_bytes((200, 200), (180, 30, 30)))
    vlm = CapturingClaimsVLMService()
    pipeline = AssetReviewPipeline(
        vlm_service=vlm,
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        asset_review_pipeline=pipeline,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_p0c_4class",
        body_version_id="ver_g",
        plate_version_id="ver_plate",
        body_pages=[_body_page_with_reference()],
        plates=_plate_with_panel(render_uri=str(render_path)),
        enable_vlm=True,
        enable_ai_review=False,
    )

    vlm_candidates = [c for c in result.candidates if c.candidate_id.startswith("cand_vlm_")]
    assert vlm_candidates, "a VLM candidate must be produced"
    for c in vlm_candidates:
        assert c.status == "pending_review", "VLM candidates are never auto-accepted"
        ev = c.evidence
        assert ev is not None and ev.kind == "vlm_observation"
        assert ev.value["status"] in VLM_STATUSES, (
            f"structured 4-class status required, got {ev.value.get('status')!r}"
        )
        assert "supported_claims" in ev.value
        assert "contradicted_claims" in ev.value
        assert "unobservable_claims" in ev.value


# ---------------------------------------------------------------------------
# P0-C #3 / anti-pattern #14 — VLM evidence provenance = visual DocumentVersion
# ---------------------------------------------------------------------------


async def test_vlm_evidence_provenance_points_to_visual_document_version(tmp_path):
    """P0-C #3 / anti-pattern #14: the VLM observation Evidence must point to
    the actual visual DocumentVersion (plate/drawing), NOT the body version."""
    driver = _bundle_driver_with_text_claims()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    render_path = tmp_path / "render.png"
    render_path.write_bytes(_png_bytes((200, 200), (180, 30, 30)))
    vlm = CapturingClaimsVLMService()
    pipeline = AssetReviewPipeline(
        vlm_service=vlm,
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        asset_review_pipeline=pipeline,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_p0c_prov",
        body_version_id="ver_g",
        plate_version_id="ver_plate",
        body_pages=[_body_page_with_reference()],
        plates=_plate_with_panel(render_uri=str(render_path)),
        enable_vlm=True,
        enable_ai_review=False,
    )

    vlm_candidates = [c for c in result.candidates if c.candidate_id.startswith("cand_vlm_")]
    assert vlm_candidates
    for c in vlm_candidates:
        ev = c.evidence
        assert ev is not None and ev.kind == "vlm_observation"
        assert ev.document_version_id == "ver_plate", (
            f"VLM evidence must point to the plate version, got {ev.document_version_id!r}"
        )
        assert ev.document_version_id != "ver_g", (
            "VLM evidence must never point to the body version"
        )


# ---------------------------------------------------------------------------
# P0-4 — Drawing visual pipeline (mirror PlateParser Task 9)
# ---------------------------------------------------------------------------


def build_synthetic_drawing_pdf(dest) -> Path:
    """Create a 2-page drawing-style PDF with deterministic embedded images.

    Page 1: 【도면 30】 with two regions at (40,80,290,400) and (305,80,555,400);
            labels "(1)" / "(2)" are drawn inside the regions.
    Page 2: 【도면 31】 with NO embedded image -> region cannot be safely isolated.
    """
    import pymupdf  # type: ignore

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
        "【도면 30】 테스트 평면도 1) 좌측  2) 우측",
        fontname="korea",
        fontsize=12,
    )
    page.insert_text((110, 300), "(1)", fontsize=16)
    page.insert_text((420, 300), "(2)", fontsize=16)

    text_page = doc.new_page(width=595, height=842)
    text_page.insert_text(
        (50, 60),
        "【도면 31】 텍스트 전용 1) 평면도",
        fontname="korea",
        fontsize=12,
    )

    pdf_path = dest / "synthetic_drawing_book.pdf"
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def _page_image_rects(pdf_path, physical_page: int) -> list[tuple[float, float, float, float]]:
    """Normalized (0..1) embedded image rects of a page, used as expectations."""
    import pymupdf  # type: ignore

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


@pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for real render")
def test_drawing_parser_renders_page_and_region_bbox_is_embedded_image_rect(tmp_path):
    """P0-4: the parser renders the full page at >=2x and the region bbox is
    the embedded image rect in normalized coords — NOT the label bbox."""
    pdf = build_synthetic_drawing_pdf(tmp_path)
    parser = DrawingParser()

    render_bytes = parser.render_page(pdf, 1)
    assert render_bytes
    with Image.open(io.BytesIO(render_bytes)) as img:
        assert img.width >= 1191, img.size
        assert img.height > 2 * 800, img.size

    index = parser.parse(
        pdf, document_version_id="ver_draw", render_dir=tmp_path / "derived"
    )
    drawing = index.get_drawing("30")
    assert drawing is not None
    assert len(drawing.regions) == 2

    expected_rects = _page_image_rects(pdf, 1)
    assert len(expected_rects) == 2

    r1, r2 = drawing.regions
    assert r1.bbox_status == "segmented"
    assert r2.bbox_status == "segmented"
    assert r1.bbox is not None and r2.bbox is not None
    for v in (*r1.bbox, *r2.bbox):
        assert 0.0 <= v <= 1.0
    for got, expected in ((r1.bbox, expected_rects[0]), (r2.bbox, expected_rects[1])):
        for k in range(4):
            assert abs(got[k] - expected[k]) < 0.005

    # render_uri points to a written, valid page render under the derived dir.
    assert r1.render_uri is not None
    uri = Path(r1.render_uri)
    assert uri.is_absolute()
    assert uri.is_file()
    assert ImageProcessor.is_valid_image(uri.read_bytes())
    assert r1.source_sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()

    # Crop round-trip: the region bbox crops the page render into a valid image.
    crop = ImageProcessor.crop_region(render_bytes, r1.bbox)
    assert ImageProcessor.is_valid_image(crop)


@pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for real render")
async def test_drawing_region_crop_reaches_vlm(tmp_path):
    """P0-4: the VLM request must receive the cropped drawing region of the
    page render (via ImageProcessor.crop_region), never the whole page."""
    pdf = build_synthetic_drawing_pdf(tmp_path)
    region = (
        DrawingParser()
        .parse(pdf, document_version_id="ver_draw")
        .get_drawing("30")
        .regions[0]
    )
    assert region.bbox is not None
    assert region.bbox_status == "segmented"

    page_render = DrawingParser.render_page(pdf, 1)
    resolution = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        target=region,
        identity_source="drawing_pdf",
        identity_evidence=["【도면 30】"],
    )
    reference = ReferenceData(
        ref_type="drawing",
        number="30",
        source_block_id="p1_b1",
        raw_text="도면 30",
        source_sha256=region.source_sha256,
        physical_page=1,
    )
    vlm = CapturingBytesVLMService()
    pipeline = AssetReviewPipeline(
        matcher=AssetMatcher(drawings_dir=tmp_path / "drawings"),
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    candidates = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=vlm,
        image_bytes=page_render,
        expected_feature="테스트",
        document_version_id="ver_draw",
        page_id="ver_draw_p1",
    )

    assert len(vlm.calls) == 1
    expected_crop = ImageProcessor.crop_region(page_render, region.bbox)
    assert vlm.calls[0] == expected_crop
    assert vlm.calls[0] != ImageProcessor.prepare_for_vlm(page_render), (
        "VLM must receive the region crop, not the whole page render"
    )
    assert ImageProcessor.is_valid_image(vlm.calls[0])
    assert len(candidates) == 1
    ev = candidates[0].evidence
    assert ev is not None and ev.kind == "vlm_observation"
    assert ev.bbox == region.bbox


@pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for real render")
async def test_drawing_insufficient_region_never_reaches_vlm(tmp_path):
    """P0-4: a drawing region that cannot be safely isolated produces
    insufficient evidence — the page render must never be sent as if it were
    the drawing region."""
    pdf = build_synthetic_drawing_pdf(tmp_path)
    index = DrawingParser().parse(pdf, document_version_id="ver_draw")
    drawing2 = index.get_drawing("31")
    assert drawing2 is not None
    region = drawing2.regions[0]
    assert region.bbox is None
    assert region.bbox_status == "insufficient"
    assert region.render_uri is None

    page_render = DrawingParser.render_page(pdf, 2)
    resolution = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        target=region,
        identity_source="drawing_pdf",
        identity_evidence=["【도면 31】"],
    )
    reference = ReferenceData(
        ref_type="drawing",
        number="31",
        source_block_id="p2_b1",
        raw_text="도면 31",
        source_sha256=region.source_sha256,
        physical_page=2,
    )
    vlm = CapturingBytesVLMService()
    pipeline = AssetReviewPipeline(
        matcher=AssetMatcher(drawings_dir=tmp_path / "drawings"),
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    candidates = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=vlm,
        image_bytes=page_render,
        expected_feature="테스트",
        document_version_id="ver_draw",
        page_id="ver_draw_p2",
    )

    assert vlm.calls == [], "VLM must never receive an unisolatable drawing region"
    assert len(candidates) == 1
    assert "conv_err" in candidates[0].candidate_id
    assert candidates[0].status == "pending_review"
    assert candidates[0].confidence == 0.0


async def test_drawing_vector_source_fails_closed_no_vlm(tmp_path):
    """P0-4 / anti-pattern #9: a DrawingRegion whose render_uri points to a
    vector source (AI/EPS/DWG/DXF) never sends raw vector bytes to VLM."""
    from unittest.mock import AsyncMock

    cad_file = tmp_path / "drawing_30.ai"
    cad_file.write_bytes(b"AC1027\x00\x00\x00\x12\x34\x56")
    region = DrawingRegionData(
        region_id="drawing_30_region_1",
        drawing_id="drawing_30",
        number="1",
        title="평면도",
        bbox=(0.1, 0.1, 0.5, 0.5),
        physical_page=1,
        render_uri=f"file://{cad_file}",
        source_sha256="sha256_draw",
    )
    resolution = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        target=region,
        identity_source="drawing_pdf",
        identity_evidence=["【도면 30】"],
    )
    reference = ReferenceData(ref_type="drawing", number="30", raw_text="도면 30")
    mock_vlm = AsyncMock()
    pipeline = AssetReviewPipeline(
        vlm_service=mock_vlm,
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    candidates = await pipeline.review_canonical_reference(
        reference=reference,
        resolution=resolution,
        vlm_service=mock_vlm,
    )

    mock_vlm.verify_plate_photo.assert_not_called()
    assert len(candidates) == 1
    assert "conv_err" in candidates[0].candidate_id
    assert candidates[0].status == "pending_review"
    assert candidates[0].confidence == 0.0


# ---------------------------------------------------------------------------
# Real Neo4j (optional) — drawing region render + provenance
# ---------------------------------------------------------------------------


def test_real_neo4j_drawing_region_render_and_provenance():
    """Real Neo4j (optional): DrawingRegion bbox / render_uri / source_sha256
    persist and the VLM evidence provenance points to the drawing version.
    Scoped p0c_test_* ids with cleanup in finally."""
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
    except Exception:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    from app.graph.canonical_repository import CanonicalRepository

    scope = f"p0c_test_{uuid.uuid4().hex[:8]}"
    drawing_id = f"{scope}_drawing_30"
    region_id = f"{scope}_drawing_30_region_1"
    version_id = f"{scope}_ver"
    try:
        repo = CanonicalRepository(driver=driver)
        driver.execute_query(
            "CREATE (v:DocumentVersion {id: $version_id, stage: '3차', sha256: 'sha256_drawing_pdf'})",
            version_id=version_id,
        )
        region = DrawingRegionData(
            region_id=region_id,
            drawing_id=drawing_id,
            number="1",
            title="평면도",
            bbox=(0.1, 0.1, 0.5, 0.5),
            bbox_status="segmented",
            physical_page=1,
            render_uri=f"file://{scope}/drawing_p001.png",
            source_sha256="sha256_drawing_pdf",
        )
        drawing = DrawingData(
            drawing_id=drawing_id,
            number="30",
            physical_page=1,
            title="테스트",
            source_sha256="sha256_drawing_pdf",
            document_version_id=version_id,
            regions=[region],
            raw_identifier="【도면 30】",
        )
        repo.save_drawings([drawing])

        records, _, _ = driver.execute_query(
            "MATCH (r:DrawingRegion {id: $region_id}) RETURN properties(r) AS props",
            region_id=region_id,
        )
        assert len(records) == 1
        props = dict(records[0]["props"])
        assert props["bbox"] == [0.1, 0.1, 0.5, 0.5]
        assert props["bbox_status"] == "segmented"
        assert props["render_uri"] == f"file://{scope}/drawing_p001.png"
        assert props["source_sha256"] == "sha256_drawing_pdf"

        rel_records, _, _ = driver.execute_query(
            "MATCH (d:Drawing {id: $drawing_id})-[:HAS_REGION]->(r:DrawingRegion {id: $region_id}) "
            "RETURN r.id AS rid",
            drawing_id=drawing_id,
            region_id=region_id,
        )
        assert len(rel_records) == 1
        assert rel_records[0]["rid"] == region_id

        # Reconstruct the DrawingIndex from the graph and verify the region
        # carries bbox / render_uri / source_sha256 / bbox_status.
        index = repo.get_drawing_index_for_version(version_id)
        drawing_re = index.get_drawing("30")
        assert drawing_re is not None
        assert len(drawing_re.regions) == 1
        reg = drawing_re.regions[0]
        assert reg.bbox == (0.1, 0.1, 0.5, 0.5)
        assert reg.bbox_status == "segmented"
        assert reg.render_uri == f"file://{scope}/drawing_p001.png"
        assert reg.source_sha256 == "sha256_drawing_pdf"
    finally:
        driver.execute_query(
            "MATCH (n) WHERE n.id STARTS WITH $scope DETACH DELETE n",
            scope=scope,
        )
        driver.close()
