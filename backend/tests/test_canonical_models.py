from app.domain.canonical_models import (
    ArchaeologyObject,
    ArchaeologyObjectData,
    Drawing,
    DrawingData,
    DrawingRegion,
    DrawingRegionData,
    Plate,
    PlateData,
    PlatePanel,
    PlatePanelData,
    Reference,
    ReferenceData,
    ResolutionStatus,
)
from app.domain.document_structure import CaptionData, ParsedPage, TextBlockData


def test_resolution_status_enum_values():
    assert ResolutionStatus.RESOLVED.value == "resolved"
    assert ResolutionStatus.AMBIGUOUS.value == "ambiguous"
    assert ResolutionStatus.MISSING.value == "missing"
    assert ResolutionStatus.UNRESOLVED.value == "unresolved"
    assert ResolutionStatus.RESOLVED == "resolved"
    assert ResolutionStatus.AMBIGUOUS == "ambiguous"
    assert ResolutionStatus.MISSING == "missing"
    assert ResolutionStatus.UNRESOLVED == "unresolved"


def test_reference_data_creation_and_fields():
    ref = ReferenceData(
        ref_type="plate",
        number="45",
        source_block_id="b_101",
        raw_text="도판 : 45",
        source_sha256="hash123",
        bbox=(10.0, 20.0, 100.0, 30.0),
        physical_page=12,
    )
    assert ref.ref_type == "plate"
    assert ref.number == "45"
    assert ref.source_block_id == "b_101"
    assert ref.raw_text == "도판 : 45"
    assert ref.source_sha256 == "hash123"
    assert ref.bbox == (10.0, 20.0, 100.0, 30.0)
    assert ref.physical_page == 12
    assert Reference is ReferenceData


def test_plate_data_separation_of_physical_page_and_publication_number():
    panel = PlatePanelData(
        panel_id="panel_45_1",
        plate_id="plate_45",
        panel_index=1,
        caption="① 전경",
        bbox=(15.0, 25.0, 200.0, 300.0),
        physical_page=47,
        render_uri="file:///storage/plate_45_1.jpg",
        source_sha256="plate_hash_1",
    )
    plate = PlateData(
        plate_id="plate_45",
        number="45",
        physical_page=47,
        title="1지점 청동기시대 6호 석관묘",
        bbox=(10.0, 20.0, 500.0, 700.0),
        source_sha256="abc45",
        document_version_id="ver_1",
        panels=[panel],
        raw_identifier="【도판 45】",
    )
    assert plate.number == "45"
    assert plate.physical_page == 47
    assert plate.title == "1지점 청동기시대 6호 석관묘"
    assert plate.bbox == (10.0, 20.0, 500.0, 700.0)
    assert plate.source_sha256 == "abc45"
    assert plate.raw_identifier == "【도판 45】"
    assert len(plate.panels) == 1
    assert plate.panels[0].panel_id == "panel_45_1"
    assert plate.panels[0].caption == "① 전경"
    assert plate.panels[0].physical_page == 47
    assert Plate is PlateData
    assert PlatePanel is PlatePanelData


def test_drawing_data_and_drawing_regions():
    region = DrawingRegionData(
        region_id="reg_16_1",
        drawing_id="drawing_16",
        number="16-1",
        title="평면도",
        bbox=(50.0, 60.0, 400.0, 400.0),
        physical_page=18,
        render_uri="file:///storage/reg_16_1.png",
        source_sha256="draw_hash_1",
    )
    drawing = DrawingData(
        drawing_id="drawing_16",
        number="16",
        physical_page=18,
        title="1지점 6호 석관묘 실측도",
        bbox=(20.0, 30.0, 550.0, 750.0),
        source_sha256="draw_doc_hash",
        document_version_id="ver_2",
        regions=[region],
        raw_identifier="【도면 16】",
    )
    assert drawing.number == "16"
    assert drawing.physical_page == 18
    assert drawing.title == "1지점 6호 석관묘 실측도"
    assert len(drawing.regions) == 1
    assert drawing.regions[0].number == "16-1"
    assert drawing.regions[0].title == "평면도"
    assert Drawing is DrawingData
    assert DrawingRegion is DrawingRegionData


