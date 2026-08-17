"""Graph queries for the visual asset delivery API (review §10 / Phase P0-D).

Every method returns the raw graph row(s) needed to build a renderable asset:
the node properties plus the owning DocumentVersion (uri/sha256) and, for
panels/regions, the parent Plate/Drawing (raw_identifier). The API layer
(VisualAssetService) resolves render bytes from these rows and never returns a
filesystem path to the browser (anti-pattern #15).
"""
from typing import Any
from neo4j import Driver


class AssetRepository:
    def __init__(self, driver: Driver | None, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    def _query_config(self) -> dict[str, Any]:
        return {"database_": self._database} if self._database is not None else {}

    def get_page_asset(self, page_id: str) -> dict[str, Any] | None:
        if self._driver is None:
            return None
        records, _, _ = self._driver.execute_query(
            """
            MATCH (page:Page {id: $page_id})
            OPTIONAL MATCH (version:DocumentVersion)-[:HAS_PAGE]->(page)
            RETURN properties(page) AS page,
                   properties(version) AS version
            """,
            page_id=page_id,
            **self._query_config(),
        )
        if not records:
            return None
        row = records[0]
        page = dict(row["page"]) if row.get("page") else None
        if not page:
            return None
        return {
            "page": page,
            "version": dict(row["version"]) if row.get("version") else None,
        }

    def get_plate_asset(self, plate_id: str) -> dict[str, Any] | None:
        if self._driver is None:
            return None
        records, _, _ = self._driver.execute_query(
            """
            MATCH (plate:Plate {id: $plate_id})
            OPTIONAL MATCH (version:DocumentVersion)-[:HAS_PLATE]->(plate)
            OPTIONAL MATCH (plate)-[:HAS_PANEL]->(panel:PlatePanel)
            RETURN properties(plate) AS plate,
                   properties(version) AS version,
                   collect(DISTINCT properties(panel)) AS panels
            """,
            plate_id=plate_id,
            **self._query_config(),
        )
        if not records:
            return None
        row = records[0]
        plate = dict(row["plate"]) if row.get("plate") else None
        if not plate:
            return None
        return {
            "plate": plate,
            "version": dict(row["version"]) if row.get("version") else None,
            "panels": [dict(p) for p in (row.get("panels") or []) if p],
        }

    def get_plate_panel_asset(self, panel_id: str) -> dict[str, Any] | None:
        if self._driver is None:
            return None
        records, _, _ = self._driver.execute_query(
            """
            MATCH (panel:PlatePanel {id: $panel_id})
            OPTIONAL MATCH (plate:Plate)-[:HAS_PANEL]->(panel)
            OPTIONAL MATCH (version:DocumentVersion)-[:HAS_PLATE]->(plate)
            RETURN properties(panel) AS panel,
                   properties(plate) AS plate,
                   properties(version) AS version
            """,
            panel_id=panel_id,
            **self._query_config(),
        )
        if not records:
            return None
        row = records[0]
        panel = dict(row["panel"]) if row.get("panel") else None
        if not panel:
            return None
        return {
            "panel": panel,
            "plate": dict(row["plate"]) if row.get("plate") else None,
            "version": dict(row["version"]) if row.get("version") else None,
        }

    def get_drawing_asset(self, drawing_id: str) -> dict[str, Any] | None:
        if self._driver is None:
            return None
        records, _, _ = self._driver.execute_query(
            """
            MATCH (drawing:Drawing {id: $drawing_id})
            OPTIONAL MATCH (version:DocumentVersion)-[:HAS_DRAWING]->(drawing)
            OPTIONAL MATCH (drawing)-[:HAS_REGION]->(region:DrawingRegion)
            RETURN properties(drawing) AS drawing,
                   properties(version) AS version,
                   collect(DISTINCT properties(region)) AS regions
            """,
            drawing_id=drawing_id,
            **self._query_config(),
        )
        if not records:
            return None
        row = records[0]
        drawing = dict(row["drawing"]) if row.get("drawing") else None
        if not drawing:
            return None
        return {
            "drawing": drawing,
            "version": dict(row["version"]) if row.get("version") else None,
            "regions": [dict(r) for r in (row.get("regions") or []) if r],
        }

    def get_drawing_region_asset(self, region_id: str) -> dict[str, Any] | None:
        if self._driver is None:
            return None
        records, _, _ = self._driver.execute_query(
            """
            MATCH (region:DrawingRegion {id: $region_id})
            OPTIONAL MATCH (drawing:Drawing)-[:HAS_REGION]->(region)
            OPTIONAL MATCH (version:DocumentVersion)-[:HAS_DRAWING]->(drawing)
            RETURN properties(region) AS region,
                   properties(drawing) AS drawing,
                   properties(version) AS version
            """,
            region_id=region_id,
            **self._query_config(),
        )
        if not records:
            return None
        row = records[0]
        region = dict(row["region"]) if row.get("region") else None
        if not region:
            return None
        return {
            "region": region,
            "drawing": dict(row["drawing"]) if row.get("drawing") else None,
            "version": dict(row["version"]) if row.get("version") else None,
        }

    def get_candidate_visual_bundle(self, candidate_id: str) -> dict[str, Any] | None:
        """Mandatory Test D: source body page (evidence chain) + canonical
        visual asset (DEPICTS) for one candidate, returned together."""
        if self._driver is None:
            return None
        records, _, _ = self._driver.execute_query(
            """
            MATCH (cand:CorrectionCandidate {id: $candidate_id})
            OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
            OPTIONAL MATCH (ev)-[:EXTRACTED_FROM]->(page:Page)
            OPTIONAL MATCH (ev)-[:FROM_VERSION]->(version:DocumentVersion)
            WITH cand,
                 collect(DISTINCT {
                     evidence: properties(ev),
                     page: properties(page),
                     version: properties(version)
                 }) AS evidence_chain
            OPTIONAL MATCH (cand)-[:ABOUT]->(obj:ArchaeologyObject)
            OPTIONAL MATCH (asset)-[:DEPICTS]->(obj)
            OPTIONAL MATCH (parent)-[:HAS_PANEL|HAS_REGION]->(asset)
            OPTIONAL MATCH (asset)-[:HAS_PANEL|HAS_REGION]->(child)
            WITH cand, evidence_chain, asset, parent,
                 collect(DISTINCT properties(child)) AS child_props
            WITH cand, evidence_chain,
                 collect(DISTINCT {
                     label: head(labels(asset)),
                     props: properties(asset),
                     parent: properties(parent),
                     children: [c IN child_props WHERE c IS NOT NULL]
                 }) AS canonical_assets
            RETURN properties(cand) AS candidate,
                   evidence_chain,
                   canonical_assets
            """,
            candidate_id=candidate_id,
            **self._query_config(),
        )
        if not records:
            return None
        row = records[0]
        candidate = dict(row["candidate"]) if row.get("candidate") else None
        if not candidate:
            return None
        return {
            "candidate": candidate,
            "evidence_chain": [
                dict(item) for item in (row.get("evidence_chain") or []) if item
            ],
            "canonical_assets": [
                dict(item) for item in (row.get("canonical_assets") or []) if item
            ],
        }

