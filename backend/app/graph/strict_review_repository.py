from __future__ import annotations

from typing import Any

from app.domain.review_models import CorrectionCandidateData
from app.graph.review_repository import (
    DECISION_VALUES,
    ReviewRepository as BaseReviewRepository,
    compute_latest_decision,
)
from app.services.review_budget import make_finding_fingerprint


class StrictReviewRepository(BaseReviewRepository):
    """Production review repository with hard project/run ownership boundaries."""

    def _candidate_to_param(self, cand: CorrectionCandidateData) -> dict[str, Any]:
        ev_params: list[dict[str, Any]] = []
        for idx, ev in enumerate(cand.evidences):
            ev_param = self._evidence_to_param(
                ev,
                fallback_id=f"ev_{cand.candidate_id}_{idx + 1}",
            )
            base_id = str(ev_param.get("id") or f"ev_{idx + 1}")
            ev_param["id"] = f"{cand.candidate_id}:{base_id}"
            ev_param["analysis_run_id"] = cand.analysis_run_id or ev_param.get(
                "analysis_run_id"
            )
            ev_params.append(ev_param)

        fingerprint = cand.finding_fingerprint or make_finding_fingerprint(cand)
        return {
            "candidate_id": cand.candidate_id,
            "rule_category": cand.rule_category,
            "change_type": cand.change_type,
            "status": cand.status,
            "original_text": cand.original_text,
            "proposed_text": cand.proposed_text,
            "confidence": cand.confidence,
            "severity": cand.severity,
            "finding_fingerprint": fingerprint,
            "archaeology_object_id": cand.archaeology_object_id,
            "analysis_run_id": cand.analysis_run_id,
            "evidence": ev_params[0] if ev_params else None,
            "evidences": ev_params,
        }

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
            (c.analysis_run_id for c in candidates if c.analysis_run_id),
            None,
        )
        if run_id:
            link_run_cypher = """
            MATCH (proj:Project {id: $project_id})-[:HAS_RUN]->
                  (run:AnalysisRun {id: $analysis_run_id})
            UNWIND $candidate_ids AS cid
            MATCH (proj)-[:HAS_CANDIDATE]->(cand:CorrectionCandidate {id: cid})
            MERGE (run)-[:PRODUCED]->(cand)
            """
            self._driver.execute_query(
                link_run_cypher,
                project_id=project_id,
                analysis_run_id=run_id,
                candidate_ids=[c.candidate_id for c in candidates],
                **self._query_config(),
            )

    def create_analysis_run(
        self,
        project_id: str,
        run_id: str,
        *,
        body_version_id: str,
        review_round_id: str | None = None,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        body_pdf_path: str | None = None,
        plate_pdf_path: str | None = None,
        drawing_pdf_path: str | None = None,
        enable_vlm: bool = True,
        enable_ai_review: bool = True,
        version_stage: str = "1차",
    ) -> None:
        if self._driver is None:
            return

        cypher = """
        MATCH (proj:Project {id: $project_id})
        OPTIONAL MATCH (proj)-[:HAS_REVIEW_ROUND]->(round:ReviewRound {id: $review_round_id})
        WITH proj, round
        WHERE $review_round_id IS NULL OR round IS NOT NULL
        MERGE (run:AnalysisRun {id: $run_id})
        SET run.status = 'queued',
            run.step = 'queued',
            run.reviewRoundId = $review_round_id,
            run.bodyVersionId = $body_version_id,
            run.plateVersionId = $plate_version_id,
            run.drawingVersionId = $drawing_version_id,
            run.bodyPdfPath = $body_pdf_path,
            run.platePdfPath = $plate_pdf_path,
            run.drawingPdfPath = $drawing_pdf_path,
            run.enableVlm = $enable_vlm,
            run.enableAiReview = $enable_ai_review,
            run.versionStage = $version_stage
        MERGE (proj)-[:HAS_RUN]->(run)
        FOREACH (_ IN CASE WHEN round IS NOT NULL THEN [1] ELSE [] END |
            MERGE (run)-[:FOR_ROUND]->(round)
        )
        WITH proj, run
        OPTIONAL MATCH (proj)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->
                       (body:DocumentVersion {id: $body_version_id})
        FOREACH (_ IN CASE WHEN body IS NOT NULL THEN [1] ELSE [] END |
            MERGE (run)-[:ANALYZES]->(body)
        )
        WITH proj, run
        OPTIONAL MATCH (proj)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->
                       (plate:DocumentVersion {id: $plate_version_id})
        FOREACH (_ IN CASE WHEN plate IS NOT NULL THEN [1] ELSE [] END |
            MERGE (run)-[:USES_PLATE]->(plate)
        )
        WITH proj, run
        OPTIONAL MATCH (proj)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->
                       (drawing:DocumentVersion {id: $drawing_version_id})
        FOREACH (_ IN CASE WHEN drawing IS NOT NULL THEN [1] ELSE [] END |
            MERGE (run)-[:USES_DRAWING]->(drawing)
        )
        RETURN run.id AS id
        """
        records, _, _ = self._driver.execute_query(
            cypher,
            project_id=project_id,
            run_id=run_id,
            review_round_id=review_round_id,
            body_version_id=body_version_id,
            plate_version_id=plate_version_id,
            drawing_version_id=drawing_version_id,
            body_pdf_path=body_pdf_path,
            plate_pdf_path=plate_pdf_path,
            drawing_pdf_path=drawing_pdf_path,
            enable_vlm=enable_vlm,
            enable_ai_review=enable_ai_review,
            version_stage=version_stage,
            **self._query_config(),
        )
        if review_round_id is not None and not records:
            raise LookupError(
                f"ReviewRound '{review_round_id}' is not owned by project '{project_id}'"
            )

    def claim_analysis(self, analysis_run_id: str) -> dict | None:
        if self._driver is None:
            return None
        records, _, _ = self._driver.execute_query(
            """
            MATCH (proj:Project)-[:HAS_RUN]->(run:AnalysisRun {id: $analysis_run_id})
            WHERE run.status = 'queued'
               OR (run.status = 'failed' AND run.retryable = true)
            SET run.status = 'running',
                run.step = 'analysis',
                run.startedAt = datetime(),
                run.completedAt = null,
                run.attemptCount = coalesce(run.attemptCount, 0) + 1,
                run.errorCode = null,
                run.retryable = false
            RETURN proj.id AS projectId, properties(run) AS run
            """,
            analysis_run_id=analysis_run_id,
            **self._query_config(),
        )
        if not records:
            return None
        record = records[0]
        props = dict(record.get("run") or {})
        return {
            "project_id": record.get("projectId"),
            "review_round_id": props.get("reviewRoundId"),
            "body_version_id": props.get("bodyVersionId"),
            "plate_version_id": props.get("plateVersionId"),
            "drawing_version_id": props.get("drawingVersionId"),
            "body_pdf_path": props.get("bodyPdfPath"),
            "plate_pdf_path": props.get("platePdfPath"),
            "drawing_pdf_path": props.get("drawingPdfPath"),
            "enable_vlm": bool(props.get("enableVlm", True)),
            "enable_ai_review": bool(props.get("enableAiReview", True)),
            "version_stage": props.get("versionStage", "1차"),
        }

    def save_review_decision(
        self,
        project_id: str,
        decision_id: str,
        candidate_id: str,
        decision_status: str,
        note: str = "",
        reviewer: str = "",
        previous_decision_id: str | None = None,
        modified_text: str | None = None,
    ) -> None:
        if self._driver is None:
            return
        normalized = str(decision_status).strip().lower()
        if normalized not in DECISION_VALUES:
            raise ValueError(
                f"decision_status must be one of {DECISION_VALUES}, got {decision_status!r}"
            )

        cypher = """
        MATCH (proj:Project {id: $project_id})-[:HAS_CANDIDATE]->
              (cand:CorrectionCandidate {id: $candidate_id})
        OPTIONAL MATCH (cand)-[:HAS_DECISION]->(prev:ReviewDecision)
        WHERE $previous_decision_id IS NULL OR prev.id = $previous_decision_id
        WITH cand, prev ORDER BY prev.created_at DESC LIMIT 1
        MERGE (dec:ReviewDecision {id: $decision_id})
        SET dec.decision_status = $decision_status,
            dec.note = $note,
            dec.reviewer = $reviewer,
            dec.modified_text = $modified_text,
            dec.previous_decision_id = CASE WHEN prev IS NOT NULL THEN prev.id ELSE null END,
            dec.created_at = toString(datetime())
        MERGE (cand)-[:HAS_DECISION]->(dec)
        FOREACH (_ IN CASE WHEN $modified_text IS NOT NULL THEN [1] ELSE [] END |
            SET cand.proposed_text = $modified_text
        )
        FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
            MERGE (dec)-[:SUPERSEDES]->(prev)
        )
        """
        self._driver.execute_query(
            cypher,
            project_id=project_id,
            decision_id=decision_id,
            candidate_id=candidate_id,
            decision_status=normalized,
            note=note,
            reviewer=reviewer,
            previous_decision_id=previous_decision_id,
            modified_text=modified_text,
            **self._query_config(),
        )

    def get_candidate(self, project_id: str, candidate_id: str) -> dict[str, Any] | None:
        if self._driver is None:
            return None
        cypher = """
        MATCH (proj:Project {id: $project_id})-[:HAS_CANDIDATE]->
              (cand:CorrectionCandidate {id: $candidate_id})
        OPTIONAL MATCH (cand)-[:ABOUT]->(obj:ArchaeologyObject)
        OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
        OPTIONAL MATCH (cand)-[:HAS_DECISION]->(dec:ReviewDecision)
        RETURN properties(cand) AS candidate,
               obj.id AS obj_id,
               collect(DISTINCT properties(ev)) AS evidences,
               collect(DISTINCT properties(dec)) AS decisions
        """
        records, _, _ = self._driver.execute_query(
            cypher,
            project_id=project_id,
            candidate_id=candidate_id,
            **self._query_config(),
        )
        if not records:
            return None
        row = records[0]
        cand_dict = dict(row["candidate"]) if row.get("candidate") else None
        if not cand_dict:
            return None
        ev_list = [dict(e) for e in (row.get("evidences") or []) if e]
        cand_dict["evidence"] = ev_list[0] if ev_list else None
        cand_dict["evidences"] = ev_list
        decisions = [dict(d) for d in (row.get("decisions") or []) if d]
        cand_dict["decisions"] = decisions
        cand_dict["latest_decision"] = compute_latest_decision(decisions)
        if row.get("obj_id"):
            cand_dict["archaeology_object_id"] = row["obj_id"]
        return cand_dict

    def get_candidate_traceability(
        self, project_id: str, candidate_id: str
    ) -> dict[str, Any]:
        if self._driver is None:
            return {}
        cypher = """
        MATCH (proj:Project {id: $project_id})-[:HAS_CANDIDATE]->
              (cand:CorrectionCandidate {id: $candidate_id})
        OPTIONAL MATCH (cand)-[:ABOUT]->(obj:ArchaeologyObject)
        OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
        OPTIONAL MATCH (ev)-[:EXTRACTED_FROM]->(page:Page)
        OPTIONAL MATCH (ev)-[:FROM_VERSION]->(doc_ver:DocumentVersion)
        OPTIONAL MATCH (cand)-[:HAS_DECISION]->(dec:ReviewDecision)
        OPTIONAL MATCH (source:TextBlock|Caption)
        WHERE (source)-[:MENTIONS]->(obj) OR (page)-[:HAS_BLOCK|HAS_CAPTION]->(source)
        OPTIONAL MATCH (source)-[:REFERENCES]->(ref:Reference)
        OPTIONAL MATCH (ref)-[:RESOLVES_TO]->(target)
        WHERE target:Plate OR target:PlatePanel OR target:Drawing OR target:DrawingRegion
        OPTIONAL MATCH (target)-[:DEPICTS]->(depicted:ArchaeologyObject)
        WHERE obj IS NULL OR depicted.id = obj.id
        RETURN properties(cand) AS candidate_props,
               properties(obj) AS object_props,
               collect(DISTINCT {
                   evidence: properties(ev),
                   page: properties(page),
                   document_version: properties(doc_ver)
               }) AS evidence_chain,
               collect(DISTINCT properties(dec)) AS decisions,
               collect(DISTINCT {
                   source_label: head(labels(source)),
                   source: properties(source),
                   ref: properties(ref),
                   target_label: head(labels(target)),
                   target: properties(target),
                   depicted: properties(depicted)
               }) AS canonical_path_rows
        """
        records, _, _ = self._driver.execute_query(
            cypher,
            project_id=project_id,
            candidate_id=candidate_id,
            **self._query_config(),
        )
        if not records:
            return {}
        row = records[0]
        cand_props = dict(row["candidate_props"]) if row.get("candidate_props") else None
        if not cand_props:
            return {}

        obj_props = dict(row["object_props"]) if row.get("object_props") else None
        decisions = [dict(d) for d in (row.get("decisions") or []) if d]
        evidences: list[dict[str, Any]] = []
        for item in row.get("evidence_chain") or []:
            if not item or not item.get("evidence"):
                continue
            ev_dict = dict(item["evidence"])
            if item.get("page"):
                ev_dict["page"] = dict(item["page"])
            if item.get("document_version"):
                ev_dict["document_version"] = dict(item["document_version"])
            evidences.append(ev_dict)

        canonical_path: list[dict[str, Any]] = []
        for item in row.get("canonical_path_rows") or []:
            if not item:
                continue
            source_props = item.get("source")
            ref_props = item.get("ref")
            target_props = item.get("target")
            depicted_props = item.get("depicted")
            source_label = item.get("source_label")
            target_label = item.get("target_label")
            if source_props and ref_props:
                canonical_path.append({
                    "from": source_props.get("id"),
                    "from_label": source_label,
                    "edge": "REFERENCES",
                    "to": ref_props.get("id"),
                    "to_label": "Reference",
                    "source": dict(source_props),
                    "target": dict(ref_props),
                })
            if ref_props and target_props:
                canonical_path.append({
                    "from": ref_props.get("id"),
                    "from_label": "Reference",
                    "edge": "RESOLVES_TO",
                    "to": target_props.get("id"),
                    "to_label": target_label,
                    "source": dict(ref_props),
                    "target": dict(target_props),
                })
            if target_props and depicted_props:
                canonical_path.append({
                    "from": target_props.get("id"),
                    "from_label": target_label,
                    "edge": "DEPICTS",
                    "to": depicted_props.get("id"),
                    "to_label": "ArchaeologyObject",
                    "source": dict(target_props),
                    "target": dict(depicted_props),
                })

        return {
            "candidate": cand_props,
            "archaeology_object": obj_props,
            "evidence": evidences,
            "decisions": decisions,
            "latest_decision": compute_latest_decision(decisions),
            "canonical_path": canonical_path,
        }

    def get_candidates(
        self,
        project_id: str,
        status: str | None = None,
        rule_category: str | None = None,
        archaeology_object_id: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._driver is None:
            return []
        cypher = """
        MATCH (proj:Project {id: $project_id})-[:HAS_CANDIDATE]->(cand:CorrectionCandidate)
        WHERE ($status IS NULL OR cand.status = $status)
          AND ($rule_category IS NULL OR cand.rule_category = $rule_category)
          AND ($severity IS NULL OR cand.severity = $severity)
          AND ($archaeology_object_id IS NULL OR cand.archaeology_object_id = $archaeology_object_id OR (cand)-[:ABOUT]->(:ArchaeologyObject {id: $archaeology_object_id}))
        OPTIONAL MATCH (cand)-[:ABOUT]->(obj:ArchaeologyObject)
        OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
        OPTIONAL MATCH (cand)-[:HAS_DECISION]->(dec:ReviewDecision)
        RETURN properties(cand) AS candidate,
               obj.id AS obj_id,
               collect(DISTINCT properties(ev)) AS evidences,
               collect(DISTINCT properties(dec)) AS decisions
        """
        records, _, _ = self._driver.execute_query(
            cypher,
            project_id=project_id,
            status=status,
            rule_category=rule_category,
            archaeology_object_id=archaeology_object_id,
            severity=severity,
            **self._query_config(),
        )
        results: list[dict[str, Any]] = []
        for row in records:
            cand_dict = dict(row["candidate"]) if row.get("candidate") else {}
            ev_list = [dict(e) for e in (row.get("evidences") or []) if e]
            cand_dict["evidence"] = ev_list[0] if ev_list else None
            cand_dict["evidences"] = ev_list
            decisions = [dict(d) for d in (row.get("decisions") or []) if d]
            cand_dict["decisions"] = decisions
            cand_dict["latest_decision"] = compute_latest_decision(decisions)
            if row.get("obj_id"):
                cand_dict["archaeology_object_id"] = row["obj_id"]
            results.append(cand_dict)
        return results

    @staticmethod
    def compute_metrics_for_candidates(
        project_id: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total = len(candidates)
        accepted = rejected = modified = deferred = 0
        by_category: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for candidate in candidates:
            latest = compute_latest_decision(candidate.get("decisions") or [])
            outcome = latest.get("decision_status") if latest else None
            if outcome == "accepted":
                accepted += 1
            elif outcome == "rejected":
                rejected += 1
            elif outcome == "modified":
                modified += 1
            elif outcome == "deferred":
                deferred += 1
            category = candidate.get("rule_category") or candidate.get("category") or "unknown"
            severity = candidate.get("severity") or "medium"
            status = candidate.get("status") or "unknown"
            by_category[category] = by_category.get(category, 0) + 1
            by_severity[severity] = by_severity.get(severity, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1

        resolved = accepted + rejected + modified + deferred
        pending = total - resolved
        completion = resolved / total if total else 0.0
        decided_non_deferred = accepted + rejected + modified
        accuracy = accepted / decided_non_deferred if decided_non_deferred else 0.0
        return {
            "project_id": project_id,
            "total_candidates": total,
            "pending_candidates": pending,
            "accepted_candidates": accepted,
            "rejected_candidates": rejected,
            "modified_candidates": modified,
            "deferred_candidates": deferred,
            "by_category": by_category,
            "by_status": by_status,
            "by_severity": by_severity,
            "completion_rate": completion,
            "accuracy_rate": accuracy,
        }

    def get_metrics(self, project_id: str) -> dict[str, Any]:
        if self._driver is None:
            return self.compute_metrics_for_candidates(project_id, [])
        return self.compute_metrics_for_candidates(
            project_id,
            self.get_candidates(project_id),
        )
