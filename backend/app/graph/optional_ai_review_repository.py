from __future__ import annotations

from typing import Any

from app.domain.ai_review_finding import AIReviewFindingData


class OptionalAIReviewRepository:
    """Persist optional model-review audit without becoming graph authority."""

    def __init__(self, driver: Any, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @property
    def _query_config(self) -> dict[str, Any]:
        return {"database_": self._database} if self._database is not None else {}

    def save(
        self,
        *,
        project_id: str,
        reference_corpus_id: str,
        analysis_run_id: str,
        findings: list[AIReviewFindingData],
    ) -> int:
        if not findings:
            return 0
        rows = [
            {
                "id": item.id,
                "source": item.source,
                "provider": item.provider,
                "model": item.model,
                "promptVersion": item.prompt_version,
                "inputHash": item.input_hash,
                "confidence": float(item.confidence),
                "verdict": item.verdict,
                "rationale": item.rationale,
                "proposedText": item.proposed_text,
                "candidateId": item.candidate_id,
                "evidenceIds": list(item.evidence_ids),
                "archaeologyObjectId": item.archaeology_object_id,
                "referenceCorpusId": item.reference_corpus_id,
                "analysisRunId": item.analysis_run_id,
            }
            for item in findings
        ]
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})
            MATCH (project)-[:HAS_REFERENCE_CORPUS]->(corpus:ReferenceCorpus {id: $reference_corpus_id})
            MATCH (project)-[:HAS_RUN]->(run:AnalysisRun {id: $analysis_run_id})
            WITH project, corpus, run
            UNWIND $rows AS row
            WITH project, corpus, run, row
            WHERE row.referenceCorpusId = $reference_corpus_id
              AND row.analysisRunId = $analysis_run_id
            MERGE (audit:AIReviewFinding {id: row.id})
            SET audit.source = row.source,
                audit.provider = row.provider,
                audit.model = row.model,
                audit.promptVersion = row.promptVersion,
                audit.inputHash = row.inputHash,
                audit.confidence = row.confidence,
                audit.verdict = row.verdict,
                audit.rationale = row.rationale,
                audit.proposedText = row.proposedText,
                audit.candidateId = row.candidateId,
                audit.evidenceIds = row.evidenceIds,
                audit.archaeologyObjectId = row.archaeologyObjectId,
                audit.referenceCorpusId = row.referenceCorpusId,
                audit.analysisRunId = row.analysisRunId
            MERGE (run)-[:HAS_AI_REVIEW_FINDING]->(audit)
            MERGE (audit)-[:USES_REFERENCE_CORPUS]->(corpus)
            WITH project, audit, row
            OPTIONAL MATCH (candidate:CorrectionCandidate {id: row.candidateId})
            FOREACH (_ IN CASE WHEN candidate IS NULL THEN [] ELSE [1] END |
                MERGE (audit)-[:REVIEWS]->(candidate)
            )
            RETURN count(audit) AS saved
            """,
            project_id=project_id,
            reference_corpus_id=reference_corpus_id,
            analysis_run_id=analysis_run_id,
            rows=rows,
            **self._query_config,
        )
        return int(records[0].get("saved") or 0) if records else 0
