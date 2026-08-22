from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Literal


ReferenceKind = Literal["plate", "drawing"]


@dataclass(frozen=True, slots=True)
class GraphReferenceResolution:
    status: str
    reference_type: str
    number: str
    reference_corpus_id: str
    target_ids: tuple[str, ...] = ()


class GraphReviewRepository:
    """Focused graph queries for corpus-mode deterministic review.

    Every visual lookup is rooted at Project -> ReferenceCorpus.  This keeps
    revision identity explicit and prevents a Reference or visual with the same
    publication number in another corpus/project from becoming authority.
    """

    def __init__(self, driver: Any, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @property
    def _query_config(self) -> dict[str, Any]:
        return {"database_": self._database} if self._database is not None else {}

    def _require_ready_corpus(self, project_id: str, corpus_id: str) -> None:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            WHERE corpus.projectId = $project_id
            RETURN corpus.status AS status
            LIMIT 1
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            **self._query_config,
        )
        if not records:
            raise ValueError(
                f"reference corpus '{corpus_id}' is not owned by project '{project_id}'"
            )
        status = str(records[0].get("status") or "").strip().lower()
        if status != "ready":
            raise ValueError(
                f"reference corpus '{corpus_id}' must be READY before review"
            )

    def resolve_reference(
        self,
        project_id: str,
        corpus_id: str,
        reference_type: str,
        number: str,
    ) -> GraphReferenceResolution:
        self._require_ready_corpus(project_id, corpus_id)
        normalized_type = str(reference_type or "").strip().lower()
        normalized_number = str(number or "").strip()
        if normalized_type not in {"plate", "drawing"} or not normalized_number:
            return GraphReferenceResolution(
                status="INVALID",
                reference_type=normalized_type,
                number=normalized_number,
                reference_corpus_id=corpus_id,
            )

        if normalized_type == "plate":
            query = """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            MATCH (corpus)-[:HAS_PLATE]->(target:Plate)
            WHERE corpus.projectId = $project_id
              AND toString(target.number) = $number
            RETURN target.id AS id
            ORDER BY target.id ASC
            """
        else:
            query = """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            MATCH (corpus)-[:HAS_DRAWING]->(target:Drawing)
            WHERE corpus.projectId = $project_id
              AND toString(target.number) = $number
            RETURN target.id AS id
            ORDER BY target.id ASC
            """

        records, _, _ = self._driver.execute_query(
            query,
            project_id=project_id,
            corpus_id=corpus_id,
            number=normalized_number,
            **self._query_config,
        )
        target_ids = tuple(
            sorted(
                {
                    str(row.get("id"))
                    for row in records
                    if row.get("id") is not None
                }
            )
        )
        if not target_ids:
            status = "MISSING"
        elif len(target_ids) == 1:
            status = "RESOLVED"
        else:
            status = "AMBIGUOUS"
        return GraphReferenceResolution(
            status=status,
            reference_type=normalized_type,
            number=normalized_number,
            reference_corpus_id=corpus_id,
            target_ids=target_ids,
        )

    @staticmethod
    def _resolution_evidence_id(
        project_id: str,
        corpus_id: str,
        analysis_run_id: str,
        reference_id: str,
        resolution: GraphReferenceResolution,
    ) -> str:
        identity = "|".join(
            [
                project_id,
                corpus_id,
                analysis_run_id,
                reference_id,
                resolution.reference_type,
                resolution.number,
                resolution.status,
                ",".join(resolution.target_ids),
            ]
        )
        return "resolution:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    def save_resolution_evidence(
        self,
        project_id: str,
        corpus_id: str,
        analysis_run_id: str,
        reference_id: str,
        resolution: GraphReferenceResolution,
    ) -> str:
        self._require_ready_corpus(project_id, corpus_id)
        if resolution.reference_corpus_id != corpus_id:
            raise ValueError("resolution evidence corpus does not match selected corpus")
        evidence_id = self._resolution_evidence_id(
            project_id,
            corpus_id,
            analysis_run_id,
            reference_id,
            resolution,
        )
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            WHERE corpus.projectId = $project_id
            OPTIONAL MATCH (project)-[:HAS_RUN]->(run:AnalysisRun {id: $analysis_run_id})
            MERGE (evidence:ResolutionEvidence {id: $evidence_id})
            SET evidence.projectId = $project_id,
                evidence.referenceCorpusId = $corpus_id,
                evidence.analysisRunId = $analysis_run_id,
                evidence.referenceId = $reference_id,
                evidence.referenceType = $reference_type,
                evidence.number = $number,
                evidence.status = $status,
                evidence.targetIds = $target_ids,
                evidence.updatedAt = datetime(),
                evidence.createdAt = coalesce(evidence.createdAt, datetime())
            MERGE (evidence)-[:FOR_CORPUS]->(corpus)
            FOREACH (_ IN CASE WHEN run IS NULL THEN [] ELSE [1] END |
                MERGE (run)-[:HAS_RESOLUTION_EVIDENCE]->(evidence)
            )
            RETURN evidence.id AS id
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            analysis_run_id=analysis_run_id,
            reference_id=reference_id,
            evidence_id=evidence_id,
            reference_type=resolution.reference_type,
            number=resolution.number,
            status=resolution.status,
            target_ids=list(resolution.target_ids),
            **self._query_config,
        )
        if not records:
            raise ValueError("resolution evidence could not be persisted in selected corpus")
        return str(records[0].get("id") or evidence_id)
