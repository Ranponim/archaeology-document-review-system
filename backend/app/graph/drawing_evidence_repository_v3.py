from __future__ import annotations

from app.domain.drawing_evidence_v3 import DrawingV3Resolution
from app.graph.drawing_evidence_repository import DrawingEvidenceRepository


class DrawingEvidenceRepositoryV3(DrawingEvidenceRepository):
    """Additive v3 persistence on top of the stable v1/v2 repository.

    v3 keeps every candidate and Codex decision auditable. Canonical TARGETS
    are deliberately gated by ``auto_promote`` and the resolver's final
    ``AUTO_VERIFIED`` status.
    """

    @staticmethod
    def _decision_id(corpus_id: str, source_asset_id: str, run_id: str) -> str:
        return f"codex-drawing-decision:{corpus_id}:{source_asset_id}:{run_id}"

    def save_v3_resolution(
        self,
        project_id: str,
        corpus_id: str,
        resolution: DrawingV3Resolution,
        *,
        auto_promote: bool,
    ) -> None:
        candidates: list[dict] = []
        evidence: list[dict] = []
        decisions: list[dict] = []
        targets: list[dict] = []

        seen_candidates: set[str] = set()
        seen_evidence: set[str] = set()

        for result in resolution.source_results:
            candidate_by_id = {row.candidate_id: row for row in result.candidates}
            for candidate in result.candidates:
                if candidate.candidate_id not in seen_candidates:
                    seen_candidates.add(candidate.candidate_id)
                    candidates.append(
                        {
                            "id": candidate.candidate_id,
                            "source_asset_id": result.source_asset_id,
                            "publication_kind": candidate.publication_kind,
                            "number": candidate.number,
                            "local_score": float(candidate.local_score),
                            "hard_contradiction": bool(candidate.hard_contradiction),
                            "strong_contradiction_ids": list(candidate.strong_contradiction_ids),
                            "raw_texts": list(candidate.raw_texts),
                        }
                    )
                for item in candidate.evidence:
                    if item.id in seen_evidence:
                        continue
                    seen_evidence.add(item.id)
                    evidence.append(
                        {
                            "id": item.id,
                            "candidate_id": candidate.candidate_id,
                            "family": item.family,
                            "method": item.method,
                            "value": item.value,
                            "supports": bool(item.supports),
                            "weak": bool(item.weak),
                        }
                    )

            if result.decision is not None:
                decision = result.decision
                decision_id = self._decision_id(
                    corpus_id, result.source_asset_id, decision.run_id
                )
                decisions.append(
                    {
                        "id": decision_id,
                        "source_asset_id": result.source_asset_id,
                        "run_id": decision.run_id,
                        "model": decision.model,
                        "verdict": decision.verdict,
                        "candidate_id": decision.candidate_id,
                        "confidence": float(decision.confidence),
                        "cited_support_ids": list(decision.cited_support_ids),
                        "cited_contradiction_ids": list(decision.cited_contradiction_ids),
                        "reason_codes": list(decision.reason_codes),
                        "summary": decision.summary,
                        "final_status": result.status,
                        "considered_candidate_ids": [
                            candidate.candidate_id for candidate in result.candidates
                        ],
                        "diagnostics": dict(result.diagnostics),
                    }
                )

                selected = (
                    candidate_by_id.get(result.selected_candidate_id)
                    if result.selected_candidate_id
                    else None
                )
                if (
                    auto_promote
                    and result.status == "AUTO_VERIFIED"
                    and decision.verdict == "match"
                    and selected is not None
                ):
                    targets.append(
                        {
                            "candidate_id": selected.candidate_id,
                            "source_asset_id": result.source_asset_id,
                            "publication_kind": selected.publication_kind,
                            "number": selected.number,
                            "decision_run_id": decision.run_id,
                        }
                    )

        if candidates:
            self._driver.execute_query(
                """
                // DRAWING_V3_CANDIDATES
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $candidates AS row
                MATCH (c)-[:USES_SOURCE]->(asset:OriginalAsset {id: row.source_asset_id})
                WHERE c.projectId = $project_id AND asset.projectId = $project_id
                MERGE (candidate:DrawingCandidate {id: row.id})
                SET candidate.referenceCorpusId = $corpus_id,
                    candidate.sourceAssetId = row.source_asset_id,
                    candidate.publicationKind = row.publication_kind,
                    candidate.candidateNumber = row.number,
                    candidate.localScore = row.local_score,
                    candidate.rawTexts = row.raw_texts,
                    candidate.hasHardContradiction = row.hard_contradiction,
                    candidate.strongContradictionIds = row.strong_contradiction_ids,
                    candidate.resolverVersion = 'drawing-evidence-v3',
                    candidate.updatedAt = datetime(),
                    candidate.createdAt = coalesce(candidate.createdAt, datetime())
                MERGE (c)-[:HAS_DRAWING_CANDIDATE]->(candidate)
                MERGE (asset)-[:PROPOSES]->(candidate)
                RETURN count(candidate) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                candidates=candidates,
                **self._query_config,
            )

        if evidence:
            self._driver.execute_query(
                """
                // DRAWING_V3_EVIDENCE
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $evidence AS row
                MATCH (c)-[:HAS_DRAWING_CANDIDATE]->(candidate:DrawingCandidate {id: row.candidate_id})
                MERGE (ev:ResolutionEvidence {id: row.id})
                SET ev.referenceCorpusId = $corpus_id,
                    ev.family = row.family,
                    ev.method = row.method,
                    ev.value = row.value,
                    ev.supports = row.supports,
                    ev.weak = row.weak,
                    ev.resolverVersion = 'drawing-evidence-v3',
                    ev.updatedAt = datetime(),
                    ev.createdAt = coalesce(ev.createdAt, datetime())
                MERGE (c)-[:HAS_RESOLUTION_EVIDENCE]->(ev)
                FOREACH (_ IN CASE WHEN row.supports THEN [1] ELSE [] END |
                    MERGE (candidate)-[:SUPPORTED_BY]->(ev)
                )
                FOREACH (_ IN CASE WHEN row.supports THEN [] ELSE [1] END |
                    MERGE (candidate)-[:CONTRADICTED_BY]->(ev)
                )
                RETURN count(ev) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                evidence=evidence,
                **self._query_config,
            )

        if decisions:
            self._driver.execute_query(
                """
                // DRAWING_V3_CODEX_DECISIONS
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $decisions AS row
                MATCH (c)-[:USES_SOURCE]->(asset:OriginalAsset {id: row.source_asset_id})
                WHERE c.projectId = $project_id AND asset.projectId = $project_id
                MERGE (decision:CodexDecision {id: row.id})
                SET decision.referenceCorpusId = $corpus_id,
                    decision.sourceAssetId = row.source_asset_id,
                    decision.runId = row.run_id,
                    decision.model = row.model,
                    decision.verdict = row.verdict,
                    decision.confidence = row.confidence,
                    decision.reasonCodes = row.reason_codes,
                    decision.summary = row.summary,
                    decision.citedSupportIds = row.cited_support_ids,
                    decision.citedContradictionIds = row.cited_contradiction_ids,
                    decision.finalStatus = row.final_status,
                    decision.resolverVersion = 'drawing-evidence-v3',
                    decision.diagnostics = toString(row.diagnostics),
                    decision.updatedAt = datetime(),
                    decision.createdAt = coalesce(decision.createdAt, datetime())
                MERGE (asset)-[:HAS_CODEX_DECISION]->(decision)
                WITH c, decision, row
                UNWIND row.considered_candidate_ids AS candidate_id
                MATCH (c)-[:HAS_DRAWING_CANDIDATE]->(candidate:DrawingCandidate {id: candidate_id})
                MERGE (decision)-[:CONSIDERED]->(candidate)
                WITH c, decision, row
                OPTIONAL MATCH (c)-[:HAS_DRAWING_CANDIDATE]->(selected:DrawingCandidate {id: row.candidate_id})
                FOREACH (_ IN CASE WHEN row.verdict = 'match' AND selected IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (decision)-[:SELECTED]->(selected)
                )
                WITH c, decision, row
                UNWIND row.cited_support_ids AS support_id
                OPTIONAL MATCH (c)-[:HAS_RESOLUTION_EVIDENCE]->(support:ResolutionEvidence {id: support_id})
                FOREACH (_ IN CASE WHEN support IS NULL THEN [] ELSE [1] END |
                    MERGE (decision)-[:CITES_SUPPORT]->(support)
                )
                WITH c, decision, row
                UNWIND row.cited_contradiction_ids AS contradiction_id
                OPTIONAL MATCH (c)-[:HAS_RESOLUTION_EVIDENCE]->(contradiction:ResolutionEvidence {id: contradiction_id})
                FOREACH (_ IN CASE WHEN contradiction IS NULL THEN [] ELSE [1] END |
                    MERGE (decision)-[:CITES_CONTRADICTION]->(contradiction)
                )
                RETURN count(DISTINCT decision) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                decisions=decisions,
                **self._query_config,
            )

        if targets:
            self._driver.execute_query(
                """
                // DRAWING_V3_TARGETS
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $targets AS row
                MATCH (c)-[:USES_SOURCE]->(asset:OriginalAsset {id: row.source_asset_id})
                MATCH (c)-[:HAS_DRAWING_CANDIDATE]->(candidate:DrawingCandidate {id: row.candidate_id})
                WITH c, asset, candidate, row,
                     'drawing:' + $corpus_id + ':' + row.publication_kind + ':' + row.number AS drawing_id
                MERGE (drawing:Drawing {id: drawing_id})
                SET drawing.referenceCorpusId = $corpus_id,
                    drawing.number = row.number,
                    drawing.publicationKind = row.publication_kind,
                    drawing.sourceAssetId = row.source_asset_id,
                    drawing.evidenceLevel = 'derived-verified',
                    drawing.evidenceMethod = 'codex-grounded-v3',
                    drawing.sourceKind = 'drawing_ai',
                    drawing.resolverVersion = 'drawing-evidence-v3'
                MERGE (c)-[:HAS_DRAWING]->(drawing)
                MERGE (candidate)-[:TARGETS]->(drawing)
                MERGE (asset)-[:RESOLVES_TO]->(drawing)
                RETURN count(drawing) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                targets=targets,
                **self._query_config,
            )
