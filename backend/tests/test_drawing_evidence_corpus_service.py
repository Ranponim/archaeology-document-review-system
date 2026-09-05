from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from app.domain.canonical_models import DrawingData, EvidenceLevel, PlateData
from app.domain.drawing_evidence import (
    BodyDrawingContext,
    DrawingCandidateResult,
    DrawingEvidenceResolution,
    DrawingSourceObservation,
)
from app.domain.reference_corpus import ReferenceCorpusData, ReferenceCorpusStatus
from app.services.drawing_evidence_corpus_service import EvidenceGraphReferenceCorpusService
from app.services.drawing_source_observer import DrawingSourceObserver


def test_source_observer_extracts_internal_id_and_keeps_filename_separate(tmp_path):
    observer = DrawingSourceObserver(
        text_extractor=lambda _path: "도면 14. 2지점 S1 E1 북동 토층"
    )
    asset = SimpleNamespace(
        id="ai14", sha256="sha14", original_name="도면99 misleading.ai"
    )

    observation = observer.observe(asset, tmp_path / "drawing.ai")

    assert observation.internal_numbers == ("14",)
    assert observation.raw_text == "도면 14. 2지점 S1 E1 북동 토층"
    assert observation.original_name == "도면99 misleading.ai"


class Repository:
    def __init__(self):
        self.corpus = ReferenceCorpusData(
            id="c1", project_id="p1", revision=1, status=ReferenceCorpusStatus.STAGING
        )
        self.sources = [
            {
                "id": "plates", "role": "plate_pdf", "uri": "incoming/plates.pdf",
                "sha256": "sha-plates", "size_bytes": 1, "mime_type": "application/pdf",
                "original_name": "plates.pdf", "relative_path": "plates.pdf",
                "asset_kind": "plate_pdf", "source_root_name": "reference-corpus",
                "import_batch_id": "c1", "parse_status": "stored", "provenance_status": "unlinked",
                "source_metadata_json": "{}",
            },
            {
                "id": "ai14", "role": "drawing_source", "uri": "incoming/도면14.ai",
                "sha256": "sha-ai14", "size_bytes": 1, "mime_type": "application/octet-stream",
                "original_name": "도면14.ai", "relative_path": "도면14.ai",
                "asset_kind": "drawing_source", "source_root_name": "reference-corpus",
                "import_batch_id": "c1", "parse_status": "stored", "provenance_status": "unlinked",
                "source_metadata_json": "{}",
            },
        ]
        self.visuals = None
        self.artifacts = []

    def get(self, project_id, corpus_id): return self.corpus
    def list_sources(self, project_id, corpus_id): return list(self.sources)
    def find_ready_by_build_identity(self, project_id, identity): return None
    def save_artifact(self, project_id, corpus_id, artifact): self.artifacts.append(artifact)
    def save_canonical_visuals(self, project_id, corpus_id, *, plates, drawings): self.visuals = (plates, drawings)
    def validate_ready_graph(self, project_id, corpus_id): return True
    def transition_status(self, project_id, corpus_id, status, **kwargs):
        self.corpus = replace(self.corpus, status=ReferenceCorpusStatus(status))
        return self.corpus


class PlateParser:
    def parse(self, _path):
        return SimpleNamespace(plates=[PlateData(
            plate_id="legacy", number="1", physical_page=1,
            raw_identifier="【도판 1】", panels=[]
        )])


class LegacyDrawingResolver:
    def resolve(self, *, corpus_id, asset, source_path):
        return SimpleNamespace(drawings=(), unresolved_source_ids=(asset.id,))


class NoAdobe:
    @property
    def version(self): raise AssertionError("Adobe must not run")
    def convert(self, _request): raise AssertionError("Adobe must not run")


class Canonicalizer:
    version = "legacy"
    def canonicalize(self, *_args): raise AssertionError("legacy canonicalizer must not run")


class Matcher:
    def match_panel(self, **_kwargs): return None


