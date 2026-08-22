from app.services.pdf_parser import PDFParser


def test_extracts_photo_reference_as_plate_channel() -> None:
    parser = PDFParser()

    refs = parser._extract_references(
        "6호 석관묘 (사진: 45)",
        source_block_id="body_v1_p10_b1",
        source_sha256="body-sha",
        physical_page=10,
    )

    assert [(ref.ref_type, ref.number) for ref in refs] == [("plate", "45")]
    assert refs[0].raw_text is not None
    assert refs[0].raw_text.startswith("사진")
    assert refs[0].source_block_id == "body_v1_p10_b1"


def test_caption_photo_reference_is_not_blank() -> None:
    parser = PDFParser()

    caption = parser._extract_caption(
        "6호 석관묘 사진: 45",
        caption_id="body_v1_p10_c1",
        source_sha256="body-sha",
        physical_page=10,
    )

    assert caption is not None
    assert caption.is_blank_reference is False
    assert [(ref.ref_type, ref.number) for ref in caption.references] == [("plate", "45")]


def test_photo_reference_does_not_change_existing_drawing_and_plate_parsing() -> None:
    parser = PDFParser()

    refs = parser._extract_references(
        "6호 석관묘 (도면: 30, 도판: 45, 사진: 46)",
        source_block_id="body_v1_p10_b2",
    )

    assert [(ref.ref_type, ref.number) for ref in refs] == [
        ("drawing", "30"),
        ("plate", "45"),
        ("plate", "46"),
    ]
