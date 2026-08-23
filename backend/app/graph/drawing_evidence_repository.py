from __future__ import annotations

import hashlib
from typing import Any

from neo4j import Driver

from app.domain.canonical_models import EvidenceLevel
from app.domain.drawing_evidence import (
    BodyDrawingContext,
    ContextFact,
    DrawingEvidenceResolution,
)


class DrawingEvidenceRepository:
    """Project/corpus-scoped persistence for explainable drawing resolution."""

    def __init__(self, driver: Driver, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @property
    def _query_config(self) -> dict[str, str]:
        return {"database_": self._database} if self._database else {}

    @staticmethod
    def _level(value: EvidenceLevel | str) -> str:
        return value.value if isinstance(value, EvidenceLevel) else str(value)

    @staticmethod
    def _context_id(corpus_id: str, fact: ContextFact) -> str:
        payload = "\0".join(
            (
                corpus_id,
                fact.kind,
                fact.normalized_value,
                fact.source_kind,
                fact.source_node_id or "",
                fact.source_sha256 or "",
            )
        ).encode("utf-8")
        return "context-entity:" + hashlib.sha256(payload).hexdigest()[:32]

    def list_body_drawing_contexts(self, project_id: str) -> list[BodyDrawingContext]:
        records, _, _ = self._driver.execute_query(
            """
            // BODY_DRAWING_CONTEXT
            MATCH (p:Project {id: $project_id})-[:HAS_DOCUMENT]->(d:Document)-[:HAS_VERSION]->(v:DocumentVersion)
            WHERE coalesce(d.kind, 'report_body') = 'report_body'
            WITH p, d, v
            ORDER BY coalesce(v.createdAt, datetime({epochMillis: 0})) DESC, v.id DESC
            WITH p, d, head(collect(v)) AS v
            MATCH (v)-[:HAS_PAGE]->(page:Page)
            MATCH (page)-[:HAS_BLOCK|HAS_CAPTION]->(source)-[:REFERENCES]->(ref:Reference)
            WHERE ref.ref_type = 'drawing'
            OPTIONAL MATCH (page)-[:HAS_BLOCK]->(neighbor:TextBlock)
            WITH ref, source, page, v, neighbor,
                 CASE
                   WHEN source:TextBlock THEN abs(coalesce(neighbor.order, 0) - coalesce(source.order, 0))
                   ELSE coalesce(neighbor.order, 999999)
                 END AS distance
            ORDER BY distance ASC, coalesce(neighbor.order, 999999) ASC, neighbor.id ASC
            WITH ref, source, v,
                 [row IN collect({id: neighbor.id, text: coalesce(neighbor.normalized_text, neighbor.text, '')})
                  WHERE row.id IS NOT NULL AND row.id <> source.id AND trim(row.text) <> ''][..4] AS neighbors
            RETURN toString(ref.number) AS number,
                   source.id AS source_id,
                   coalesce(source.raw_text, source.normalized_text, source.text, ref.raw_text, '') AS source_text,
                   v.sha256 AS source_sha256,
                   [row IN neighbors | row.text] AS neighbor_texts,
                   [row IN neighbors | row.id] AS neighbor_ids
            ORDER BY number, source_id
            """,
            project_id=project_id,
            **self._query_config,
        )

        grouped: dict[str, dict[str, Any]] = {}
        for record in records:
            number = str(record.get("number") or "").strip()
            if not number:
                continue
            item = grouped.setdefault(
                number,
                {"texts": [], "ids": [], "sha": record.get("source_sha256")},
            )
            source_text = str(record.get("source_text") or "").strip()
            source_id = record.get("source_id")
            if source_text and source_text not in item["texts"]:
                item["texts"].append(source_text)
                item["ids"].append(str(source_id) if source_id else "")
            for neighbor_id, neighbor_text in zip(
                record.get("neighbor_ids") or [], record.get("neighbor_texts") or []
            ):
                text = str(neighbor_text or "").strip()
                if text and text not in item["texts"]:
                    item["texts"].append(text)
                    item["ids"].append(str(neighbor_id) if neighbor_id else "")

        return [
            BodyDrawingContext(
                number=number,
                raw_texts=tuple(item["texts"]),
                source_node_ids=tuple(item["ids"]),
                source_sha256=str(item["sha"]) if item["sha"] else None,
            )
            for number, item in sorted(grouped.items())
        ]

    def save_resolution(
        self,
        project_id: str,
        corpus_id: str,
        resolution: DrawingEvidenceResolution,
    ) -> None:
        candidates = [
            {
                "id": item.candidate_id,
                "reference_corpus_id": item.reference_corpus_id,
                "source_asset_id": item.source_asset_id,
                "source_sha256": item.source_sha256,
                "candidate_number": item.candidate_number,
                "status": item.status,
                "evidence_level": self._level(item.evidence_level),
                "resolver_version": item.resolver_version,
                "score": float(item.score),
                "runner_up_score": float(item.runner_up_score),
                "margin": float(item.margin),
                "evidence_families": list(item.evidence_families),
                "has_hard_contradiction": bool(item.has_hard_contradiction),
            }
            for item in resolution.candidates
        ]
        if candidates:
            self._driver.execute_query(
                """
                // DRAWING_EVIDENCE_CANDIDATES
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $candidates AS row
                MATCH (c)-[:USES_SOURCE]->(asset:OriginalAsset {id: row.source_asset_id})
                WHERE c.projectId = $project_id AND asset.projectId = $project_id
                MERGE (candidate:DrawingCandidate {id: row.id})
                SET candidate.referenceCorpusId = $corpus_id,
                    candidate.sourceAssetId = row.source_asset_id,
                    candidate.sourceSha256 = row.source_sha256,
                    candidate.candidateNumber = row.candidate_number,
                    candidate.status = row.status,
                    candidate.evidenceLevel = row.evidence_level,
                    candidate.resolverVersion = row.resolver_version,
                    candidate.score = row.score,
                    candidate.runnerUpScore = row.runner_up_score,
                    candidate.margin = row.margin,
                    candidate.evidenceFamilies = row.evidence_families,
                    candidate.hasHardContradiction = row.has_hard_contradiction,
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

        facts = [
            {
                "id": self._context_id(corpus_id, fact),
                "kind": fact.kind,
                "value": fact.value,
                "normalized_value": fact.normalized_value,
                "source_kind": fact.source_kind,
                "source_node_id": fact.source_node_id,
                "source_sha256": fact.source_sha256,
            }
            for fact in resolution.context_facts
        ]
        if facts:
            self._driver.execute_query(
                """
                // DRAWING_EVIDENCE_FACTS
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $facts AS row
                MERGE (fact:ContextEntity {id: row.id})
                SET fact.referenceCorpusId = $corpus_id,
                    fact.kind = row.kind,
                    fact.value = row.value,
                    fact.normalizedValue = row.normalized_value,
                    fact.sourceKind = row.source_kind,
                    fact.sourceNodeId = row.source_node_id,
                    fact.sourceSha256 = row.source_sha256,
                    fact.updatedAt = datetime(),
                    fact.createdAt = coalesce(fact.createdAt, datetime())
                MERGE (c)-[:HAS_CONTEXT_ENTITY]->(fact)
                WITH p, fact, row
                OPTIONAL MATCH (p)-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset {id: row.source_node_id})
                OPTIONAL MATCH (p)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PAGE]->(:Page)-[:HAS_BLOCK|HAS_CAPTION]->(bodySource)
                WHERE bodySource.id = row.source_node_id
                FOREACH (_ IN CASE WHEN asset IS NULL THEN [] ELSE [1] END |
                    MERGE (asset)-[:HAS_CONTEXT]->(fact)
                )
                FOREACH (_ IN CASE WHEN bodySource IS NULL THEN [] ELSE [1] END |
                    MERGE (bodySource)-[:HAS_CONTEXT]->(fact)
                )
                RETURN count(fact) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                facts=facts,
                **self._query_config,
            )

        evidence = [
            {
                "id": item.id,
                "candidate_id": item.candidate_id,
                "family": item.family,
                "method": item.method,
                "value": item.value,
                "normalized_value": item.normalized_value,
                "score": float(item.score),
                "supports": bool(item.supports),
                "source_node_id": item.source_node_id,
                "source_sha256": item.source_sha256,
            }
            for item in resolution.evidence
        ]
        if evidence:
            self._driver.execute_query(
                """
                // DRAWING_EVIDENCE_ITEMS
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $evidence AS row
                MATCH (c)-[:HAS_DRAWING_CANDIDATE]->(candidate:DrawingCandidate {id: row.candidate_id})
                MERGE (ev:ResolutionEvidence {id: row.id})
                SET ev.referenceCorpusId = $corpus_id,
                    ev.family = row.family,
                    ev.method = row.method,
                    ev.value = row.value,
                    ev.normalizedValue = row.normalized_value,
                    ev.score = row.score,
                    ev.supports = row.supports,
                    ev.sourceNodeId = row.source_node_id,
                    ev.sourceSha256 = row.source_sha256,
                    ev.updatedAt = datetime(),
                    ev.createdAt = coalesce(ev.createdAt, datetime())
                MERGE (c)-[:HAS_RESOLUTION_EVIDENCE]->(ev)
                FOREACH (_ IN CASE WHEN row.supports THEN [1] ELSE [] END |
                    MERGE (candidate)-[:SUPPORTED_BY]->(ev)
                )
                FOREACH (_ IN CASE WHEN row.supports THEN [] ELSE [1] END |
                    MERGE (candidate)-[:CONTRADICTED_BY]->(ev)
                )
                WITH p, candidate, ev, row
                OPTIONAL MATCH (p)-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset {id: row.source_node_id})
                OPTIONAL MATCH (p)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_PAGE]->(:Page)-[:HAS_BLOCK|HAS_CAPTION]->(bodySource)
                WHERE bodySource.id = row.source_node_id
                FOREACH (_ IN CASE WHEN asset IS NULL THEN [] ELSE [1] END |
                    MERGE (ev)-[:FROM_SOURCE]->(asset)
                )
                FOREACH (_ IN CASE WHEN bodySource IS NULL THEN [] ELSE [1] END |
                    MERGE (ev)-[:FROM_SOURCE]->(bodySource)
                )
                RETURN count(ev) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                evidence=evidence,
                **self._query_config,
            )

        verified = [
            {
                "candidate_id": item.candidate_id,
                "number": item.candidate_number,
                "level": self._level(item.evidence_level),
                "source_asset_id": item.source_asset_id,
            }
            for item in resolution.candidates
            if self._level(item.evidence_level)
            in {EvidenceLevel.DIRECT.value, EvidenceLevel.DERIVED_VERIFIED.value}
            and item.status == "verified"
        ]
        if verified:
            self._driver.execute_query(
                """
                // DRAWING_EVIDENCE_TARGETS
                MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
                UNWIND $verified AS row
                MATCH (c)-[:HAS_DRAWING_CANDIDATE]->(candidate:DrawingCandidate {id: row.candidate_id})
                MATCH (c)-[:USES_SOURCE]->(asset:OriginalAsset {id: row.source_asset_id})
                MERGE (drawing:Drawing {id: 'drawing:' + $corpus_id + ':' + row.number})
                SET drawing.referenceCorpusId = $corpus_id,
                    drawing.number = row.number,
                    drawing.sourceAssetId = row.source_asset_id,
                    drawing.evidenceLevel = row.level,
                    drawing.sourceKind = 'drawing_ai'
                MERGE (c)-[:HAS_DRAWING]->(drawing)
                MERGE (candidate)-[:TARGETS]->(drawing)
                RETURN count(drawing) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                verified=verified,
                **self._query_config,
            )
