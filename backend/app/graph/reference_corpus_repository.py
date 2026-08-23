from __future__ import annotations

from typing import Any, Iterable
from uuid import uuid4

from neo4j import Driver

from app.domain.canonical_models import (
    DrawingData,
    DrawingRegionData,
    EvidenceLevel,
    PlateData,
    PlatePanelData,
)
from app.domain.reference_corpus import (
    DerivedArtifactData,
    ReferenceCorpusData,
    ReferenceCorpusFailureCode,
    ReferenceCorpusStatus,
)


_ALLOWED_SOURCE_ROLES = {"plate_layout", "plate_pdf", "plate_link", "drawing_source"}
_ALLOWED_TRANSITIONS: dict[ReferenceCorpusStatus, set[ReferenceCorpusStatus]] = {
    ReferenceCorpusStatus.STAGING: {
        ReferenceCorpusStatus.CONVERTING,
        ReferenceCorpusStatus.FAILED,
    },
    ReferenceCorpusStatus.CONVERTING: {
        ReferenceCorpusStatus.VALIDATING,
        ReferenceCorpusStatus.FAILED,
    },
    ReferenceCorpusStatus.VALIDATING: {
        ReferenceCorpusStatus.CANONICALIZING,
        ReferenceCorpusStatus.FAILED,
    },
    ReferenceCorpusStatus.CANONICALIZING: {
        ReferenceCorpusStatus.GRAPH_VALIDATING,
        ReferenceCorpusStatus.FAILED,
    },
    ReferenceCorpusStatus.GRAPH_VALIDATING: {
        ReferenceCorpusStatus.READY,
        ReferenceCorpusStatus.FAILED,
    },
    ReferenceCorpusStatus.READY: set(),
    ReferenceCorpusStatus.FAILED: set(),
}


