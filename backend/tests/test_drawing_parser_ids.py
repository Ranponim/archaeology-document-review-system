"""Version-scoped Drawing/DrawingRegion IDs.

Regression guard for task-1-5 review Issue 5.1 (Critical): the unscoped
``drawing_{number}`` / ``region_{number}_{idx}`` forms let two projects (or two
versions) sharing the same publication number MERGE into one canonical
Drawing/DrawingRegion node (schema.py enforces ``id`` uniqueness on both
labels). Parser-bound IDs must be version-scoped exactly like plates
(plate_parser.py uses ``{document_version_id}_plate_{number}``).
"""
from pathlib import Path

import pytest

from app.services.drawing_parser import HAS_PYMUPDF, DrawingParser

DRAWING_HEADER = "【도면 45】 1지점 청동기시대 6호 석관묘 ① 평면도 ② 단면도"


@pytest.fixture
def drawing_pdf(tmp_path: Path) -> Path:
    """A real, text-extractable drawing book page (PyMuPDF-needed for CJK)."""
    if not HAS_PYMUPDF:
        pytest.skip("PyMuPDF not available to build a text-bearing PDF fixture")
    import pymupdf

    pdf_path = tmp_path / "drawings.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=700, height=300)
    page.insert_text((72, 72), DRAWING_HEADER, fontname="korea", fontsize=12)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


@pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for real parse")
def test_pymupdf_path_scopes_drawing_and_region_ids_with_version(
    drawing_pdf: Path,
):
    parser = DrawingParser()
    index = parser.parse(drawing_pdf, document_version_id="ver_draw_1")

    drawing = index.get_drawing("45")
    assert drawing is not None
    assert drawing.drawing_id == "ver_draw_1_drawing_45"
    assert drawing.number == "45"  # plain property kept for resolution
    assert drawing.document_version_id == "ver_draw_1"
    assert [r.drawing_id for r in drawing.regions] == ["ver_draw_1_drawing_45"] * 2
    assert [r.region_id for r in drawing.regions] == [
        "ver_draw_1_drawing_45_region_1",
        "ver_draw_1_drawing_45_region_2",
    ]


@pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF required for real parse")
def test_pymupdf_path_drawing_ids_fallback_is_prefixed_when_version_missing(
    drawing_pdf: Path,
):
    parser = DrawingParser()
    index = parser.parse(drawing_pdf)

    drawing = index.get_drawing("45")
    assert drawing is not None
    # Never reuse the old unscoped form: the fallback prefix keeps these ids
    # disjoint from every version-scoped id ({uuid}_drawing_45, ...).
    assert drawing.drawing_id == "doc_drawing_45"
    assert drawing.drawing_id != "drawing_45"
    assert [r.region_id for r in drawing.regions] == [
        "doc_drawing_45_region_1",
        "doc_drawing_45_region_2",
    ]


def test_pypdf_path_scopes_drawing_and_region_ids_like_pymupdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pdf_path = tmp_path / "drawings.pdf"
    pdf_path.write_bytes(b"not actually read: PdfReader is stubbed")

    class FakePage:
        def extract_text(self) -> str:
            return DRAWING_HEADER

    class FakeReader:
        pages = [FakePage()]

    class FakePypdf:
        @staticmethod
        def PdfReader(path: str):
            assert path == str(pdf_path)
            return FakeReader()

    monkeypatch.setattr("app.services.drawing_parser.pypdf", FakePypdf)
    monkeypatch.setattr("app.services.drawing_parser.HAS_PYMUPDF", False)

    parser = DrawingParser()
    index = parser.parse(pdf_path, document_version_id="ver_pypdf_1")

    drawing = index.get_drawing("45")
    assert drawing is not None
    assert drawing.drawing_id == "ver_pypdf_1_drawing_45"
    assert drawing.number == "45"
    assert [r.region_id for r in drawing.regions] == [
        "ver_pypdf_1_drawing_45_region_1",
        "ver_pypdf_1_drawing_45_region_2",
    ]


def test_pypdf_path_drawing_ids_fallback_is_prefixed_when_version_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pdf_path = tmp_path / "drawings.pdf"
    pdf_path.write_bytes(b"not actually read; PdfReader is stubbed")

    class FakePage:
        def extract_text(self) -> str:
            return DRAWING_HEADER

    class FakeReader:
        pages = [FakePage()]

    class FakePypdf:
        @staticmethod
        def PdfReader(path: str):
            return FakeReader()

    monkeypatch.setattr("app.services.drawing_parser.pypdf", FakePypdf)
    monkeypatch.setattr("app.services.drawing_parser.HAS_PYMUPDF", False)

    parser = DrawingParser()
    index = parser.parse(pdf_path)

    drawing = index.get_drawing("45")
    assert drawing is not None
    assert drawing.drawing_id == "doc_drawing_45"
    assert drawing.drawing_id != "drawing_45"