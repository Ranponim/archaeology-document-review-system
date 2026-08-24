from __future__ import annotations

from types import SimpleNamespace

from app.domain.canonical_models import EvidenceLevel
from app.services.drawing_evidence_graph_resolver import DrawingEvidenceGraphResolver
from app.services.drawing_evidence_graph_resolver_v2 import DrawingEvidenceGraphResolverV2
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
    """Reference-corpus service with corpus-wide drawing evidence resolution.

    v1 remains the production default until the local `/src` v2 acceptance
    metrics satisfy the design thresholds. v2 must be requested explicitly.
    """

    @staticmethod
    def _build_drawing_evidence_resolver(version: str):
        normalized = str(version or "v1").strip().lower()
        if normalized in {"v1", "drawing-evidence-v1"}:
            return DrawingEvidenceGraphResolver()
        if normalized in {"v2", "drawing-evidence-v2"}:
            return DrawingEvidenceGraphResolverV2()
        raise ValueError(f"Unsupported drawing evidence resolver version: {version}")

    def _body_context_mode(self) -> str:
        version = str(
            getattr(self._drawing_evidence_resolver, "resolver_version", "drawing-evidence-v1")
        ).strip().lower()
        return "v2" if version == "drawing-evidence-v2" else "v1"

    def __init__(
        self,
        repository,
        converter,
        canonicalizer,
        *,
        drawing_evidence_repository,
        drawing_evidence_resolver=None,
        drawing_evidence_resolver_version: str = "v1",
        drawing_source_observer: DrawingSourceObserver | None = None,
        **kwargs,
    ) -> None:
        kwargs["drawing_identity_resolver"] = _NoopDrawingIdentityResolver()
        super().__init__(repository, converter, canonicalizer, **kwargs)
        self._drawing_evidence_repository = drawing_evidence_repository
        self._drawing_evidence_resolver = (
            drawing_evidence_resolver
            if drawing_evidence_resolver is not None
            else self._build_drawing_evidence_resolver(drawing_evidence_resolver_version)
        )
        self._drawing_source_observer = drawing_source_observer or DrawingSourceObserver()

    def _list_body_contexts(self, project_id: str):
        if self._body_context_mode() == "v2":
            return self._drawing_evidence_repository.list_body_drawing_contexts(
                project_id,
                resolver_version="v2",
            )
        return self._drawing_evidence_repository.list_body_drawing_contexts(project_id)

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
            observation = self._drawing_source_observer.observe(
                asset,
                self._source_path(corpus_id, asset),
            )
            # Keep relative path as weak evidence for v2 without changing the
            # observer's content/filename separation contract.
            if self._body_context_mode() == "v2" and not observation.source_path:
                try:
                    from dataclasses import replace

                    observation = replace(
                        observation,
                        source_path=str(asset.relative_path or asset.original_name or ""),
                    )
                except TypeError:
                    pass
            observations.append(observation)

        body_contexts = self._list_body_contexts(project_id)
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