def test_archaeology_object_data():
    obj = ArchaeologyObjectData(
        object_id="obj_site1_bronze_stone_cist_6",
        site="1지점",
        point="1지점",
        period="청동기시대",
        type="석관묘",
        number="6호",
        canonical_name="1지점 청동기시대 6호 석관묘",
        source_block_ids=["p12_b1", "p12_b2"],
        source_sha256="obj_doc_hash",
    )
    assert obj.object_id == "obj_site1_bronze_stone_cist_6"
    assert obj.site == "1지점"
    assert obj.point == "1지점"
    assert obj.period == "청동기시대"
    assert obj.type == "석관묘"
    assert obj.number == "6호"
    assert obj.canonical_name == "1지점 청동기시대 6호 석관묘"
    assert obj.source_block_ids == ["p12_b1", "p12_b2"]
    assert obj.source_sha256 == "obj_doc_hash"
    assert ArchaeologyObject is ArchaeologyObjectData


def test_text_block_data_extended_fields_and_backwards_compatibility():
    # Backwards compatible initialization without new fields
    block_legacy = TextBlockData(
        block_id="b_legacy",
        text="기존 텍스트",
        normalized_text="기존 텍스트",
        order=1,
    )
    assert block_legacy.bbox is None
    assert block_legacy.source_sha256 is None
    assert block_legacy.references == []

    # New initialization with bbox, source_sha256, and references
    ref = ReferenceData(ref_type="plate", number="45", source_block_id="b_new")
    block_new = TextBlockData(
        block_id="b_new",
        text="도판 45 참조",
        normalized_text="도판 45 참조",
        order=2,
        block_type="paragraph",
        bbox=(10.0, 20.0, 200.0, 50.0),
        source_sha256="sha_abc",
        references=[ref],
    )
    assert block_new.bbox == (10.0, 20.0, 200.0, 50.0)
    assert block_new.source_sha256 == "sha_abc"
    assert len(block_new.references) == 1
    assert block_new.references[0].number == "45"


def test_caption_data_extended_fields_and_backwards_compatibility():
    # Backwards compatible initialization
    cap_legacy = CaptionData(
        caption_id="c_legacy",
        raw_text="도판 1. 전경",
    )
    assert cap_legacy.bbox is None
    assert cap_legacy.source_sha256 is None
    assert cap_legacy.references == []

    # Extended initialization
    ref = ReferenceData(ref_type="plate", number="1", source_block_id="c_ext")
    cap_ext = CaptionData(
        caption_id="c_ext",
        raw_text="도판 1. 전경",
        drawing_number=None,
        plate_number="1",
        is_blank_reference=False,
        bbox=(30.0, 40.0, 150.0, 60.0),
        source_sha256="cap_sha_123",
        references=[ref],
    )
    assert cap_ext.bbox == (30.0, 40.0, 150.0, 60.0)
    assert cap_ext.source_sha256 == "cap_sha_123"
    assert len(cap_ext.references) == 1
    assert cap_ext.references[0].ref_type == "plate"


def test_parsed_page_with_extended_blocks_and_captions():
    ref = ReferenceData(ref_type="plate", number="45", source_block_id="b1")
    block = TextBlockData(
        block_id="b1",
        text="본문 내용 (도판 45)",
        normalized_text="본문 내용 (도판 45)",
        order=1,
        bbox=(10.0, 20.0, 300.0, 40.0),
        source_sha256="page_hash",
        references=[ref],
    )
    cap = CaptionData(
        caption_id="c1",
        raw_text="<도판 45> 6호 석관묘",
        plate_number="45",
        bbox=(10.0, 50.0, 200.0, 70.0),
        source_sha256="page_hash",
        references=[ref],
    )
    page = ParsedPage(
        physical_page=12,
        printed_page=10,
        header="II. 조사내용",
        raw_text="본문 내용 (도판 45)\n<도판 45> 6호 석관묘",
        normalized_text="본문 내용 (도판 45) <도판 45> 6호 석관묘",
        text_blocks=[block],
        captions=[cap],
        source_sha256="page_hash",
    )
    assert page.physical_page == 12
    assert page.printed_page == 10
    assert len(page.text_blocks) == 1
    assert page.text_blocks[0].references[0].number == "45"
    assert len(page.captions) == 1
    assert page.source_sha256 == "page_hash"
