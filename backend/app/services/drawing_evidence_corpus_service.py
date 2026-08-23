from __future__ import annotations

from types import SimpleNamespace

from app.domain.canonical_models import EvidenceLevel
from app.services.drawing_evidence_graph_resolver import DrawingEvidenceGraphResolver
from app.services.drawing_source_observer import DrawingSourceObserver
from app.services.reference_corpus_service import ReferenceCorpusService


class _NoopDrawingIdentityResolver:
    """Suppress the legacy per-file filename fallback inside the base service.

    The evidence-graph subclass resolves all drawing sources in one corpus-wide
    batch after the base service has finished the plate pipeline.
    """

    def resolve(self, *, corpus_id, asset, source_path):
        return SimpleNamespace(drawings=(), unresolved_source_ids=(asset.id,))


class EvidenceGraphReferenceCorpusService(ReferenceCorpusService):
    """Reference-corpus service with corpus-wide drawing evidence resolution."""

    def __init__(
        self,
        repository,
        converter,
        canonicalizer,
        *,
        drawing_evidence_repository,
        drawing_evidence_resolver: DrawingEvidenceGraphResolver | None = None,
        drawing_source_observer: DrawingSourceObserver | None = None,
        **kwargs,
    ) -> None:
        kwargs["drawing_identity_resolver"] = _NoopDrawingIdentityResolver()
        super().__init__(repository, converter, canonicalizer, **kwargs)
        self._drawing_evidence_repository = drawing_evidence_repository
        self._drawing_evidence_resolver = (
            drawing_evidence_resolver or DrawingEvidenceGraphResolver()
        )
        self._drawing_source_observer = drawing_source_observer or DrawingSourceObserver()

    def _adobe_free_visuals(
        self,
        project_id: str,
        corpus_id: str,
        source_rows: list[dict],
    ):
        plates, _legacy_drawings, diagnostics = super()._adobe_free_visuals(
            project_id,
            corpus_id,
            source_rows,
        )

        observations = []
        for row in source_rows:
            if str(row.get("role") or "") != "drawing_source":
                continue
            asset = self._asset_from_row({**row, "project_id": project_id})
            observations.append(
                self._drawing_source_observer.observe(
                    asset,
                    self._source_path(corpus_id, asset),
                )
            )

        body_contexts = self._drawing_evidence_repository.list_body_drawing_contexts(
            project_id
        )
        resolution = self._drawing_evidence_resolver.resolve_observations(
            corpus_id=corpus_id,
            observations=observations,
            body_contexts=body_contexts,
            include_filename_evidence=True,
        )
        self._drawing_evidence_repository.save_resolution(
            project_id,
            corpus_id,
            resolution,
        )

        drawings = list(resolution.canonical_drawings)
        diagnostics = dict(diagnostics or {})
        diagnostics["drawingCount"] = len(drawings)
        diagnostics["unresolvedDrawingSourceIds"] = list(
            resolution.unresolved_source_ids
        )
        diagnostics["ambiguousDrawingSourceIds"] = list(
            resolution.ambiguous_source_ids
        )
        diagnostics["drawingResolution"] = dict(resolution.diagnostics)

        evidence_counts = {
            level.value: 0
            for level in (
                EvidenceLevel.DIRECT,
                EvidenceLevel.DERIVED_VERIFIED,
                EvidenceLevel.HEURISTIC,
                EvidenceLevel.UNRESOLVED,
            )
        }
        for plate in plates:
            evidence_counts[self._evidence_value(plate.evidence_level)] += 1
            for panel in plate.panels:
                evidence_counts[self._evidence_value(panel.evidence_level)] += 1
        for drawing in drawings:
            evidence_counts[self._evidence_value(drawing.evidence_level)] += 1
            for region in drawing.regions:
                evidence_counts[self._evidence_value(region.evidence_level)] += 1
        diagnostics["evidenceCounts"] = evidence_counts

        return plates, drawings, diagnostics
