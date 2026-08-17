from __future__ import annotations

import json
from typing import Any

from app.domain.review_models import CorrectionCandidateData
from app.graph.strict_review_repository import StrictReviewRepository
from app.services.review_budget import make_finding_fingerprint, make_run_candidate_id


class AuditedReviewRepository(StrictReviewRepository):
    """Strict repository plus immutable per-run finding instances and run metrics."""

    def _candidate_to_param(self, cand: CorrectionCandidateData) -> dict[str, Any]:
        base = super()._candidate_to_param(cand)
        fingerprint = cand.finding_fingerprint or make_finding_fingerprint(cand)
        run_id = cand.analysis_run_id or "unscoped"
        effective_candidate_id = make_run_candidate_id(run_id, cand)
        base["candidate_id"] = effective_candidate_id
        base["finding_fingerprint"] = fingerprint
        base["analysis_run_id"] = cand.analysis_run_id
        for idx, ev in enumerate(base.get("evidences") or []):
            raw_ev_id = str(ev.get("id") or f"ev_{idx + 1}")
            ev["id"] = f"{effective_candidate_id}:{raw_ev_id.split(':')[-1]}"
            ev["analysis_run_id"] = cand.analysis_run_id or ev.get("analysis_run_id")
        base["evidence"] = base["evidences"][0] if base.get("evidences") else None
        return base

    def save_candidates(
        self,
        project_id: str,
        candidates: list[CorrectionCandidateData],
        analysis_run_id: str | None = None,
    ) -> None:
        if self._driver is None or not candidates:
            return
        cand_params = [self._candidate_to_param(c) for c in candidates]
        cypher = """
        MATCH (proj:Project {id: $project_id})
        UNWIND $candidates AS c
        MERGE (cand:CorrectionCandidate {id: c.candidate_id})
        SET cand.rule_category = c.rule_category,
            cand.change_type = c.change_type,
            cand.status = c.status,
            cand.original_text = c.original_text,
            cand.proposed_text = c.proposed_text,
            cand.confidence = c.confidence,
            cand.severity = c.severity,
            cand.findingFingerprint = c.finding_fingerprint,
            cand.analysisRunId = c.analysis_run_id
        MERGE (proj)-[:HAS_CANDIDATE]->(cand)
        WITH proj, cand, c
        OPTIONAL MATCH (proj)-[:HAS_OBJECT]->(obj:ArchaeologyObject {id: c.archaeology_object_id})
        FOREACH (_ IN CASE WHEN obj IS NOT NULL THEN [1] ELSE [] END |
            MERGE (cand)-[:ABOUT]->(obj)
        )
        WITH proj, cand, c
        UNWIND c.evidences AS ev_param
        MERGE (ev:Evidence {id: ev_param.id})
        SET ev.kind = ev_param.kind,
            ev.source_sha256 = ev_param.source_sha256,
            ev.document_version_id = ev_param.document_version_id,
            ev.page_id = ev_param.page_id,
            ev.region_id = ev_param.region_id,
            ev.bbox = ev_param.bbox,
            ev.method = ev_param.method,
            ev.analysis_run_id = ev_param.analysis_run_id,
            ev.value = ev_param.value,
            ev.rationale = ev_param.rationale,
            ev.confidence = ev_param.confidence,
            ev.version_from = ev_param.version_from,
            ev.version_to = ev_param.version_to,
            ev.physical_page_from = ev_param.physical_page_from,
            ev.physical_page_to = ev_param.physical_page_to,
            ev.printed_page_from = ev_param.printed_page_from,
            ev.printed_page_to = ev_param.printed_page_to,
            ev.rule_name = ev_param.rule_name
        MERGE (cand)-[:SUPPORTED_BY]->(ev)
        WITH proj, ev, ev_param
        OPTIONAL MATCH (proj)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->
                       (:DocumentVersion)-[:HAS_PAGE]->(p:Page {id: ev_param.page_id})
        FOREACH (_ IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END |
            MERGE (ev)-[:EXTRACTED_FROM]->(p)
        )
        WITH proj, ev, ev_param
        OPTIONAL MATCH (proj)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->
                       (v:DocumentVersion {id: ev_param.document_version_id})
        FOREACH (_ IN CASE WHEN v IS NOT NULL THEN [1] ELSE [] END |
            MERGE (ev)-[:FROM_VERSION]->(v)
        )
        """
        self._driver.execute_query(
            cypher,
            project_id=project_id,
            candidates=cand_params,
            **self._query_config(),
        )

        run_id = analysis_run_id or next(
            (param.get("analysis_run_id") for param in cand_params if param.get("analysis_run_id")),
            None,
        )
        if run_id:
            self._driver.execute_query(
                """
                MATCH (proj:Project {id: $project_id})-[:HAS_RUN]->
                      (run:AnalysisRun {id: $analysis_run_id})
                UNWIND $candidate_ids AS cid
                MATCH (proj)-[:HAS_CANDIDATE]->(cand:CorrectionCandidate {id: cid})
                MERGE (run)-[:PRODUCED]->(cand)
                """,
                project_id=project_id,
                analysis_run_id=run_id,
                candidate_ids=[param["candidate_id"] for param in cand_params],
                **self._query_config(),
            )

    def save_run_summary(self, run_id: str, summary: dict[str, Any]) -> None:
        if self._driver is None:
            return
        self._driver.execute_query(
            """
            MATCH (run:AnalysisRun {id: $run_id})
            SET run.reviewSummary = $summary_json,
                run.rawFindings = $raw_findings,
                run.dedupedFindings = $deduped_findings,
                run.selectedCandidates = $selected_candidates,
                run.expensiveOperations = $expensive_operations,
                run.selectionMode = $selection_mode
            """,
            run_id=run_id,
            summary_json=json.dumps(summary, ensure_ascii=False, sort_keys=True),
            raw_findings=int(summary.get("raw_findings", 0)),
            deduped_findings=int(summary.get("deduped_findings", 0)),
            selected_candidates=int(summary.get("selected_candidates", 0)),
            expensive_operations=int(summary.get("expensive_operations", 0)),
            selection_mode=summary.get("selection_mode"),
            **self._query_config(),
        )

    def get_analysis_run(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        if self._driver is None:
            return None
        records, _, _ = self._driver.execute_query(
            """
            MATCH (proj:Project {id: $project_id})-[:HAS_RUN]->
                  (run:AnalysisRun {id: $run_id})
            RETURN properties(run) AS run
            """,
            project_id=project_id,
            run_id=run_id,
            **self._query_config(),
        )
        if not records:
            return None
        props = dict(records[0].get("run") or {})
        normalized: dict[str, Any] = {}
        for k, v in props.items():
            if hasattr(v, "iso_format"):
                normalized[k] = v.iso_format()
            elif hasattr(v, "isoformat"):
                normalized[k] = v.isoformat()
            elif hasattr(v, "to_native"):
                native = v.to_native()
                normalized[k] = native.isoformat() if hasattr(native, "isoformat") else str(native)
            elif type(v).__name__ in ("DateTime", "Date", "Time", "Duration"):
                normalized[k] = str(v)
            else:
                normalized[k] = v

        raw_summary = normalized.get("reviewSummary")
        if isinstance(raw_summary, str) and raw_summary:
            try:
                normalized["summary"] = json.loads(raw_summary)
            except json.JSONDecodeError:
                normalized["summary"] = {}
        else:
            normalized["summary"] = {}
        return normalized
