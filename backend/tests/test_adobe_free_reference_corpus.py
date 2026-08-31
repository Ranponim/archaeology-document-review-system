from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.canonical_models import (
    DrawingData,
    EvidenceLevel,
    PlateData,
    PlatePanelData,
)
from app.domain.reference_corpus import ReferenceCorpusData, ReferenceCorpusStatus
from app.services.drawing_identity_resolver import DrawingIdentityResolution
from app.services.reference_corpus_service import ReferenceCorpusService
from app.services.visual_asset_matcher import VisualAssetMatch


def _corpus(status: ReferenceCorpusStatus = ReferenceCorpusStatus.STAGING):
    return ReferenceCorpusData(id="c1", project_id="p1", revision=1, status=status)


def _source(source_id: str, role: str, relative_path: str, sha: str) -> dict:
    return {
        "id": source_id,
        "role": role,
        "uri": f"incoming/{source_id}/{Path(relative_path).name}",
        "sha256": sha,
        "size_bytes": 10,
        "mime_type": "application/octet-stream",
        "original_name": Path(relative_path).name,
        "relative_path": relative_path,
        "asset_kind": role,
        "source_root_name": "reference-corpus",
        "import_batch_id": "c1",
        "parse_status": "stored",
        "provenance_status": "unlinked",
        "created_at": None,
        "source_metadata_json": "{}",
    }


class Repository:
    def __init__(self):
        self.corpus = _corpus()
        self.sources = [
            _source("plates", "plate_pdf", "plates/plate-book.pdf", "sha-plates"),
            _source("photo", "plate_link", "plates/Links/photo.jpg", "sha-photo"),
            _source("drawing", "drawing_source", "drawings/도면27.ai", "sha-drawing"),
        ]
        self.transitions: list[tuple[ReferenceCorpusStatus, dict]] = []
        self.artifacts = []
        self.visuals = None

    def get(self, project_id, corpus_id):
        return self.corpus if (project_id, corpus_id) == ("p1", "c1") else None

    def list_sources(self, project_id, corpus_id):
        return list(self.sources)

    def find_ready_by_build_identity(self, project_id, identity):
        return None

    def transition_status(self, project_id, corpus_id, status, **kwargs):
        target = ReferenceCorpusStatus(status)
        self.transitions.append((target, kwargs))
        self.corpus = replace(
            self.corpus,
            status=target,
            source_set_hash=kwargs.get("source_set_hash") or self.corpus.source_set_hash,
            converter_version=kwargs.get("converter_version") or self.corpus.converter_version,
            manifest_schema_version=kwargs.get("manifest_schema_version") or self.corpus.manifest_schema_version,
            canonicalizer_version=kwargs.get("canonicalizer_version") or self.corpus.canonicalizer_version,
            build_identity=kwargs.get("build_identity") or self.corpus.build_identity,
            failure_code=kwargs.get("failure_code") if target == ReferenceCorpusStatus.FAILED else None,
        )
        return self.corpus

    def save_artifact(self, project_id, corpus_id, artifact):
        self.artifacts.append(artifact)

    def save_canonical_visuals(self, project_id, corpus_id, *, plates, drawings):
        self.visuals = (plates, drawings)

    def validate_ready_graph(self, project_id, corpus_id):
        return True


class NoAdobeConverter:
    @property
    def version(self):
        raise AssertionError("Adobe converter must not be consulted in plate_pdf mode")

    def convert(self, request):
        raise AssertionError("Adobe converter must not be called in plate_pdf mode")


class LegacyCanonicalizer:
    version = "legacy-canonicalizer-v1"

    def canonicalize(self, corpus_id, manifests, assets):
        raise AssertionError("Adobe canonicalizer must not run in plate_pdf mode")


class PlateParser:
    def parse(self, path, **kwargs):
        return SimpleNamespace(
            plates=[
                PlateData(
                    plate_id="legacy-plate-3",
                    number="3",
                    physical_page=1,
                    title="유적 전경",
                    source_sha256="derived-pdf-sha",
                    panels=[
                        PlatePanelData(
                            panel_id="legacy-panel",
                            plate_id="legacy-plate-3",
                            panel_index=1,
                            caption="전경",
                            bbox=None,
                            bbox_status="insufficient",
                            physical_page=1,
                        )
                    ],
                    raw_identifier="【도판 3】",
                )
            ]
        )


class SegmentedPlateParser:
    def parse(self, path, **kwargs):
        return SimpleNamespace(
            plates=[
                PlateData(
                    plate_id="legacy-plate-3",
                    number="3",
                    physical_page=1,
                    title="유적 전경",
                    source_sha256="derived-pdf-sha",
                    panels=[
                        PlatePanelData(
                            panel_id="legacy-panel-1",
                            plate_id="legacy-plate-3",
                            panel_index=1,
                            caption="전경 1",
                            bbox=(0.05, 0.10, 0.45, 0.45),
                            bbox_status="segmented",
                            physical_page=1,
                        ),
                        PlatePanelData(
                            panel_id="legacy-panel-2",
                            plate_id="legacy-plate-3",
                            panel_index=2,
                            caption="전경 2",
                            bbox=(0.55, 0.10, 0.95, 0.45),
                            bbox_status="segmented",
                            physical_page=1,
                        ),
                    ],
                    raw_identifier="【도판 3】",
                )
            ]
        )


