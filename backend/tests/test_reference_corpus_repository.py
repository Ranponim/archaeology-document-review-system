from __future__ import annotations

from app.domain.canonical_models import DrawingData, PlateData, PlatePanelData
from app.domain.reference_corpus import ReferenceCorpusStatus
from app.graph.reference_corpus_repository import ReferenceCorpusRepository


def test_reference_corpus_repository_exposes_build_contract():
    expected = {
        "create_staging",
        "attach_source",
        "list_sources",
        "save_artifact",
        "transition_status",
        "find_ready_by_build_identity",
        "save_canonical_visuals",
        "validate_ready_graph",
        "get",
        "list_for_project",
    }
    missing = sorted(name for name in expected if not callable(getattr(ReferenceCorpusRepository, name, None)))
    assert missing == []


def test_reference_corpus_repository_serializes_corpus_and_panel_provenance():
    plate = PlateData(
        plate_id="plate:c1:45",
        number="45",
        physical_page=1,
        reference_corpus_id="c1",
    )
    panel = PlatePanelData(
        panel_id="plate-panel:c1:45:1",
        plate_id=plate.plate_id,
        panel_index=1,
        source_asset_id="asset-photo-1",
    )
    drawing = DrawingData(
        drawing_id="drawing:c1:30",
        number="30",
        physical_page=1,
        reference_corpus_id="c1",
    )

    assert ReferenceCorpusRepository._plate_payload(plate)["reference_corpus_id"] == "c1"
    assert ReferenceCorpusRepository._panel_payload(panel)["source_asset_id"] == "asset-photo-1"
    assert ReferenceCorpusRepository._drawing_payload(drawing)["reference_corpus_id"] == "c1"


def test_ready_reference_corpus_is_terminal():
    assert ReferenceCorpusStatus.READY.is_terminal is True
