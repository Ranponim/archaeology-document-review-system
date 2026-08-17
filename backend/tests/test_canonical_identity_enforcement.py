import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import warnings

from app.domain.canonical_models import (
    DrawingData,
    DrawingRegionData,
    PlateData,
    PlatePanelData,
    ReferenceData,
    ResolutionStatus,
)
from app.domain.document_structure import ParsedPage, TextBlockData
from app.services.asset_matcher import AssetMatcher, ResolutionResult, resolve_reference
from app.services.asset_cache import AssetHashCache
from app.services.asset_review_pipeline import AssetReviewPipeline
from app.services.drawing_parser import DrawingIndex
from app.services.plate_parser import PlateIndex
from app.services.proofreading_orchestrator import ProofreadingOrchestrator


def test_canonical_drawing_reference_resolution_simple():
    """ReferenceData(ref_type='drawing', number='30') resolves canonically against DrawingIndex."""
    drawing_30 = DrawingData(
        drawing_id="drawing_30",
        number="30",
        physical_page=45,
        title="2지점 목관묘 평면도",
        raw_identifier="【도면 30】",
        source_sha256="sha256_dwg_30",
    )
    drawing_index = DrawingIndex(
        drawings_by_number={"30": drawing_30},
        drawings=[drawing_30],
    )

    ref = ReferenceData(
        ref_type="drawing",
        number="30",
        raw_text="도면 30",
        physical_page=12,
    )

    result = resolve_reference(reference=ref, drawing_index=drawing_index)

    assert result.status == ResolutionStatus.RESOLVED
    assert result.target == drawing_30
    assert result.identity_source == "drawing_pdf"
    assert "【도면 30】" in result.identity_evidence or "2지점 목관묘 평면도" in result.identity_evidence
    assert "30" in result.rationale


def test_canonical_drawing_reference_resolution_korean_type():
    """ReferenceData with Korean ref_type '도면' resolves correctly."""
    drawing_12 = DrawingData(
        drawing_id="drawing_12",
        number="12",
        physical_page=18,
        title="1호 주거지 단면도",
        raw_identifier="도면 12",
    )
    drawing_index = DrawingIndex(
        drawings_by_number={"12": drawing_12},
        drawings=[drawing_12],
    )

    ref = ReferenceData(
        ref_type="도면",
        number="12",
        raw_text="(도면 12)",
    )

    result = resolve_reference(reference=ref, drawing_index=drawing_index)

    assert result.status == ResolutionStatus.RESOLVED
    assert result.target == drawing_12
    assert result.identity_source == "drawing_pdf"


def test_canonical_drawing_reference_resolution_with_compound_regions():
    """Drawing reference with compound numbers (30-1, 30-①, 30 (1)) resolves to DrawingRegionData."""
    region_1 = DrawingRegionData(
        region_id="region_30_1",
        drawing_id="drawing_30",
        number="1",
        title="목관묘 1호 토기",
        physical_page=45,
    )
    region_2 = DrawingRegionData(
        region_id="region_30_2",
        drawing_id="drawing_30",
        number="2",
        title="목관묘 2호 철검",
        physical_page=45,
    )
    drawing_30 = DrawingData(
        drawing_id="drawing_30",
        number="30",
        physical_page=45,
        title="2지점 유물 실측도",
        regions=[region_1, region_2],
    )
    drawing_index = DrawingIndex(
        drawings_by_number={"30": drawing_30},
        drawings=[drawing_30],
    )

    # 1. Hyphen notation: 30-1
    ref_hyphen = ReferenceData(ref_type="drawing", number="30-1", raw_text="도면 30-1")
    res_hyphen = resolve_reference(reference=ref_hyphen, drawing_index=drawing_index)
    assert res_hyphen.status == ResolutionStatus.RESOLVED
    assert res_hyphen.target == region_1
    assert res_hyphen.identity_source == "drawing_pdf"

    # 2. Circled notation: 30-①
    ref_circled = ReferenceData(ref_type="drawing", number="30-①", raw_text="도면 30-①")
    res_circled = resolve_reference(reference=ref_circled, drawing_index=drawing_index)
    assert res_circled.status == ResolutionStatus.RESOLVED
    assert res_circled.target == region_1

    # 3. Parentheses notation: 30 (2)
    ref_paren = ReferenceData(ref_type="drawing", number="30 (2)", raw_text="도면 30 (2)")
    res_paren = resolve_reference(reference=ref_paren, drawing_index=drawing_index)
    assert res_paren.status == ResolutionStatus.RESOLVED
    assert res_paren.target == region_2

    # 4. Fallback to base drawing when region is not found
    ref_unindexed_region = ReferenceData(ref_type="drawing", number="30-99", raw_text="도면 30-99")
    res_unindexed = resolve_reference(reference=ref_unindexed_region, drawing_index=drawing_index)
    assert res_unindexed.status == ResolutionStatus.RESOLVED
    assert res_unindexed.target == drawing_30


