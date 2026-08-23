from __future__ import annotations

from types import SimpleNamespace

from app.domain.canonical_models import (
    DrawingData,
    EvidenceLevel,
    PlateData,
    PlatePanelData,
)
from app.domain.reference_corpus import ReferenceCorpusStatus
from app.graph.reference_corpus_repository import ReferenceCorpusRepository


class _CaptureDriver:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def execute_query(self, query: str, **kwargs):
        self.calls.append((query, kwargs))
        if "UNWIND $plates" in query:
            return ([{"saved": len(kwargs["plates"])}], None, None)
        if "UNWIND $panels" in query:
            return ([{"saved": len(kwargs["panels"])}], None, None)
        if "UNWIND $drawings" in query:
            return ([{"saved": len(kwargs["drawings"])}], None, None)
        if "UNWIND $regions" in query:
            return ([{"saved": len(kwargs["regions"])}], None, None)
        if "MERGE (c)-[rel:USES_SOURCE]" in query:
            return ([{"id": kwargs["source_asset_id"]}], None, None)
        return ([], None, None)


class _MutableRepository(ReferenceCorpusRepository):
    def _require_mutable(self, project_id: str, corpus_id: str):
        return SimpleNamespace(status=ReferenceCorpusStatus.CANONICALIZING)

    def _attached_source_ids(self, project_id: str, corpus_id: str, source_ids):
        return {str(item) for item in source_ids if item}


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
    missing = sorted(
        name
        for name in expected
        if not callable(getattr(ReferenceCorpusRepository, name, None))
    )
    assert missing == []


def test_reference_corpus_repository_accepts_plate_pdf_source_role():
    driver = _CaptureDriver()
    repository = _MutableRepository(driver)

    repository.attach_source("p1", "c1", "plate-pdf", "plate_pdf")

    assert any(
        kwargs.get("role") == "plate_pdf" and kwargs.get("source_asset_id") == "plate-pdf"
        for _, kwargs in driver.calls
    )


def test_reference_corpus_repository_serializes_graded_provenance():
    plate = PlateData(
        plate_id="plate:c1:45",
        number="45",
        physical_page=1,
        reference_corpus_id="c1",
        source_asset_id="asset-plate-pdf",
        evidence_level=EvidenceLevel.DIRECT,
        evidence_method="plate_pdf_identifier",
    )
    panel = PlatePanelData(
        panel_id="plate-panel:c1:45:1",
        plate_id=plate.plate_id,
        panel_index=1,
        source_asset_id="asset-photo-1",
        evidence_level=EvidenceLevel.DERIVED_VERIFIED,
        evidence_method="pixel_thumbnail_similarity",
    )
    drawing = DrawingData(
        drawing_id="drawing:c1:30",
        number="30",
        physical_page=1,
        reference_corpus_id="c1",
        source_asset_id="asset-ai-30",
        evidence_level=EvidenceLevel.HEURISTIC,
        evidence_method="filename_identifier",
    )

    plate_payload = ReferenceCorpusRepository._plate_payload(plate)
    panel_payload = ReferenceCorpusRepository._panel_payload(panel)
    drawing_payload = ReferenceCorpusRepository._drawing_payload(drawing)

    assert plate_payload["source_asset_id"] == "asset-plate-pdf"
    assert plate_payload["evidence_level"] == "direct"
    assert plate_payload["evidence_method"] == "plate_pdf_identifier"
    assert panel_payload["source_asset_id"] == "asset-photo-1"
    assert panel_payload["evidence_level"] == "derived_verified"
    assert panel_payload["evidence_method"] == "pixel_thumbnail_similarity"
    assert drawing_payload["source_asset_id"] == "asset-ai-30"
    assert drawing_payload["evidence_level"] == "heuristic"


def test_explicit_unresolved_panel_is_persisted_without_fake_source_edge():
    driver = _CaptureDriver()
    repository = _MutableRepository(driver)
    panel = PlatePanelData(
        panel_id="plate-panel:c1:45:1",
        plate_id="plate:c1:45",
        panel_index=1,
        bbox_status="insufficient",
        source_asset_id=None,
        evidence_level=EvidenceLevel.UNRESOLVED,
        evidence_method="panel_source_unresolved",
    )
    plate = PlateData(
        plate_id="plate:c1:45",
        number="45",
        physical_page=1,
        reference_corpus_id="c1",
        source_asset_id="asset-plate-pdf",
        evidence_level=EvidenceLevel.DIRECT,
        evidence_method="plate_pdf_identifier",
        panels=[panel],
    )

    repository.save_canonical_visuals("p1", "c1", plates=[plate], drawings=[])

    panel_calls = [kwargs for query, kwargs in driver.calls if "UNWIND $panels" in query]
    assert len(panel_calls) == 1
    assert panel_calls[0]["panels"][0]["source_asset_id"] is None
    assert panel_calls[0]["panels"][0]["evidence_level"] == "unresolved"


def test_missing_source_is_rejected_unless_explicitly_unresolved():
    driver = _CaptureDriver()
    repository = _MutableRepository(driver)
    panel = PlatePanelData(
        panel_id="plate-panel:c1:45:1",
        plate_id="plate:c1:45",
        panel_index=1,
        source_asset_id=None,
        evidence_level=EvidenceLevel.DIRECT,
    )
    plate = PlateData(
        plate_id="plate:c1:45",
        number="45",
        physical_page=1,
        reference_corpus_id="c1",
        source_asset_id="asset-plate-pdf",
        panels=[panel],
    )

    try:
        repository.save_canonical_visuals("p1", "c1", plates=[plate], drawings=[])
    except ValueError as error:
        assert "provenance" in str(error)
    else:
        raise AssertionError("direct panel without source provenance must fail")


def test_ready_reference_corpus_is_terminal():
    assert ReferenceCorpusStatus.READY.is_terminal is True
