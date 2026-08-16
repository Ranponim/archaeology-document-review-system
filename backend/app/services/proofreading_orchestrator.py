from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any
import uuid

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    DrawingRegionData,
    PlateData,
    PlatePanelData,
    ReferenceData,
    ResolutionStatus,
)
from app.domain.document_structure import (
    CaptionData,
    ParsedPage,
    TextBlockData,
    make_reference_id,
)
from app.domain.evidence_bundle import ObjectEvidenceBundle
from app.domain.review_models import (
    CorrectionCandidateData,
    EvidenceData,
)
from app.graph.canonical_repository import CanonicalRepository
from app.graph.project_repository import DocumentVersionNotFoundError
from app.graph.review_repository import ReviewRepository
from app.services.ai_review_service import AIReviewService
from app.services.asset_matcher import AssetMatcher, ResolutionResult
from app.services.asset_review_pipeline import AssetReviewPipeline
from app.services.drawing_parser import DrawingIndex, DrawingParser
from app.services.object_resolver import ObjectResolver
from app.services.page_aligner import PageAligner
from app.services.pdf_parser import PDFParser
from app.services.plate_parser import PlateIndex, PlateParser
from app.services.rule_engine import RuleEngine
from app.services.vlm_review_service import VLMReviewService


@dataclass(frozen=True, slots=True)
class OrchestratorResult:
    project_id: str
    analysis_run_id: str
    status: str
    pages_parsed: int
    objects_resolved: int
    references_resolved: int
    candidates: list[CorrectionCandidateData]
    evidences: list[EvidenceData]
    objects: list[ArchaeologyObjectData]
    plates: list[PlateData]
    drawings: list[DrawingData]
    summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ProofreadingOrchestrator:
    """End-to-End Canonical Proofreading Orchestrator.

    Coordinates PDF structural parsing, Plate Book parsing, Archaeological Object
    resolution, Canonical Reference resolution, RuleEngine consistency checking,
    VLM visual observation, Contextual LLM review, and unified Neo4j persistence.
    """

    def __init__(
        self,
        pdf_parser: PDFParser | None = None,
        plate_parser: PlateParser | None = None,
        drawing_parser: DrawingParser | None = None,
        object_resolver: ObjectResolver | None = None,
        asset_matcher: AssetMatcher | None = None,
        rule_engine: RuleEngine | None = None,
        asset_review_pipeline: AssetReviewPipeline | None = None,
        ai_review_service: AIReviewService | None = None,
        canonical_repo: CanonicalRepository | None = None,
        review_repo: ReviewRepository | None = None,
        vlm_service: VLMReviewService | None = None,
        project_repo: Any | None = None,
    ) -> None:
        self.pdf_parser = pdf_parser or PDFParser()
        self.plate_parser = plate_parser or PlateParser()
        self.drawing_parser = drawing_parser or DrawingParser()
        self.object_resolver = object_resolver or ObjectResolver()
        self.asset_matcher = asset_matcher or AssetMatcher()
        self.rule_engine = rule_engine or RuleEngine()
        self.asset_review_pipeline = asset_review_pipeline
        self.ai_review_service = ai_review_service
        self.canonical_repo = canonical_repo
        self.review_repo = review_repo
        self.vlm_service = vlm_service
        self.project_repo = project_repo

    @staticmethod
    def _compute_sha256(path: Path | str) -> str:
        p = Path(path)
        if not p.is_file():
            return "sha256_unknown"
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    async def run_proofreading(
        self,
        project_id: str,
        body_version_id: str,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        body_pdf_path: str | Path | None = None,
        plate_pdf_path: str | Path | None = None,
        drawing_pdf_path: str | Path | None = None,
        body_pages: list[ParsedPage] | None = None,
        plate_index: PlateIndex | None = None,
        plates: list[PlateData] | None = None,
        drawings: list[DrawingData] | None = None,
        analysis_run_id: str | None = None,
        body_page_range: tuple[int, int] | None = None,
        plate_page_range: tuple[int, int] | None = None,
        enable_vlm: bool = True,
        enable_ai_review: bool = True,
        version_stage: str = "1차",
        project_repo: Any | None = None,
        version_pages: dict[str, list[ParsedPage]] | None = None,
        version_ids: dict[str, str] | None = None,
    ) -> OrchestratorResult:
        run_id = analysis_run_id or f"run_{uuid.uuid4().hex[:12]}"
        errors: list[str] = []
        warnings: list[str] = []
        effective_project_repo = project_repo or self.project_repo

        # 0. Fail-closed validation for body_version_id
        if not body_version_id or not str(body_version_id).strip():
            if self.review_repo is not None:
                self.review_repo.save_analysis_run(
                    project_id=project_id,
                    run_id=run_id,
                    status="failed",
                    step="ingest",
                    error_code="INVALID_BODY_VERSION_ID",
                )
            raise DocumentVersionNotFoundError("body_version_id cannot be empty")

        ver = None
        if effective_project_repo is not None:
            ver = effective_project_repo.get_document_version_by_id(body_version_id)
            if ver is None:
                if self.review_repo is not None:
                    self.review_repo.save_analysis_run(
                        project_id=project_id,
                        run_id=run_id,
                        status="failed",
                        step="ingest",
                        error_code="DOCUMENT_VERSION_NOT_FOUND",
                    )
                raise DocumentVersionNotFoundError(
                    f"DocumentVersion '{body_version_id}' not found for project '{project_id}'"
                )

        # 0. Fail-closed validation for input file paths
        if body_pages is None:
            if body_pdf_path is None and ver is not None and getattr(ver, "uri", None):
                from app.config import DATA_ROOT
                cand_path = DATA_ROOT / ver.uri
                if cand_path.is_file():
                    body_pdf_path = cand_path
                elif Path(ver.uri).is_file():
                    body_pdf_path = Path(ver.uri)

            if body_pdf_path is None:
                if self.review_repo is not None:
                    self.review_repo.save_analysis_run(
                        project_id=project_id,
                        run_id=run_id,
                        status="failed",
                        step="ingest",
                        error_code="BODY_PDF_NOT_PROVIDED",
                    )
                raise ValueError("Neither body_pages nor body_pdf_path was provided")

            p_path = Path(body_pdf_path)
            if not p_path.is_file():
                if self.review_repo is not None:
                    self.review_repo.save_analysis_run(
                        project_id=project_id,
                        run_id=run_id,
                        status="failed",
                        step="ingest",
                        error_code="FILE_NOT_FOUND",
                    )
                raise FileNotFoundError(f"Body PDF file not found at '{body_pdf_path}'")

        if plate_pdf_path is not None:
            pl_path = Path(plate_pdf_path)
            if not pl_path.is_file():
                if self.review_repo is not None:
                    self.review_repo.save_analysis_run(
                        project_id=project_id,
                        run_id=run_id,
                        status="failed",
                        step="ingest",
                        error_code="FILE_NOT_FOUND",
                    )
                raise FileNotFoundError(f"Plate PDF file not found at '{plate_pdf_path}'")

        if drawing_pdf_path is not None:
            dr_path = Path(drawing_pdf_path)
            if not dr_path.is_file():
                if self.review_repo is not None:
                    self.review_repo.save_analysis_run(
                        project_id=project_id,
                        run_id=run_id,
                        status="failed",
                        step="ingest",
                        error_code="FILE_NOT_FOUND",
                    )
                raise FileNotFoundError(f"Drawing PDF file not found at '{drawing_pdf_path}'")

        # 1. Initialize and Record AnalysisRun
        if self.review_repo is not None:
            self.review_repo.save_analysis_run(
                project_id=project_id,
                run_id=run_id,
                status="running",
                step="ingest",
            )

        # 2. Parse / Ingest Body PDF
        parsed_body_pages: list[ParsedPage] = []
        body_sha256: str | None = None
        if body_pages is not None:
            parsed_body_pages = list(body_pages)
            if parsed_body_pages and parsed_body_pages[0].source_sha256:
                body_sha256 = parsed_body_pages[0].source_sha256
        elif body_pdf_path is not None:
            p_path = Path(body_pdf_path)
            body_sha256 = self._compute_sha256(p_path)
            if body_page_range:
                parsed_body_pages = self.pdf_parser.parse_page_range(
                    p_path,
                    start_page=body_page_range[0],
                    end_page=body_page_range[1],
                    version_id=body_version_id,
                )
            else:
                parsed_body_pages = self.pdf_parser.parse_pdf(
                    p_path,
                    version_id=body_version_id,
                )

        if not body_sha256:
            body_sha256 = f"sha256_{body_version_id}"

        # Gate G: a body file that parses to zero pages must not produce a
        # normal completed result (anti-pattern #3).
        if not parsed_body_pages:
            if self.review_repo is not None:
                self.review_repo.save_analysis_run(
                    project_id=project_id,
                    run_id=run_id,
                    status="failed",
                    step="ingest",
                    error_code="ZERO_PAGES_PARSED",
                )
            raise ValueError(
                f"Body document '{body_version_id}' produced zero parsed pages"
            )

        # Persist body pages & text blocks into Neo4j
        if self.review_repo is not None and parsed_body_pages:
            self.review_repo.save_pages_and_blocks(
                version_id=body_version_id,
                pages=parsed_body_pages,
            )

        # Task 8: persist version lineage (PRECEDES) and page alignment
        # (ALIGNED_TO) when multiple body versions are available.
        if version_pages and len(version_pages) >= 2:
            self.persist_version_alignment(
                project_id=project_id,
                version_pages=version_pages,
                version_ids=version_ids or {},
                run_id=run_id,
            )

        # 3. Parse / Ingest Plate Book
        active_plate_index = plate_index
        all_plates: list[PlateData] = []
        plate_sha256: str | None = None

        if active_plate_index is not None:
            all_plates = list(active_plate_index.plates)
        elif plates is not None:
            all_plates = list(plates)
            active_plate_index = PlateIndex(
                plates_by_number={p.number: p for p in all_plates},
                plates=all_plates,
            )
        elif plate_pdf_path is not None:
            pl_path = Path(plate_pdf_path)
            plate_sha256 = self._compute_sha256(pl_path)
            doc_v_id = plate_version_id or "plate_pdf"
            if plate_page_range:
                plate_list = self.plate_parser.parse_page_range(
                    pl_path,
                    start_page=plate_page_range[0],
                    end_page=plate_page_range[1],
                    document_version_id=doc_v_id,
                )
                active_plate_index = PlateIndex(
                    plates_by_number={p.number: p for p in plate_list},
                    plates=plate_list,
                )
            else:
                active_plate_index = self.plate_parser.parse(
                    pl_path,
                    document_version_id=doc_v_id,
                )
            all_plates = list(active_plate_index.plates)
        else:
            active_plate_index = PlateIndex()


        if not plate_sha256:
            plate_sha256 = f"sha256_{plate_version_id or 'plate'}"

        # Persist plates and panels into Neo4j
        if self.canonical_repo is not None and all_plates:
            self.canonical_repo.save_plates(plates=all_plates)

        # 4. Drawings Ingestion
        active_drawing_index: DrawingIndex | None = None
        all_drawings: list[DrawingData] = []
        drawing_sha256: str | None = None

        if drawings is not None:
            all_drawings = list(drawings)
            active_drawing_index = DrawingIndex(
                drawings_by_number={d.number: d for d in all_drawings},
                drawings=all_drawings,
            )
        elif drawing_pdf_path is not None:
            dr_path = Path(drawing_pdf_path)
            drawing_sha256 = self._compute_sha256(dr_path)
            doc_v_id = drawing_version_id or "drawing_pdf"
            active_drawing_index = self.drawing_parser.parse(
                dr_path,
                document_version_id=doc_v_id,
            )
            all_drawings = list(active_drawing_index.drawings)
        else:
            active_drawing_index = DrawingIndex()

        if not drawing_sha256:
            drawing_sha256 = f"sha256_{drawing_version_id or 'drawing'}"

        if self.canonical_repo is not None and all_drawings:
            self.canonical_repo.save_drawings(drawings=all_drawings)

        # 5. Archaeological Objects Extraction & Resolution
        all_blocks: list[TextBlockData] = [
            b for p in parsed_body_pages for b in p.text_blocks
        ]
        all_captions: list[CaptionData] = [
            c for p in parsed_body_pages for c in p.captions
        ]

        obj_resolution_results = self.object_resolver.resolve_mentions(
            blocks=all_blocks,
            captions=all_captions,
            project_id=project_id,
        )
        all_objects = [r.object_data for r in obj_resolution_results]

        if self.canonical_repo is not None and all_objects:
            self.canonical_repo.save_archaeology_objects(objects=all_objects)

        # 5b. Persist DEPICTS links from visual assets to ArchaeologyObjects.
        # Plates/drawings (steps 3-4) and objects (step 5) are already saved,
        # so the MERGE can MATCH the persisted nodes.
        if self.canonical_repo is not None:
            self.canonical_repo.link_visual_assets_to_objects(
                plates=all_plates,
                drawings=all_drawings,
                objects=all_objects,
            )

        # 6. References Extraction & Canonical Resolution
        all_references: list[ReferenceData] = []
        page_by_block_id: dict[str, ParsedPage] = {}
        block_by_id: dict[str, TextBlockData] = {}
        caption_by_id: dict[str, CaptionData] = {}

        for p in parsed_body_pages:
            for b in p.text_blocks:
                page_by_block_id[b.block_id] = p
                block_by_id[b.block_id] = b
                for ref in b.references:
                    ref_with_meta = ReferenceData(
                        ref_type=ref.ref_type,
                        number=ref.number,
                        source_block_id=b.block_id,
                        raw_text=ref.raw_text,
                        source_sha256=ref.source_sha256 or p.source_sha256 or body_sha256,
                        bbox=ref.bbox or b.bbox,
                        physical_page=ref.physical_page or p.physical_page,
                    )
                    all_references.append(ref_with_meta)

            for c in p.captions:
                page_by_block_id[c.caption_id] = p
                caption_by_id[c.caption_id] = c
                for ref in c.references:
                    ref_with_meta = ReferenceData(
                        ref_type=ref.ref_type,
                        number=ref.number,
                        source_block_id=c.caption_id,
                        raw_text=ref.raw_text,
                        source_sha256=ref.source_sha256 or p.source_sha256 or body_sha256,
                        bbox=ref.bbox or c.bbox,
                        physical_page=ref.physical_page or p.physical_page,
                    )
                    all_references.append(ref_with_meta)

        # Persist all Reference nodes first so they exist before linking targets
        if self.canonical_repo is not None and all_references:
            self.canonical_repo.save_references(all_references)

        # Canonically resolve references against PlateIndex and DrawingIndex
        resolved_refs_count = 0
        resolved_resolutions: list[tuple[ReferenceData, ResolutionResult]] = []

        for ref in all_references:
            resolution = self.asset_matcher.resolve_reference(
                reference=ref,
                plate_index=active_plate_index,
                drawing_index=active_drawing_index,
            )
            if resolution.status == ResolutionStatus.RESOLVED and resolution.target is not None:
                resolved_refs_count += 1
                resolved_resolutions.append((ref, resolution))

                if self.canonical_repo is not None:
                    target_label = "Plate" if isinstance(resolution.target, PlateData) else "Drawing"
                    target_id = getattr(resolution.target, "plate_id", None) or getattr(resolution.target, "drawing_id", None)
                    ref_id = self.canonical_repo._reference_id(ref)
                    if target_id:
                        self.canonical_repo.link_reference_to_target(
                            reference_id=ref_id,
                            target_label=target_label,
                            target_id=target_id,
                        )

        # 7. Grounded Evidence Graph Construction for Archaeological Objects
        all_evidences: list[EvidenceData] = []
        objects_with_evidences: list[tuple[ArchaeologyObjectData, list[EvidenceData]]] = []

        for obj in all_objects:
            obj_evidences: list[EvidenceData] = []
            seen_ev_ids: set[str] = set()

            for block_id in obj.source_block_ids:
                p_page = page_by_block_id.get(block_id)
                t_block = block_by_id.get(block_id)
                c_block = caption_by_id.get(block_id)

                page_num = p_page.physical_page if p_page else None
                printed_page_num = p_page.printed_page if p_page else None
                page_id = f"{body_version_id}_p{page_num}" if page_num else f"{body_version_id}_p1"
                src_sha = (
                    (t_block.source_sha256 if t_block else None)
                    or (c_block.source_sha256 if c_block else None)
                    or (p_page.source_sha256 if p_page else None)
                    or body_sha256
                )

                # Text claim evidence
                ev_claim_id = f"ev_claim_{obj.object_id}_{block_id}"
                if ev_claim_id not in seen_ev_ids:
                    seen_ev_ids.add(ev_claim_id)
                    block_text = t_block.text if t_block else (c_block.raw_text if c_block else "")
                    bbox_val = t_block.bbox if t_block else (c_block.bbox if c_block else None)

                    ev_claim = EvidenceData(
                        id=ev_claim_id,
                        kind="text_claim",
                        source_sha256=src_sha,
                        document_version_id=body_version_id,
                        page_id=page_id,
                        region_id=block_id,
                        bbox=bbox_val,
                        method="object_resolver",
                        analysis_run_id=run_id,
                        value=block_text,
                        rationale=f"Text mention claiming object '{obj.canonical_name}'",
                        confidence=1.0,
                        version_from=version_stage,
                        version_to=version_stage,
                        physical_page_from=page_num,
                        physical_page_to=page_num,
                        printed_page_from=printed_page_num,
                        printed_page_to=printed_page_num,
                        rule_name="mention_claim",
                    )
                    obj_evidences.append(ev_claim)
                    all_evidences.append(ev_claim)

                # Reference evidences from this block
                block_refs = t_block.references if t_block else (c_block.references if c_block else [])
                for r in block_refs:
                    ev_ref_id = f"ev_ref_{obj.object_id}_{r.ref_type}_{r.number}"
                    if ev_ref_id not in seen_ev_ids:
                        seen_ev_ids.add(ev_ref_id)
                        ev_ref = EvidenceData(
                            id=ev_ref_id,
                            kind="reference",
                            source_sha256=src_sha,
                            document_version_id=body_version_id,
                            page_id=page_id,
                            region_id=block_id,
                            bbox=r.bbox or bbox_val,
                            method="pdf_parser",
                            analysis_run_id=run_id,
                            value={"ref_type": r.ref_type, "number": r.number, "raw_text": r.raw_text},
                            rationale=f"Reference '{r.raw_text}' associated with object '{obj.canonical_name}'",
                            confidence=1.0,
                            version_from=version_stage,
                            version_to=version_stage,
                            physical_page_from=page_num,
                            physical_page_to=page_num,
                            printed_page_from=printed_page_num,
                            printed_page_to=printed_page_num,
                            rule_name="reference_evidence",
                        )
                        obj_evidences.append(ev_ref)
                        all_evidences.append(ev_ref)

                        # If reference matches a plate in plate index, attach plate caption evidence
                        if r.ref_type in ("plate", "도판"):
                            plate_obj = active_plate_index.get_plate(r.number)
                            if plate_obj:
                                ev_plate_id = f"ev_plate_{obj.object_id}_{plate_obj.plate_id}"
                                if ev_plate_id not in seen_ev_ids:
                                    seen_ev_ids.add(ev_plate_id)
                                    plate_p_id = f"{plate_version_id or body_version_id}_p{plate_obj.physical_page}"
                                    ev_plate = EvidenceData(
                                        id=ev_plate_id,
                                        kind="plate_caption",
                                        source_sha256=plate_obj.source_sha256 or plate_sha256,
                                        document_version_id=plate_version_id or body_version_id,
                                        page_id=plate_p_id,
                                        bbox=plate_obj.bbox,
                                        method="plate_parser",
                                        analysis_run_id=run_id,
                                        value={"plate_number": plate_obj.number, "title": plate_obj.title},
                                        rationale=f"Canonical plate publication '{plate_obj.raw_identifier or plate_obj.number} {plate_obj.title}'",
                                        confidence=1.0,
                                        version_from=version_stage,
                                        version_to=version_stage,
                                        physical_page_from=plate_obj.physical_page,
                                        physical_page_to=plate_obj.physical_page,
                                        rule_name="plate_caption_evidence",
                                    )
                                    obj_evidences.append(ev_plate)
                                    all_evidences.append(ev_plate)

            objects_with_evidences.append((obj, obj_evidences))

        if self.review_repo is not None and all_evidences:
            self.review_repo.save_evidences(all_evidences)

        # 7b. Graph evidence bundles (Task 7, Gate B). When the canonical
        # repository is available, query the Neo4j graph for each object's
        # evidence bundle and feed Rule/LLM with graph-derived evidence. The
        # in-memory lists remain ONLY as an explicit degradation path with a
        # recorded warning — never silently.
        graph_bundles: dict[str, ObjectEvidenceBundle] = {}
        if self.canonical_repo is not None:
            for obj in all_objects:
                try:
                    bundle = self.canonical_repo.get_object_evidence_bundle(
                        obj.object_id
                    )
                except Exception as exc:  # noqa: BLE001 - degrade explicitly
                    warnings.append(
                        f"graph evidence unavailable for object '{obj.object_id}': "
                        f"{exc} — falling back to in-memory evidence (DEGRADED)"
                    )
                    continue
                if bundle.has_graph_evidence():
                    graph_bundles[obj.object_id] = bundle
                else:
                    warnings.append(
                        f"graph evidence empty for object '{obj.object_id}' — "
                        "falling back to in-memory evidence (DEGRADED)"
                    )

        # 8. Run Consistency Rules & AI Review Pipelines
        all_candidates: list[CorrectionCandidateData] = []

        # A. RuleEngine Consistency Checking — graph-first
        rule_candidates: list[CorrectionCandidateData] = []
        if graph_bundles:
            for obj, in_memory_evs in objects_with_evidences:
                bundle = graph_bundles.get(obj.object_id)
                if bundle is not None:
                    rule_candidates.extend(
                        self.rule_engine.check_object_bundle_consistency(
                            bundle=bundle,
                            plate_index=active_plate_index,
                            drawing_index=active_drawing_index,
                            plates=all_plates,
                            drawings=all_drawings,
                            archaeology_object=obj,
                        )
                    )
                else:
                    rule_candidates.extend(
                        self.rule_engine.check_object_consistency(
                            archaeology_object=obj,
                            evidences=in_memory_evs,
                            plate_index=active_plate_index,
                            drawing_index=active_drawing_index,
                            plates=all_plates,
                            drawings=all_drawings,
                        )
                    )
        else:
            rule_candidates = self.rule_engine.check_objects_consistency(
                objects_with_evidences=objects_with_evidences,
                plate_index=active_plate_index,
                drawing_index=active_drawing_index,
                plates=all_plates,
                drawings=all_drawings,
            )
        for rc in rule_candidates:
            # Enforce auditability invariants
            cand = CorrectionCandidateData(
                candidate_id=rc.candidate_id,
                rule_category=rc.rule_category,
                change_type=rc.change_type,
                status="pending_review",
                original_text=rc.original_text,
                proposed_text=rc.proposed_text,
                evidence=rc.evidence,
                evidence_list=rc.evidence_list,
                archaeology_object_id=rc.archaeology_object_id,
                confidence=rc.confidence,
                analysis_run_id=run_id,
            )
            all_candidates.append(cand)

        # B. VLM Visual Observation via AssetReviewPipeline
        if enable_vlm and (self.asset_review_pipeline is not None or self.vlm_service is not None):
            pipeline = self.asset_review_pipeline
            if pipeline is None:
                try:
                    pipeline = AssetReviewPipeline(vlm_service=self.vlm_service)
                except Exception:
                    import tempfile
                    from app.services.asset_cache import AssetHashCache
                    cache = AssetHashCache(cache_dir=Path(tempfile.gettempdir()) / "asset_cache")
                    pipeline = AssetReviewPipeline(vlm_service=self.vlm_service, cache=cache)

            for ref, resolution in resolved_resolutions:
                try:
                    ref_p_id = f"{body_version_id}_p{ref.physical_page}" if ref.physical_page else f"{body_version_id}_p1"
                    vlm_cands = await pipeline.review_canonical_reference(
                        reference=ref,
                        resolution=resolution,
                        analysis_run_id=run_id,
                        document_version_id=body_version_id,
                        page_id=ref_p_id,
                    )
                    for vc in vlm_cands:
                        for ev in vc.evidences:
                            if ev not in all_evidences:
                                all_evidences.append(ev)
                        cand = CorrectionCandidateData(
                            candidate_id=vc.candidate_id,
                            rule_category=vc.rule_category,
                            change_type=vc.change_type,
                            status="pending_review",
                            original_text=vc.original_text,
                            proposed_text=vc.proposed_text,
                            evidence=vc.evidence,
                            evidence_list=vc.evidence_list,
                            archaeology_object_id=vc.archaeology_object_id,
                            confidence=vc.confidence,
                            analysis_run_id=run_id,
                        )
                        all_candidates.append(cand)
                except Exception as e:
                    errors.append(f"VLM review error for ref {ref.number}: {e}")

        # C. Contextual LLM Review via AIReviewService
        if enable_ai_review and self.ai_review_service is not None:
            for obj, obj_evs in objects_with_evidences:
                if not obj_evs:
                    continue
                try:
                    ai_cands = await self.ai_review_service.review_object_evidence(
                        archaeology_object=obj,
                        evidences=obj_evs,
                        references=all_references,
                        project_id=project_id,
                        version_stage=version_stage,
                        analysis_run_id=run_id,
                        plates=all_plates,
                        drawings=all_drawings,
                    )
                    for ac in ai_cands:
                        for ev in ac.evidences:
                            if ev not in all_evidences:
                                all_evidences.append(ev)
                        cand = CorrectionCandidateData(
                            candidate_id=ac.candidate_id,
                            rule_category=ac.rule_category,
                            change_type=ac.change_type,
                            status="pending_review",
                            original_text=ac.original_text,
                            proposed_text=ac.proposed_text,
                            evidence=ac.evidence,
                            evidence_list=ac.evidence_list,
                            archaeology_object_id=ac.archaeology_object_id or obj.object_id,
                            confidence=ac.confidence,
                            analysis_run_id=run_id,
                        )
                        all_candidates.append(cand)
                except Exception as e:
                    errors.append(f"AI review error for object {obj.canonical_name}: {e}")

        # 9. Deduplicate Candidates & Persist to Graph
        deduped_candidates: list[CorrectionCandidateData] = []
        seen_cand_keys: set[str] = set()

        for c in all_candidates:
            key = f"{c.rule_category}|{c.original_text}|{c.proposed_text}|{c.archaeology_object_id}"
            if key not in seen_cand_keys:
                seen_cand_keys.add(key)
                deduped_candidates.append(c)

        if self.review_repo is not None:
            if deduped_candidates:
                self.review_repo.save_candidates(
                    project_id=project_id,
                    candidates=deduped_candidates,
                    analysis_run_id=run_id,
                )
            self.review_repo.save_analysis_run(
                project_id=project_id,
                run_id=run_id,
                status="completed",
                step="proofreading",
            )

        # 10. Summary Metrics
        summary: dict[str, Any] = {
            "total_candidates": len(deduped_candidates),
            "by_category": {},
            "by_change_type": {},
            "by_status": {"pending_review": len(deduped_candidates)},
            "total_evidences": len(all_evidences),
            "total_objects": len(all_objects),
            "total_references": len(all_references),
            "resolved_references": resolved_refs_count,
        }

        for c in deduped_candidates:
            cat = str(c.rule_category)
            ch = str(c.change_type)
            summary["by_category"][cat] = summary["by_category"].get(cat, 0) + 1
            summary["by_change_type"][ch] = summary["by_change_type"].get(ch, 0) + 1

        return OrchestratorResult(
            project_id=project_id,
            analysis_run_id=run_id,
            status="completed",
            pages_parsed=len(parsed_body_pages),
            objects_resolved=len(all_objects),
            references_resolved=resolved_refs_count,
            candidates=deduped_candidates,
            evidences=all_evidences,
            objects=all_objects,
            plates=all_plates,
            drawings=all_drawings,
            summary=summary,
            errors=errors,
            warnings=warnings,
        )

    def persist_version_alignment(
        self,
        project_id: str,
        version_pages: dict[str, list[ParsedPage]],
        version_ids: dict[str, str],
        run_id: str,
    ) -> None:
        """Run PageAligner over parsed body versions and persist PRECEDES +
        ALIGNED_TO into the canonical graph (Task 8).

        version_pages maps stage -> parsed pages; version_ids maps stage ->
        version_id. A single version persists no ALIGNED_TO rows and does not
        error (the DocumentVersion node is already persisted by ingest).
        """
        if self.review_repo is None:
            return
        if not version_pages:
            return

        aligner = PageAligner()
        rows = aligner.align_parallel_ranges(version_pages)

        ordered = [
            (version_ids[st], st) for st in version_pages if st in version_ids
        ]
        if len(ordered) >= 2:
            self.review_repo.save_version_precedes(project_id, ordered)
        self.review_repo.save_aligned_pages(rows, version_pages, run_id)

    def ensure_canonical_graph_ingested(
        self,
        project_id: str,
        version_id: str,
        kind: str,
        file_path: str | Path,
        **kwargs: Any,
    ):
        """Invoke kind-aware canonical graph ingestion pipeline as a prerequisite."""
        from app.jobs.ingest import run_ingest_job as run_kind_ingest_job

        return run_kind_ingest_job(
            project_id=project_id,
            version_id=version_id,
            kind=kind,
            file_path=file_path,
            canonical_repo=self.canonical_repo,
            review_repo=self.review_repo,
            pdf_parser=self.pdf_parser,
            plate_parser=self.plate_parser,
            drawing_parser=self.drawing_parser,
            object_resolver=self.object_resolver,
            **kwargs,
        )


async def run_proofreading(
    project_id: str,
    body_version_id: str,
    plate_version_id: str | None = None,
    **kwargs: Any,
) -> OrchestratorResult:
    """Module-level convenience function executing the canonical proofreading pipeline."""
    orchestrator = ProofreadingOrchestrator()
    return await orchestrator.run_proofreading(
        project_id=project_id,
        body_version_id=body_version_id,
        plate_version_id=plate_version_id,
        **kwargs,
    )
