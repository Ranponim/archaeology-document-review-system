from __future__ import annotations

from typing import Any

from app.graph.asset_repository import AssetRepository


class StrictAssetRepository(AssetRepository):
    """Candidate visual queries that fail closed on identity ambiguity.

    The canonical side is discovered from explicit Reference -> RESOLVES_TO
    graph paths attached to sources that mention the candidate's object. It
    never starts from every asset that merely DEPICTS the same object.

    The bundle also carries ReviewRound previous/current body ids so revision
    candidates can display the exact body versions compared without consulting
    DocumentVersion.stage.
    """

    def get_candidate_visual_bundle(
        self,
        candidate_id: str,
        project_id: str,
    ) -> dict[str, Any] | None:
        if self._driver is None:
            return None
        records, _, _ = self._driver.execute_query(
            """
            MATCH (proj:Project {id: $project_id})-[:HAS_CANDIDATE]->
                  (cand:CorrectionCandidate {id: $candidate_id})
            OPTIONAL MATCH (run:AnalysisRun)-[:PRODUCED]->(cand)
            OPTIONAL MATCH (run)-[:FOR_ROUND]->(current_round:ReviewRound)
            OPTIONAL MATCH (proj)-[:HAS_REVIEW_ROUND]->
                           (previous_round:ReviewRound)-[:PRECEDES]->(current_round)
            OPTIONAL MATCH (previous_round)-[:USES_BODY_VERSION]->(previous_body:DocumentVersion)
            OPTIONAL MATCH (current_round)-[:USES_BODY_VERSION]->(current_body:DocumentVersion)
            WITH proj, cand,
                 {
                     analysis_run_id: run.id,
                     current_round_id: current_round.id,
                     previous_round_id: previous_round.id,
                     previous_body_version_id: previous_body.id,
                     current_body_version_id: current_body.id
                 } AS round_context
            OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
            OPTIONAL MATCH (ev)-[:EXTRACTED_FROM]->(page:Page)
            OPTIONAL MATCH (ev)-[:FROM_VERSION]->(version:DocumentVersion)
            WITH proj, cand, round_context,
                 collect(DISTINCT {
                     evidence: properties(ev),
                     page: properties(page),
                     version: properties(version)
                 }) AS evidence_chain
            OPTIONAL MATCH (cand)-[:ABOUT]->(obj:ArchaeologyObject)
            OPTIONAL MATCH (source:TextBlock|Caption)-[:MENTIONS]->(obj)
            OPTIONAL MATCH (source)-[:REFERENCES]->(ref:Reference)-[:RESOLVES_TO]->(target)
            WHERE target:Plate OR target:PlatePanel OR target:Drawing OR target:DrawingRegion
            OPTIONAL MATCH (plate_parent:Plate)-[:HAS_PANEL]->(target)
            OPTIONAL MATCH (drawing_parent:Drawing)-[:HAS_REGION]->(target)
            OPTIONAL MATCH (direct_plate_version:DocumentVersion)-[:HAS_PLATE]->(target)
            OPTIONAL MATCH (panel_version:DocumentVersion)-[:HAS_PLATE]->(plate_parent)
            OPTIONAL MATCH (direct_drawing_version:DocumentVersion)-[:HAS_DRAWING]->(target)
            OPTIONAL MATCH (region_version:DocumentVersion)-[:HAS_DRAWING]->(drawing_parent)
            OPTIONAL MATCH (target)-[:HAS_PANEL|HAS_REGION]->(child)
            WITH cand, evidence_chain, round_context, ref, target,
                 CASE
                     WHEN plate_parent IS NOT NULL THEN properties(plate_parent)
                     WHEN drawing_parent IS NOT NULL THEN properties(drawing_parent)
                     ELSE null
                 END AS parent_props,
                 CASE
                     WHEN direct_plate_version IS NOT NULL THEN properties(direct_plate_version)
                     WHEN panel_version IS NOT NULL THEN properties(panel_version)
                     WHEN direct_drawing_version IS NOT NULL THEN properties(direct_drawing_version)
                     WHEN region_version IS NOT NULL THEN properties(region_version)
                     ELSE null
                 END AS document_version,
                 collect(DISTINCT properties(child)) AS child_props
            WITH cand, evidence_chain, round_context,
                 collect(DISTINCT {
                     ref: properties(ref),
                     label: head(labels(target)),
                     props: properties(target),
                     parent: parent_props,
                     children: [c IN child_props WHERE c IS NOT NULL],
                     document_version: document_version
                 }) AS canonical_assets
            RETURN properties(cand) AS candidate,
                   evidence_chain,
                   round_context,
                   canonical_assets
            """,
            project_id=project_id,
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
                dict(item)
                for item in (row.get("evidence_chain") or [])
                if item and item.get("evidence")
            ],
            "round_context": dict(row.get("round_context") or {}),
            "canonical_assets": [
                dict(item)
                for item in (row.get("canonical_assets") or [])
                if item and item.get("props") and item.get("ref")
            ],
        }