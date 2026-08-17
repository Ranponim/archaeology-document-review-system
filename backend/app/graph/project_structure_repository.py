from __future__ import annotations

from typing import Any

from neo4j import Driver

from app.api.project_structure_contract import ProjectStructureNodeType
from app.graph.project_repository import ProjectNotFoundError


class ProjectStructureRepository:
    """Read-only, project-scoped view of the canonical Neo4j graph.

    Every persisted-node query starts at Project and traverses ownership edges.
    Client supplied node ids are never matched globally as authority.
    """

    def __init__(self, driver: Driver, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @property
    def _query_config(self) -> dict[str, str]:
        return {"database_": self._database} if self._database else {}

    def _records(self, cypher: str, **params) -> list[dict[str, Any]]:
        records, _, _ = self._driver.execute_query(
            cypher,
            **params,
            **self._query_config,
        )
        return [dict(record) for record in records]

    @staticmethod
    def _derived_parent(node_id: str, expected_prefix: str) -> str:
        prefix = f"{expected_prefix}:"
        if not node_id.startswith(prefix) or len(node_id) <= len(prefix):
            raise ValueError("Invalid project structure node id")
        return node_id[len(prefix) :]

    def project_summary(self, project_id: str) -> dict[str, Any]:
        project_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})
            RETURN p.id AS id, p.name AS name, p.internalCode AS internal_code
            """,
            project_id=project_id,
        )
        if not project_rows:
            raise ProjectNotFoundError(project_id)

        material_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})
            UNWIND ['report_body', 'plate_book', 'drawing_book'] AS wanted_kind
            OPTIONAL MATCH (p)-[:HAS_DOCUMENT]->(d:Document)
            WHERE coalesce(d.kind, 'report_body') = wanted_kind
            OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:DocumentVersion)
            OPTIONAL MATCH (run:AnalysisRun)-[:ANALYZES]->(v)
            OPTIONAL MATCH (v)-[:HAS_PAGE]->(page:Page)
            OPTIONAL MATCH (v)-[:HAS_PLATE]->(plate:Plate)
            OPTIONAL MATCH (plate)-[:HAS_PANEL]->(panel:PlatePanel)
            OPTIONAL MATCH (v)-[:HAS_DRAWING]->(drawing:Drawing)
            OPTIONAL MATCH (drawing)-[:HAS_REGION]->(region:DrawingRegion)
            RETURN wanted_kind AS kind,
                   count(DISTINCT d) AS document_count,
                   count(DISTINCT v) AS version_count,
                   count(DISTINCT CASE WHEN run.status = 'completed' THEN v END) AS completed_count,
                   count(DISTINCT page) AS page_count,
                   count(DISTINCT plate) AS plate_count,
                   count(DISTINCT panel) AS panel_count,
                   count(DISTINCT drawing) AS drawing_count,
                   count(DISTINCT region) AS region_count
            ORDER BY wanted_kind
            """,
            project_id=project_id,
        )
        count_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})
            OPTIONAL MATCH (p)-[:HAS_REVIEW_ROUND]->(round:ReviewRound)
            WITH p, count(DISTINCT round) AS review_round_count
            OPTIONAL MATCH (p)-[:HAS_OBJECT]->(obj:ArchaeologyObject)
            RETURN review_round_count, count(DISTINCT obj) AS object_count
            """,
            project_id=project_id,
        )
        counts = count_rows[0] if count_rows else {"review_round_count": 0, "object_count": 0}
        asset_rows = self._records(
            "MATCH (:Project {id: $project_id})-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset) RETURN count(asset) AS total",
            project_id=project_id,
        )
        return {
            **project_rows[0],
            "materials": material_rows,
            "review_round_count": int(counts.get("review_round_count") or 0),
            "object_count": int(counts.get("object_count") or 0),
            "original_asset_count": int(asset_rows[0].get("total") or 0) if asset_rows else 0,
        }

    def list_children(
        self,
        project_id: str,
        node_type: ProjectStructureNodeType,
        node_id: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        if node_type == ProjectStructureNodeType.material_group:
            kind = self._derived_parent(node_id, "material")
            if kind not in {"report_body", "plate_book", "drawing_book"}:
                raise ValueError("Unknown material group")
            return self._list_documents(project_id, kind, offset, limit)
        if node_type == ProjectStructureNodeType.document:
            return self._list_versions(project_id, node_id, offset, limit)
        if node_type == ProjectStructureNodeType.document_version:
            return self._version_groups(project_id, node_id)
        if node_type == ProjectStructureNodeType.page_group:
            version_id = self._derived_parent(node_id, "pages")
            return self._list_pages(project_id, version_id, offset, limit)
        if node_type == ProjectStructureNodeType.page:
            return self._page_groups(project_id, node_id)
        if node_type == ProjectStructureNodeType.textblock_group:
            page_id = self._derived_parent(node_id, "textblocks")
            return self._list_text_blocks(project_id, page_id, offset, limit)
        if node_type == ProjectStructureNodeType.caption_group:
            page_id = self._derived_parent(node_id, "captions")
            return self._list_captions(project_id, page_id, offset, limit)
        if node_type == ProjectStructureNodeType.reference_group:
            page_id = self._derived_parent(node_id, "references")
            return self._list_references(project_id, page_id, offset, limit)
        if node_type == ProjectStructureNodeType.plate_group:
            version_id = self._derived_parent(node_id, "plates")
            return self._list_plates(project_id, version_id, offset, limit)
        if node_type == ProjectStructureNodeType.plate:
            return self._list_panels(project_id, node_id, offset, limit)
        if node_type == ProjectStructureNodeType.panel_group:
            plate_id = self._derived_parent(node_id, "panels")
            return self._list_panels(project_id, plate_id, offset, limit)
        if node_type == ProjectStructureNodeType.drawing_group:
            version_id = self._derived_parent(node_id, "drawings")
            return self._list_drawings(project_id, version_id, offset, limit)
        if node_type == ProjectStructureNodeType.drawing:
            return self._list_regions(project_id, node_id, offset, limit)
        if node_type == ProjectStructureNodeType.region_group:
            drawing_id = self._derived_parent(node_id, "regions")
            return self._list_regions(project_id, drawing_id, offset, limit)
        if node_type == ProjectStructureNodeType.source_asset_group:
            return self._source_kind_groups(project_id)
        if node_type == ProjectStructureNodeType.source_kind_group:
            kind = self._derived_parent(node_id, "source-kind")
            return self._list_original_assets(project_id, kind, offset, limit)
        if node_type == ProjectStructureNodeType.review_round_group:
            return self._list_rounds(project_id, offset, limit)
        if node_type == ProjectStructureNodeType.original_asset:
            rows = self._records(
                """MATCH (p:Project {id: $project_id})-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset {id: $node_id})
                RETURN asset.id AS id, asset.originalName AS original_name, asset.relativePath AS relative_path,
                       asset.assetKind AS asset_kind, asset.parseStatus AS parse_status, asset.provenanceStatus AS provenance_status,
                       asset.uri AS uri, asset.sha256 AS sha256, asset.mimeType AS mime_type, asset.sizeBytes AS size_bytes""",
                project_id=project_id, node_id=node_id,
            )
            if not rows: return None
            rels = self._records(
                """MATCH (p:Project {id: $project_id})-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset {id: $node_id})
                MATCH (p)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(v:DocumentVersion)
                OPTIONAL MATCH (v)-[:HAS_PLATE]->(plate:Plate)
                OPTIONAL MATCH (plate)-[:HAS_PANEL]->(panel:PlatePanel)
                OPTIONAL MATCH (v)-[:HAS_DRAWING]->(drawing:Drawing)
                OPTIONAL MATCH (drawing)-[:HAS_REGION]->(region:DrawingRegion)
                WITH asset, [x IN [plate,panel,drawing,region] WHERE x IS NOT NULL] AS targets
                UNWIND targets AS target
                MATCH (target)-[rel:DERIVED_FROM]->(asset)
                RETURN DISTINCT target.id AS id, labels(target)[0] AS label, rel.method AS method, rel.status AS status""",
                project_id=project_id, node_id=node_id,
            )
            rows[0]['relationships'] = rels
            return rows[0]
        if node_type == ProjectStructureNodeType.review_round:
            return self._round_version_refs(project_id, node_id)
        if node_type == ProjectStructureNodeType.archaeology_object_group:
            return self._list_objects(project_id, offset, limit)
        return [], 0

    def _list_documents(self, project_id: str, kind: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(d:Document)
            WHERE coalesce(d.kind, 'report_body') = $kind
            OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:DocumentVersion)
            WITH d, count(DISTINCT v) AS child_count
            RETURN d.id AS id, coalesce(d.title, d.name, d.id) AS label,
                   coalesce(d.kind, 'report_body') AS kind, child_count
            ORDER BY d.createdAt, d.id
            SKIP $offset LIMIT $limit
            """,
            project_id=project_id,
            kind=kind,
            offset=offset,
            limit=limit,
        )
        total_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(d:Document)
            WHERE coalesce(d.kind, 'report_body') = $kind
            RETURN count(DISTINCT d) AS total
            """,
            project_id=project_id,
            kind=kind,
        )
        return rows, int(total_rows[0]["total"] if total_rows else 0)

    def _list_versions(self, project_id: str, document_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(d:Document {id: $document_id})-[:HAS_VERSION]->(v:DocumentVersion)
            OPTIONAL MATCH (run:AnalysisRun)-[:ANALYZES]->(v)
            OPTIONAL MATCH (v)-[:HAS_PAGE]->(page:Page)
            OPTIONAL MATCH (v)-[:HAS_PLATE]->(plate:Plate)
            OPTIONAL MATCH (v)-[:HAS_DRAWING]->(drawing:Drawing)
            RETURN v.id AS id,
                   v.originalName AS label,
                   coalesce(d.kind, 'report_body') AS kind,
                   v.uri AS uri,
                   v.sha256 AS sha256,
                   v.sizeBytes AS size_bytes,
                   v.mimeType AS mime_type,
                   v.stage AS stage,
                   head(collect(DISTINCT run.status)) AS ingest_status,
                   count(DISTINCT page) AS page_count,
                   count(DISTINCT plate) AS plate_count,
                   count(DISTINCT drawing) AS drawing_count
            ORDER BY v.createdAt, v.id
            SKIP $offset LIMIT $limit
            """,
            project_id=project_id,
            document_id=document_id,
            offset=offset,
            limit=limit,
        )
        total_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(d:Document {id: $document_id})-[:HAS_VERSION]->(v:DocumentVersion)
            RETURN count(v) AS total
            """,
            project_id=project_id,
            document_id=document_id,
        )
        return rows, int(total_rows[0]["total"] if total_rows else 0)

    def _version_groups(self, project_id: str, version_id: str):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(d:Document)-[:HAS_VERSION]->(v:DocumentVersion {id: $version_id})
            OPTIONAL MATCH (v)-[:HAS_PAGE]->(page:Page)
            OPTIONAL MATCH (v)-[:HAS_PLATE]->(plate:Plate)
            OPTIONAL MATCH (v)-[:HAS_DRAWING]->(drawing:Drawing)
            RETURN coalesce(d.kind, 'report_body') AS kind,
                   count(DISTINCT page) AS page_count,
                   count(DISTINCT plate) AS plate_count,
                   count(DISTINCT drawing) AS drawing_count
            """,
            project_id=project_id,
            version_id=version_id,
        )
        if not rows:
            return [], 0
        row = rows[0]
        groups: list[dict[str, Any]] = []
        if int(row.get("page_count") or 0) > 0:
            groups.append({"id": f"pages:{version_id}", "node_type": "page_group", "label": "페이지", "child_count": int(row["page_count"])})
        if int(row.get("plate_count") or 0) > 0:
            groups.append({"id": f"plates:{version_id}", "node_type": "plate_group", "label": "표준 도판", "child_count": int(row["plate_count"])})
        if int(row.get("drawing_count") or 0) > 0:
            groups.append({"id": f"drawings:{version_id}", "node_type": "drawing_group", "label": "표준 도면", "child_count": int(row["drawing_count"])})
        return groups, len(groups)

    def _list_pages(self, project_id: str, version_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(v:DocumentVersion {id: $version_id})-[:HAS_PAGE]->(page:Page)
            OPTIONAL MATCH (page)-[:HAS_BLOCK]->(block:TextBlock)
            OPTIONAL MATCH (page)-[:HAS_CAPTION]->(caption:Caption)
            OPTIONAL MATCH (page)-[:HAS_BLOCK|HAS_CAPTION]->(source)-[:REFERENCES]->(ref:Reference)
            RETURN page.id AS id,
                   page.physical_page AS physical_page,
                   page.printed_page AS printed_page,
                   page.header AS header,
                   count(DISTINCT block) AS block_count,
                   count(DISTINCT caption) AS caption_count,
                   count(DISTINCT ref) AS reference_count
            ORDER BY page.physical_page, page.id
            SKIP $offset LIMIT $limit
            """,
            project_id=project_id,
            version_id=version_id,
            offset=offset,
            limit=limit,
        )
        total_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(v:DocumentVersion {id: $version_id})-[:HAS_PAGE]->(page:Page)
            RETURN count(page) AS total
            """,
            project_id=project_id,
            version_id=version_id,
        )
        return rows, int(total_rows[0]["total"] if total_rows else 0)

    def _page_groups(self, project_id: str, page_id: str):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PAGE]->(page:Page {id: $page_id})
            OPTIONAL MATCH (page)-[:HAS_BLOCK]->(block:TextBlock)
            OPTIONAL MATCH (page)-[:HAS_CAPTION]->(caption:Caption)
            OPTIONAL MATCH (page)-[:HAS_BLOCK|HAS_CAPTION]->(source)-[:REFERENCES]->(ref:Reference)
            RETURN count(DISTINCT block) AS block_count,
                   count(DISTINCT caption) AS caption_count,
                   count(DISTINCT ref) AS reference_count
            """,
            project_id=project_id,
            page_id=page_id,
        )
        if not rows:
            return [], 0
        row = rows[0]
        groups = []
        for prefix, node_type, label, key in (
            ("textblocks", "textblock_group", "본문 블록", "block_count"),
            ("captions", "caption_group", "캡션", "caption_count"),
            ("references", "reference_group", "참조", "reference_count"),
        ):
            count = int(row.get(key) or 0)
            if count:
                groups.append({"id": f"{prefix}:{page_id}", "node_type": node_type, "label": label, "child_count": count})
        return groups, len(groups)

    def _list_text_blocks(self, project_id: str, page_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PAGE]->(page:Page {id: $page_id})-[:HAS_BLOCK]->(node:TextBlock)
            RETURN node.id AS id, node.text AS text, node.normalized_text AS normalized_text, node.order AS ordering
            ORDER BY node.order, node.id SKIP $offset LIMIT $limit
            """,
            project_id=project_id, page_id=page_id, offset=offset, limit=limit,
        )
        total = self._single_count(project_id, page_id, "HAS_BLOCK", "TextBlock")
        return rows, total

    def _list_captions(self, project_id: str, page_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PAGE]->(page:Page {id: $page_id})-[:HAS_CAPTION]->(node:Caption)
            RETURN node.id AS id, node.raw_text AS text, node.plate_number AS plate_number, node.drawing_number AS drawing_number
            ORDER BY node.id SKIP $offset LIMIT $limit
            """,
            project_id=project_id, page_id=page_id, offset=offset, limit=limit,
        )
        total = self._single_count(project_id, page_id, "HAS_CAPTION", "Caption")
        return rows, total

    def _single_count(self, project_id: str, page_id: str, relationship: str, label: str) -> int:
        if relationship not in {"HAS_BLOCK", "HAS_CAPTION"} or label not in {"TextBlock", "Caption"}:
            raise ValueError("Invalid structure relationship")
        rows = self._records(
            f"""
            MATCH (p:Project {{id: $project_id}})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PAGE]->(page:Page {{id: $page_id}})-[:{relationship}]->(node:{label})
            RETURN count(node) AS total
            """,
            project_id=project_id, page_id=page_id,
        )
        return int(rows[0]["total"] if rows else 0)

    def _list_references(self, project_id: str, page_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PAGE]->(page:Page {id: $page_id})
            MATCH (page)-[:HAS_BLOCK|HAS_CAPTION]->(source)-[:REFERENCES]->(ref:Reference)
            RETURN DISTINCT ref.id AS id, ref.ref_type AS ref_type, ref.number AS number, ref.raw_text AS raw_text
            ORDER BY ref.ref_type, ref.number, ref.id SKIP $offset LIMIT $limit
            """,
            project_id=project_id, page_id=page_id, offset=offset, limit=limit,
        )
        total_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PAGE]->(page:Page {id: $page_id})
            MATCH (page)-[:HAS_BLOCK|HAS_CAPTION]->(source)-[:REFERENCES]->(ref:Reference)
            RETURN count(DISTINCT ref) AS total
            """,
            project_id=project_id, page_id=page_id,
        )
        return rows, int(total_rows[0]["total"] if total_rows else 0)

    def _list_plates(self, project_id: str, version_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(v:DocumentVersion {id: $version_id})-[:HAS_PLATE]->(plate:Plate)
            OPTIONAL MATCH (plate)-[:HAS_PANEL]->(panel:PlatePanel)
            RETURN plate.id AS id, plate.number AS number, plate.raw_identifier AS raw_identifier,
                   plate.title AS title, plate.physical_page AS physical_page,
                   count(DISTINCT panel) AS child_count
            ORDER BY plate.number, plate.id SKIP $offset LIMIT $limit
            """,
            project_id=project_id, version_id=version_id, offset=offset, limit=limit,
        )
        total_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion {id: $version_id})-[:HAS_PLATE]->(plate:Plate)
            RETURN count(plate) AS total
            """,
            project_id=project_id, version_id=version_id,
        )
        return rows, int(total_rows[0]["total"] if total_rows else 0)

    def _list_panels(self, project_id: str, plate_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PLATE]->(plate:Plate {id: $plate_id})-[:HAS_PANEL]->(panel:PlatePanel)
            RETURN panel.id AS id, panel.panel_index AS panel_index, panel.caption AS caption,
                   panel.physical_page AS physical_page, panel.render_uri AS render_uri
            ORDER BY panel.panel_index, panel.id SKIP $offset LIMIT $limit
            """,
            project_id=project_id, plate_id=plate_id, offset=offset, limit=limit,
        )
        total_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PLATE]->(plate:Plate {id: $plate_id})-[:HAS_PANEL]->(panel:PlatePanel)
            RETURN count(panel) AS total
            """,
            project_id=project_id, plate_id=plate_id,
        )
        return rows, int(total_rows[0]["total"] if total_rows else 0)

    def _list_drawings(self, project_id: str, version_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(v:DocumentVersion {id: $version_id})-[:HAS_DRAWING]->(drawing:Drawing)
            OPTIONAL MATCH (drawing)-[:HAS_REGION]->(region:DrawingRegion)
            RETURN drawing.id AS id, drawing.number AS number, drawing.raw_identifier AS raw_identifier,
                   drawing.title AS title, drawing.physical_page AS physical_page,
                   count(DISTINCT region) AS child_count
            ORDER BY drawing.number, drawing.id SKIP $offset LIMIT $limit
            """,
            project_id=project_id, version_id=version_id, offset=offset, limit=limit,
        )
        total_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion {id: $version_id})-[:HAS_DRAWING]->(drawing:Drawing)
            RETURN count(drawing) AS total
            """,
            project_id=project_id, version_id=version_id,
        )
        return rows, int(total_rows[0]["total"] if total_rows else 0)

    def _list_regions(self, project_id: str, drawing_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_DRAWING]->(drawing:Drawing {id: $drawing_id})-[:HAS_REGION]->(region:DrawingRegion)
            RETURN region.id AS id, region.number AS number, region.title AS title,
                   region.physical_page AS physical_page, region.render_uri AS render_uri
            ORDER BY region.number, region.id SKIP $offset LIMIT $limit
            """,
            project_id=project_id, drawing_id=drawing_id, offset=offset, limit=limit,
        )
        total_rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_DRAWING]->(drawing:Drawing {id: $drawing_id})-[:HAS_REGION]->(region:DrawingRegion)
            RETURN count(region) AS total
            """,
            project_id=project_id, drawing_id=drawing_id,
        )
        return rows, int(total_rows[0]["total"] if total_rows else 0)

    def _source_kind_groups(self, project_id: str):
        rows = self._records(
            """
            MATCH (:Project {id: $project_id})-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset)
            WITH CASE WHEN asset.assetKind IN ['body_source','drawing_source','layout_source','linked_photo']
                      THEN asset.assetKind ELSE 'other_source' END AS kind, count(asset) AS child_count
            RETURN 'source-kind:' + kind AS id, 'source_kind_group' AS node_type, kind AS asset_kind, child_count
            ORDER BY CASE kind WHEN 'body_source' THEN 1 WHEN 'drawing_source' THEN 2 WHEN 'layout_source' THEN 3 WHEN 'linked_photo' THEN 4 ELSE 5 END
            """, project_id=project_id,
        )
        labels = {'body_source':'본문 원본','drawing_source':'도면 원본','layout_source':'조판 원본','linked_photo':'링크 사진','other_source':'기타'}
        for row in rows: row['label'] = labels.get(row.get('asset_kind'), '기타')
        return rows, len(rows)

    def _list_original_assets(self, project_id: str, kind: str, offset: int, limit: int):
        allowed = {'body_source','drawing_source','layout_source','linked_photo','other_source'}
        if kind not in allowed: raise ValueError('Unknown source kind group')
        condition = "asset.assetKind = $kind" if kind != 'other_source' else "NOT asset.assetKind IN ['body_source','drawing_source','layout_source','linked_photo']"
        rows = self._records(
            f"""MATCH (:Project {{id: $project_id}})-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset)
            WHERE {condition}
            RETURN asset.id AS id, 'original_asset' AS node_type, asset.originalName AS original_name,
                   asset.relativePath AS relative_path, asset.assetKind AS asset_kind, asset.parseStatus AS parse_status,
                   asset.provenanceStatus AS provenance_status, asset.uri AS uri, asset.sha256 AS sha256,
                   asset.mimeType AS mime_type, asset.sizeBytes AS size_bytes
            ORDER BY asset.relativePath, asset.id SKIP $offset LIMIT $limit""",
            project_id=project_id, kind=kind, offset=offset, limit=limit,
        )
        totals = self._records(
            f"MATCH (:Project {{id: $project_id}})-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset) WHERE {condition} RETURN count(asset) AS total",
            project_id=project_id, kind=kind,
        )
        return rows, int(totals[0]['total'] if totals else 0)

    def _list_rounds(self, project_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->(round:ReviewRound)
            OPTIONAL MATCH (previous:ReviewRound)-[:PRECEDES]->(round)
            RETURN round.id AS id, round.sequence AS sequence, round.status AS status,
                   round.notes AS notes, previous.id AS previous_round_id
            ORDER BY round.sequence, round.id SKIP $offset LIMIT $limit
            """,
            project_id=project_id, offset=offset, limit=limit,
        )
        total_rows = self._records(
            "MATCH (:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->(round:ReviewRound) RETURN count(round) AS total",
            project_id=project_id,
        )
        return rows, int(total_rows[0]["total"] if total_rows else 0)

    def _round_version_refs(self, project_id: str, round_id: str):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->(round:ReviewRound {id: $round_id})
            OPTIONAL MATCH (round)-[:USES_BODY_VERSION]->(body:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_PLATE_VERSION]->(plate:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_DRAWING_VERSION]->(drawing:DocumentVersion)
            RETURN body.id AS body_id, body.originalName AS body_name,
                   plate.id AS plate_id, plate.originalName AS plate_name,
                   drawing.id AS drawing_id, drawing.originalName AS drawing_name
            """,
            project_id=project_id, round_id=round_id,
        )
        if not rows:
            return [], 0
        row = rows[0]
        refs = []
        for role, node_id, name in (
            ("본문", row.get("body_id"), row.get("body_name")),
            ("도판 / 사진", row.get("plate_id"), row.get("plate_name")),
            ("도면", row.get("drawing_id"), row.get("drawing_name")),
        ):
            if node_id:
                refs.append({"id": str(node_id), "node_type": "version_reference", "label": f"{role} → {name or node_id}", "target_id": str(node_id), "role": role})
        return refs, len(refs)

    def _list_objects(self, project_id: str, offset: int, limit: int):
        rows = self._records(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_OBJECT]->(obj:ArchaeologyObject)
            RETURN obj.id AS id, obj.canonical_name AS canonical_name, obj.site AS site,
                   obj.period AS period, obj.type AS type, obj.number AS number
            ORDER BY obj.canonical_name, obj.id SKIP $offset LIMIT $limit
            """,
            project_id=project_id, offset=offset, limit=limit,
        )
        total_rows = self._records(
            "MATCH (:Project {id: $project_id})-[:HAS_OBJECT]->(obj:ArchaeologyObject) RETURN count(obj) AS total",
            project_id=project_id,
        )
        return rows, int(total_rows[0]["total"] if total_rows else 0)

    def get_detail(
        self,
        project_id: str,
        node_type: ProjectStructureNodeType,
        node_id: str,
    ) -> dict[str, Any] | None:
        if node_type == ProjectStructureNodeType.project:
            return self.project_summary(project_id) if node_id == project_id else None
        if node_type == ProjectStructureNodeType.document:
            rows = self._records(
                """
                MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(d:Document {id: $node_id})
                OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:DocumentVersion)
                RETURN d.id AS id, coalesce(d.title, d.name, d.id) AS label,
                       coalesce(d.kind, 'report_body') AS kind, count(DISTINCT v) AS child_count
                """,
                project_id=project_id, node_id=node_id,
            )
            return rows[0] if rows else None
        if node_type in {ProjectStructureNodeType.document_version, ProjectStructureNodeType.version_reference}:
            rows = self._records(
                """
                MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(d:Document)-[:HAS_VERSION]->(v:DocumentVersion {id: $node_id})
                OPTIONAL MATCH (run:AnalysisRun)-[:ANALYZES]->(v)
                OPTIONAL MATCH (v)-[:HAS_PAGE]->(page:Page)
                OPTIONAL MATCH (v)-[:HAS_PLATE]->(plate:Plate)
                OPTIONAL MATCH (v)-[:HAS_DRAWING]->(drawing:Drawing)
                RETURN v.id AS id, v.originalName AS label, coalesce(d.kind, 'report_body') AS kind,
                       v.uri AS uri, v.sha256 AS sha256, v.sizeBytes AS size_bytes,
                       v.mimeType AS mime_type, v.stage AS stage,
                       head(collect(DISTINCT run.status)) AS ingest_status,
                       count(DISTINCT page) AS page_count,
                       count(DISTINCT plate) AS plate_count,
                       count(DISTINCT drawing) AS drawing_count
                """,
                project_id=project_id, node_id=node_id,
            )
            return rows[0] if rows else None
        if node_type == ProjectStructureNodeType.page:
            rows = self._records(
                """
                MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(v:DocumentVersion)-[:HAS_PAGE]->(page:Page {id: $node_id})
                RETURN page.id AS id, page.physical_page AS physical_page, page.printed_page AS printed_page,
                       page.header AS header, page.normalized_text AS normalized_text, v.id AS document_version_id
                """,
                project_id=project_id, node_id=node_id,
            )
            return rows[0] if rows else None
        if node_type == ProjectStructureNodeType.reference:
            rows = self._records(
                """
                MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PAGE]->(page:Page)
                MATCH (page)-[:HAS_BLOCK|HAS_CAPTION]->(source)-[:REFERENCES]->(ref:Reference {id: $node_id})
                OPTIONAL MATCH (ref)-[:RESOLVES_TO]->(target)
                RETURN ref.id AS id, ref.ref_type AS ref_type, ref.number AS number,
                       ref.raw_text AS raw_text, ref.physical_page AS physical_page,
                       page.id AS page_id,
                       CASE WHEN target IS NULL THEN null ELSE labels(target)[0] END AS target_label,
                       target.id AS target_id, properties(target) AS target_properties
                """,
                project_id=project_id, node_id=node_id,
            )
            return rows[0] if rows else None
        if node_type in {ProjectStructureNodeType.plate, ProjectStructureNodeType.plate_panel}:
            if node_type == ProjectStructureNodeType.plate:
                match = "(v:DocumentVersion)-[:HAS_PLATE]->(asset:Plate {id: $node_id})"
            else:
                match = "(v:DocumentVersion)-[:HAS_PLATE]->(:Plate)-[:HAS_PANEL]->(asset:PlatePanel {id: $node_id})"
            rows = self._records(
                f"""
                MATCH (p:Project {{id: $project_id}})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->{match}
                OPTIONAL MATCH (ref:Reference)-[:RESOLVES_TO]->(asset)
                OPTIONAL MATCH (asset)-[:DEPICTS]->(obj:ArchaeologyObject)
                RETURN asset.id AS id, properties(asset) AS properties, v.id AS document_version_id,
                       collect(DISTINCT {{id: ref.id, number: ref.number, ref_type: ref.ref_type}}) AS references,
                       collect(DISTINCT {{id: obj.id, canonical_name: obj.canonical_name}}) AS objects
                """,
                project_id=project_id, node_id=node_id,
            )
            return rows[0] if rows else None
        if node_type in {ProjectStructureNodeType.drawing, ProjectStructureNodeType.drawing_region}:
            if node_type == ProjectStructureNodeType.drawing:
                match = "(v:DocumentVersion)-[:HAS_DRAWING]->(asset:Drawing {id: $node_id})"
            else:
                match = "(v:DocumentVersion)-[:HAS_DRAWING]->(:Drawing)-[:HAS_REGION]->(asset:DrawingRegion {id: $node_id})"
            rows = self._records(
                f"""
                MATCH (p:Project {{id: $project_id}})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->{match}
                OPTIONAL MATCH (ref:Reference)-[:RESOLVES_TO]->(asset)
                OPTIONAL MATCH (asset)-[:DEPICTS]->(obj:ArchaeologyObject)
                RETURN asset.id AS id, properties(asset) AS properties, v.id AS document_version_id,
                       collect(DISTINCT {{id: ref.id, number: ref.number, ref_type: ref.ref_type}}) AS references,
                       collect(DISTINCT {{id: obj.id, canonical_name: obj.canonical_name}}) AS objects
                """,
                project_id=project_id, node_id=node_id,
            )
            return rows[0] if rows else None
        if node_type == ProjectStructureNodeType.review_round:
            rows = self._records(
                """
                MATCH (p:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->(round:ReviewRound {id: $node_id})
                OPTIONAL MATCH (previous:ReviewRound)-[:PRECEDES]->(round)
                OPTIONAL MATCH (round)-[:USES_BODY_VERSION]->(body:DocumentVersion)
                OPTIONAL MATCH (round)-[:USES_PLATE_VERSION]->(plate:DocumentVersion)
                OPTIONAL MATCH (round)-[:USES_DRAWING_VERSION]->(drawing:DocumentVersion)
                RETURN round.id AS id, round.sequence AS sequence, round.status AS status, round.notes AS notes,
                       previous.id AS previous_round_id,
                       body.id AS body_id, body.originalName AS body_name,
                       plate.id AS plate_id, plate.originalName AS plate_name,
                       drawing.id AS drawing_id, drawing.originalName AS drawing_name
                """,
                project_id=project_id, node_id=node_id,
            )
            return rows[0] if rows else None
        if node_type == ProjectStructureNodeType.archaeology_object:
            rows = self._records(
                """
                MATCH (p:Project {id: $project_id})-[:HAS_OBJECT]->(obj:ArchaeologyObject {id: $node_id})
                OPTIONAL MATCH (source)-[:MENTIONS]->(obj)
                OPTIONAL MATCH (asset)-[:DEPICTS]->(obj)
                RETURN obj.id AS id, properties(obj) AS properties,
                       collect(DISTINCT {id: source.id, label: labels(source)[0]}) AS mention_sources,
                       collect(DISTINCT {id: asset.id, label: labels(asset)[0]}) AS depicted_by
                """,
                project_id=project_id, node_id=node_id,
            )
            return rows[0] if rows else None
        return None
