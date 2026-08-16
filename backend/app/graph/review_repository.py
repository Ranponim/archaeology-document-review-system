import json
from typing import Any
from neo4j import Driver
from app.domain.document_structure import (
    ParsedPage,
    make_block_id,
    make_caption_id,
    make_page_id,
)
from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.graph.project_repository import DocumentVersionNotFoundError
from app.services.page_aligner import AlignedPageRow, AlignmentStatus


DECISION_VALUES: tuple[str, ...] = ("accepted", "rejected", "modified", "deferred")


def compute_latest_decision(decisions: list[dict]) -> dict | None:
    """Most recent ReviewDecision by created_at (chronologically last append)."""
    if not decisions:
        return None
    return max(decisions, key=lambda d: str(d.get("created_at") or "") or str(d.get("id") or ""))


def compute_review_metrics(project_id: str, candidates: list[dict]) -> dict[str, Any]:
    """Metrics from the latest ReviewDecision per candidate; the frozen
    candidate.status (generation status) never counts as an expert outcome."""
    total = len(candidates)
    accepted = rejected = modified = deferred = 0
    by_cat: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for c in candidates:
        latest = compute_latest_decision(c.get("decisions") or [])
        outcome = latest.get("decision_status") if latest else None
        if outcome == "accepted":
            accepted += 1
        elif outcome == "rejected":
            rejected += 1
        elif outcome == "modified":
            modified += 1
        elif outcome == "deferred":
            deferred += 1
        cat = c.get("rule_category") or c.get("category") or "unknown"
        by_cat[cat] = by_cat.get(cat, 0) + 1
        st = c.get("status") or "unknown"
        by_status[st] = by_status.get(st, 0) + 1

    resolved = accepted + rejected + modified + deferred
    pending = total - resolved
    completion = resolved / total if total > 0 else 0.0
    heuristically_accurate = accepted + rejected + modified
    accuracy = accepted / heuristically_accurate if heuristically_accurate > 0 else 0.0

    return {
        "project_id": project_id,
        "total_candidates": total,
        "pending_candidates": pending,
        "accepted_candidates": accepted,
        "rejected_candidates": rejected,
        "modified_candidates": modified,
        "deferred_candidates": deferred,
        "by_category": by_cat,
        "by_status": by_status,
        "by_severity": {"high": 0, "medium": total, "low": 0},
        "completion_rate": completion,
        "accuracy_rate": accuracy,
    }


