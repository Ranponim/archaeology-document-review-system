from __future__ import annotations

from app.domain import canonical_models
from app.services.pdf_parser import PDFParser


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