class EvidenceRepository:
    def __init__(self): self.saved = []
    def list_body_drawing_contexts(self, project_id):
        return [BodyDrawingContext(number="14", raw_texts=("도면 14 2지점 S1E1 북동 토층",), source_node_ids=("caption14",))]
    def save_resolution(self, project_id, corpus_id, resolution): self.saved.append(resolution)


class Observer:
    def observe(self, asset, source_path):
        return DrawingSourceObservation(
            source_asset_id=asset.id,
            source_sha256=asset.sha256,
            original_name=asset.original_name,
            raw_text="2지점 S1 E1 북동 토층",
        )


class GraphResolver:
    resolver_version = "drawing-evidence-v1"
    def __init__(self, canonical: bool): self.canonical = canonical; self.calls = []
    def resolve_observations(self, **kwargs):
        self.calls.append(kwargs)
        candidate = DrawingCandidateResult(
            candidate_id="drawing-candidate:c1:ai14:14",
            reference_corpus_id="c1", source_asset_id="ai14", source_sha256="sha-ai14",
            candidate_number="14", status="verified" if self.canonical else "candidate",
            evidence_level=EvidenceLevel.DERIVED_VERIFIED if self.canonical else EvidenceLevel.HEURISTIC,
            evidence_families=("identity", "semantic_content"), score=.9, margin=.4,
        )
        drawing = DrawingData(
            drawing_id="drawing:c1:14", number="14", physical_page=1,
            reference_corpus_id="c1", source_asset_id="ai14", source_sha256="sha-ai14",
            source_kind="drawing_ai", evidence_level=EvidenceLevel.DERIVED_VERIFIED,
            evidence_method="drawing-evidence-v1",
        )
        return DrawingEvidenceResolution(
            canonical_drawings=(drawing,) if self.canonical else (), candidates=(candidate,),
            unresolved_source_ids=() if self.canonical else ("ai14",),
            diagnostics={"resolverVersion": self.resolver_version},
        )


def _service(tmp_path, canonical: bool):
    repository = Repository()
    evidence_repository = EvidenceRepository()
    graph_resolver = GraphResolver(canonical)
    paths = {}
    for source in repository.sources:
        path = tmp_path / source["relative_path"]
        path.write_bytes(source["sha256"].encode())
        paths[source["uri"]] = path
    service = EvidenceGraphReferenceCorpusService(
        repository, NoAdobe(), Canonicalizer(),
        artifact_root=tmp_path / "derived",
        source_path_resolver=lambda uri: paths[uri],
        plate_parser=PlateParser(),
        drawing_identity_resolver=LegacyDrawingResolver(),
        visual_asset_matcher=Matcher(),
        drawing_evidence_repository=evidence_repository,
        drawing_evidence_resolver=graph_resolver,
        drawing_source_observer=Observer(),
    )
    return service, repository, evidence_repository, graph_resolver


def test_batch_graph_resolution_persists_reasoning_and_only_verified_canonical(tmp_path):
    service, repository, evidence_repository, resolver = _service(tmp_path, True)

    result = service.build("p1", "c1")

    assert result.status == ReferenceCorpusStatus.READY
    assert len(resolver.calls) == 1
    assert resolver.calls[0]["include_filename_evidence"] is True
    assert len(evidence_repository.saved) == 1
    assert repository.visuals is not None
    _plates, drawings = repository.visuals
    assert [drawing.number for drawing in drawings] == ["14"]
    assert drawings[0].evidence_level == EvidenceLevel.DERIVED_VERIFIED


def test_heuristic_candidate_is_saved_but_excluded_from_canonical_drawings(tmp_path):
    service, repository, evidence_repository, _resolver = _service(tmp_path, False)

    result = service.build("p1", "c1")

    assert result.status == ReferenceCorpusStatus.READY
    assert len(evidence_repository.saved) == 1
    _plates, drawings = repository.visuals
    assert drawings == []
    diagnostics_artifact = next(item for item in repository.artifacts if item.artifact_type == "build_diagnostics")
    assert diagnostics_artifact is not None