class ReviewRepository:
    def __init__(self, driver: Driver | None, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    def _query_config(self) -> dict[str, Any]:
        return {"database_": self._database} if self._database is not None else {}

    def _page_to_param(self, version_id: str, page: ParsedPage) -> dict[str, Any]:
        page_id = page.page_id or make_page_id(version_id, page.physical_page)
        return {
            "id": page_id,
            "physical_page": page.physical_page,
            "printed_page": page.printed_page,
            "header": page.header,
            "normalized_text": page.normalized_text,
            "blocks": [
                {
                    "id": b.block_id or make_block_id(version_id, page.physical_page, b.order),
                    "text": b.text,
                    "normalized_text": b.normalized_text,
                    "order": b.order,
                    "block_type": b.block_type,
                }
                for b in page.text_blocks
            ],
            "captions": [
                {
                    "id": c.caption_id or make_caption_id(version_id, page.physical_page, idx + 1),
                    "raw_text": c.raw_text,
                    "drawing_number": c.drawing_number,
                    "plate_number": c.plate_number,
                    "is_blank_reference": c.is_blank_reference,
                }
                for idx, c in enumerate(page.captions)
            ],
        }

    def _evidence_to_param(
        self, ev: EvidenceData, fallback_id: str | None = None
    ) -> dict[str, Any]:
        ev_id = ev.id if ev.id else (fallback_id or f"ev_{id(ev)}")
        val = ev.value
        if val is not None and not isinstance(val, (str, int, float, bool)):
            val = json.dumps(val, ensure_ascii=False)

        return {
            "id": ev_id,
            "kind": ev.kind,
            "source_sha256": ev.source_sha256,
            "document_version_id": ev.document_version_id,
            "page_id": ev.page_id,
            "region_id": ev.region_id,
            "bbox": list(ev.bbox) if ev.bbox is not None else None,
            "method": ev.method,
            "analysis_run_id": ev.analysis_run_id,
            "value": val if val is not None else "",
            "rationale": ev.rationale,
            "confidence": ev.confidence,
            "version_from": ev.version_from,
            "version_to": ev.version_to,
            "physical_page_from": ev.physical_page_from,
            "physical_page_to": ev.physical_page_to,
            "printed_page_from": ev.printed_page_from,
            "printed_page_to": ev.printed_page_to,
            "rule_name": ev.rule_name,
        }

    def _candidate_to_param(self, cand: CorrectionCandidateData) -> dict[str, Any]:
        ev_params: list[dict[str, Any]] = []
        if cand.evidence is not None:
            ev_params.append(
                self._evidence_to_param(
                    cand.evidence, fallback_id=f"ev_{cand.candidate_id}"
                )
            )
        for idx, ev in enumerate(cand.evidence_list):
            ev_param = self._evidence_to_param(
                ev, fallback_id=f"ev_{cand.candidate_id}_{idx+1}"
            )
            if not any(p["id"] == ev_param["id"] for p in ev_params):
                ev_params.append(ev_param)

        primary_evidence = ev_params[0] if ev_params else None

        return {
            "candidate_id": cand.candidate_id,
            "rule_category": cand.rule_category,
            "change_type": cand.change_type,
            "status": cand.status,
            "original_text": cand.original_text,
            "proposed_text": cand.proposed_text,
            "confidence": cand.confidence,
            "archaeology_object_id": cand.archaeology_object_id,
            "analysis_run_id": cand.analysis_run_id,
            "evidence": primary_evidence,
            "evidences": ev_params,
        }

    def save_pages_and_blocks(
        self, version_id: str, pages: list[ParsedPage]
    ) -> None:
        if self._driver is None:
            return

        page_params = [self._page_to_param(version_id, p) for p in pages]
        cypher = """
        OPTIONAL MATCH (v:DocumentVersion {id: $version_id})
        UNWIND $pages AS p
        MERGE (page:Page {id: p.id})
        SET page.physical_page = p.physical_page,
            page.printed_page = p.printed_page,
            page.header = p.header,
            page.normalized_text = p.normalized_text
        FOREACH (_ IN CASE WHEN v IS NOT NULL THEN [1] ELSE [] END |
            MERGE (v)-[:HAS_PAGE]->(page)
        )
        WITH page, p
        FOREACH (b IN p.blocks |
            MERGE (block:TextBlock {id: b.id})
            SET block.text = b.text,
                block.normalized_text = b.normalized_text,
                block.order = b.order,
                block.block_type = b.block_type
            MERGE (page)-[:HAS_BLOCK]->(block)
        )
        FOREACH (c IN p.captions |
            MERGE (cap:Caption {id: c.id})
            SET cap.raw_text = c.raw_text,
                cap.drawing_number = c.drawing_number,
                cap.plate_number = c.plate_number,
                cap.is_blank_reference = c.is_blank_reference
            MERGE (page)-[:HAS_CAPTION]->(cap)
        )
        """
        self._driver.execute_query(
            cypher,
            version_id=version_id,
            pages=page_params,
            **self._query_config(),
        )

    def save_version_precedes(
        self, project_id: str, versions: list[tuple[str, str]]
    ) -> None:
        """MERGE (v1:DocumentVersion)-[:PRECEDES]->(v2:DocumentVersion) for the
        ordered version list (1차→2차→3차).

        Versions are passed as an ordered list of (version_id, stage). Existing
        DocumentVersion nodes are hard-MATCHed by id; if any node is missing the
        method fails closed (raises) rather than silently skipping (plan §3
        Gate G). project_id is accepted for API symmetry; versions are matched
        by id.
        """
        if self._driver is None:
            return
        if len(versions) < 2:
            return

        pairs = [
            {"from_id": versions[i][0], "to_id": versions[i + 1][0]}
            for i in range(len(versions) - 1)
        ]
        cypher = """
        UNWIND $pairs AS p
        MATCH (v1:DocumentVersion {id: p.from_id})
        MATCH (v2:DocumentVersion {id: p.to_id})
        MERGE (v1)-[:PRECEDES]->(v2)
        RETURN count(*) AS matched
        """
        records, _, _ = self._driver.execute_query(
            cypher,
            pairs=pairs,
            **self._query_config(),
        )
        if records and records[0].get("matched") is not None:
            matched = records[0]["matched"]
            if matched != len(pairs):
                raise DocumentVersionNotFoundError(
                    "One or more DocumentVersion nodes missing for PRECEDES "
                    f"(expected {len(pairs)} pairs, matched {matched})"
                )

    def save_aligned_pages(
        self,
        rows: list[AlignedPageRow],
        pages_by_version: dict[str, list[ParsedPage]],
        run_id: str,
        version_ids: dict[str, str],
    ) -> None:
        """MERGE (pageA)-[:ALIGNED_TO {score,status,method,run_id}]->(pageB) for
        each unordered version pair of a row with >=2 versions present and a
        status in the allowed set {exact, probable, manual_review}.

        Page nodes already exist (inserted by the Task 2 body graph) and are
        hard-MATCHed by id (page_id = make_page_id(version_id, physical_page)).
        version_ids maps each stage to its real DocumentVersion id; a stage
        without one fails closed (never fabricates a stage-derived page id).
        Unmatched rows and rows with fewer than two versions produce no edge.
        """
        if self._driver is None:
            return

        missing = [st for st in pages_by_version if not version_ids.get(st)]
        if missing:
            raise ValueError(
                "version_ids missing entries for stages: " + ", ".join(sorted(missing))
            )

        page_ids: dict[str, dict[int, str]] = {}
        for stage, pages in pages_by_version.items():
            version_id = version_ids[stage]
            page_ids[stage] = {
                p.physical_page: (p.page_id or make_page_id(version_id, p.physical_page))
                for p in pages
            }

        edges: list[dict[str, Any]] = []
        for row in rows:
            status = (
                str(row.status.value)
                if isinstance(row.status, AlignmentStatus)
                else str(row.status)
            )
            if status not in ("exact", "probable", "manual_review"):
                continue
            present = [(st, pg) for st, pg in row.pages.items() if pg is not None]
            if len(present) < 2:
                continue
            for idx_a in range(len(present)):
                for idx_b in range(idx_a + 1, len(present)):
                    st_a, page_a = present[idx_a]
                    st_b, page_b = present[idx_b]
                    from_id = (
                        page_ids.get(st_a, {}).get(page_a.physical_page)
                        or page_a.page_id
                        or make_page_id(version_ids[st_a], page_a.physical_page)
                    )
                    to_id = (
                        page_ids.get(st_b, {}).get(page_b.physical_page)
                        or page_b.page_id
                        or make_page_id(version_ids[st_b], page_b.physical_page)
                    )
                    edges.append(
                        {
                            "from_id": from_id,
                            "to_id": to_id,
                            "score": row.similarity_score,
                            "status": status,
                            "method": getattr(row, "method", "dtw_weighted"),
                            "run_id": run_id,
                            "row_id": row.row_id,
                        }
                    )

        if not edges:
            return

        cypher = """
        UNWIND $edges AS e
        MATCH (a:Page {id: e.from_id})
        MATCH (b:Page {id: e.to_id})
        SET a.alignment_row = e.row_id, b.alignment_row = e.row_id
        MERGE (a)-[:ALIGNED_TO {score: e.score, status: e.status, method: e.method, run_id: e.run_id}]->(b)
        RETURN count(*) AS matched
        """
        records, _, _ = self._driver.execute_query(
            cypher,
            edges=edges,
            **self._query_config(),
        )
        if records and records[0].get("matched") is not None:
            matched = records[0]["matched"]
            if matched != len(edges):
                raise LookupError(
                    "One or more Page nodes missing for ALIGNED_TO "
                    f"(expected {len(edges)} edges, matched {matched})"
                )

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
            cand.confidence = c.confidence
        MERGE (proj)-[:HAS_CANDIDATE]->(cand)
        WITH cand, c
        OPTIONAL MATCH (obj:ArchaeologyObject {id: c.archaeology_object_id})
        FOREACH (_ IN CASE WHEN obj IS NOT NULL THEN [1] ELSE [] END |
            MERGE (cand)-[:ABOUT]->(obj)
        )
        WITH cand, c
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
        WITH ev, ev_param
        OPTIONAL MATCH (p:Page {id: ev_param.page_id})
        FOREACH (_ IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END |
            MERGE (ev)-[:EXTRACTED_FROM]->(p)
        )
        WITH ev, ev_param
        OPTIONAL MATCH (v:DocumentVersion {id: ev_param.document_version_id})
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

        run_id = analysis_run_id
        if not run_id:
            for c in candidates:
                if c.analysis_run_id:
                    run_id = c.analysis_run_id
                    break

        if run_id:
            link_run_cypher = """
            MATCH (run:AnalysisRun {id: $analysis_run_id})
            UNWIND $candidate_ids AS cid
            MATCH (cand:CorrectionCandidate {id: cid})
            MERGE (run)-[:PRODUCED]->(cand)
            """
            self._driver.execute_query(
                link_run_cypher,
                analysis_run_id=run_id,
                candidate_ids=[c.candidate_id for c in candidates],
                **self._query_config(),
            )

    def save_evidences(self, evidences: list[EvidenceData]) -> None:
        if self._driver is None or not evidences:
            return

        ev_params = [self._evidence_to_param(e) for e in evidences]
        cypher = """
        UNWIND $evidences AS e
        MERGE (ev:Evidence {id: e.id})
        SET ev.kind = e.kind,
            ev.source_sha256 = e.source_sha256,
            ev.document_version_id = e.document_version_id,
            ev.page_id = e.page_id,
            ev.region_id = e.region_id,
            ev.bbox = e.bbox,
            ev.method = e.method,
            ev.analysis_run_id = e.analysis_run_id,
            ev.value = e.value,
            ev.rationale = e.rationale,
            ev.confidence = e.confidence,
            ev.version_from = e.version_from,
            ev.version_to = e.version_to,
            ev.physical_page_from = e.physical_page_from,
            ev.physical_page_to = e.physical_page_to,
            ev.printed_page_from = e.printed_page_from,
            ev.printed_page_to = e.printed_page_to,
            ev.rule_name = e.rule_name
        WITH ev, e
        OPTIONAL MATCH (p:Page {id: e.page_id})
        FOREACH (_ IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END |
            MERGE (ev)-[:EXTRACTED_FROM]->(p)
        )
        WITH ev, e
        OPTIONAL MATCH (v:DocumentVersion {id: e.document_version_id})
        FOREACH (_ IN CASE WHEN v IS NOT NULL THEN [1] ELSE [] END |
            MERGE (ev)-[:FROM_VERSION]->(v)
        )
        """
        self._driver.execute_query(
            cypher,
            evidences=ev_params,
            **self._query_config(),
        )

    def create_analysis_run(
        self,
        project_id: str,
        run_id: str,
        *,
        body_version_id: str,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        body_pdf_path: str | None = None,
        plate_pdf_path: str | None = None,
        drawing_pdf_path: str | None = None,
        enable_vlm: bool = True,
        enable_ai_review: bool = True,
        version_stage: str = "1차",
    ) -> None:
        """Create the AnalysisRun node in queued state with the resolved version
        input properties, linked to the project (Task 12). The worker claims
        and executes it asynchronously; heavy work never runs in the request."""
        if self._driver is None:
            return

        cypher = """
        MATCH (proj:Project {id: $project_id})
        MERGE (run:AnalysisRun {id: $run_id})
        SET run.status = 'queued',
            run.step = 'queued',
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
        """
        self._driver.execute_query(
            cypher,
            project_id=project_id,
            run_id=run_id,
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

    def claim_analysis(self, analysis_run_id: str) -> dict | None:
        """Claim a queued proofreading run (status CAS: queued -> running).

        Only one worker can win the claim; a failed+retryable run can be
        reclaimed. Returns the claimed run context or None when another worker
        already owns the run (callers must not re-execute then)."""
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

    def analysis_status(self, analysis_run_id: str) -> str:
        if self._driver is None:
            raise LookupError(analysis_run_id)
        records, _, _ = self._driver.execute_query(
            """
            MATCH (run:AnalysisRun {id: $analysis_run_id})
            RETURN run.status AS status
            """,
            analysis_run_id=analysis_run_id,
            **self._query_config(),
        )
        if not records:
            raise LookupError(analysis_run_id)
        return records[0]["status"]

    def save_analysis_run(
        self,
        project_id: str,
        run_id: str,
        status: str = "pending",
        model: str | None = None,
        step: str | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        if self._driver is None:
            return

        cypher = """
        MATCH (proj:Project {id: $project_id})
        MERGE (run:AnalysisRun {id: $run_id})
        SET run.status = $status,
            run.model = $model,
            run.step = $step
        FOREACH (_ IN CASE WHEN $error_code IS NOT NULL THEN [1] ELSE [] END |
            SET run.errorCode = $error_code
        )
        FOREACH (_ IN CASE WHEN $retryable IS NOT NULL THEN [1] ELSE [] END |
            SET run.retryable = $retryable
        )
        MERGE (proj)-[:HAS_RUN]->(run)
        """
        self._driver.execute_query(
            cypher,
            project_id=project_id,
            run_id=run_id,
            status=status,
            model=model,
            step=step,
            error_code=error_code,
            retryable=retryable,
            **self._query_config(),
        )

    def save_review_decision(
        self,
        decision_id: str,
        candidate_id: str,
        decision_status: str,
        note: str = "",
        reviewer: str = "",
        previous_decision_id: str | None = None,
        modified_text: str | None = None,
    ) -> None:
        """Append an expert ReviewDecision record (Gate F).

        Exactly one of accepted | rejected | modified | deferred. The
        candidate generation status (pending_review) is never touched;
        earlier decisions stay queryable and are chained through SUPERSEDES
        plus a persisted previous_decision_id property.
        """
        if self._driver is None:
            return

        normalized = str(decision_status).strip().lower()
        if normalized not in DECISION_VALUES:
            raise ValueError(
                f"decision_status must be one of {DECISION_VALUES}, got {decision_status!r}"
            )

        cypher = """
        MATCH (cand:CorrectionCandidate {id: $candidate_id})
        OPTIONAL MATCH (cand)-[:HAS_DECISION]->(prev:ReviewDecision)
        WHERE ($previous_decision_id IS NOT NULL AND prev.id = $previous_decision_id)
           OR ($previous_decision_id IS NULL AND NOT (() -[:SUPERSEDES]-> (prev)) AND prev.id <> $decision_id)
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
            decision_id=decision_id,
            candidate_id=candidate_id,
            decision_status=normalized,
            note=note,
            reviewer=reviewer,
            previous_decision_id=previous_decision_id,
            modified_text=modified_text,
            **self._query_config(),
        )

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        if self._driver is None:
            return None

        cypher = """
        MATCH (cand:CorrectionCandidate {id: $candidate_id})
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

    def get_candidate_traceability(self, candidate_id: str) -> dict[str, Any]:
        if self._driver is None:
            return {}

        cypher = """
        MATCH (cand:CorrectionCandidate {id: $candidate_id})
        OPTIONAL MATCH (cand)-[:ABOUT]->(obj:ArchaeologyObject)
        OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
        OPTIONAL MATCH (ev)-[:EXTRACTED_FROM]->(page:Page)
        OPTIONAL MATCH (ev)-[:FROM_VERSION]->(doc_ver:DocumentVersion)
        OPTIONAL MATCH (cand)-[:HAS_DECISION]->(dec:ReviewDecision)
        RETURN properties(cand) AS candidate_props,
               properties(obj) AS object_props,
               collect(DISTINCT {
                   evidence: properties(ev),
                   page: properties(page),
                   document_version: properties(doc_ver)
               }) AS evidence_chain,
               collect(DISTINCT properties(dec)) AS decisions
        """
        records, _, _ = self._driver.execute_query(
            cypher,
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

        evidences = []
        for item in (row.get("evidence_chain") or []):
            if not item or not item.get("evidence"):
                continue
            ev_dict = dict(item["evidence"])
            if item.get("page"):
                ev_dict["page"] = dict(item["page"])
            if item.get("document_version"):
                ev_dict["document_version"] = dict(item["document_version"])
            evidences.append(ev_dict)

        return {
            "candidate": cand_props,
            "archaeology_object": obj_props,
            "evidence": evidences,
            "decisions": decisions,
            "latest_decision": compute_latest_decision(decisions),
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
            **self._query_config(),
        )
        results = []
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

    def get_metrics(self, project_id: str) -> dict[str, Any]:
        if self._driver is None:
            return {
                "project_id": project_id,
                "total_candidates": 0,
                "pending_candidates": 0,
                "accepted_candidates": 0,
                "rejected_candidates": 0,
                "modified_candidates": 0,
                "deferred_candidates": 0,
                "by_category": {},
                "by_status": {},
                "by_severity": {},
                "completion_rate": 0.0,
                "accuracy_rate": 0.0,
            }

        candidates = self.get_candidates(project_id)
        return compute_review_metrics(project_id, candidates)
