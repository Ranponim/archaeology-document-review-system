from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.domain.canonical_models import ArchaeologyObjectData
from app.domain.evidence_bundle import ObjectEvidenceBundle
from app.domain.review_models import EvidenceData
from app.services.rule_engine import RuleEngine
from app.services.visual_reference_coverage import VisualReferenceCoverageService


class StrictRuleEngine(RuleEngine):
    """Precision-first RuleEngine for production graph evidence.

    Generated rationale is explanatory text, not source evidence. Type parsing
    therefore consumes structured `Evidence.value` (or its raw string form)
    only and never promotes words from rationale into new factual claims.

    Bidirectional visual-reference coverage is composed here because the
    production orchestrator already calls `check_object_bundle_consistency`
    immediately after obtaining the graph-authoritative ObjectEvidenceBundle.
    This keeps coverage deterministic and inside the existing candidate
    dedupe/budget/persistence path without adding a parallel workflow.
    """

    def __init__(
        self,
        *args: Any,
        visual_reference_coverage_service: VisualReferenceCoverageService | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.visual_reference_coverage_service = (
            visual_reference_coverage_service or VisualReferenceCoverageService()
        )

    def extract_types_from_evidence(
        self,
        ev: EvidenceData,
        target_object: ArchaeologyObjectData | None = None,
    ) -> list[str]:
        if isinstance(ev.value, dict):
            explicit_type = ev.value.get("type")
            if explicit_type:
                normalized = self.normalize_type(str(explicit_type))
                return [normalized] if normalized else []
            return []

        sanitized = replace(ev, rationale=None)
        return super().extract_types_from_evidence(
            sanitized,
            target_object=target_object,
        )

    def check_object_bundle_consistency(
        self,
        bundle: ObjectEvidenceBundle,
        plate_index=None,
        drawing_index=None,
        plates=None,
        drawings=None,
        archaeology_object: ArchaeologyObjectData | None = None,
        max_candidates: int | None = None,
    ):
        candidates = list(
            super().check_object_bundle_consistency(
                bundle=bundle,
                plate_index=plate_index,
                drawing_index=drawing_index,
                plates=plates,
                drawings=drawings,
                archaeology_object=archaeology_object,
                max_candidates=max_candidates,
            )
        )
        if archaeology_object is None:
            return candidates

        analysis_run_id = next(
            (
                str(ev.analysis_run_id)
                for ev in bundle.evidences
                if ev.analysis_run_id is not None and str(ev.analysis_run_id).strip()
            ),
            "",
        )
        coverage_candidates = self.visual_reference_coverage_service.review_object(
            bundle=bundle,
            archaeology_object=archaeology_object,
            analysis_run_id=analysis_run_id,
        )

        # A precise graph-grounded blank fill (or graph-grounded ambiguity for
        # that exact blank token) supersedes the older generic blank detector,
        # which can only emit proposed_text=None. Keep the evidence-aware
        # coverage candidate and remove only the ungrounded duplicate.
        superseded_blank_texts = {
            candidate.original_text
            for candidate in coverage_candidates
            if candidate.original_text
            and candidate.evidence is not None
            and candidate.evidence.rule_name
            in {"visual_reference_blank_fill", "visual_reference_ambiguous"}
        }
        if superseded_blank_texts:
            candidates = [
                candidate
                for candidate in candidates
                if not (
                    candidate.original_text in superseded_blank_texts
                    and candidate.proposed_text is None
                    and not (
                        candidate.evidence is not None
                        and str(candidate.evidence.rule_name or "").startswith(
                            "visual_reference_"
                        )
                    )
                )
            ]

        candidates.extend(coverage_candidates)
        return candidates