def test_canonical_plate_reference_resolution_with_compound_panels():
    """Plate reference with compound numbers (85-1, 85-①, 85 (2)) resolves to PlatePanelData."""
    panel_1 = PlatePanelData(
        panel_id="plate_85_panel_1",
        plate_id="plate_85",
        panel_index=1,
        caption="조사 전경",
        physical_page=100,
    )
    panel_2 = PlatePanelData(
        panel_id="plate_85_panel_2",
        plate_id="plate_85",
        panel_index=2,
        caption="유물 출토 상태",
        physical_page=100,
    )
    plate_85 = PlateData(
        plate_id="plate_85",
        number="85",
        physical_page=100,
        title="2지점 유구 및 유물",
        panels=[panel_1, panel_2],
    )
    plate_index = PlateIndex(
        plates_by_number={"85": plate_85},
        plates=[plate_85],
    )

    # 1. Hyphen notation: 85-1
    ref_hyphen = ReferenceData(ref_type="plate", number="85-1", raw_text="도판 85-1")
    res_hyphen = resolve_reference(reference=ref_hyphen, plate_index=plate_index)
    assert res_hyphen.status == ResolutionStatus.RESOLVED
    assert res_hyphen.target == panel_1
    assert res_hyphen.identity_source == "plate_pdf"

    # 2. Circled notation: 85-②
    ref_circled = ReferenceData(ref_type="plate", number="85-②", raw_text="도판 85-②")
    res_circled = resolve_reference(reference=ref_circled, plate_index=plate_index)
    assert res_circled.status == ResolutionStatus.RESOLVED
    assert res_circled.target == panel_2


def test_canonical_drawing_missing_strictly_returns_missing_status():
    """Missing drawing references resolve strictly to MISSING with target=None."""
    drawing_index = DrawingIndex(
        drawings_by_number={},
        drawings=[],
    )
    ref = ReferenceData(ref_type="drawing", number="999", raw_text="도면 999")
    res = resolve_reference(reference=ref, drawing_index=drawing_index)

    assert res.status == ResolutionStatus.MISSING
    assert res.target is None
    assert res.identity_evidence == []
    assert "999" in res.rationale


def test_rejection_of_disk_filename_matching_when_absent_from_index(tmp_path):
    """Zero filename matching: files on disk (30.dwg, drawing_30.jpg, 30.pdf) are REJECTED when absent from DrawingIndex."""
    drawings_dir = tmp_path / "drawings"
    plates_dir = tmp_path / "plates"
    drawings_dir.mkdir()
    plates_dir.mkdir()

    # Create files on disk that match reference number "30" and "85"
    (drawings_dir / "30.dwg").write_bytes(b"AUTOCAD_DWG_DATA_30")
    (drawings_dir / "drawing_30.jpg").write_bytes(b"JPEG_DATA_30")
    (drawings_dir / "도면_30.pdf").write_bytes(b"PDF_DATA_30")
    (plates_dir / "도판_85.jpg").write_bytes(b"JPEG_DATA_85")
    (plates_dir / "85.png").write_bytes(b"PNG_DATA_85")

    # Empty canonical indices
    empty_drawing_index = DrawingIndex()
    empty_plate_index = PlateIndex()

    matcher = AssetMatcher(
        drawings_dir=drawings_dir,
        plates_dir=plates_dir,
        drawing_index=empty_drawing_index,
        plate_index=empty_plate_index,
    )

    # 1. Resolve drawing 30 -> MUST be MISSING with target=None, never matching disk files
    ref_drawing = ReferenceData(ref_type="drawing", number="30", raw_text="도면 30")
    res_drawing = matcher.resolve_reference(ref_drawing)
    assert res_drawing.status == ResolutionStatus.MISSING
    assert res_drawing.target is None
    assert res_drawing.identity_evidence == []

    # 2. Resolve plate 85 -> MUST be MISSING with target=None, never matching disk files
    ref_plate = ReferenceData(ref_type="plate", number="85", raw_text="도판 85")
    res_plate = matcher.resolve_reference(ref_plate)
    assert res_plate.status == ResolutionStatus.MISSING
    assert res_plate.target is None
    assert res_plate.identity_evidence == []


def test_legacy_match_reference_is_quarantined_and_warns(tmp_path):
    """Legacy match_reference is quarantined and emits a DeprecationWarning."""
    drawings_dir = tmp_path / "drawings"
    drawings_dir.mkdir()
    (drawings_dir / "도면_1.pdf").write_bytes(b"PDF")

    matcher = AssetMatcher(drawings_dir=drawings_dir)

    with pytest.deprecated_call():
        matcher.match_reference(ref_type="drawing", number="1")


