from typing import Any
from neo4j import Driver
from app.domain.document_structure import ParsedPage
from app.domain.review_models import CorrectionCandidateData
from app.services.page_aligner import AlignedPageRow


class ReviewRepository:
    def __init__(self, driver: Driver | None, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    def _query_config(self) -> dict[str, Any]:
        return {"database_": self._database} if self._database is not None else {}

    def _page_to_param(self, version_id: str, page: ParsedPage) -> dict[str, Any]:
        page_id = f"{version_id}_p{page.physical_page}"
        return {
            "id": page_id,
            "physical_page": page.physical_page,
            "printed_page": page.printed_page,
            "header": page.header,
            "normalized_text": page.normalized_text,
            "blocks": [
                {
                    "id": f"{page_id}_b{b.order}",
                    "text": b.text,
                    "normalized_text": b.normalized_text,
                    "order": b.order,
                    "block_type": b.block_type,
                }
                for b in page.text_blocks
            ],
            "captions": [
                {
                    "id": f"{page_id}_{c.caption_id}",
                    "raw_text": c.raw_text,
                    "drawing_number": c.drawing_number,
                    "plate_number": c.plate_number,
                    "is_blank_reference": c.is_blank_reference,
                }
                for c in page.captions
            ],
        }

    def _candidate_to_param(self, cand: CorrectionCandidateData) -> dict[str, Any]:
        ev = cand.evidence
        evidence_id = f"ev_{cand.candidate_id}"
        return {
            "candidate_id": cand.candidate_id,
            "rule_category": cand.rule_category,
            "change_type": cand.change_type,
            "status": cand.status,
            "original_text": cand.original_text,
            "proposed_text": cand.proposed_text,
            "evidence": {
                "id": evidence_id,
                "version_from": ev.version_from,
                "version_to": ev.version_to,
                "physical_page_from": ev.physical_page_from,
                "physical_page_to": ev.physical_page_to,
                "printed_page_from": ev.printed_page_from,
                "printed_page_to": ev.printed_page_to,
                "rule_name": ev.rule_name,
                "rationale": ev.rationale,
            },
        }

    def save_pages_and_blocks(
        self, version_id: str, pages: list[ParsedPage]
    ) -> None:
        if self._driver is None:
            return

        page_params = [self._page_to_param(version_id, p) for p in pages]
        cypher = """
        MATCH (v:DocumentVersion {id: $version_id})
        UNWIND $pages AS p
        MERGE (page:Page {id: p.id})
        SET page.physical_page = p.physical_page,
            page.printed_page = p.printed_page,
            page.header = p.header,
            page.normalized_text = p.normalized_text
        MERGE (v)-[:HAS_PAGE]->(page)
        WITH page, p
        UNWIND p.blocks AS b
        MERGE (block:TextBlock {id: b.id})
        SET block.text = b.text,
            block.normalized_text = b.normalized_text,
            block.order = b.order,
            block.block_type = b.block_type
        MERGE (page)-[:HAS_BLOCK]->(block)
        """
        self._driver.execute_query(
            cypher,
            version_id=version_id,
            pages=page_params,
            **self._query_config(),
        )

    def save_candidates(
        self,
        project_id: str,
        candidates: list[CorrectionCandidateData],
        analysis_run_id: str | None = None,
    ) -> None:
        if self._driver is None:
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
            cand.proposed_text = c.proposed_text
        MERGE (proj)-[:HAS_CANDIDATE]->(cand)
        WITH cand, c
        MERGE (ev:Evidence {id: c.evidence.id})
        SET ev.version_from = c.evidence.version_from,
            ev.version_to = c.evidence.version_to,
            ev.physical_page_from = c.evidence.physical_page_from,
            ev.physical_page_to = c.evidence.physical_page_to,
            ev.printed_page_from = c.evidence.printed_page_from,
            ev.printed_page_to = c.evidence.printed_page_to,
            ev.rule_name = c.evidence.rule_name,
            ev.rationale = c.evidence.rationale
        MERGE (cand)-[:SUPPORTED_BY]->(ev)
        """
        self._driver.execute_query(
            cypher,
            project_id=project_id,
            candidates=cand_params,
            **self._query_config(),
        )

        if analysis_run_id:
            link_run_cypher = """
            MATCH (run:AnalysisRun {id: $analysis_run_id})
            UNWIND $candidate_ids AS cid
            MATCH (cand:CorrectionCandidate {id: cid})
            MERGE (run)-[:PRODUCED]->(cand)
            """
            self._driver.execute_query(
                link_run_cypher,
                analysis_run_id=analysis_run_id,
                candidate_ids=[c.candidate_id for c in candidates],
                **self._query_config(),
            )

    def save_analysis_run(
        self,
        project_id: str,
        run_id: str,
        status: str = "pending",
        model: str | None = None,
        step: str | None = None,
    ) -> None:
        if self._driver is None:
            return

        cypher = """
        MATCH (proj:Project {id: $project_id})
        MERGE (run:AnalysisRun {id: $run_id})
        SET run.status = $status,
            run.model = $model,
            run.step = $step
        MERGE (proj)-[:HAS_RUN]->(run)
        """
        self._driver.execute_query(
            cypher,
            project_id=project_id,
            run_id=run_id,
            status=status,
            model=model,
            step=step,
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
    ) -> None:
        if self._driver is None:
            return

        cypher = """
        MATCH (cand:CorrectionCandidate {id: $candidate_id})
        MERGE (dec:ReviewDecision {id: $decision_id})
        SET dec.decision_status = $decision_status,
            dec.note = $note,
            dec.reviewer = $reviewer
        MERGE (cand)-[:HAS_DECISION]->(dec)
        WITH dec
        WHERE $previous_decision_id IS NOT NULL
        OPTIONAL MATCH (prev:ReviewDecision {id: $previous_decision_id})
        FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
            MERGE (dec)-[:SUPERSEDES]->(prev)
        )
        """
        self._driver.execute_query(
            cypher,
            decision_id=decision_id,
            candidate_id=candidate_id,
            decision_status=decision_status,
            note=note,
            reviewer=reviewer,
            previous_decision_id=previous_decision_id,
            **self._query_config(),
        )

    def get_candidates(self, project_id: str) -> list[dict[str, Any]]:
        if self._driver is None:
            return []

        cypher = """
        MATCH (proj:Project {id: $project_id})-[:HAS_CANDIDATE]->(cand:CorrectionCandidate)
        OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
        OPTIONAL MATCH (cand)-[:HAS_DECISION]->(dec:ReviewDecision)
        RETURN properties(cand) AS candidate,
               properties(ev) AS evidence,
               collect(DISTINCT properties(dec)) AS decisions
        """
        records, _, _ = self._driver.execute_query(
            cypher,
            project_id=project_id,
            **self._query_config(),
        )
        results = []
        for row in records:
            cand_dict = dict(row["candidate"]) if row.get("candidate") else {}
            cand_dict["evidence"] = dict(row["evidence"]) if row.get("evidence") else None
            cand_dict["decisions"] = [dict(d) for d in (row.get("decisions") or [])]
            results.append(cand_dict)
        return results