class ReferenceCorpusRepository:
    """Project-rooted persistence for immutable reference-corpus revisions.

    Canonical identity and source provenance are corpus-scoped. Evidence is
    explicitly graded; only an ``unresolved`` panel/region may omit a source
    edge. This lets the Adobe-free path remain conservative without inventing a
    JPG/AI relationship, while legacy/direct objects retain the stricter source
    requirement.
    """

    def __init__(self, driver: Driver, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @property
    def _query_config(self) -> dict[str, str]:
        return {"database_": self._database} if self._database else {}

    @staticmethod
    def _failure(value: Any) -> ReferenceCorpusFailureCode | str | None:
        if value in (None, ""):
            return None
        text = str(value)
        try:
            return ReferenceCorpusFailureCode(text)
        except ValueError:
            return text

    @staticmethod
    def _evidence(value: EvidenceLevel | str) -> str:
        return value.value if isinstance(value, EvidenceLevel) else str(value)

    @staticmethod
    def _edge_status(value: EvidenceLevel | str) -> str:
        evidence = ReferenceCorpusRepository._evidence(value)
        if evidence in {EvidenceLevel.DIRECT.value, EvidenceLevel.DERIVED_VERIFIED.value}:
            return "verified"
        if evidence == EvidenceLevel.HEURISTIC.value:
            return "candidate"
        return "unresolved"

    @classmethod
    def _corpus_from_row(cls, row: Any) -> ReferenceCorpusData:
        return ReferenceCorpusData(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            revision=int(row["revision"]),
            status=ReferenceCorpusStatus(str(row["status"])),
            source_set_hash=str(row.get("source_set_hash") or ""),
            converter_version=str(row.get("converter_version") or ""),
            manifest_schema_version=str(row.get("manifest_schema_version") or ""),
            canonicalizer_version=str(row.get("canonicalizer_version") or ""),
            build_identity=str(row.get("build_identity") or ""),
            created_at=row.get("created_at"),
            ready_at=row.get("ready_at"),
            failure_code=cls._failure(row.get("failure_code")),
        )

    @staticmethod
    def _corpus_projection(alias: str = "c") -> str:
        return f"""
            {alias}.id AS id,
            {alias}.projectId AS project_id,
            {alias}.revision AS revision,
            {alias}.status AS status,
            coalesce({alias}.sourceSetHash, '') AS source_set_hash,
            coalesce({alias}.converterVersion, '') AS converter_version,
            coalesce({alias}.manifestSchemaVersion, '') AS manifest_schema_version,
            coalesce({alias}.canonicalizerVersion, '') AS canonicalizer_version,
            coalesce({alias}.buildIdentity, '') AS build_identity,
            toString({alias}.createdAt) AS created_at,
            toString({alias}.readyAt) AS ready_at,
            {alias}.failureCode AS failure_code
        """

    def create_staging(
        self,
        project_id: str,
        *,
        corpus_id: str | None = None,
        revision: int | None = None,
    ) -> ReferenceCorpusData:
        corpus_id = corpus_id or str(uuid4())
        projection = self._corpus_projection("c")
        records, _, _ = self._driver.execute_query(
            f"""
            MATCH (p:Project {{id: $project_id}})
            OPTIONAL MATCH (p)-[:HAS_REFERENCE_CORPUS]->(existing:ReferenceCorpus)
            WITH p, coalesce(max(existing.revision), 0) AS max_revision
            WITH p, CASE WHEN $revision IS NULL THEN max_revision + 1 ELSE $revision END AS selected_revision
            OPTIONAL MATCH (p)-[:HAS_REFERENCE_CORPUS]->(duplicate:ReferenceCorpus)
            WHERE duplicate.revision = selected_revision OR duplicate.id = $corpus_id
            WITH p, selected_revision, collect(duplicate) AS duplicates
            WHERE size([item IN duplicates WHERE item IS NOT NULL]) = 0
            CREATE (c:ReferenceCorpus {{
                id: $corpus_id,
                projectId: $project_id,
                revision: selected_revision,
                status: 'staging',
                sourceSetHash: '',
                converterVersion: '',
                manifestSchemaVersion: '',
                canonicalizerVersion: '',
                buildIdentity: '',
                failureCode: null,
                createdAt: datetime(),
                readyAt: null
            }})
            MERGE (p)-[:HAS_REFERENCE_CORPUS]->(c)
            WITH p, c
            OPTIONAL MATCH (p)-[:HAS_REFERENCE_CORPUS]->(prev:ReferenceCorpus)
            WHERE prev.id <> c.id AND prev.revision = c.revision - 1
            FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END |
                MERGE (prev)-[:PRECEDES]->(c)
            )
            RETURN {projection}
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            revision=revision,
            **self._query_config,
        )
        if not records:
            raise ValueError("reference corpus project/revision is invalid")
        return self._corpus_from_row(records[0])

    def get(self, project_id: str, corpus_id: str) -> ReferenceCorpusData | None:
        projection = self._corpus_projection("c")
        records, _, _ = self._driver.execute_query(
            f"""
            MATCH (p:Project {{id: $project_id}})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {{id: $corpus_id}})
            WHERE c.projectId = $project_id
            RETURN {projection}
            LIMIT 1
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            **self._query_config,
        )
        return self._corpus_from_row(records[0]) if records else None

    def list_for_project(self, project_id: str) -> list[ReferenceCorpusData]:
        projection = self._corpus_projection("c")
        records, _, _ = self._driver.execute_query(
            f"""
            MATCH (p:Project {{id: $project_id}})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus)
            WHERE c.projectId = $project_id
            RETURN {projection}
            ORDER BY c.revision ASC, c.id ASC
            """,
            project_id=project_id,
            **self._query_config,
        )
        return [self._corpus_from_row(row) for row in records]

    def _require_mutable(self, project_id: str, corpus_id: str) -> ReferenceCorpusData:
        corpus = self.get(project_id, corpus_id)
        if corpus is None:
            raise ValueError("reference corpus does not belong to project")
        if corpus.status == ReferenceCorpusStatus.READY:
            raise ValueError("READY reference corpus is immutable")
        return corpus

    def attach_source(
        self,
        project_id: str,
        corpus_id: str,
        source_asset_id: str,
        role: str,
    ) -> None:
        if role not in _ALLOWED_SOURCE_ROLES:
            raise ValueError(f"unsupported reference corpus source role: {role}")
        self._require_mutable(project_id, corpus_id)
        records, _, _ = self._driver.execute_query(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (p)-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset {id: $source_asset_id})
            WHERE c.projectId = $project_id AND asset.projectId = $project_id
            MERGE (c)-[rel:USES_SOURCE]->(asset)
            SET rel.role = $role,
                rel.attachedAt = coalesce(rel.attachedAt, datetime())
            RETURN asset.id AS id
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            source_asset_id=source_asset_id,
            role=role,
            **self._query_config,
        )
        if not records:
            raise ValueError("source asset is not owned by project")

    def list_sources(self, project_id: str, corpus_id: str) -> list[dict[str, Any]]:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (c)-[rel:USES_SOURCE]->(asset:OriginalAsset)
            WHERE c.projectId = $project_id AND asset.projectId = $project_id
            RETURN asset.id AS id,
                   rel.role AS role,
                   asset.uri AS uri,
                   asset.sha256 AS sha256,
                   asset.sizeBytes AS size_bytes,
                   asset.mimeType AS mime_type,
                   asset.originalName AS original_name,
                   asset.relativePath AS relative_path,
                   asset.assetKind AS asset_kind,
                   asset.sourceRootName AS source_root_name,
                   asset.importBatchId AS import_batch_id,
                   asset.parseStatus AS parse_status,
                   asset.provenanceStatus AS provenance_status,
                   toString(asset.createdAt) AS created_at,
                   asset.sourceMetadataJson AS source_metadata_json
            ORDER BY rel.role ASC, asset.id ASC
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            **self._query_config,
        )
        return [dict(row) for row in records]

    def _attached_source_ids(
        self,
        project_id: str,
        corpus_id: str,
        source_ids: Iterable[str],
    ) -> set[str]:
        wanted = sorted({item for item in source_ids if item})
        if not wanted:
            return set()
        records, _, _ = self._driver.execute_query(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (c)-[:USES_SOURCE]->(asset:OriginalAsset)
            WHERE c.projectId = $project_id
              AND asset.projectId = $project_id
              AND asset.id IN $source_ids
            RETURN collect(DISTINCT asset.id) AS ids
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            source_ids=wanted,
            **self._query_config,
        )
        if not records:
            return set()
        return {str(item) for item in (records[0].get("ids") or [])}

    def save_artifact(
        self,
        project_id: str,
        corpus_id: str,
        artifact: DerivedArtifactData,
    ) -> None:
        self._require_mutable(project_id, corpus_id)
        if artifact.reference_corpus_id != corpus_id:
            raise ValueError("artifact reference corpus does not match corpus")
        if artifact.source_asset_id:
            attached = self._attached_source_ids(
                project_id, corpus_id, [artifact.source_asset_id]
            )
            if artifact.source_asset_id not in attached:
                raise ValueError(
                    "artifact source provenance is not attached to project corpus"
                )
        payload = {
            "id": artifact.id,
            "referenceCorpusId": corpus_id,
            "artifactType": artifact.artifact_type,
            "uri": artifact.uri,
            "sha256": artifact.sha256,
            "mimeType": artifact.mime_type,
            "sourceAssetId": artifact.source_asset_id,
            "converterVersion": artifact.converter_version,
        }
        records, _, _ = self._driver.execute_query(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            WHERE c.projectId = $project_id AND c.status <> 'ready'
            OPTIONAL MATCH (c)-[:USES_SOURCE]->(source:OriginalAsset {id: $artifact.sourceAssetId})
            WITH c, source
            WHERE $artifact.sourceAssetId IS NULL OR source IS NOT NULL
            MERGE (a:DerivedArtifact {id: $artifact.id})
            WITH c, source, a
            WHERE a.referenceCorpusId IS NULL OR a.referenceCorpusId = $corpus_id
            SET a.referenceCorpusId = $artifact.referenceCorpusId,
                a.artifactType = $artifact.artifactType,
                a.uri = $artifact.uri,
                a.sha256 = $artifact.sha256,
                a.mimeType = $artifact.mimeType,
                a.sourceAssetId = $artifact.sourceAssetId,
                a.converterVersion = $artifact.converterVersion,
                a.createdAt = coalesce(a.createdAt, datetime())
            MERGE (c)-[:HAS_ARTIFACT]->(a)
            FOREACH (_ IN CASE WHEN source IS NULL THEN [] ELSE [1] END |
                MERGE (a)-[:DERIVED_FROM]->(source)
            )
            RETURN a.id AS id
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            artifact=payload,
            **self._query_config,
        )
        if not records:
            raise ValueError("artifact corpus/project provenance is invalid")

    def transition_status(
        self,
        project_id: str,
        corpus_id: str,
        status: ReferenceCorpusStatus | str,
        *,
        source_set_hash: str | None = None,
        converter_version: str | None = None,
        manifest_schema_version: str | None = None,
        canonicalizer_version: str | None = None,
        build_identity: str | None = None,
        failure_code: ReferenceCorpusFailureCode | str | None = None,
    ) -> ReferenceCorpusData:
        target = ReferenceCorpusStatus(status)
        current = self.get(project_id, corpus_id)
        if current is None:
            raise ValueError("reference corpus does not belong to project")
        if current.status == target:
            return current
        if current.status == ReferenceCorpusStatus.READY:
            raise ValueError("READY reference corpus is immutable")
        if target not in _ALLOWED_TRANSITIONS[current.status]:
            raise ValueError(
                f"invalid reference corpus status transition: {current.status.value}->{target.value}"
            )
        failure_value = (
            failure_code.value
            if isinstance(failure_code, ReferenceCorpusFailureCode)
            else failure_code
        )
        projection = self._corpus_projection("c")
        records, _, _ = self._driver.execute_query(
            f"""
            MATCH (p:Project {{id: $project_id}})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {{id: $corpus_id}})
            WHERE c.projectId = $project_id AND c.status = $expected_status
            SET c.status = $status,
                c.sourceSetHash = CASE WHEN $source_set_hash IS NULL THEN c.sourceSetHash ELSE $source_set_hash END,
                c.converterVersion = CASE WHEN $converter_version IS NULL THEN c.converterVersion ELSE $converter_version END,
                c.manifestSchemaVersion = CASE WHEN $manifest_schema_version IS NULL THEN c.manifestSchemaVersion ELSE $manifest_schema_version END,
                c.canonicalizerVersion = CASE WHEN $canonicalizer_version IS NULL THEN c.canonicalizerVersion ELSE $canonicalizer_version END,
                c.buildIdentity = CASE WHEN $build_identity IS NULL THEN c.buildIdentity ELSE $build_identity END,
                c.failureCode = CASE WHEN $status = 'failed' THEN $failure_code ELSE null END,
                c.readyAt = CASE WHEN $status = 'ready' THEN datetime() ELSE c.readyAt END
            RETURN {projection}
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            expected_status=current.status.value,
            status=target.value,
            source_set_hash=source_set_hash,
            converter_version=converter_version,
            manifest_schema_version=manifest_schema_version,
            canonicalizer_version=canonicalizer_version,
            build_identity=build_identity,
            failure_code=failure_value,
            **self._query_config,
        )
        if not records:
            raise ValueError("reference corpus status changed concurrently")
        return self._corpus_from_row(records[0])

    def find_ready_by_build_identity(
        self, project_id: str, build_identity: str
    ) -> ReferenceCorpusData | None:
        projection = self._corpus_projection("c")
        records, _, _ = self._driver.execute_query(
            f"""
            MATCH (p:Project {{id: $project_id}})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus)
            WHERE c.projectId = $project_id
              AND c.status = 'ready'
              AND c.buildIdentity = $build_identity
            RETURN {projection}
            ORDER BY c.revision DESC
            LIMIT 1
            """,
            project_id=project_id,
            build_identity=build_identity,
            **self._query_config,
        )
        return self._corpus_from_row(records[0]) if records else None

    @classmethod
    def _plate_payload(cls, plate: PlateData) -> dict[str, Any]:
        evidence = cls._evidence(plate.evidence_level)
        return {
            "id": plate.plate_id,
            "number": plate.number,
            "physical_page": plate.physical_page,
            "title": plate.title,
            "bbox": list(plate.bbox) if plate.bbox is not None else None,
            "source_sha256": plate.source_sha256,
            "raw_identifier": plate.raw_identifier,
            "source_kind": plate.source_kind,
            "reference_corpus_id": plate.reference_corpus_id,
            "source_asset_id": plate.source_asset_id,
            "evidence_level": evidence,
            "evidence_method": plate.evidence_method,
            "edge_status": cls._edge_status(evidence),
        }

    @classmethod
    def _panel_payload(cls, panel: PlatePanelData) -> dict[str, Any]:
        evidence = cls._evidence(panel.evidence_level)
        return {
            "id": panel.panel_id,
            "plate_id": panel.plate_id,
            "panel_index": panel.panel_index,
            "caption": panel.caption,
            "bbox": list(panel.bbox) if panel.bbox is not None else None,
            "bbox_status": panel.bbox_status,
            "physical_page": panel.physical_page,
            "render_uri": panel.render_uri,
            "source_sha256": panel.source_sha256,
            "source_asset_id": panel.source_asset_id,
            "evidence_level": evidence,
            "evidence_method": panel.evidence_method,
            "edge_status": cls._edge_status(evidence),
        }

    @classmethod
    def _drawing_payload(cls, drawing: DrawingData) -> dict[str, Any]:
        evidence = cls._evidence(drawing.evidence_level)
        return {
            "id": drawing.drawing_id,
            "number": drawing.number,
            "physical_page": drawing.physical_page,
            "title": drawing.title,
            "bbox": list(drawing.bbox) if drawing.bbox is not None else None,
            "source_sha256": drawing.source_sha256,
            "raw_identifier": drawing.raw_identifier,
            "source_kind": drawing.source_kind,
            "reference_corpus_id": drawing.reference_corpus_id,
            "source_asset_id": drawing.source_asset_id,
            "evidence_level": evidence,
            "evidence_method": drawing.evidence_method,
            "edge_status": cls._edge_status(evidence),
        }

    @classmethod
    def _region_payload(cls, region: DrawingRegionData) -> dict[str, Any]:
        evidence = cls._evidence(region.evidence_level)
        return {
            "id": region.region_id,
            "drawing_id": region.drawing_id,
            "number": region.number,
            "title": region.title,
            "bbox": list(region.bbox) if region.bbox is not None else None,
            "bbox_status": region.bbox_status,
            "physical_page": region.physical_page,
            "render_uri": region.render_uri,
            "source_sha256": region.source_sha256,
            "source_asset_id": region.source_asset_id,
            "evidence_level": evidence,
            "evidence_method": region.evidence_method,
            "edge_status": cls._edge_status(evidence),
        }

    @classmethod
    def _validate_child_provenance(cls, item: PlatePanelData | DrawingRegionData) -> None:
        evidence = cls._evidence(item.evidence_level)
        if evidence == EvidenceLevel.UNRESOLVED.value:
            if item.source_asset_id is not None:
                raise ValueError("unresolved visual provenance cannot declare a source asset")
            return
        if item.source_asset_id is None:
            raise ValueError("canonical visual provenance is incomplete")

    def save_canonical_visuals(
        self,
        project_id: str,
        corpus_id: str,
        *,
        plates: list[PlateData],
        drawings: list[DrawingData],
    ) -> None:
        self._require_mutable(project_id, corpus_id)
        for visual in [*plates, *drawings]:
            if visual.reference_corpus_id != corpus_id:
                raise ValueError(
                    "canonical visual reference corpus does not match corpus"
                )
            if visual.document_version_id is not None:
                raise ValueError(
                    "corpus canonical visual cannot use legacy DocumentVersion ownership"
                )

        panels = [panel for plate in plates for panel in plate.panels]
        regions = [region for drawing in drawings for region in drawing.regions]
        for item in [*panels, *regions]:
            self._validate_child_provenance(item)

        provenance_ids = [
            item.source_asset_id
            for item in [*plates, *drawings, *panels, *regions]
            if item.source_asset_id
        ]
        attached = self._attached_source_ids(project_id, corpus_id, provenance_ids)
        missing = sorted(set(provenance_ids) - attached)
        if missing:
            raise ValueError(
                "canonical visual provenance source is outside project corpus"
            )

        if plates:
            payloads = [self._plate_payload(item) for item in plates]
            records, _, _ = self._driver.execute_query(
                """
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                WHERE c.projectId = $project_id AND c.status <> 'ready'
                UNWIND $plates AS item
                OPTIONAL MATCH (c)-[:USES_SOURCE]->(source:OriginalAsset {id: item.source_asset_id})
                WITH c, source, item
                WHERE item.source_asset_id IS NULL OR source IS NOT NULL
                MERGE (plate:Plate {id: item.id})
                WITH c, source, plate, item
                WHERE plate.referenceCorpusId IS NULL OR plate.referenceCorpusId = $corpus_id
                SET plate.number = item.number,
                    plate.physical_page = item.physical_page,
                    plate.title = item.title,
                    plate.bbox = item.bbox,
                    plate.source_sha256 = item.source_sha256,
                    plate.raw_identifier = item.raw_identifier,
                    plate.source_kind = item.source_kind,
                    plate.referenceCorpusId = $corpus_id,
                    plate.sourceAssetId = item.source_asset_id,
                    plate.evidenceLevel = item.evidence_level,
                    plate.evidenceMethod = item.evidence_method
                MERGE (c)-[:HAS_PLATE]->(plate)
                FOREACH (_ IN CASE WHEN source IS NULL THEN [] ELSE [1] END |
                    MERGE (plate)-[derived:DERIVED_FROM]->(source)
                    SET derived.method = item.evidence_method,
                        derived.status = item.edge_status,
                        derived.referenceCorpusId = $corpus_id,
                        derived.createdAt = coalesce(derived.createdAt, datetime()),
                        source.provenanceStatus = item.edge_status
                )
                RETURN count(plate) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                plates=payloads,
                **self._query_config,
            )
            if not records or int(records[0]["saved"]) != len(plates):
                raise ValueError("plate corpus identity conflicts with existing graph")

        if panels:
            payloads = [self._panel_payload(item) for item in panels]
            records, _, _ = self._driver.execute_query(
                """
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                WHERE c.projectId = $project_id AND c.status <> 'ready'
                UNWIND $panels AS item
                MATCH (c)-[:HAS_PLATE]->(plate:Plate {id: item.plate_id})
                OPTIONAL MATCH (c)-[:USES_SOURCE]->(source:OriginalAsset {id: item.source_asset_id})
                WITH c, plate, source, item
                WHERE (item.evidence_level = 'unresolved' AND item.source_asset_id IS NULL)
                   OR (item.evidence_level <> 'unresolved' AND item.source_asset_id IS NOT NULL AND source IS NOT NULL)
                MERGE (panel:PlatePanel {id: item.id})
                WITH c, plate, source, panel, item
                WHERE panel.plate_id IS NULL OR panel.plate_id = item.plate_id
                SET panel.plate_id = item.plate_id,
                    panel.panel_index = item.panel_index,
                    panel.caption = item.caption,
                    panel.bbox = item.bbox,
                    panel.bbox_status = item.bbox_status,
                    panel.physical_page = item.physical_page,
                    panel.render_uri = item.render_uri,
                    panel.source_sha256 = item.source_sha256,
                    panel.sourceAssetId = item.source_asset_id,
                    panel.evidenceLevel = item.evidence_level,
                    panel.evidenceMethod = item.evidence_method
                MERGE (plate)-[:HAS_PANEL]->(panel)
                FOREACH (_ IN CASE WHEN source IS NULL THEN [] ELSE [1] END |
                    MERGE (panel)-[derived:DERIVED_FROM]->(source)
                    SET derived.method = item.evidence_method,
                        derived.status = item.edge_status,
                        derived.referenceCorpusId = $corpus_id,
                        derived.createdAt = coalesce(derived.createdAt, datetime()),
                        source.provenanceStatus = item.edge_status
                )
                RETURN count(panel) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                panels=payloads,
                **self._query_config,
            )
            if not records or int(records[0]["saved"]) != len(panels):
                raise ValueError(
                    "plate panel provenance conflicts with existing graph"
                )

        if drawings:
            payloads = [self._drawing_payload(item) for item in drawings]
            records, _, _ = self._driver.execute_query(
                """
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                WHERE c.projectId = $project_id AND c.status <> 'ready'
                UNWIND $drawings AS item
                OPTIONAL MATCH (c)-[:USES_SOURCE]->(source:OriginalAsset {id: item.source_asset_id})
                WITH c, source, item
                WHERE item.source_asset_id IS NULL OR source IS NOT NULL
                MERGE (drawing:Drawing {id: item.id})
                WITH c, source, drawing, item
                WHERE drawing.referenceCorpusId IS NULL OR drawing.referenceCorpusId = $corpus_id
                SET drawing.number = item.number,
                    drawing.physical_page = item.physical_page,
                    drawing.title = item.title,
                    drawing.bbox = item.bbox,
                    drawing.source_sha256 = item.source_sha256,
                    drawing.raw_identifier = item.raw_identifier,
                    drawing.source_kind = item.source_kind,
                    drawing.referenceCorpusId = $corpus_id,
                    drawing.sourceAssetId = item.source_asset_id,
                    drawing.evidenceLevel = item.evidence_level,
                    drawing.evidenceMethod = item.evidence_method
                MERGE (c)-[:HAS_DRAWING]->(drawing)
                FOREACH (_ IN CASE WHEN source IS NULL THEN [] ELSE [1] END |
                    MERGE (drawing)-[derived:DERIVED_FROM]->(source)
                    SET derived.method = item.evidence_method,
                        derived.status = item.edge_status,
                        derived.referenceCorpusId = $corpus_id,
                        derived.createdAt = coalesce(derived.createdAt, datetime()),
                        source.provenanceStatus = item.edge_status
                )
                RETURN count(drawing) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                drawings=payloads,
                **self._query_config,
            )
            if not records or int(records[0]["saved"]) != len(drawings):
                raise ValueError(
                    "drawing corpus identity conflicts with existing graph"
                )

        if regions:
            payloads = [self._region_payload(item) for item in regions]
            records, _, _ = self._driver.execute_query(
                """
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                WHERE c.projectId = $project_id AND c.status <> 'ready'
                UNWIND $regions AS item
                MATCH (c)-[:HAS_DRAWING]->(drawing:Drawing {id: item.drawing_id})
                OPTIONAL MATCH (c)-[:USES_SOURCE]->(source:OriginalAsset {id: item.source_asset_id})
                WITH c, drawing, source, item
                WHERE (item.evidence_level = 'unresolved' AND item.source_asset_id IS NULL)
                   OR (item.evidence_level <> 'unresolved' AND item.source_asset_id IS NOT NULL AND source IS NOT NULL)
                MERGE (region:DrawingRegion {id: item.id})
                WITH c, drawing, source, region, item
                WHERE region.drawing_id IS NULL OR region.drawing_id = item.drawing_id
                SET region.drawing_id = item.drawing_id,
                    region.number = item.number,
                    region.title = item.title,
                    region.bbox = item.bbox,
                    region.bbox_status = item.bbox_status,
                    region.physical_page = item.physical_page,
                    region.render_uri = item.render_uri,
                    region.source_sha256 = item.source_sha256,
                    region.sourceAssetId = item.source_asset_id,
                    region.evidenceLevel = item.evidence_level,
                    region.evidenceMethod = item.evidence_method
                MERGE (drawing)-[:HAS_REGION]->(region)
                FOREACH (_ IN CASE WHEN source IS NULL THEN [] ELSE [1] END |
                    MERGE (region)-[derived:DERIVED_FROM]->(source)
                    SET derived.method = item.evidence_method,
                        derived.status = item.edge_status,
                        derived.referenceCorpusId = $corpus_id,
                        derived.createdAt = coalesce(derived.createdAt, datetime()),
                        source.provenanceStatus = item.edge_status
                )
                RETURN count(region) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                regions=payloads,
                **self._query_config,
            )
            if not records or int(records[0]["saved"]) != len(regions):
                raise ValueError(
                    "drawing region provenance conflicts with existing graph"
                )

    def _scalar_count(self, query: str, **params: Any) -> int:
        records, _, _ = self._driver.execute_query(
            query, **params, **self._query_config
        )
        if not records:
            return 0
        return int(records[0].get("count") or 0)

    def validate_ready_graph(self, project_id: str, corpus_id: str) -> bool:
        if self.get(project_id, corpus_id) is None:
            return False
        common = {"project_id": project_id, "corpus_id": corpus_id}
        visual_count = self._scalar_count(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            OPTIONAL MATCH (c)-[:HAS_PLATE|HAS_DRAWING]->(visual)
            RETURN count(DISTINCT visual) AS count
            """,
            **common,
        )
        artifact_count = self._scalar_count(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            OPTIONAL MATCH (c)-[:HAS_ARTIFACT]->(artifact:DerivedArtifact)
            RETURN count(DISTINCT artifact) AS count
            """,
            **common,
        )
        bad_visual_count = self._scalar_count(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (c)-[:HAS_PLATE|HAS_DRAWING]->(visual)
            WHERE visual.referenceCorpusId IS NULL OR visual.referenceCorpusId <> $corpus_id
            RETURN count(DISTINCT visual) AS count
            """,
            **common,
        )
        cross_project_sources = self._scalar_count(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (c)-[:HAS_PLATE|HAS_DRAWING]->(visual)
            MATCH (visual)-[:DERIVED_FROM]->(source:OriginalAsset)
            WHERE source.projectId <> $project_id
            RETURN count(DISTINCT source) AS count
            UNION ALL
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (c)-[:HAS_PLATE]->(:Plate)-[:HAS_PANEL]->(child:PlatePanel)-[:DERIVED_FROM]->(source:OriginalAsset)
            WHERE source.projectId <> $project_id
            RETURN count(DISTINCT source) AS count
            UNION ALL
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (c)-[:HAS_DRAWING]->(:Drawing)-[:HAS_REGION]->(child:DrawingRegion)-[:DERIVED_FROM]->(source:OriginalAsset)
            WHERE source.projectId <> $project_id
            RETURN count(DISTINCT source) AS count
            """,
            **common,
        )
        bad_visual_provenance = self._scalar_count(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (c)-[:HAS_PLATE|HAS_DRAWING]->(visual)
            OPTIONAL MATCH (visual)-[:DERIVED_FROM]->(source:OriginalAsset)
            WITH visual, collect(DISTINCT source) AS sources
            WHERE (visual.sourceAssetId IS NOT NULL AND none(item IN sources WHERE item IS NOT NULL AND item.id = visual.sourceAssetId AND item.projectId = $project_id))
               OR (visual.evidenceLevel = 'unresolved' AND visual.sourceAssetId IS NOT NULL)
            RETURN count(DISTINCT visual) AS count
            """,
            **common,
        )
        bad_panel_provenance = self._scalar_count(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (c)-[:HAS_PLATE]->(:Plate)-[:HAS_PANEL]->(panel:PlatePanel)
            OPTIONAL MATCH (panel)-[:DERIVED_FROM]->(source:OriginalAsset)
            WITH panel, collect(DISTINCT source) AS sources
            WHERE (panel.evidenceLevel = 'unresolved' AND (panel.sourceAssetId IS NOT NULL OR any(item IN sources WHERE item IS NOT NULL)))
               OR (coalesce(panel.evidenceLevel, 'direct') <> 'unresolved' AND (panel.sourceAssetId IS NULL OR none(item IN sources WHERE item IS NOT NULL AND item.id = panel.sourceAssetId AND item.projectId = $project_id)))
            RETURN count(DISTINCT panel) AS count
            """,
            **common,
        )
        bad_region_provenance = self._scalar_count(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (c)-[:HAS_DRAWING]->(:Drawing)-[:HAS_REGION]->(region:DrawingRegion)
            OPTIONAL MATCH (region)-[:DERIVED_FROM]->(source:OriginalAsset)
            WITH region, collect(DISTINCT source) AS sources
            WHERE (region.evidenceLevel = 'unresolved' AND (region.sourceAssetId IS NOT NULL OR any(item IN sources WHERE item IS NOT NULL)))
               OR (coalesce(region.evidenceLevel, 'direct') <> 'unresolved' AND (region.sourceAssetId IS NULL OR none(item IN sources WHERE item IS NOT NULL AND item.id = region.sourceAssetId AND item.projectId = $project_id)))
            RETURN count(DISTINCT region) AS count
            """,
            **common,
        )
        return (
            visual_count > 0
            and artifact_count > 0
            and bad_visual_count == 0
            and cross_project_sources == 0
            and bad_visual_provenance == 0
            and bad_panel_provenance == 0
            and bad_region_provenance == 0
        )
