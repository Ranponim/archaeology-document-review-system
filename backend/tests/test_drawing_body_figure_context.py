from __future__ import annotations

import importlib.util
from pathlib import Path

import pymupdf


def _load_evaluator():
    path = Path(__file__).resolve().parents[2] / "tools" / "evaluate_drawing_evidence_v3.py"
    spec = importlib.util.spec_from_file_location("evaluate_drawing_evidence_v3", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_body_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((20, 60), "유구(도면 : 52)", fontname="korea")
    page.draw_rect(pymupdf.Rect(80, 180, 320, 320))
    page.insert_text((90, 380), "도면 52. 평면도", fontname="korea")
    document.save(str(path))
    document.close()
    return path


def test_narrative_drawing_reference_is_not_used_as_visual_evidence(tmp_path):
    module = _load_evaluator()
    body_pdf = _make_body_pdf(tmp_path / "body.pdf")

    packets = module.build_body_packets(body_pdf, tmp_path / "renders")

    narrative = [
        packet
        for packet in packets
        if packet.number == "52"
        and packet.source_bbox is not None
        and packet.source_bbox[1] < 100
    ]
    assert narrative
    assert all(packet.visual_regions == () for packet in narrative)


def test_figure_caption_visual_includes_bounded_context_above_caption(tmp_path):
    module = _load_evaluator()
    body_pdf = _make_body_pdf(tmp_path / "body.pdf")

    packets = module.build_body_packets(body_pdf, tmp_path / "renders")

    figure_packets = [
        packet
        for packet in packets
        if packet.number == "52"
        and packet.source_bbox is not None
        and packet.source_bbox[1] > 300
    ]
    assert figure_packets
    visual = next(
        region
        for packet in figure_packets
        for region in packet.visual_regions
    )
    assert visual.bbox is not None
    assert visual.bbox[1] <= 180.0
    assert visual.bbox[3] < 450.0
