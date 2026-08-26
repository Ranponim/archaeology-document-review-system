from pathlib import Path

from app.domain.drawing_evidence import DrawingSourceObservation
from app.domain.drawing_evidence_v3 import DrawingV3Resolution, DrawingV3SourceResult
from app.services.drawing_context_normalizer import DrawingContextNormalizer
from app.services.drawing_evidence_corpus_service import EvidenceGraphReferenceCorpusService


class FakeDrawingEvidenceRepository:
    def __init__(self):
        self.saved = []

    def list_body_drawing_v3_contexts(self, project_id):
        assert project_id == "project-1"
        return []

    def save_v3_resolution(self, project_id, corpus_id, resolution, *, auto_promote):
        self.saved.append((project_id, corpus_id, resolution, auto_promote))


class FakeObserver:
    def __init__(self):
        self.calls = []

    def observe(self, asset, source_path):
        self.calls.append((asset.id, Path(source_path).name))
        return DrawingSourceObservation(
            source_asset_id=asset.id,
            source_sha256=asset.sha256,
            original_name=asset.original_name,
            raw_text="2지점 조선시대 1호 토광묘 평단면",
            internal_numbers=(),
        )


class FakeVisualExtractor:
    def render_source(self, *args, **kwargs):
        raise ValueError("visual unavailable in unit test")


class FakeV3Resolver:
    resolver_version = "drawing-evidence-v3"

    def __init__(self):
        self.calls = []

    def resolve_observations(self, corpus_id, sources, bodies, **kwargs):
        self.calls.append((corpus_id, tuple(sources), tuple(bodies), kwargs))
        return DrawingV3Resolution(
            source_results=tuple(
                DrawingV3SourceResult(
                    source_asset_id=source.source_asset_id,
                    status="REVIEW_REQUIRED",
                    candidates=(),
                    decision=None,
                    selected_candidate_id=None,
                    diagnostics={"resolver_version": self.resolver_version},
                )
                for source in sources
            ),
            diagnostics={"resolver_version": self.resolver_version},
        )


def source_row(asset_id, name):
    return {
        "id": asset_id,
        "role": "drawing_source",
        "project_id": "project-1",
        "uri": name,
        "sha256": f"sha-{asset_id}",
        "size_bytes": 1,
        "mime_type": "application/postscript",
        "original_name": name,
        "relative_path": name,
    }


def test_v3_batch_processes_every_drawing_source_and_persists_shadow(tmp_path):
    repo = FakeDrawingEvidenceRepository()
    observer = FakeObserver()
    resolver = FakeV3Resolver()
    service = object.__new__(EvidenceGraphReferenceCorpusService)
    service._drawing_evidence_repository = repo
    service._drawing_evidence_resolver = resolver
    service._drawing_source_observer = observer
    service._drawing_visual_extractor = FakeVisualExtractor()
    service._drawing_context_normalizer = DrawingContextNormalizer()
    service._project_repository = None
    service._drawing_evidence_v3_auto_promote = False
    service._artifact_root = tmp_path / "artifacts"
    service._source_path = lambda corpus_id, asset: tmp_path / asset.original_name

    result = service._resolve_v3_batch(
        "project-1",
        "corpus-1",
        [source_row("asset-1", "a.ai"), source_row("asset-2", "b.ai")],
    )

    assert service._body_context_mode() == "v3"
    assert [call[0] for call in observer.calls] == ["asset-1", "asset-2"]
    assert len(resolver.calls) == 1
    submitted = resolver.calls[0][1]
    assert [source.source_asset_id for source in submitted] == ["asset-1", "asset-2"]
    assert all(source.source_path in {"a.ai", "b.ai"} for source in submitted)
    assert all(source.facts for source in submitted)
    assert result.diagnostics["resolver_version"] == "drawing-evidence-v3"
    assert len(repo.saved) == 1
    assert repo.saved[0][3] is False
