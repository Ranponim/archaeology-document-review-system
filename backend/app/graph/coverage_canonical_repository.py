from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.domain.evidence_bundle import ObjectEvidenceBundle
from app.domain.review_models import EvidenceData
from app.graph.canonical_repository import CanonicalRepository


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    return tuple(float(item) for item in value)  # type: ignore[return-value]


class CoverageCanonicalRepository(CanonicalRepository):
    """Canonical repository view enriched for bidirectional visual coverage.

    All reverse-coverage facts are reconstructed from project-scoped Neo4j
    relationships. No filesystem path or OriginalAsset filename participates in
    publication identity.
    """

    def get_object_evidence_bundle(
        self,
        object_id: str,
        analysis_run_id: str | None = None,
        document_version_ids: list[str] | None = None,
    ) -> ObjectEvidenceBundle:
        base = super().get_object_evidence_bundle(
            object_id,
            analysis_run_id=analysis_run_id,
            document_version_ids=document_version_ids,
        )
        if self._driver is None:
            return base

        references = self._enrich_reference_resolution(
            object_id,
            base.references,
            document_version_ids=document_version_ids,
        )
        plate_claims, drawing_claims = self._query_scoped_visual_claims(
            object_id,
            analysis_run_id=analysis_run_id,
            document_version_ids=document_version_ids,
        )
        return ObjectEvidenceBundle(
            object_id=base.object_id,
            canonical_name=base.canonical_name,
            text_claims=base.text_claims,
            references=references,
            plate_claims=plate_claims,
            drawing_claims=drawing_claims,
            visual_observations=base.visual_observations,
            version_claims=base.version_claims,
        )

    def _enrich_reference_resolution(
        self,
        object_id: str,
        references: list[EvidenceData],
        *,
        document_version_ids: list[str] | None,
    ) -> list[EvidenceData]:
        if not references:
            return []
        cypher = """
        MATCH (source)-[:MENTIONS]->(obj:ArchaeologyObject {id: $object_id})
        MATCH (source)-[:REFERENCES]->(ref:Reference)
        OPTIONAL MATCH (ref)-[:RESOLVES_TO]->(resolved)
        OPTIONAL MATCH (direct_v:DocumentVersion)-[:HAS_PLATE|HAS_DRAWING]->(resolved)
        OPTIONAL MATCH (panel_v:DocumentVersion)-[:HAS_PLATE]->(:Plate)-[:HAS_PANEL]->(resolved)
        OPTIONAL MATCH (region_v:DocumentVersion)-[:HAS_DRAWING]->(:Drawing)-[:HAS_REGION]->(resolved)
        WITH source, obj, ref, resolved,
             coalesce(direct_v, panel_v, region_v) AS owner_v
        OPTIONAL MATCH (p:Project {id: obj.projectId})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(owner_v)
        OPTIONAL MATCH (resolved)-[:DEPICTS]->(depicted:ArchaeologyObject {id: $object_id})
        WITH source, ref, resolved, owner_v, p, depicted,
             CASE
               WHEN resolved IS NOT NULL
                AND owner_v IS NOT NULL
                AND p IS NOT NULL
                AND ($document_version_ids IS NULL OR owner_v.id IN $document_version_ids)
               THEN true ELSE false
             END AS scope_ok
        RETURN source.id AS source_block_id,
               ref.ref_type AS ref_type,
               toString(ref.number) AS number,
               CASE WHEN scope_ok THEN resolved.id ELSE null END AS target_id,
               CASE WHEN scope_ok THEN head(labels(resolved)) ELSE null END AS target_label,
               CASE WHEN scope_ok AND depicted IS NOT NULL THEN true ELSE false END AS depicts_object
        """
        records, _, _ = self._driver.execute_query(
            cypher,
            object_id=object_id,
            document_version_ids=document_version_ids,
            **self._query_config(),
        )
        by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for record in records:
            row = dict(record)
            key = (
                str(row.get("source_block_id") or ""),
                str(row.get("ref_type") or ""),
                str(row.get("number") or ""),
            )
            by_key.setdefault(key, []).append(row)

        enriched: list[EvidenceData] = []
        for evidence in references:
            value = dict(evidence.value) if isinstance(evidence.value, dict) else {}
            ref_type = str(value.get("ref_type") or value.get("reference_type") or "")
            number = str(value.get("number") or value.get("reference_number") or "")
            rows = by_key.get((str(evidence.region_id or ""), ref_type, number), [])
            distinct_targets: dict[str, dict[str, Any]] = {}
            for row in rows:
                target_id = row.get("target_id")
                if target_id:
                    distinct_targets[str(target_id)] = row
            if len(distinct_targets) == 1:
                selected = next(iter(distinct_targets.values()))
                value.update(
                    {
                        "resolved_target_id": str(selected["target_id"]),
                        "resolved_target_label": str(selected.get("target_label") or ""),
                        "resolved_depicts_object": bool(selected.get("depicts_object")),
                    }
                )
            else:
                value.update(
                    {
                        "resolved_target_id": None,
                        "resolved_target_label": None,
                        "resolved_depicts_object": False,
                    }
                )
            enriched.append(replace(evidence, value=value))
        return enriched

    def _query_scoped_visual_claims(
        self,
        object_id: str,
        *,
        analysis_run_id: str | None,
        document_version_ids: list[str] | None,
    ) -> tuple[list[EvidenceData], list[EvidenceData]]:
        queries: tuple[tuple[str, str], ...] = (
            (
                "plate",
                """
                MATCH (obj:ArchaeologyObject {id: $object_id})
                MATCH (p:Project {id: obj.projectId})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(version:DocumentVersion)-[:HAS_PLATE]->(asset:Plate)
                MATCH (asset)-[:DEPICTS]->(obj)
                WHERE $document_version_ids IS NULL OR version.id IN $document_version_ids
                RETURN 'Plate' AS asset_label, properties(asset) AS asset,
                       {} AS parent, properties(version) AS version
                """,
            ),
            (
                "plate",
                """
                MATCH (obj:ArchaeologyObject {id: $object_id})
                MATCH (p:Project {id: obj.projectId})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(version:DocumentVersion)-[:HAS_PLATE]->(parent:Plate)-[:HAS_PANEL]->(asset:PlatePanel)
                MATCH (asset)-[:DEPICTS]->(obj)
                WHERE $document_version_ids IS NULL OR version.id IN $document_version_ids
                RETURN 'PlatePanel' AS asset_label, properties(asset) AS asset,
                       properties(parent) AS parent, properties(version) AS version
                """,
            ),
            (
                "drawing",
                """
                MATCH (obj:ArchaeologyObject {id: $object_id})
                MATCH (p:Project {id: obj.projectId})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(version:DocumentVersion)-[:HAS_DRAWING]->(asset:Drawing)
                MATCH (asset)-[:DEPICTS]->(obj)
                WHERE $document_version_ids IS NULL OR version.id IN $document_version_ids
                RETURN 'Drawing' AS asset_label, properties(asset) AS asset,
                       {} AS parent, properties(version) AS version
                """,
            ),
            (
                "drawing",
                """
                MATCH (obj:ArchaeologyObject {id: $object_id})
                MATCH (p:Project {id: obj.projectId})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(version:DocumentVersion)-[:HAS_DRAWING]->(parent:Drawing)-[:HAS_REGION]->(asset:DrawingRegion)
                MATCH (asset)-[:DEPICTS]->(obj)
                WHERE $document_version_ids IS NULL OR version.id IN $document_version_ids
                RETURN 'DrawingRegion' AS asset_label, properties(asset) AS asset,
                       properties(parent) AS parent, properties(version) AS version
                """,
            ),
        )

        plate_claims: list[EvidenceData] = []
        drawing_claims: list[EvidenceData] = []
        for family, cypher in queries:
            records, _, _ = self._driver.execute_query(
                cypher,
                object_id=object_id,
                document_version_ids=document_version_ids,
                **self._query_config(),
            )
            for row in records:
                asset = dict(row.get("asset") or {})
                parent = dict(row.get("parent") or {})
                version = dict(row.get("version") or {})
                asset_id = str(asset.get("id") or "")
                version_id = str(version.get("id") or "")
                source_sha256 = str(
                    asset.get("source_sha256")
                    or parent.get("source_sha256")
                    or version.get("sha256")
                    or ""
                )
                physical_page = asset.get("physical_page")
                if physical_page is None:
                    physical_page = parent.get("physical_page")
                if not asset_id or not version_id or not source_sha256 or physical_page is None:
                    continue
                number = str(
                    (asset.get("number") if row.get("asset_label") in {"Plate", "Drawing"} else parent.get("number"))
                    or ""
                ).strip()
                if not number:
                    continue
                title = str(
                    asset.get("caption")
                    or asset.get("title")
                    or parent.get("title")
                    or ""
                )
                raw_identifier = asset.get("raw_identifier") or parent.get("raw_identifier")
                is_plate = family == "plate"
                evidence = EvidenceData(
                    id=f"ev_{family}_coverage_{object_id}_{asset_id}",
                    kind="plate_caption" if is_plate else "drawing_caption",
                    source_sha256=source_sha256,
                    document_version_id=version_id,
                    page_id=f"{version_id}_p{physical_page}",
                    region_id=asset_id,
                    bbox=_bbox(asset.get("bbox") or parent.get("bbox")),
                    method="graph_traversal",
                    analysis_run_id=analysis_run_id,
                    value={
                        "label": str(row.get("asset_label") or ""),
                        "plate_number" if is_plate else "drawing_number": number,
                        "title": title,
                        "raw_identifier": raw_identifier,
                    },
                    confidence=1.0,
                    version_from=version.get("stage"),
                    version_to=version.get("stage"),
                    physical_page_from=int(physical_page),
                    physical_page_to=int(physical_page),
                    rule_name="plate_caption_evidence" if is_plate else "drawing_caption_evidence",
                )
                if is_plate:
                    plate_claims.append(evidence)
                else:
                    drawing_claims.append(evidence)
        return plate_claims, drawing_claims
