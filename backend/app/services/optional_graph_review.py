from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from app.domain.ai_review_finding import AIReviewFindingData
from app.services.graph_rules import GraphRuleFinding


@dataclass(frozen=True, slots=True)
class OptionalReviewOutcome:
    findings: list[AIReviewFindingData]
    warnings: list[str]


class OptionalGraphReviewDispatcher:
    """Dispatch only semantic graph findings to optional model reviewers.

    Deterministic graph findings never enter this boundary. Reviewer failures
    are converted to warnings so graph-successful runs remain successful.
    """

    PROMPT_VERSION = "graph-semantic-review-v1"

    def __init__(self, *, ai_reviewer: Any | None, vlm_reviewer: Any | None) -> None:
        self.ai_reviewer = ai_reviewer
        self.vlm_reviewer = vlm_reviewer

    @staticmethod
    def _context_key(finding: GraphRuleFinding) -> str:
        return f"{finding.rule_code}:{finding.source_block_id or ''}"

    @staticmethod
    def _safe_context(context: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in sorted(context.items()):
            if key in {"object", "evidence", "image_bytes"}:
                if key == "object" and value is not None:
                    safe[key] = {
                        "object_id": getattr(value, "object_id", None),
                        "canonical_name": getattr(value, "canonical_name", None),
                    }
                elif key == "evidence" and value is not None:
                    safe[key] = {
                        "id": getattr(value, "id", None),
                        "rule_name": getattr(value, "rule_name", None),
                    }
                elif key == "image_bytes" and value is not None:
                    safe[key] = hashlib.sha256(bytes(value)).hexdigest()
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe[key] = value
            elif isinstance(value, (list, tuple)):
                safe[key] = [str(item) for item in value]
            else:
                safe[key] = str(value)
        return safe

    @classmethod
    def _input_hash(
        cls, finding: GraphRuleFinding, context: dict[str, Any]
    ) -> str:
        payload = {
            "ruleCode": finding.rule_code,
            "objectId": finding.archaeology_object_id,
            "referenceCorpusId": finding.reference_corpus_id,
            "sourceBlockId": finding.source_block_id,
            "canonicalTargetIds": list(finding.canonical_target_ids),
            "originalText": finding.original_text,
            "rationale": finding.rationale,
            "context": cls._safe_context(context),
            "promptVersion": cls.PROMPT_VERSION,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _provider(reviewer: Any) -> str:
        client = getattr(reviewer, "_client", None)
        if client is not None:
            return client.__class__.__name__
        return reviewer.__class__.__name__

    @staticmethod
    def _normalize_result(result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            return result
        if result is None:
            return {
                "verdict": "NO_RESULT",
                "confidence": 0.0,
                "rationale": "Optional reviewer returned no result.",
                "proposed_text": None,
            }
        if isinstance(result, list):
            if not result:
                return {
                    "verdict": "NO_CHANGE",
                    "confidence": 1.0,
                    "rationale": "Optional AI review produced no additional proposal.",
                    "proposed_text": None,
                }
            candidate = result[0]
            evidence = getattr(candidate, "evidence", None)
            return {
                "verdict": "REVIEWED",
                "confidence": float(getattr(candidate, "confidence", 0.5)),
                "rationale": str(
                    getattr(evidence, "rationale", None)
                    or "Optional AI review produced a grounded proposal."
                ),
                "proposed_text": getattr(candidate, "proposed_text", None),
            }
        return {
            "verdict": str(getattr(result, "status", "REVIEWED")),
            "confidence": float(getattr(result, "confidence", 0.5)),
            "rationale": str(getattr(result, "rationale", "")),
            "proposed_text": getattr(result, "proposed_text", None),
        }

    async def _invoke_ai(
        self, reviewer: Any, finding: GraphRuleFinding, context: dict[str, Any]
    ) -> Any:
        if hasattr(reviewer, "review_graph_finding"):
            return await reviewer.review_graph_finding(
                finding=finding,
                context=context,
            )
        if hasattr(reviewer, "review_object_evidence"):
            obj = context.get("object")
            evidence = context.get("evidence")
            if obj is None or evidence is None:
                return []
            return await reviewer.review_object_evidence(
                archaeology_object=obj,
                evidences=[evidence],
                project_id=str(context.get("project_id") or ""),
                version_stage=str(context.get("version_stage") or ""),
                analysis_run_id=str(context.get("analysis_run_id") or ""),
            )
        raise RuntimeError("AI reviewer has no bounded graph-review interface")

    async def _invoke_vlm(
        self, reviewer: Any, finding: GraphRuleFinding, context: dict[str, Any]
    ) -> Any:
        if hasattr(reviewer, "review_graph_finding"):
            return await reviewer.review_graph_finding(
                finding=finding,
                context=context,
            )
        image_bytes = context.get("image_bytes")
        if image_bytes is not None and hasattr(reviewer, "verify_plate_photo"):
            obj = context.get("object")
            expected_feature = str(
                getattr(obj, "canonical_name", None)
                or getattr(obj, "number", None)
                or finding.archaeology_object_id
                or ""
            )
            expected_site = str(getattr(obj, "site", None) or "")
            claims = [finding.original_text] if finding.original_text else []
            return await reviewer.verify_plate_photo(
                image_bytes=bytes(image_bytes),
                expected_feature=expected_feature,
                expected_site=expected_site,
                claims=claims,
            )
        raise RuntimeError("VLM render is unavailable for bounded semantic review")

    def _audit_record(
        self,
        *,
        source: str,
        reviewer: Any,
        finding: GraphRuleFinding,
        context: dict[str, Any],
        result: Any,
    ) -> AIReviewFindingData:
        normalized = self._normalize_result(result)
        input_hash = self._input_hash(finding, context)
        confidence = max(0.0, min(1.0, float(normalized.get("confidence", 0.0))))
        candidate_id = context.get("candidate_id")
        evidence_ids = context.get("evidence_ids") or list(finding.evidence_ids)
        analysis_run_id = str(context.get("analysis_run_id") or "")
        audit_identity = "|".join(
            [source, finding.reference_corpus_id, analysis_run_id, input_hash]
        )
        audit_id = "ai_review:" + hashlib.sha256(
            audit_identity.encode("utf-8")
        ).hexdigest()[:24]
        return AIReviewFindingData(
            id=audit_id,
            source=source,
            provider=self._provider(reviewer),
            model=str(getattr(reviewer, "_model", reviewer.__class__.__name__)),
            prompt_version=self.PROMPT_VERSION,
            input_hash=input_hash,
            confidence=confidence,
            verdict=str(normalized.get("verdict") or "REVIEWED"),
            rationale=str(normalized.get("rationale") or ""),
            proposed_text=(
                str(normalized["proposed_text"])
                if normalized.get("proposed_text") is not None
                else None
            ),
            candidate_id=str(candidate_id) if candidate_id else None,
            evidence_ids=tuple(str(item) for item in evidence_ids),
            archaeology_object_id=finding.archaeology_object_id,
            reference_corpus_id=finding.reference_corpus_id,
            analysis_run_id=analysis_run_id,
        )

    async def review(
        self,
        *,
        findings: list[GraphRuleFinding],
        enable_ai_review: bool,
        enable_vlm: bool,
        context_by_finding: dict[str, dict[str, Any]] | None = None,
    ) -> OptionalReviewOutcome:
        if not enable_ai_review and not enable_vlm:
            return OptionalReviewOutcome(findings=[], warnings=[])

        contexts = context_by_finding or {}
        audits: list[AIReviewFindingData] = []
        warnings: list[str] = []
        semantic_findings = [finding for finding in findings if finding.requires_ai]
        for finding in semantic_findings:
            context = dict(contexts.get(self._context_key(finding), {}))
            if enable_ai_review and self.ai_reviewer is not None:
                try:
                    result = await self._invoke_ai(
                        self.ai_reviewer,
                        finding,
                        context,
                    )
                    audits.append(
                        self._audit_record(
                            source="ai",
                            reviewer=self.ai_reviewer,
                            finding=finding,
                            context=context,
                            result=result,
                        )
                    )
                except Exception as error:  # optional boundary is warning-only
                    warnings.append(
                        f"optional ai review warning: {error.__class__.__name__}: {error}"
                    )

            if enable_vlm and self.vlm_reviewer is not None:
                try:
                    result = await self._invoke_vlm(
                        self.vlm_reviewer,
                        finding,
                        context,
                    )
                    audits.append(
                        self._audit_record(
                            source="vlm",
                            reviewer=self.vlm_reviewer,
                            finding=finding,
                            context=context,
                            result=result,
                        )
                    )
                except Exception as error:  # optional boundary is warning-only
                    warnings.append(
                        f"optional vlm review warning: {error.__class__.__name__}: {error}"
                    )

        return OptionalReviewOutcome(findings=audits, warnings=warnings)
