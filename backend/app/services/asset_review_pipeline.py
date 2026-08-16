from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import uuid

from app.domain.canonical_models import (
    DrawingData,
    DrawingRegionData,
    PlateData,
    PlatePanelData,
    ReferenceData,
    ResolutionStatus,
)
from app.domain.review_models import (
    CorrectionCandidateData,
    EvidenceData,
)
from app.services.asset_cache import AssetHashCache
from app.services.asset_matcher import AssetMatcher, MatchedAssetResult, ResolutionResult
from app.services.image_processor import ImageProcessor
from app.services.vlm_review_service import VLMReviewService

MAX_VLM_CANDIDATES: int = 5


@dataclass(frozen=True, slots=True)
class AssetPipelineSummary:
    total_references: int
    status_counts: dict[str, int] = field(default_factory=dict)
    results: list[MatchedAssetResult] = field(default_factory=list)


class AssetReviewPipeline:
    MAX_VLM_CANDIDATES: int = MAX_VLM_CANDIDATES

    def __init__(
        self,
        matcher: AssetMatcher | None = None,
        vlm_service: VLMReviewService | None = None,
        cache: AssetHashCache | None = None,
        max_vlm_candidates: int = MAX_VLM_CANDIDATES,
    ) -> None:
        self.matcher = matcher
        self.vlm = vlm_service
        self.cache = cache or AssetHashCache()
        self.max_vlm_candidates = max_vlm_candidates

    async def review_canonical_reference(
        self,
        reference: ReferenceData,
        resolution: ResolutionResult,
        vlm_service: VLMReviewService | None = None,
        image_bytes: bytes | None = None,
        expected_feature: str = "",
        expected_site: str = "",
        claims: list[str] | None = None,
        analysis_run_id: str | None = None,
        document_version_id: str | None = None,
        page_id: str | None = None,
    ) -> list[CorrectionCandidateData]:
        """Review a canonically resolved reference using VLM visual observation.

        Invariants:
        1. Consumes only canonical targets (PlatePanelData, DrawingRegionData, PlateData, DrawingData).
        2. Never accepts or invokes VLM on arbitrary numeric filename coincidences.
        3. Gracefully handles empty, corrupt, or unconvertible image payloads (conversion_error/manual_review).
        4. Never auto-promotes candidates to accepted; status is strictly 'pending_review'.
        5. Links generated candidate to structured EvidenceData (kind='vlm_observation').
        """
        vlm = vlm_service or self.vlm
        orig_text = reference.raw_text or f"{reference.ref_type} {reference.number}"
        doc_ver = document_version_id or "doc_ver_canonical"
        pg_id = page_id or (f"page_{reference.physical_page}" if reference.physical_page else "page_unknown")
        src_sha = reference.source_sha256 or "sha256_canonical_ref"

        # 1. Reject non-resolved status or missing target
        if resolution.status != ResolutionStatus.RESOLVED or resolution.target is None:
            cand = CorrectionCandidateData(
                candidate_id=f"cand_unresolved_{uuid.uuid4().hex[:8]}",
                rule_category="figure_plate_table_photo_ref",
                change_type="modified",
                status="pending_review",
                original_text=orig_text,
                proposed_text=None,
                confidence=0.0,
                analysis_run_id=analysis_run_id,
            )
            return [cand]

        target = resolution.target

        # 2. Reject non-canonical target types (never accept arbitrary filenames or raw strings)
        if not isinstance(target, (PlatePanelData, DrawingRegionData, PlateData, DrawingData)):
            cand = CorrectionCandidateData(
                candidate_id=f"cand_invalid_target_{uuid.uuid4().hex[:8]}",
                rule_category="figure_plate_table_photo_ref",
                change_type="modified",
                status="pending_review",
                original_text=orig_text,
                proposed_text=None,
                confidence=0.0,
                analysis_run_id=analysis_run_id,
            )
            return [cand]

        # 3. Resolve target panels/regions
        targets_to_review: list[PlatePanelData | DrawingRegionData | PlateData | DrawingData] = []
        if isinstance(target, PlateData):
            if target.panels:
                targets_to_review = list(target.panels)
            else:
                targets_to_review = [target]
        elif isinstance(target, DrawingData):
            if target.regions:
                targets_to_review = list(target.regions)
            else:
                targets_to_review = [target]
        else:
            targets_to_review = [target]

        candidates: list[CorrectionCandidateData] = []

        for item in targets_to_review:
            # 4. Extract / validate image bytes
            raw_bytes = image_bytes
            render_uri = getattr(item, "render_uri", None)
            if raw_bytes is None and render_uri:
                try:
                    uri_str = str(render_uri)
                    p = Path(uri_str[7:] if uri_str.startswith("file://") else uri_str)
                    if p.is_file():
                        ext = p.suffix.lower()
                        # Reject unsupported non-rendered vector formats (AI, DWG, DXF, EPS)
                        if ext in (".ai", ".dwg", ".dxf", ".eps", ".cdr"):
                            cand = CorrectionCandidateData(
                                candidate_id=f"cand_conv_err_{uuid.uuid4().hex[:8]}",
                                rule_category="figure_plate_table_photo_ref",
                                change_type="modified",
                                status="pending_review",
                                original_text=orig_text,
                                proposed_text=None,
                                confidence=0.0,
                                analysis_run_id=analysis_run_id,
                            )
                            candidates.append(cand)
                            continue
                        raw_bytes = p.read_bytes()
                    else:
                        raw_bytes = b""
                except Exception:
                    raw_bytes = b""

            if raw_bytes is None:
                raw_bytes = b""

            # 5. Crop the actual panel photo region from the high-resolution
            # page render (panel bbox in normalized page coordinates) or
            # prepare the whole photo bytes for a region-less target. A panel
            # whose region could not be safely isolated (bbox_status
            # "insufficient") never sends the page render: that would be
            # unrelated content, not panel evidence.
            item_bbox = getattr(item, "bbox", None)
            bbox_status = getattr(item, "bbox_status", None)
            if item_bbox is not None and raw_bytes:
                processed_bytes = ImageProcessor.crop_region(raw_bytes, item_bbox)
            elif raw_bytes:
                if bbox_status == "insufficient":
                    processed_bytes = b""
                else:
                    processed_bytes = ImageProcessor.prepare_for_vlm(raw_bytes)
            else:
                processed_bytes = b""

            # Validate processed image bytes before invoking VLM
            if not processed_bytes or not ImageProcessor.is_valid_image(processed_bytes):
                cand = CorrectionCandidateData(
                    candidate_id=f"cand_conv_err_{uuid.uuid4().hex[:8]}",
                    rule_category="figure_plate_table_photo_ref",
                    change_type="modified",
                    status="pending_review",
                    original_text=orig_text,
                    proposed_text=None,
                    confidence=0.0,
                    analysis_run_id=analysis_run_id,
                )
                candidates.append(cand)
                continue

            # If no VLM service configured
            if vlm is None:
                cand = CorrectionCandidateData(
                    candidate_id=f"cand_no_vlm_{uuid.uuid4().hex[:8]}",
                    rule_category="figure_plate_table_photo_ref",
                    change_type="modified",
                    status="pending_review",
                    original_text=orig_text,
                    proposed_text=None,
                    confidence=0.0,
                    analysis_run_id=analysis_run_id,
                )
                candidates.append(cand)
                continue

            # 6. Invoke VLM
            feat = expected_feature or getattr(item, "caption", "") or getattr(item, "title", "")
            site = expected_site
            vlm_res = await vlm.verify_plate_photo(
                image_bytes=processed_bytes,
                expected_feature=feat,
                expected_site=site,
                claims=claims,
            )

            # 7. Create EvidenceData
            item_sha = getattr(item, "source_sha256", None) or src_sha
            item_page = getattr(item, "physical_page", None)
            item_page_id = f"page_{item_page}" if item_page else pg_id
            item_region_id = getattr(item, "panel_id", None) or getattr(item, "region_id", None)

            evidence = EvidenceData(
                id=f"ev_vlm_{uuid.uuid4().hex[:8]}",
                kind="vlm_observation",
                source_sha256=item_sha,
                document_version_id=doc_ver,
                page_id=item_page_id,
                region_id=item_region_id,
                bbox=item_bbox,
                method="vlm",
                analysis_run_id=analysis_run_id,
                value={
                    "status": vlm_res.status,
                    "observations": vlm_res.observations,
                    "supported_claims": vlm_res.supported_claims,
                    "contradicted_claims": vlm_res.contradicted_claims,
                    "unobservable_claims": vlm_res.unobservable_claims,
                },
                rationale=vlm_res.rationale,
                confidence=min(max(vlm_res.confidence, 0.0), 1.0),
                rule_name="vlm_canonical_asset_review",
            )

            # 8. Create CorrectionCandidateData (strictly status="pending_review")
            cand = CorrectionCandidateData(
                candidate_id=f"cand_vlm_{uuid.uuid4().hex[:8]}",
                rule_category="figure_plate_table_photo_ref",
                change_type="modified",
                status="pending_review",
                original_text=orig_text,
                proposed_text=getattr(item, "title", None) or (f"{reference.ref_type} {getattr(item, 'number', reference.number)}"),
                evidence=evidence,
                evidence_list=[evidence],
                confidence=min(max(vlm_res.confidence, 0.0), 1.0),
                analysis_run_id=analysis_run_id,
            )
            candidates.append(cand)

        return candidates

    async def review_references(
        self, references: list[dict[str, Any]]
    ) -> AssetPipelineSummary:
        if self.matcher is None:
            raise ValueError("AssetMatcher is required for review_references")
        status_counts = {
            "exact": 0,
            "multiple": 0,
            "missing": 0,
            "semantic_review": 0,
        }
        results: list[MatchedAssetResult] = []

        for ref in references:
            ref_type = ref.get("type", "drawing")
            number = str(ref.get("number", ""))
            context = ref.get("context", {})

            # 1. Local zero-cost matching
            match_res = self.matcher.match_reference(
                ref_type=ref_type,
                number=number,
                context=context,
            )

            # 2. If multiple or semantic_review, resolve via VLM if candidate_paths has files
            if (
                self.vlm is not None
                and match_res.status in ("multiple", "semantic_review")
                and match_res.candidate_paths
            ):
                expected_feature = (
                    context.get("feature")
                    or context.get("structure")
                    or ""
                )
                expected_site = (
                    context.get("site_point")
                    or context.get("site")
                    or context.get("location")
                    or ""
                )

                candidates_to_check = match_res.candidate_paths[: self.max_vlm_candidates]
                for candidate_path in candidates_to_check:
                    try:
                        image_bytes = candidate_path.read_bytes()
                    except OSError:
                        image_bytes = b""

                    vlm_res = await self.vlm.verify_plate_photo(
                        image_bytes=image_bytes,
                        expected_feature=expected_feature,
                        expected_site=expected_site,
                    )

                    if vlm_res.is_match:
                        match_res = MatchedAssetResult(
                            ref_type=match_res.ref_type,
                            number=match_res.number,
                            status="exact",
                            matched_path=candidate_path,
                            candidate_paths=match_res.candidate_paths,
                            rationale=vlm_res.rationale,
                        )
                        break

            results.append(match_res)
            if match_res.status in status_counts:
                status_counts[match_res.status] += 1

        return AssetPipelineSummary(
            total_references=len(references),
            status_counts=status_counts,
            results=results,
        )
