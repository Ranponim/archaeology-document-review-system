from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from app.config import DATA_ROOT
from app.domain.canonical_models import ReferenceData
from app.domain.document_structure import ParsedPage, make_page_id
from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.services.graph_rules import GraphBodyRegion, GraphRuleFinding
from app.services.proofreading_orchestrator import OrchestratorResult
from app.services.review_round_orchestrator import ReviewRoundProofreadingOrchestrator


class GraphFirstReviewRoundOrchestrator(ReviewRoundProofreadingOrchestrator):
    """ReferenceCorpus-native proofreading while preserving legacy rounds.

    A call without ``reference_corpus_id`` delegates unchanged to the historical
    ReviewRound orchestrator.  A corpus call never lets legacy visual PDFs,
    global RESOLVES_TO edges, or StrictRuleEngine choose visual identity.
    """

    def __init__(
        self,
        *args: Any,
        graph_rule_engine: Any,
        corpus_object_linker: Any,
        **kwargs: Any,
    ) -> None:
        self.graph_rule_engine = graph_rule_engine
        self.corpus_object_linker = corpus_object_linker
        super().__init__(*args, **kwargs)

    async def run_proofreading(
        self,
        *args: Any,
        reference_corpus_id: str | None = None,
        **kwargs: Any,
    ) -> OrchestratorResult:
        if reference_corpus_id is None:
            return await super().run_proofreading(*args, **kwargs)
        if args:
            raise TypeError(
                "ReferenceCorpus mode requires keyword arguments so graph authority "
                "cannot be confused with legacy positional visual inputs"
            )
        return await self._run_reference_corpus_proofreading(
            reference_corpus_id=reference_corpus_id,
            **kwargs,
        )

    @staticmethod
    def _semantic_topics(text: str) -> tuple[str, ...]:
        normalized = (text or "").lower()
        topics: list[str] = []
        if any(
            token in normalized
            for token in (
                "방향",
                "북쪽",
                "남쪽",
                "동쪽",
                "서쪽",
                "orientation",
                "north",
                "south",
                "east",
                "west",
            )
        ):
            topics.append("orientation")
        if any(
            token in normalized
            for token in ("배치", "중첩", "겹", "형상", "geometry", "overlap")
        ):
            topics.append("geometry")
        return tuple(topics)

    @staticmethod
    def _page_id(body_version_id: str, page: ParsedPage) -> str:
        return page.page_id or make_page_id(body_version_id, page.physical_page)

    def _resolve_body_pages(
        self,
        *,
        body_version_id: str,
        body_pages: list[ParsedPage] | None,
        version_pages: dict[str, list[ParsedPage]] | None,
        version_stage: str,
        body_pdf_path: str | Path | None,
    ) -> list[ParsedPage]:
        if body_pages is not None:
            return list(body_pages)
        if version_pages:
            if version_pages.get("current"):
                return list(version_pages["current"])
            if version_pages.get(version_stage):
                return list(version_pages[version_stage])
            non_empty = [pages for pages in version_pages.values() if pages]
            if non_empty:
                return list(non_empty[-1])

        source_path: Path | None = None
        if body_pdf_path is not None:
            source_path = Path(body_pdf_path)
        elif self.project_repo is not None:
            version = self.project_repo.get_document_version_by_id(body_version_id)
            if version is not None and getattr(version, "uri", None):
                candidate = DATA_ROOT / version.uri
                if candidate.is_file():
                    source_path = candidate
                elif Path(version.uri).is_file():
                    source_path = Path(version.uri)
        if source_path is None or not source_path.is_file():
            raise ValueError(
                f"ReferenceCorpus review has no parseable body source for '{body_version_id}'"
            )
        pages = self.pdf_parser.parse_pdf(source_path, version_id=body_version_id)
        return list(pages)

    @staticmethod
    def _collect_references(pages: list[ParsedPage]) -> list[ReferenceData]:
        result: list[ReferenceData] = []
        for page in pages:
            for block in page.text_blocks:
                for reference in block.references:
                    result.append(
                        ReferenceData(
                            ref_type=reference.ref_type,
                            number=reference.number,
                            source_block_id=block.block_id,
                            raw_text=reference.raw_text,
                            source_sha256=(
                                reference.source_sha256
                                or block.source_sha256
                                or page.source_sha256
                            ),
                            bbox=reference.bbox or block.bbox,
                            physical_page=(
                                reference.physical_page or page.physical_page
                            ),
                        )
                    )
            for caption in page.captions:
                for reference in caption.references:
                    result.append(
                        ReferenceData(
                            ref_type=reference.ref_type,
                            number=reference.number,
                            source_block_id=caption.caption_id,
                            raw_text=reference.raw_text,
                            source_sha256=(
                                reference.source_sha256
                                or caption.source_sha256
                                or page.source_sha256
                            ),
                            bbox=reference.bbox or caption.bbox,
                            physical_page=(
                                reference.physical_page or page.physical_page
                            ),
                        )
                    )
        return result

    def _body_region_maps(
        self,
        *,
        body_version_id: str,
        pages: list[ParsedPage],
        objects: list[Any],
    ) -> tuple[dict[str, list[GraphBodyRegion]], dict[str, dict[str, Any]]]:
        source_map: dict[str, dict[str, Any]] = {}
        for page in pages:
            page_id = self._page_id(body_version_id, page)
            for block in page.text_blocks:
                source_map[block.block_id] = {
                    "page_id": page_id,
                    "physical_page": page.physical_page,
                    "printed_page": page.printed_page,
                    "text": block.text,
                    "bbox": block.bbox,
                    "source_sha256": block.source_sha256 or page.source_sha256,
                }
            for caption in page.captions:
                source_map[caption.caption_id] = {
                    "page_id": page_id,
                    "physical_page": page.physical_page,
                    "printed_page": page.printed_page,
                    "text": caption.raw_text,
                    "bbox": caption.bbox,
                    "source_sha256": caption.source_sha256 or page.source_sha256,
                }

        regions_by_object: dict[str, list[GraphBodyRegion]] = {}
        for obj in objects:
            regions: list[GraphBodyRegion] = []
            for source_id in getattr(obj, "source_block_ids", []) or []:
                source = source_map.get(source_id)
                if source is None:
                    continue
                text = str(source.get("text") or "")
                regions.append(
                    GraphBodyRegion(
                        source_block_id=source_id,
                        text=text,
                        semantic_topics=self._semantic_topics(text),
                    )
                )
            regions_by_object[obj.object_id] = regions
        return regions_by_object, source_map

    @staticmethod
    def _candidate_fingerprint(finding: GraphRuleFinding) -> str:
        payload = {
            "ruleCode": finding.rule_code,
            "objectId": finding.archaeology_object_id,
            "corpusId": finding.reference_corpus_id,
            "sourceBlockId": finding.source_block_id,
            "targets": list(finding.canonical_target_ids),
            "original": finding.original_text,
            "proposed": finding.proposed_text,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _finding_to_candidate(
        self,
        *,
        finding: GraphRuleFinding,
        run_id: str,
        body_version_id: str,
        pages: list[ParsedPage],
        objects_by_id: dict[str, Any],
        source_map: dict[str, dict[str, Any]],
    ) -> tuple[CorrectionCandidateData, EvidenceData]:
        source_id = finding.source_block_id
        obj = objects_by_id.get(finding.archaeology_object_id or "")
        if source_id is None and obj is not None:
            source_id = next(
                (
                    item
                    for item in (getattr(obj, "source_block_ids", []) or [])
                    if item in source_map
                ),
                None,
            )
        source = source_map.get(source_id or "")
        if source is None:
            if not pages:
                raise ValueError("graph finding has no body provenance anchor")
            page = pages[0]
            source = {
                "page_id": self._page_id(body_version_id, page),
                "physical_page": page.physical_page,
                "printed_page": page.printed_page,
                "text": page.normalized_text or page.raw_text,
                "bbox": None,
                "source_sha256": page.source_sha256,
            }

        source_sha256 = str(
            source.get("source_sha256") or f"sha256_{body_version_id}"
        )
        fingerprint = self._candidate_fingerprint(finding)
        evidence = EvidenceData(
            id=f"ev_graph_{fingerprint[:20]}",
            kind="rule_finding",
            source_sha256=source_sha256,
            document_version_id=body_version_id,
            page_id=str(source["page_id"]),
            region_id=source_id,
            bbox=source.get("bbox"),
            method="graph_rule_engine",
            analysis_run_id=run_id,
            value={
                "ruleCode": finding.rule_code,
                "referenceCorpusId": finding.reference_corpus_id,
                "canonicalTargetIds": list(finding.canonical_target_ids),
                "graphEvidenceIds": list(finding.evidence_ids),
                "requiresAi": finding.requires_ai,
            },
            rationale=finding.rationale,
            confidence=1.0 if not finding.requires_ai else 0.5,
            physical_page_from=source.get("physical_page"),
            physical_page_to=source.get("physical_page"),
            printed_page_from=source.get("printed_page"),
            printed_page_to=source.get("printed_page"),
            rule_name=finding.rule_code,
        )
        category = (
            "direction_period_term"
            if finding.rule_code == "SEMANTIC_REVIEW_REQUIRED"
            else "figure_plate_table_photo_ref"
        )
        change_type = (
            "added" if finding.rule_code == "VISUAL_REFERENCE_MISSING" else "modified"
        )
        candidate = CorrectionCandidateData(
            candidate_id=f"cand_graph_{fingerprint[:20]}",
            rule_category=category,
            change_type=change_type,
            status="pending_review",
            original_text=finding.original_text,
            proposed_text=finding.proposed_text,
            evidence=evidence,
            evidence_list=[evidence],
            archaeology_object_id=finding.archaeology_object_id,
            confidence=1.0 if not finding.requires_ai else 0.5,
            analysis_run_id=run_id,
            severity=finding.severity,
            finding_fingerprint=fingerprint,
        )
        return candidate, evidence

    async def _run_reference_corpus_proofreading(
        self,
        *,
        project_id: str,
        body_version_id: str,
        reference_corpus_id: str,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        body_pdf_path: str | Path | None = None,
        plate_pdf_path: str | Path | None = None,
        drawing_pdf_path: str | Path | None = None,
        body_pages: list[ParsedPage] | None = None,
        plate_index: Any | None = None,
        drawing_index: Any | None = None,
        analysis_run_id: str | None = None,
        enable_vlm: bool = False,
        enable_ai_review: bool = False,
        version_stage: str = "1차",
        version_pages: dict[str, list[ParsedPage]] | None = None,
        version_ids: dict[str, str] | None = None,
        **_: Any,
    ) -> OrchestratorResult:
        del plate_version_id, drawing_version_id, plate_pdf_path, drawing_pdf_path
        if not reference_corpus_id.strip():
            raise ValueError("reference_corpus_id cannot be empty")
        if self.graph_rule_engine is None or self.corpus_object_linker is None:
            raise RuntimeError(
                "ReferenceCorpus review requires graph_rule_engine and corpus_object_linker"
            )

        run_id = analysis_run_id or f"run_{uuid.uuid4().hex[:12]}"
        pages = self._resolve_body_pages(
            body_version_id=body_version_id,
            body_pages=body_pages,
            version_pages=version_pages,
            version_stage=version_stage,
            body_pdf_path=body_pdf_path,
        )
        if not pages:
            raise ValueError(
                f"Body document '{body_version_id}' produced zero parsed pages"
            )

        if self.review_repo is not None:
            self.review_repo.save_analysis_run(
                project_id=project_id,
                run_id=run_id,
                status="running",
                step="graph_first",
            )
            self.review_repo.save_pages_and_blocks(
                version_id=body_version_id,
                pages=pages,
            )

        if version_pages and len(version_pages) >= 2:
            self.persist_version_alignment(
                project_id=project_id,
                version_pages=version_pages,
                version_ids=version_ids or {},
                run_id=run_id,
            )

        blocks = [block for page in pages for block in page.text_blocks]
        captions = [caption for page in pages for caption in page.captions]
        object_results = self.object_resolver.resolve_mentions(
            blocks=blocks,
            captions=captions,
            project_id=project_id,
        )
        objects = [item.object_data for item in object_results]

        if self.canonical_repo is None:
            raise RuntimeError(
                "ReferenceCorpus graph-first review requires canonical repository"
            )
        if objects:
            self.canonical_repo.save_archaeology_objects(
                objects=objects,
                project_id=project_id,
            )

        # Order is authority: body objects must exist before selected-corpus
        # visuals can receive DEPICTS edges.
        self.corpus_object_linker.link(project_id, reference_corpus_id, objects)

        references = self._collect_references(pages)
        if references:
            self.canonical_repo.save_references(references)

        regions_by_object, source_map = self._body_region_maps(
            body_version_id=body_version_id,
            pages=pages,
            objects=objects,
        )
        findings = self.graph_rule_engine.run(
            project_id=project_id,
            reference_corpus_id=reference_corpus_id,
            analysis_run_id=run_id,
            archaeology_object_ids=[obj.object_id for obj in objects],
            body_regions_by_object=regions_by_object,
        )

        objects_by_id = {obj.object_id: obj for obj in objects}
        candidates: list[CorrectionCandidateData] = []
        evidences: list[EvidenceData] = []
        seen_fingerprints: set[str] = set()
        for finding in findings:
            candidate, evidence = self._finding_to_candidate(
                finding=finding,
                run_id=run_id,
                body_version_id=body_version_id,
                pages=pages,
                objects_by_id=objects_by_id,
                source_map=source_map,
            )
            if candidate.finding_fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(candidate.finding_fingerprint or candidate.candidate_id)
            candidates.append(candidate)
            evidences.append(evidence)

        if self.review_repo is not None:
            if evidences:
                self.review_repo.save_evidences(evidences)
            if candidates:
                self.review_repo.save_candidates(
                    project_id=project_id,
                    candidates=candidates,
                    analysis_run_id=run_id,
                )
            self.review_repo.save_analysis_run(
                project_id=project_id,
                run_id=run_id,
                status="completed",
                step="complete",
            )

        warnings: list[str] = []
        if enable_ai_review or enable_vlm:
            warnings.append(
                "optional semantic AI/VLM escalation requested; graph findings were "
                "preserved without delegating canonical identity"
            )

        plates = list(getattr(plate_index, "plates", []) or [])
        drawings = list(getattr(drawing_index, "drawings", []) or [])
        return OrchestratorResult(
            project_id=project_id,
            analysis_run_id=run_id,
            status="completed",
            pages_parsed=len(pages),
            objects_resolved=len(objects),
            references_resolved=len(references),
            candidates=candidates,
            evidences=evidences,
            objects=objects,
            plates=plates,
            drawings=drawings,
            summary={
                "mode": "reference_corpus",
                "reference_corpus_id": reference_corpus_id,
                "graph_findings": len(findings),
                "pending_candidates": len(candidates),
                "enable_ai_review": bool(enable_ai_review),
                "enable_vlm": bool(enable_vlm),
            },
            errors=[],
            warnings=warnings,
            unresolved=[],
        )