@pytest.mark.anyio
async def test_production_orchestrator_quarantines_legacy_matching():
    """Production orchestrator strictly uses resolve_reference and never calls legacy match_reference."""
    matcher = AssetMatcher()
    # Mock match_reference to raise an error if invoked
    matcher.match_reference = MagicMock(side_effect=RuntimeError("match_reference must NEVER be called by orchestrator"))

    drawing_1 = DrawingData(
        drawing_id="drawing_1",
        number="1",
        physical_page=10,
        title="조사지역 위치도",
    )
    drawing_index = DrawingIndex(
        drawings_by_number={"1": drawing_1},
        drawings=[drawing_1],
    )

    body_page = ParsedPage(
        page_id="doc_p1",
        physical_page=1,
        printed_page=1,
        header="",
        raw_text="위치도는 (도면 1)에 제시하였다.",
        normalized_text="위치도는 (도면 1)에 제시하였다.",
        source_sha256="sha256_body",
        text_blocks=[
            TextBlockData(
                block_id="b1",
                text="위치도는 (도면 1)에 제시하였다.",
                normalized_text="위치도는 (도면 1)에 제시하였다.",
                order=1,
                references=[
                    ReferenceData(ref_type="drawing", number="1", raw_text="도면 1", physical_page=1)
                ],
            )
        ],
    )

    orchestrator = ProofreadingOrchestrator(
        asset_matcher=matcher,
        allow_degraded_mode=True,
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_test",
        body_version_id="ver_body_1",
        body_pages=[body_page],
        drawings=[drawing_1],
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert result.references_resolved == 1
    # Verify legacy match_reference was never called
    matcher.match_reference.assert_not_called()


@pytest.mark.anyio
async def test_vector_cad_safety_in_asset_review_pipeline(tmp_path):
    """Vector CAD formats (.dwg, .dxf, .ai, .eps, .cdr, .dgn) without raster render caches are tagged conversion_error and never sent to VLM."""
    cad_file = tmp_path / "cad_drawing_30.dwg"
    cad_file.write_bytes(b"AC1032_AUTOCAD_DWG_BINARY_HEADER_DATA")

    cad_drawing = DrawingData(
        drawing_id="drawing_30",
        number="30",
        physical_page=45,
        title="CAD 도면",
        regions=[
            DrawingRegionData(
                region_id="region_30_1",
                drawing_id="drawing_30",
                number="1",
                title="CAD 평면",
                render_uri=f"file://{cad_file}",
            )
        ],
    )

    ref = ReferenceData(ref_type="drawing", number="30-1", raw_text="도면 30-1")
    resolution = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        target=cad_drawing.regions[0],
        identity_source="drawing_pdf",
    )

    mock_vlm = AsyncMock()
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    pipeline = AssetReviewPipeline(vlm_service=mock_vlm, cache=cache)

    candidates = await pipeline.review_canonical_reference(
        reference=ref,
        resolution=resolution,
        vlm_service=mock_vlm,
    )

    # VLM must NOT be called for raw CAD files
    mock_vlm.verify_plate_photo.assert_not_called()

    assert len(candidates) == 1
    cand = candidates[0]
    assert "conv_err" in cand.candidate_id
    assert cand.status == "pending_review"
    assert cand.confidence == 0.0


@pytest.mark.anyio
async def test_vector_cad_raw_bytes_safety_in_asset_review_pipeline(tmp_path):
    """Raw vector/corrupt bytes passed to review_canonical_reference produce conversion_error without invoking VLM."""
    drawing = DrawingData(
        drawing_id="drawing_5",
        number="5",
        physical_page=10,
        title="유물 도면",
    )
    ref = ReferenceData(ref_type="drawing", number="5", raw_text="도면 5")
    resolution = ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        target=drawing,
        identity_source="drawing_pdf",
    )

    mock_vlm = AsyncMock()
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    pipeline = AssetReviewPipeline(vlm_service=mock_vlm, cache=cache)

    # Pass non-decodable CAD bytes
    cad_raw_bytes = b"AC1027\x00\x00\x00\x12\x34\x56"
    candidates = await pipeline.review_canonical_reference(
        reference=ref,
        resolution=resolution,
        image_bytes=cad_raw_bytes,
        vlm_service=mock_vlm,
    )

    mock_vlm.verify_plate_photo.assert_not_called()
    assert len(candidates) == 1
    assert "conv_err" in candidates[0].candidate_id
    assert candidates[0].status == "pending_review"
    assert candidates[0].confidence == 0.0


def test_drawing_index_extended_methods():
    """DrawingIndex supports get, get_drawing, get_region with circled numbers and digits."""
    reg1 = DrawingRegionData(
        region_id="reg_1",
        drawing_id="dwg_1",
        number="1",
        title="1호",
    )
    dwg1 = DrawingData(
        drawing_id="dwg_1",
        number="1",
        physical_page=5,
        title="도면 1",
        regions=[reg1],
    )
    index = DrawingIndex(
        drawings_by_number={"1": dwg1},
        drawings=[dwg1],
    )

    assert index.get("1") == dwg1
    assert index.get("99", None) is None
    assert index.get_drawing("1") == dwg1
    assert index.get_region("1", "1") == reg1
    assert index.get_region("1", "①") == reg1
    assert index.get_region("1", 1) == reg1
    assert index.get_region("1", "99") is None
    assert "1" in index
    assert len(index) == 1
    assert list(index) == [dwg1]
