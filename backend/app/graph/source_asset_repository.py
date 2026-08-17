from __future__ import annotations

from typing import Any

from neo4j import Driver

from app.domain.source_assets import OriginalAssetData


_TARGET_PATHS = {
    "Plate": "(v)-[:HAS_PLATE]->(target:Plate)",
    "PlatePanel": "(v)-[:HAS_PLATE]->(:Plate)-[:HAS_PANEL]->(target:PlatePanel)",
    "Drawing": "(v)-[:HAS_DRAWING]->(target:Drawing)",
    "DrawingRegion": "(v)-[:HAS_DRAWING]->(:Drawing)-[:HAS_REGION]->(target:DrawingRegion)",
    "DocumentVersion": "(v)",
}


class SourceAssetRepository:
    def __init__(self, driver: Driver, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @property
    def _query_config(self) -> dict[str, str]:
        return {"database_": self._database} if self._database else {}

    def save_original_asset(self, asset: OriginalAssetData) -> OriginalAssetData:
        params = {
            "id": asset.id,
            "projectId": asset.project_id,
            "uri": asset.uri,
            "sha256": asset.sha256,
            "sizeBytes": asset.size_bytes,
            "mimeType": asset.mime_type,
            "originalName": asset.original_name,
            "relativePath": asset.relative_path,
            "assetKind": asset.asset_kind,
            "sourceRootName": asset.source_root_name,
            "importBatchId": asset.import_batch_id,
            "parseStatus": asset.parse_status,
            "provenanceStatus": asset.provenance_status,
            "sourceMetadata": asset.source_metadata or {},
        }
        cypher = """
        MATCH (p:Project {id: $project_id})
        MERGE (asset:OriginalAsset {id: $asset.id})
        WITH p, asset
        WHERE asset.projectId IS NULL OR asset.projectId = $project_id
        SET asset.projectId = $asset.projectId,
            asset.uri = $asset.uri,
            asset.sha256 = $asset.sha256,
            asset.sizeBytes = $asset.sizeBytes,
            asset.mimeType = $asset.mimeType,
            asset.originalName = $asset.originalName,
            asset.relativePath = $asset.relativePath,
            asset.assetKind = $asset.assetKind,
            asset.sourceRootName = $asset.sourceRootName,
            asset.importBatchId = $asset.importBatchId,
            asset.parseStatus = $asset.parseStatus,
            asset.provenanceStatus = $asset.provenanceStatus,
            asset.sourceMetadata = $asset.sourceMetadata,
            asset.createdAt = coalesce(asset.createdAt, datetime())
        MERGE (p)-[:HAS_ORIGINAL_ASSET]->(asset)
        SET p.updatedAt = datetime()
        RETURN asset.id AS id
        """
        self._driver.execute_query(
            cypher,
            project_id=asset.project_id,
            asset=params,
            **self._query_config,
        )
        return asset

    def resolve_scoped_target(
        self,
        project_id: str,
        document_version_id: str,
        node_type: str,
        node_id: str | None = None,
        publication_identifier: str | None = None,
    ) -> dict[str, str] | None:
        path = _TARGET_PATHS.get(node_type)
        if path is None:
            raise ValueError("Unsupported provenance target type")
        if not node_id and not publication_identifier:
            raise ValueError("A target nodeId or publication identifier is required")
        predicate = "target.id = $node_id" if node_id else "(toString(target.number) = $publication_identifier OR target.raw_identifier = $publication_identifier)"
        cypher = f"""
        MATCH (p:Project {{id: $project_id}})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(v:DocumentVersion {{id: $document_version_id}})
        MATCH {path}
        WHERE {predicate}
        RETURN target.id AS id, labels(target)[0] AS label
        LIMIT 2
        """
        records, _, _ = self._driver.execute_query(
            cypher,
            project_id=project_id,
            document_version_id=document_version_id,
            node_id=node_id,
            publication_identifier=publication_identifier,
            **self._query_config,
        )
        rows = [dict(row) for row in records]
        if len(rows) != 1:
            return None
        return {"id": str(rows[0]["id"]), "label": str(rows[0]["label"])}

    def link_derived_from(
        self,
        project_id: str,
        target_label: str,
        target_id: str,
        asset_id: str,
        *,
        method: str,
        manifest_sha256: str,
    ) -> None:
        if method != "manifest_mapping":
            raise ValueError("Automated provenance requires manifest_mapping")
        path = _TARGET_PATHS.get(target_label)
        if path is None:
            raise ValueError("Unsupported provenance target type")
        cypher = f"""
        MATCH (p:Project {{id: $project_id}})-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset {{id: $asset_id}})
        WHERE asset.projectId = $project_id
        MATCH (p)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(v:DocumentVersion)
        MATCH {path}
        WHERE target.id = $target_id
        MERGE (target)-[rel:DERIVED_FROM]->(asset)
        SET rel.method = $method,
            rel.status = 'declared',
            rel.manifestSha256 = $manifest_sha256,
            rel.createdAt = coalesce(rel.createdAt, datetime()),
            asset.provenanceStatus = 'declared',
            p.updatedAt = datetime()
        """
        self._driver.execute_query(
            cypher,
            project_id=project_id,
            target_id=target_id,
            asset_id=asset_id,
            method=method,
            manifest_sha256=manifest_sha256,
            **self._query_config,
        )
