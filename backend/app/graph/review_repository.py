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
        self, project_id: str, candidates: list[CorrectionCandidateData]
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