class DrawingResolver:
    def resolve(self, *, corpus_id, asset, source_path):
        return DrawingIdentityResolution(
            drawings=(
                DrawingData(
                    drawing_id=f"drawing:{corpus_id}:27",
                    number="27",
                    physical_page=1,
                    source_sha256=asset.sha256,
                    source_kind="drawing_ai",
                    reference_corpus_id=corpus_id,
                    source_asset_id=asset.id,
                    evidence_level=EvidenceLevel.HEURISTIC,
                    evidence_method="filename_identifier",
                ),
            )
        )


class Matcher:
    def __init__(self):
        self.calls = []

    def match_panel(self, **kwargs):
        self.calls.append(kwargs)
        return None


class BatchMatcher:
    def __init__(self):
        self.calls = []

    def match_panels(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "plate-panel:c1:3:1": VisualAssetMatch(
                source_asset_id="photo",
                score=0.99,
            )
        }


def test_plate_pdf_is_valid_adobe_free_source_role():
    assert ReferenceCorpusService.validate_source_role("plate_pdf", "도판-3차.pdf") == "plate_pdf"
    with pytest.raises(ValueError):
        ReferenceCorpusService.validate_source_role("plate_pdf", "도판.indd")


def test_adobe_free_build_uses_plate_pdf_ai_and_explicit_unresolved_panel(tmp_path):
    repository = Repository()
    matcher = Matcher()
    paths = {}
    for row in repository.sources:
        path = tmp_path / row["relative_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(row["sha256"].encode("ascii"))
        paths[row["uri"]] = path

    service = ReferenceCorpusService(
        repository,
        NoAdobeConverter(),
        LegacyCanonicalizer(),
        artifact_root=tmp_path / "derived",
        source_path_resolver=lambda uri: paths[uri],
        plate_parser=PlateParser(),
        drawing_identity_resolver=DrawingResolver(),
        visual_asset_matcher=matcher,
    )

    result = service.build("p1", "c1")

    assert result.status == ReferenceCorpusStatus.READY
    assert [status for status, _ in repository.transitions] == [
        ReferenceCorpusStatus.CONVERTING,
        ReferenceCorpusStatus.VALIDATING,
        ReferenceCorpusStatus.CANONICALIZING,
        ReferenceCorpusStatus.GRAPH_VALIDATING,
        ReferenceCorpusStatus.READY,
    ]
    converting = repository.transitions[0][1]
    assert converting["converter_version"] == "adobe-free-native-v1"
    assert converting["canonicalizer_version"] == "adobe-free-canonicalizer-v1"
    assert converting["manifest_schema_version"] == "native-v1"

    assert repository.visuals is not None
    plates, drawings = repository.visuals
    assert len(plates) == 1 and len(drawings) == 1
    plate = plates[0]
    assert plate.plate_id == "plate:c1:3"
    assert plate.source_asset_id == "plates"
    assert plate.evidence_level == EvidenceLevel.DIRECT
    assert plate.evidence_method == "plate_pdf_identifier"

    panel = plate.panels[0]
    assert panel.panel_id == "plate-panel:c1:3:1"
    assert panel.source_asset_id is None
    assert panel.source_sha256 is None
    assert panel.evidence_level == EvidenceLevel.UNRESOLVED
    assert panel.evidence_method == "panel_source_unresolved"
    assert matcher.calls == []  # bbox insufficient, therefore no unsafe image guess

    assert drawings[0].source_asset_id == "drawing"
    assert drawings[0].evidence_level == EvidenceLevel.HEURISTIC
    assert any(artifact.artifact_type == "build_diagnostics" for artifact in repository.artifacts)


def test_adobe_free_build_resolves_segmented_panels_once_as_a_corpus_batch(tmp_path):
    repository = Repository()
    matcher = BatchMatcher()
    paths = {}
    for row in repository.sources:
        path = tmp_path / row["relative_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(row["sha256"].encode("ascii"))
        paths[row["uri"]] = path

    service = ReferenceCorpusService(
        repository,
        NoAdobeConverter(),
        LegacyCanonicalizer(),
        artifact_root=tmp_path / "derived",
        source_path_resolver=lambda uri: paths[uri],
        plate_parser=SegmentedPlateParser(),
        drawing_identity_resolver=DrawingResolver(),
        visual_asset_matcher=matcher,
    )

    result = service.build("p1", "c1")

    assert result.status == ReferenceCorpusStatus.READY
    assert len(matcher.calls) == 1
    request_ids = [item.panel_id for item in matcher.calls[0]["panels"]]
    assert request_ids == ["plate-panel:c1:3:1", "plate-panel:c1:3:2"]
    assert len(matcher.calls[0]["candidates"]) == 1

    assert repository.visuals is not None
    plates, _ = repository.visuals
    first, second = plates[0].panels
    assert first.source_asset_id == "photo"
    assert first.source_sha256 == "sha-photo"
    assert first.evidence_level == EvidenceLevel.DERIVED_VERIFIED
    assert first.evidence_method == "pixel_thumbnail_similarity"
    assert second.source_asset_id is None
    assert second.source_sha256 is None
    assert second.evidence_level == EvidenceLevel.UNRESOLVED
    assert second.evidence_method == "panel_source_unresolved"
