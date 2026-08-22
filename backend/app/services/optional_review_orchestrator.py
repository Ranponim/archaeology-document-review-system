from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.services.graph_rules import GraphRuleFinding


class OptionalReviewOrchestratorMixin:
    """Run optional model review only after deterministic graph review completes.

    The wrapped graph-first orchestrator remains the source of candidates and
    canonical identity. Optional reviewers can add audit records and warnings,
    but can neither delete graph candidates nor change a successful core run to
    failed.
    """

    def __init__(
        self,
        *args: Any,
        optional_review_dispatcher: Any | None = None,
        optional_review_repository: Any | None = None,
        **kwargs: Any,
    ) -> None:
        self.optional_review_dispatcher = optional_review_dispatcher
        self.optional_review_repository = optional_review_repository
        super().__init__(*args, **kwargs)

    @staticmethod
    def _semantic_finding(candidate: Any, reference_corpus_id: str) -> GraphRuleFinding | None:
        evidence = getattr(candidate, "evidence", None)
        value = getattr(evidence, "value", None)
        if not isinstance(value, dict) or not bool(value.get("requiresAi")):
            return None
        return GraphRuleFinding(
            rule_code=str(value.get("ruleCode") or "SEMANTIC_REVIEW_REQUIRED"),
            severity=str(getattr(candidate, "severity", "medium")),
            source_block_id=(getattr(evidence, "region_id", None) or None),
            archaeology_object_id=getattr(candidate, "archaeology_object_id", None),
            reference_corpus_id=str(value.get("referenceCorpusId") or reference_corpus_id),
            canonical_target_ids=tuple(str(item) for item in value.get("canonicalTargetIds", []) or []),
            original_text=getattr(candidate, "original_text", None),
            proposed_text=getattr(candidate, "proposed_text", None),
            rationale=str(getattr(evidence, "rationale", None) or "semantic graph escalation"),
            evidence_ids=tuple(str(item) for item in value.get("graphEvidenceIds", []) or []),
            requires_ai=True,
        )

    async def run_proofreading(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        reference_corpus_id = kwargs.get("reference_corpus_id")
        enable_ai_review = bool(kwargs.get("enable_ai_review", False))
        enable_vlm = bool(kwargs.get("enable_vlm", False))
        result = await super().run_proofreading(*args, **kwargs)

        if (
            not reference_corpus_id
            or (not enable_ai_review and not enable_vlm)
            or self.optional_review_dispatcher is None
        ):
            return result

        objects_by_id = {
            getattr(obj, "object_id", ""): obj
            for obj in getattr(result, "objects", []) or []
            if getattr(obj, "object_id", None)
        }
        findings: list[GraphRuleFinding] = []
        context_by_finding: dict[str, dict[str, Any]] = {}
        for candidate in getattr(result, "candidates", []) or []:
            finding = self._semantic_finding(candidate, str(reference_corpus_id))
            if finding is None:
                continue
            findings.append(finding)
            key = self.optional_review_dispatcher._context_key(finding)
            evidence = getattr(candidate, "evidence", None)
            context_by_finding[key] = {
                "project_id": getattr(result, "project_id", ""),
                "analysis_run_id": getattr(result, "analysis_run_id", ""),
                "version_stage": str(kwargs.get("version_stage") or ""),
                "candidate_id": getattr(candidate, "candidate_id", None),
                "evidence_ids": [
                    getattr(item, "id", "")
                    for item in getattr(candidate, "evidences", []) or []
                    if getattr(item, "id", None)
                ],
                "object": objects_by_id.get(finding.archaeology_object_id or ""),
                "evidence": evidence,
            }

        outcome = await self.optional_review_dispatcher.review(
            findings=findings,
            enable_ai_review=enable_ai_review,
            enable_vlm=enable_vlm,
            context_by_finding=context_by_finding,
        )
        warnings = list(getattr(result, "warnings", []) or []) + list(outcome.warnings)

        if outcome.findings and self.optional_review_repository is not None:
            try:
                self.optional_review_repository.save(
                    project_id=result.project_id,
                    reference_corpus_id=str(reference_corpus_id),
                    analysis_run_id=result.analysis_run_id,
                    findings=outcome.findings,
                )
            except Exception as error:  # optional persistence is non-fatal
                warnings.append(
                    f"optional review audit warning: {error.__class__.__name__}: {error}"
                )

        summary = dict(getattr(result, "summary", {}) or {})
        summary["optional_review_findings"] = len(outcome.findings)
        summary["optional_review_semantic_inputs"] = len(findings)
        return replace(result, warnings=warnings, summary=summary)


class OptionalGraphFirstReviewRoundOrchestrator(
    OptionalReviewOrchestratorMixin,
):
    """Factory helper mixed dynamically with the graph-first concrete class."""

    pass
