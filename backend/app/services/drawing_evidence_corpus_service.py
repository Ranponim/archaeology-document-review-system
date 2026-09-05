from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace

from app.config import CodexDrawingResolverConfig
from app.domain.canonical_models import DrawingData, EvidenceLevel
from app.domain.drawing_evidence_v3 import (
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
)
from app.jobs.run_inputs import resolve_stored_pdf_path
from app.services.codex_drawing_resolver_client import CodexDrawingResolverClient
from app.services.drawing_candidate_generator_v3 import DrawingCandidateGeneratorV3
from app.services.drawing_context_normalizer import DrawingContextNormalizer
from app.services.drawing_evidence_graph_resolver import DrawingEvidenceGraphResolver
from app.services.drawing_evidence_graph_resolver_v2 import DrawingEvidenceGraphResolverV2
from app.services.drawing_evidence_resolver_v3 import DrawingEvidenceResolverV3
from app.services.drawing_source_observer import DrawingSourceObserver
from app.services.drawing_visual_extractor import DrawingVisualExtractor
from app.services.reference_corpus_service import ReferenceCorpusService


_SOURCE_FAMILY_BY_KIND = {
    "publication_kind": "identity_signature",
    "site_point": "spatial_signature",
    "point": "spatial_signature",
    "grid": "spatial_signature",
    "direction": "spatial_signature",
    "period": "archaeology_signature",
    "feature_type": "archaeology_signature",
    "feature_number": "archaeology_signature",
    "feature": "archaeology_signature",
    "drawing_type": "drawing_signature",
    "section_label": "drawing_signature",
    "content_type": "drawing_signature",
    "map_type": "map_signature",
    "year": "map_signature",
}


class _NoopDrawingIdentityResolver:
    """Suppress the legacy per-file filename fallback inside the base service.

    The evidence-graph subclass resolves all drawing sources in one corpus-wide
    batch after the base service has finished the plate pipeline.
    """

    def resolve(self, *, corpus_id, asset, source_path):
        return SimpleNamespace(drawings=(), unresolved_source_ids=(asset.id,))


