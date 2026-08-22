from __future__ import annotations

from dataclasses import replace

import pytest

from app.domain.canonical_models import DrawingData, PlateData
from app.domain.reference_corpus import ReferenceCorpusData, ReferenceCorpusStatus
from app.services.adobe_conversion_client import AdobeConversionError, ConversionResult
from app.services.reference_canonicalizer import CanonicalizationResult
from app.services.reference_corpus_service import ReferenceCorpusService


def _corpus(corpus_id: str = "c1", status: ReferenceCorpusStatus = ReferenceCorpusStatus.STAGING):
    return ReferenceCorpusData(
        id=corpus_id,
        project_id="p1",
        revision=1,
        status=status,
    )


def _source(source_id: str, role: str, sha: str):
    suffix = {"plate_layout": ".indd", "plate_link": ".jpg", "drawing_source": ".ai"}[role]
    return {
        "id": source_id,
        "role": role,
        "uri": f"incoming/p1/{sha}/source{suffix}",
        "sha256": sha,
        "size_bytes": 10,
        "mime_type": "application/octet-stream",
        "original_name": f"source{suffix}",
        "relative_path": f"source{suffix}",
        "asset_kind": role,
        "source_root_name": "reference-corpus",
        "import_batch_id": "batch",
        "parse_status": "stored",
        "provenance_status": "unlinked",
        "created_at": None,
        "source_metadata_json": "{}",
    }


class FakeRepository:
    def __init__(self):
        self.corpus = _corpus()
        self.sources = [
            _source("layout", "plate_layout", "sha-layout"),
            _source("photo", "plate_link", "sha-photo"),
            _source("drawing", "drawing_source", "sha-drawing"),
        ]
        self.transitions = []
        self.artifacts = []
        self.visuals = None
        self.ready_match = None

    def get(self, project_id, corpus_id):
        return self.corpus if project_id == "p1" and corpus_id == self.corpus.id else None

    def list_sources(self, project_id, corpus_id):
        return list(self.sources)

    def find_ready_by_build_identity(self, project_id, identity):
        return self.ready_match

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


class FakeConverter:
    version = "fixture-adobe-v1"

    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def convert(self, request):
        self.calls.append(request)
        if self.fail:
            raise AdobeConversionError("ADOBE_UNAVAILABLE")
        application = "indesign" if request.source_role == "plate_layout" else "illustrator"
        from app.domain.adobe_manifest import AdobeManifestV1

        payload = {
            "schemaVersion": 1,
            "application": application,
            "sourceAssetId": request.source_asset_id,
            "sourceSha256": "sha-layout" if application == "indesign" else "sha-drawing",
            "pages": [],
            "artboards": [],
            "artifacts": [],
        }
        return ConversionResult(manifest=AdobeManifestV1.from_dict(payload), converter_version=self.version)


class FakeCanonicalizer:
    version = "canon-v1"

    def canonicalize(self, corpus_id, manifests, assets):
        return CanonicalizationResult(
            plates=[PlateData(plate_id=f"plate:{corpus_id}:45", number="45", physical_page=1, reference_corpus_id=corpus_id)],
            drawings=[DrawingData(drawing_id=f"drawing:{corpus_id}:30", number="30", physical_page=1, reference_corpus_id=corpus_id)],
        )


def test_identical_build_reuses_existing_ready_corpus_without_conversion(tmp_path):
    repository = FakeRepository()
    ready = replace(_corpus("ready", ReferenceCorpusStatus.READY), build_identity="existing")
    repository.ready_match = ready
    converter = FakeConverter()
    service = ReferenceCorpusService(repository, converter, FakeCanonicalizer(), artifact_root=tmp_path)

    result = service.build("p1", "c1")

    assert result.id == "ready"
    assert converter.calls == []
    assert repository.transitions == []


def test_build_runs_exact_state_machine_and_ignores_plate_link_as_converter_input(tmp_path):
    repository = FakeRepository()
    converter = FakeConverter()
    service = ReferenceCorpusService(repository, converter, FakeCanonicalizer(), artifact_root=tmp_path)

    result = service.build("p1", "c1")

    assert result.status == ReferenceCorpusStatus.READY
    assert [status for status, _ in repository.transitions] == [
        ReferenceCorpusStatus.CONVERTING,
        ReferenceCorpusStatus.VALIDATING,
        ReferenceCorpusStatus.CANONICALIZING,
        ReferenceCorpusStatus.GRAPH_VALIDATING,
        ReferenceCorpusStatus.READY,
    ]
    assert [call.source_role for call in converter.calls] == ["drawing_source", "plate_layout"]
    assert repository.visuals is not None


def test_converter_error_transitions_build_to_failed_with_normalized_code(tmp_path):
    repository = FakeRepository()
    service = ReferenceCorpusService(repository, FakeConverter(fail=True), FakeCanonicalizer(), artifact_root=tmp_path)

    with pytest.raises(AdobeConversionError):
        service.build("p1", "c1")

    assert repository.transitions[-1][0] == ReferenceCorpusStatus.FAILED
    failure = repository.transitions[-1][1]["failure_code"]
    assert getattr(failure, "value", failure) == "ADOBE_UNAVAILABLE"


def test_source_role_validation_never_uses_filename_number_for_identity():
    assert ReferenceCorpusService.validate_source_role("plate_layout", "anything_45.indd") == "plate_layout"
    assert ReferenceCorpusService.validate_source_role("plate_link", "anything_45.JPG") == "plate_link"
    assert ReferenceCorpusService.validate_source_role("drawing_source", "도면30.ai") == "drawing_source"
    with pytest.raises(ValueError):
        ReferenceCorpusService.validate_source_role("drawing_source", "도면30.jpg")
