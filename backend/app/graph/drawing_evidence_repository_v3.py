from __future__ import annotations

import hashlib
import json
from urllib.parse import quote
from uuid import uuid4

from app.domain.drawing_evidence_v3 import (
    DrawingSourceEvidencePacket,
    DrawingV3Resolution,
)
from app.graph.drawing_evidence_repository import DrawingEvidenceRepository


class DrawingReviewNotFoundError(LookupError):
    pass


class DrawingReviewConflictError(RuntimeError):
    pass


class DrawingEvidenceRepositoryV3(DrawingEvidenceRepository):
    """Additive v3 persistence and human review on top of stable v1/v2 storage."""

    @staticmethod
    def _decision_id(corpus_id: str, source_asset_id: str, run_id: str) -> str:
        return f"codex-drawing-decision:{corpus_id}:{source_asset_id}:{run_id}"

    @staticmethod
    def _source_snapshot_id(corpus_id: str, source_asset_id: str) -> str:
        payload = f"{corpus_id}\0{source_asset_id}".encode("utf-8")
        return "drawing-v3-source:" + hashlib.sha256(payload).hexdigest()[:32]

    @staticmethod
    def _review_visual_id(corpus_id: str, owner_id: str, region_id: str) -> str:
        payload = f"{corpus_id}\0{owner_id}\0{region_id}".encode("utf-8")
        return "drawing-review-visual:" + hashlib.sha256(payload).hexdigest()[:32]

    @staticmethod
    def _visual_url(region_id: str | None) -> str | None:
        if not region_id:
            return None
        return f"/api/v1/assets/drawing-regions/{quote(str(region_id), safe='')}/render"

    def save_v3_resolution(
        self,
        project_id: str,
        corpus_id: str,
        resolution: DrawingV3Resolution,
        *,
        auto_promote: bool,
        sources: tuple[DrawingSourceEvidencePacket, ...] | list[DrawingSourceEvidencePacket] = (),
    ) -> None:
        candidates: list[dict] = []
        candidate_evidence: list[dict] = []
        source_snapshots: list[dict] = []
        source_evidence: list[dict] = []
        visuals: list[dict] = []
        decisions: list[dict] = []
        support_citations: list[dict] = []
        contradiction_citations: list[dict] = []
        targets: list[dict] = []

        seen_candidates: set[str] = set()
        seen_evidence: set[str] = set()
        source_by_id = {source.source_asset_id: source for source in sources}

        for source in source_by_id.values():
            snapshot_id = self._source_snapshot_id(corpus_id, source.source_asset_id)
            source_snapshots.append(
                {
                    "id": snapshot_id,
                    "source_asset_id": source.source_asset_id,
                    "source_sha256": source.source_sha256,
                    "original_name": source.original_name,
                    "source_path": source.source_path,
                    "raw_text": source.raw_text,
                    "publication_kind": source.publication_kind,
                    "internal_numbers": list(source.internal_numbers),
                }
            )
            for item in source.evidence:
                if item.id in seen_evidence:
                    continue
                seen_evidence.add(item.id)
                source_evidence.append(
                    {
                        "id": item.id,
                        "snapshot_id": snapshot_id,
                        "family": item.family,
                        "method": item.method,
                        "value": item.value,
                        "supports": bool(item.supports),
                        "weak": bool(item.weak),
                    }
                )
            for region in source.visual_regions:
                visuals.append(
                    {
                        "node_id": self._review_visual_id(
                            corpus_id, snapshot_id, region.region_id
                        ),
                        "region_id": region.region_id,
                        "owner_type": "source",
                        "owner_id": snapshot_id,
                        "render_uri": region.image_path,
                        "physical_page": region.page,
                        "original_bbox": list(region.bbox) if region.bbox else None,
                        "source_sha256": region.source_sha256,
                        "confidence": float(region.confidence),
                    }
                )

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
                    for region in candidate.visual_regions:
                        visuals.append(
                            {
                                "node_id": self._review_visual_id(
                                    corpus_id, candidate.candidate_id, region.region_id
                                ),
                                "region_id": region.region_id,
                                "owner_type": "candidate",
                                "owner_id": candidate.candidate_id,
                                "render_uri": region.image_path,
                                "physical_page": region.page,
                                "original_bbox": list(region.bbox) if region.bbox else None,
                                "source_sha256": region.source_sha256,
                                "confidence": float(region.confidence),
                            }
                        )
                for item in candidate.evidence:
                    if item.id in seen_evidence:
                        continue
                    seen_evidence.add(item.id)
                    candidate_evidence.append(
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
                        "diagnostics": json.dumps(
                            dict(result.diagnostics),
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                    }
                )
                support_citations.extend(
                    {"decision_id": decision_id, "evidence_id": evidence_id}
                    for evidence_id in decision.cited_support_ids
                )
                contradiction_citations.extend(
                    {"decision_id": decision_id, "evidence_id": evidence_id}
                    for evidence_id in decision.cited_contradiction_ids
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

        if source_snapshots:
            self._driver.execute_query(
                """
                // DRAWING_V3_SOURCE_SNAPSHOTS
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $snapshots AS row
                MATCH (c)-[:USES_SOURCE]->(asset:OriginalAsset {id: row.source_asset_id})
                WHERE c.projectId = $project_id AND asset.projectId = $project_id
                MERGE (snapshot:DrawingSourceSnapshot {id: row.id})
                SET snapshot.referenceCorpusId = $corpus_id,
                    snapshot.sourceAssetId = row.source_asset_id,
                    snapshot.sourceSha256 = row.source_sha256,
                    snapshot.originalName = row.original_name,
                    snapshot.sourcePath = row.source_path,
                    snapshot.rawText = row.raw_text,
                    snapshot.publicationKind = row.publication_kind,
                    snapshot.internalNumbers = row.internal_numbers,
                    snapshot.resolverVersion = 'drawing-evidence-v3',
                    snapshot.updatedAt = datetime(),
                    snapshot.createdAt = coalesce(snapshot.createdAt, datetime())
                MERGE (asset)-[:HAS_DRAWING_SOURCE_SNAPSHOT]->(snapshot)
                RETURN count(snapshot) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                snapshots=source_snapshots,
                **self._query_config,
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

        if source_evidence:
            self._driver.execute_query(
                """
                // DRAWING_V3_SOURCE_EVIDENCE
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $evidence AS row
                MATCH (snapshot:DrawingSourceSnapshot {id: row.snapshot_id})
                WHERE snapshot.referenceCorpusId = $corpus_id
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
                MERGE (snapshot)-[:HAS_SOURCE_EVIDENCE]->(ev)
                RETURN count(ev) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                evidence=source_evidence,
                **self._query_config,
            )

        if candidate_evidence:
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
                evidence=candidate_evidence,
                **self._query_config,
            )

        if visuals:
            self._driver.execute_query(
                """
                // DRAWING_V3_REVIEW_VISUALS
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $visuals AS row
                MERGE (region:DrawingRegion {id: row.node_id})
                SET region.referenceCorpusId = $corpus_id,
                    region.originalRegionId = row.region_id,
                    region.render_uri = row.render_uri,
                    region.physical_page = row.physical_page,
                    region.bbox = [0.0, 0.0, 1.0, 1.0],
                    region.original_bbox = row.original_bbox,
                    region.source_sha256 = row.source_sha256,
                    region.confidence = row.confidence,
                    region.reviewVisual = true,
                    region.resolverVersion = 'drawing-evidence-v3',
                    region.updatedAt = datetime(),
                    region.createdAt = coalesce(region.createdAt, datetime())
                WITH c, row, region
                OPTIONAL MATCH (candidate:DrawingCandidate {id: row.owner_id})
                WHERE row.owner_type = 'candidate' AND candidate.referenceCorpusId = $corpus_id
                OPTIONAL MATCH (snapshot:DrawingSourceSnapshot {id: row.owner_id})
                WHERE row.owner_type = 'source' AND snapshot.referenceCorpusId = $corpus_id
                FOREACH (_ IN CASE WHEN candidate IS NULL THEN [] ELSE [1] END |
                    MERGE (candidate)-[:HAS_REVIEW_VISUAL]->(region)
                )
                FOREACH (_ IN CASE WHEN snapshot IS NULL THEN [] ELSE [1] END |
                    MERGE (snapshot)-[:HAS_REVIEW_VISUAL]->(region)
                )
                RETURN count(region) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                visuals=visuals,
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
                    decision.candidateId = row.candidate_id,
                    decision.verdict = row.verdict,
                    decision.confidence = row.confidence,
                    decision.reasonCodes = row.reason_codes,
                    decision.summary = row.summary,
                    decision.citedSupportIds = row.cited_support_ids,
                    decision.citedContradictionIds = row.cited_contradiction_ids,
                    decision.finalStatus = row.final_status,
                    decision.resolverVersion = 'drawing-evidence-v3',
                    decision.diagnostics = row.diagnostics,
                    decision.updatedAt = datetime(),
                    decision.createdAt = coalesce(decision.createdAt, datetime())
                MERGE (asset)-[:HAS_CODEX_DECISION]->(decision)
                WITH c, decision, row
                OPTIONAL MATCH (c)-[:HAS_DRAWING_CANDIDATE]->(considered:DrawingCandidate)
                WHERE considered.id IN row.considered_candidate_ids
                WITH c, decision, row, collect(considered) AS considered_candidates
                FOREACH (candidate IN considered_candidates |
                    MERGE (decision)-[:CONSIDERED]->(candidate)
                )
                WITH c, decision, row
                OPTIONAL MATCH (c)-[:HAS_DRAWING_CANDIDATE]->(selected:DrawingCandidate {id: row.candidate_id})
                FOREACH (_ IN CASE WHEN row.verdict = 'match' AND selected IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (decision)-[:SELECTED]->(selected)
                )
                RETURN count(DISTINCT decision) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                decisions=decisions,
                **self._query_config,
            )

        if support_citations:
            self._driver.execute_query(
                """
                // DRAWING_V3_CODEX_SUPPORT_CITATIONS
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $citations AS row
                MATCH (decision:CodexDecision {id: row.decision_id})
                MATCH (c)-[:HAS_RESOLUTION_EVIDENCE]->(evidence:ResolutionEvidence {id: row.evidence_id})
                MERGE (decision)-[:CITES_SUPPORT]->(evidence)
                RETURN count(*) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                citations=support_citations,
                **self._query_config,
            )

        if contradiction_citations:
            self._driver.execute_query(
                """
                // DRAWING_V3_CODEX_CONTRADICTION_CITATIONS
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $citations AS row
                MATCH (decision:CodexDecision {id: row.decision_id})
                MATCH (c)-[:HAS_RESOLUTION_EVIDENCE]->(evidence:ResolutionEvidence {id: row.evidence_id})
                MERGE (decision)-[:CITES_CONTRADICTION]->(evidence)
                RETURN count(*) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                citations=contradiction_citations,
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

    def list_v3_review_cases(self, project_id: str) -> list[dict]:
        records, _, _ = self._driver.execute_query(
            """
            // DRAWING_V3_REVIEW_CASES
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus)-[:USES_SOURCE]->(asset:OriginalAsset)
            MATCH (asset)-[:HAS_CODEX_DECISION]->(decision:CodexDecision)
            WHERE decision.referenceCorpusId = c.id
              AND decision.resolverVersion = 'drawing-evidence-v3'
              AND decision.finalStatus = 'REVIEW_REQUIRED'
              AND NOT EXISTS {
                  MATCH (asset)-[:HAS_HUMAN_RESOLUTION]->(:HumanDrawingResolution)-[:REVIEWS]->(decision)
              }
            WITH asset, c, decision
            ORDER BY decision.createdAt DESC, decision.id DESC
            WITH asset, head(collect({corpus_id: c.id, decision_id: decision.id})) AS latest
            MATCH (decision:CodexDecision {id: latest.decision_id})
            MATCH (c:ReferenceCorpus {id: latest.corpus_id})
            OPTIONAL MATCH (asset)-[:HAS_DRAWING_SOURCE_SNAPSHOT]->(snapshot:DrawingSourceSnapshot)
            WHERE snapshot.referenceCorpusId = c.id
            OPTIONAL MATCH (snapshot)-[:HAS_REVIEW_VISUAL]->(source_visual:DrawingRegion)
            MATCH (decision)-[:CONSIDERED]->(candidate:DrawingCandidate)
            OPTIONAL MATCH (candidate)-[:HAS_REVIEW_VISUAL]->(candidate_visual:DrawingRegion)
            OPTIONAL MATCH (candidate)-[:SUPPORTED_BY]->(support:ResolutionEvidence)
            OPTIONAL MATCH (candidate)-[:CONTRADICTED_BY]->(contradiction:ResolutionEvidence)
            WITH asset, decision, candidate,
                 head([item IN collect(DISTINCT snapshot) WHERE item IS NOT NULL]) AS snapshot,
                 head([item IN collect(DISTINCT source_visual.id) WHERE item IS NOT NULL]) AS source_visual_id,
                 head([item IN collect(DISTINCT candidate_visual.id) WHERE item IS NOT NULL]) AS candidate_visual_id,
                 [item IN collect(DISTINCT support.value) WHERE item IS NOT NULL][..5] AS evidence_summary,
                 [item IN collect(DISTINCT contradiction.value) WHERE item IS NOT NULL][..5] AS contradiction_summary
            RETURN asset.id AS source_asset_id,
                   coalesce(snapshot.originalName, asset.originalName, asset.original_name, asset.id) AS source_name,
                   coalesce(snapshot.rawText, '') AS source_text,
                   source_visual_id,
                   decision.id AS decision_id,
                   decision.candidateId AS codex_candidate_id,
                   decision.confidence AS codex_confidence,
                   decision.summary AS codex_summary,
                   candidate.id AS candidate_id,
                   candidate.publicationKind AS publication_kind,
                   candidate.candidateNumber AS number,
                   coalesce(candidate.rawTexts[0], '') AS caption,
                   coalesce(candidate.localScore, 0.0) AS local_score,
                   candidate_visual_id,
                   evidence_summary,
                   contradiction_summary
            ORDER BY source_asset_id, candidate_id
            """,
            project_id=project_id,
            **self._query_config,
        )

        grouped: dict[str, dict] = {}
        for record in records:
            source_id = str(record.get("source_asset_id") or "")
            if not source_id:
                continue
            case = grouped.setdefault(
                source_id,
                {
                    "source_asset_id": source_id,
                    "source_name": str(record.get("source_name") or source_id),
                    "source_image_url": self._visual_url(record.get("source_visual_id")),
                    "source_text": str(record.get("source_text") or ""),
                    "codex_candidate_id": (
                        str(record.get("codex_candidate_id"))
                        if record.get("codex_candidate_id")
                        else None
                    ),
                    "codex_confidence": (
                        float(record.get("codex_confidence"))
                        if record.get("codex_confidence") is not None
                        else None
                    ),
                    "codex_summary": (
                        str(record.get("codex_summary"))
                        if record.get("codex_summary") is not None
                        else None
                    ),
                    "candidates": [],
                },
            )
            candidate_id = record.get("candidate_id")
            if not candidate_id:
                continue
            case["candidates"].append(
                {
                    "candidate_id": str(candidate_id),
                    "publication_kind": str(record.get("publication_kind") or "drawing"),
                    "number": str(record.get("number") or ""),
                    "caption": str(record.get("caption") or ""),
                    "image_url": self._visual_url(record.get("candidate_visual_id")),
                    "local_score": float(record.get("local_score") or 0.0),
                    "evidence_summary": [
                        str(value) for value in (record.get("evidence_summary") or [])
                    ],
                    "contradiction_summary": [
                        str(value)
                        for value in (record.get("contradiction_summary") or [])
                    ],
                }
            )

        for case in grouped.values():
            codex_candidate_id = case["codex_candidate_id"]
            case["candidates"].sort(
                key=lambda candidate: (
                    0 if candidate["candidate_id"] == codex_candidate_id else 1,
                    -candidate["local_score"],
                    candidate["publication_kind"],
                    candidate["number"],
                )
            )
        return [grouped[key] for key in sorted(grouped)]

    def _review_lookup(self, project_id: str, source_asset_id: str) -> dict:
        records, _, _ = self._driver.execute_query(
            """
            // DRAWING_V3_REVIEW_RESOLVE_LOOKUP
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus)-[:USES_SOURCE]->(asset:OriginalAsset {id: $source_asset_id})
            MATCH (asset)-[:HAS_CODEX_DECISION]->(decision:CodexDecision)
            WHERE decision.referenceCorpusId = c.id
              AND decision.resolverVersion = 'drawing-evidence-v3'
              AND decision.finalStatus = 'REVIEW_REQUIRED'
              AND NOT EXISTS {
                  MATCH (asset)-[:HAS_HUMAN_RESOLUTION]->(:HumanDrawingResolution)-[:REVIEWS]->(decision)
              }
            WITH asset, c, decision
            ORDER BY decision.createdAt DESC, decision.id DESC
            WITH asset, head(collect({corpus_id: c.id, decision_id: decision.id})) AS latest
            MATCH (decision:CodexDecision {id: latest.decision_id})
            MATCH (c:ReferenceCorpus {id: latest.corpus_id})
            OPTIONAL MATCH (decision)-[:SELECTED]->(codex_selected:DrawingCandidate)
            MATCH (decision)-[:CONSIDERED]->(candidate:DrawingCandidate)
            WITH asset, c, decision, codex_selected, collect(candidate) AS candidates
            RETURN asset.id AS source_asset_id,
                   c.id AS corpus_id,
                   decision.id AS decision_id,
                   codex_selected.id AS codex_candidate_id,
                   decision.runId AS codex_run_id,
                   decision.model AS codex_model,
                   [candidate IN candidates | candidate.id] AS candidate_ids,
                   [candidate IN candidates | {
                       id: candidate.id,
                       publication_kind: candidate.publicationKind,
                       number: candidate.candidateNumber
                   }] AS candidates
            """,
            project_id=project_id,
            source_asset_id=source_asset_id,
            **self._query_config,
        )
        if not records:
            raise DrawingReviewNotFoundError(source_asset_id)
        return dict(records[0])

    def resolve_v3_review(
        self,
        project_id: str,
        source_asset_id: str,
        action: str,
        candidate_id: str | None,
        reviewer: str,
    ) -> dict:
        if action not in {"approve", "choose", "none"}:
            raise DrawingReviewConflictError(f"unsupported review action: {action}")
        lookup = self._review_lookup(project_id, source_asset_id)
        candidate_ids = {str(value) for value in (lookup.get("candidate_ids") or [])}
        codex_candidate_id = (
            str(lookup.get("codex_candidate_id"))
            if lookup.get("codex_candidate_id")
            else None
        )

        if action in {"approve", "choose"}:
            if not candidate_id or candidate_id not in candidate_ids:
                raise DrawingReviewConflictError("candidate was not considered by Codex")
            if action == "approve" and candidate_id != codex_candidate_id:
                raise DrawingReviewConflictError(
                    "approve requires the Codex-selected candidate"
                )
        elif candidate_id is not None:
            raise DrawingReviewConflictError("none must not select a candidate")

        candidates = {
            str(row.get("id")): row
            for row in (lookup.get("candidates") or [])
            if row and row.get("id")
        }
        selected = candidates.get(candidate_id) if candidate_id else None
        if candidate_id and selected is None:
            raise DrawingReviewConflictError("selected candidate metadata is unavailable")

        corpus_id = str(lookup.get("corpus_id") or "")
        decision_id = str(lookup.get("decision_id") or "")
        if not corpus_id or not decision_id:
            raise DrawingReviewNotFoundError(source_asset_id)

        final_status = (
            "HUMAN_UNRESOLVED" if action == "none" else "HUMAN_VERIFIED"
        )
        rejected_candidate_ids = sorted(
            candidate_ids if candidate_id is None else candidate_ids - {candidate_id}
        )
        drawing_id = None
        if selected is not None:
            publication_kind = str(selected.get("publication_kind") or "drawing")
            number = str(selected.get("number") or "")
            if not number:
                raise DrawingReviewConflictError("selected candidate has no drawing number")
            drawing_id = f"drawing:{corpus_id}:{publication_kind}:{number}"

        human_id = "human-drawing-resolution:" + uuid4().hex
        self._driver.execute_query(
            """
            // DRAWING_V3_HUMAN_RESOLUTION
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})-[:USES_SOURCE]->(asset:OriginalAsset {id: $source_asset_id})
            MATCH (asset)-[:HAS_CODEX_DECISION]->(decision:CodexDecision {id: $decision_id})
            CREATE (human:HumanDrawingResolution {
                id: $human_id,
                action: $action,
                reviewer: $reviewer,
                finalStatus: $final_status,
                resolverVersion: 'drawing-evidence-v3',
                codexRunId: $codex_run_id,
                codexModel: $codex_model,
                selectedCandidateId: $candidate_id,
                rejectedCandidateIds: $rejected_candidate_ids,
                createdAt: datetime()
            })
            MERGE (asset)-[:HAS_HUMAN_RESOLUTION]->(human)
            MERGE (human)-[:REVIEWS]->(decision)
            WITH c, asset, human
            OPTIONAL MATCH (c)-[:HAS_DRAWING_CANDIDATE]->(rejected:DrawingCandidate)
            WHERE rejected.id IN $rejected_candidate_ids
            WITH c, asset, human, collect(rejected) AS rejected_candidates
            FOREACH (candidate IN rejected_candidates |
                MERGE (human)-[:REJECTED]->(candidate)
            )
            WITH c, asset, human
            OPTIONAL MATCH (c)-[:HAS_DRAWING_CANDIDATE]->(selected:DrawingCandidate {id: $candidate_id})
            FOREACH (_ IN CASE WHEN selected IS NULL THEN [] ELSE [1] END |
                MERGE (human)-[:SELECTED]->(selected)
            )
            FOREACH (_ IN CASE WHEN selected IS NULL THEN [] ELSE [1] END |
                MERGE (drawing:Drawing {id: $drawing_id})
                SET drawing.referenceCorpusId = $corpus_id,
                    drawing.number = $drawing_number,
                    drawing.publicationKind = $publication_kind,
                    drawing.sourceAssetId = $source_asset_id,
                    drawing.evidenceLevel = 'direct',
                    drawing.evidenceMethod = 'human-verified-v3',
                    drawing.sourceKind = 'drawing_ai',
                    drawing.resolverVersion = 'drawing-evidence-v3'
                MERGE (c)-[:HAS_DRAWING]->(drawing)
                MERGE (selected)-[:TARGETS]->(drawing)
                MERGE (asset)-[:RESOLVES_TO]->(drawing)
            )
            RETURN count(human) AS saved
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            source_asset_id=source_asset_id,
            decision_id=decision_id,
            human_id=human_id,
            action=action,
            reviewer=str(reviewer or "human"),
            final_status=final_status,
            codex_run_id=lookup.get("codex_run_id"),
            codex_model=lookup.get("codex_model"),
            candidate_id=candidate_id,
            rejected_candidate_ids=rejected_candidate_ids,
            drawing_id=drawing_id,
            drawing_number=(str(selected.get("number")) if selected else None),
            publication_kind=(
                str(selected.get("publication_kind") or "drawing")
                if selected
                else None
            ),
            **self._query_config,
        )
        return {
            "source_asset_id": source_asset_id,
            "action": action,
            "candidate_id": candidate_id,
            "final_status": final_status,
        }