class EvidenceGraphReferenceCorpusService(ReferenceCorpusService):
    """Reference-corpus service with corpus-wide drawing evidence resolution.

    v1 remains the production default. v2 and v3 are explicit opt-ins; v3 is
    shadow-only unless the separate auto-promotion gate is explicitly enabled.
    """

    @staticmethod
    def _build_drawing_evidence_resolver(version: str):
        normalized = str(version or "v1").strip().lower()
        if normalized in {"v1", "drawing-evidence-v1"}:
            return DrawingEvidenceGraphResolver()
        if normalized in {"v2", "drawing-evidence-v2"}:
            return DrawingEvidenceGraphResolverV2()
        raise ValueError(f"Unsupported drawing evidence resolver version: {version}")

    @staticmethod
    def _build_v3_resolver(
        *,
        normalizer: DrawingContextNormalizer,
        codex_client=None,
    ) -> DrawingEvidenceResolverV3:
        config = CodexDrawingResolverConfig.from_env()
        generator = DrawingCandidateGeneratorV3(normalizer)
        client = codex_client or CodexDrawingResolverClient(config)
        return DrawingEvidenceResolverV3(
            generator,
            client,
            auto_confidence=config.auto_confidence,
            max_candidates=config.max_candidates,
            max_expansions=config.max_expansions,
        )

    def _body_context_mode(self) -> str:
        version = str(
            getattr(self._drawing_evidence_resolver, "resolver_version", "drawing-evidence-v1")
        ).strip().lower()
        if version == "drawing-evidence-v3":
            return "v3"
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
        drawing_visual_extractor: DrawingVisualExtractor | None = None,
        drawing_context_normalizer: DrawingContextNormalizer | None = None,
        project_repository=None,
        drawing_evidence_v3_auto_promote: bool = False,
        codex_drawing_resolver_client=None,
        **kwargs,
    ) -> None:
        kwargs["drawing_identity_resolver"] = _NoopDrawingIdentityResolver()
        super().__init__(repository, converter, canonicalizer, **kwargs)
        self._drawing_evidence_repository = drawing_evidence_repository
        self._drawing_source_observer = drawing_source_observer or DrawingSourceObserver()
        self._drawing_visual_extractor = drawing_visual_extractor or DrawingVisualExtractor()
        self._drawing_context_normalizer = drawing_context_normalizer or DrawingContextNormalizer()
        self._project_repository = project_repository
        self._drawing_evidence_v3_auto_promote = bool(drawing_evidence_v3_auto_promote)

        normalized_version = str(drawing_evidence_resolver_version or "v1").strip().lower()
        if drawing_evidence_resolver is not None:
            self._drawing_evidence_resolver = drawing_evidence_resolver
        elif normalized_version in {"v3", "drawing-evidence-v3"}:
            self._drawing_evidence_resolver = self._build_v3_resolver(
                normalizer=self._drawing_context_normalizer,
                codex_client=codex_drawing_resolver_client,
            )
        else:
            self._drawing_evidence_resolver = self._build_drawing_evidence_resolver(
                normalized_version
            )

    def _list_body_contexts(self, project_id: str):
        mode = self._body_context_mode()
        if mode == "v3":
            return self._drawing_evidence_repository.list_body_drawing_v3_contexts(
                project_id
            )
        if mode == "v2":
            return self._drawing_evidence_repository.list_body_drawing_contexts(
                project_id,
                resolver_version="v2",
            )
        return self._drawing_evidence_repository.list_body_drawing_contexts(project_id)

    @staticmethod
    def _source_evidence(asset_id: str, facts) -> tuple[DrawingV3Evidence, ...]:
        rows = []
        seen = set()
        for fact in facts:
            family = _SOURCE_FAMILY_BY_KIND.get(fact.kind)
            if family is None:
                continue
            key = (fact.kind, fact.normalized_value, family)
            if key in seen:
                continue
            seen.add(key)
            payload = "\0".join((asset_id, fact.kind, fact.normalized_value)).encode(
                "utf-8"
            )
            rows.append(
                DrawingV3Evidence(
                    id="drawing-v3-source-evidence:"
                    + hashlib.sha256(payload).hexdigest()[:32],
                    family=family,
                    method=f"source_{fact.kind}",
                    value=fact.normalized_value,
                    supports=True,
                    weak=False,
                )
            )
        return tuple(rows)

    def _enrich_v3_body_visuals(self, project_id: str, corpus_id: str, bodies):
        if self._project_repository is None:
            return bodies
        output_dir = self._artifact_root / corpus_id / "v3-drawing-visuals" / "body"
        enriched = []
        version_path_cache: dict[str, Path | None] = {}
        for body in bodies:
            if (
                not body.document_version_id
                or body.physical_page is None
                or body.source_bbox is None
            ):
                enriched.append(body)
                continue
            version_id = body.document_version_id
            if version_id not in version_path_cache:
                version = self._project_repository.resolve_version_input(
                    project_id,
                    "report_body",
                    None,
                    version_id,
                )
                version_path_cache[version_id] = (
                    resolve_stored_pdf_path(version) if version is not None else None
                )
            body_path = version_path_cache[version_id]
            if body_path is None:
                enriched.append(body)
                continue
            source_id = body.source_node_ids[0] if body.source_node_ids else f"{body.publication_kind}-{body.number}"
            try:
                region = self._drawing_visual_extractor.crop_body_region(
                    body_path,
                    output_dir,
                    f"body:{source_id}",
                    body.physical_page,
                    body.source_bbox,
                    body.source_sha256,
                )
            except (OSError, RuntimeError, ValueError):
                enriched.append(body)
                continue
            enriched.append(replace(body, visual_regions=(region,)))
        return enriched

    def _resolve_v3_batch(
        self,
        project_id: str,
        corpus_id: str,
        source_rows: list[dict],
    ):
        bodies = self._enrich_v3_body_visuals(
            project_id,
            corpus_id,
            self._drawing_evidence_repository.list_body_drawing_v3_contexts(project_id),
        )
        output_dir = self._artifact_root / corpus_id / "v3-drawing-visuals" / "source"
        sources = []
        for row in source_rows:
            if str(row.get("role") or "") != "drawing_source":
                continue
            asset = self._asset_from_row({**row, "project_id": project_id})
            source_path = self._source_path(corpus_id, asset)
            observation = self._drawing_source_observer.observe(asset, source_path)
            normalized = self._drawing_context_normalizer.normalize(
                observation.raw_text,
                source_kind="drawing_ai",
                source_node_id=observation.source_asset_id,
                source_sha256=observation.source_sha256,
            )
            try:
                source_region = self._drawing_visual_extractor.render_source(
                    source_path,
                    output_dir,
                    observation.source_asset_id,
                    observation.source_sha256,
                )
                visual_regions = (source_region,)
            except (OSError, RuntimeError, ValueError):
                visual_regions = ()
            sources.append(
                DrawingSourceEvidencePacket(
                    source_asset_id=observation.source_asset_id,
                    source_sha256=observation.source_sha256,
                    original_name=observation.original_name,
                    source_path=str(asset.relative_path or asset.original_name or ""),
                    raw_text=observation.raw_text,
                    publication_kind=(
                        observation.publication_kind or normalized.publication_kind
                    ),
                    internal_numbers=tuple(observation.internal_numbers),
                    facts=tuple(normalized.facts),
                    visual_regions=visual_regions,
                    evidence=self._source_evidence(
                        observation.source_asset_id, normalized.facts
                    ),
                )
            )

        resolution = self._drawing_evidence_resolver.resolve_observations(
            corpus_id,
            sources,
            bodies,
            render_dir=str(output_dir),
        )
        self._drawing_evidence_repository.save_v3_resolution(
            project_id,
            corpus_id,
            resolution,
            auto_promote=self._drawing_evidence_v3_auto_promote,
            sources=tuple(sources),
        )
        return resolution

    def _v3_canonical_drawings(self, corpus_id: str, resolution, source_rows: list[dict]):
        if not self._drawing_evidence_v3_auto_promote:
            return []
        source_by_id = {str(row.get("id")): row for row in source_rows}
        drawings = []
        for result in resolution.source_results:
            if result.status != "AUTO_VERIFIED" or not result.selected_candidate_id:
                continue
            selected = next(
                (
                    candidate
                    for candidate in result.candidates
                    if candidate.candidate_id == result.selected_candidate_id
                ),
                None,
            )
            if selected is None:
                continue
            row = source_by_id.get(result.source_asset_id, {})
            drawings.append(
                DrawingData(
                    drawing_id=f"drawing:{corpus_id}:{selected.publication_kind}:{selected.number}",
                    number=selected.number,
                    physical_page=1,
                    title=(selected.raw_texts[0] if selected.raw_texts else f"도면 {selected.number}"),
                    source_sha256=str(row.get("sha256") or ""),
                    source_kind="drawing_ai",
                    reference_corpus_id=corpus_id,
                    source_asset_id=result.source_asset_id,
                    evidence_level=EvidenceLevel.DERIVED_VERIFIED,
                    evidence_method="codex-grounded-v3",
                    publication_kind=selected.publication_kind,
                )
            )
        return drawings

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

        if self._body_context_mode() == "v3":
            resolution = self._resolve_v3_batch(project_id, corpus_id, source_rows)
            drawings = self._v3_canonical_drawings(corpus_id, resolution, source_rows)
            diagnostics = dict(diagnostics or {})
            diagnostics["drawingCount"] = len(drawings)
            diagnostics["unresolvedDrawingSourceIds"] = [
                item.source_asset_id
                for item in resolution.source_results
                if item.status == "UNRESOLVED"
            ]
            diagnostics["ambiguousDrawingSourceIds"] = [
                item.source_asset_id
                for item in resolution.source_results
                if item.status == "REVIEW_REQUIRED"
            ]
            diagnostics["drawingResolution"] = dict(resolution.diagnostics)
            diagnostics["drawingResolution"]["shadowMode"] = not self._drawing_evidence_v3_auto_promote
        else:
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
