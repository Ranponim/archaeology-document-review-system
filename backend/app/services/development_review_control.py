from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable

from app.domain.review_models import CorrectionCandidateData
from app.services.review_budget import (
    make_finding_fingerprint,
    select_development_candidates,
)


class DevelopmentReviewBudget:
    """Shared coordinator for cheap-rule scanning and expensive AI/VLM work.

    RuleEngine still scans the complete graph. After rule scanning has recorded
    its findings, the coordinator freezes a deterministic representative sample
    and allows at most `max_expensive_operations` VLM/LLM calls in total.
    """

    def __init__(self, max_expensive_operations: int = 10) -> None:
        self.max_expensive_operations = max(1, int(max_expensive_operations))
        self.reset()

    def reset(self) -> None:
        self._rule_candidates: list[CorrectionCandidateData] = []
        self._selected_rule_candidates: list[CorrectionCandidateData] | None = None
        self._selected_object_ids: set[str] = set()
        self._visual_kinds_seen: set[str] = set()
        self.expensive_operations = 0

    def record_rule_candidates(
        self, candidates: Iterable[CorrectionCandidateData]
    ) -> None:
        self._rule_candidates.extend(list(candidates))
        self._selected_rule_candidates = None
        self._selected_object_ids = set()

    def _freeze(self) -> None:
        if self._selected_rule_candidates is not None:
            return
        self._selected_rule_candidates = select_development_candidates(
            self._rule_candidates,
            max_candidates=self.max_expensive_operations,
        )
        self._selected_object_ids = {
            c.archaeology_object_id
            for c in self._selected_rule_candidates
            if c.archaeology_object_id
        }

    def _consume(self) -> bool:
        if self.expensive_operations >= self.max_expensive_operations:
            return False
        self.expensive_operations += 1
        return True

    def allow_visual(self, ref_type: str | None) -> bool:
        """Allow representative visual review while preserving plate/drawing paths.

        At most one plate and one drawing observation are guaranteed first.
        Additional visual calls are intentionally denied in development mode so
        the remaining budget can exercise graph-guided LLM review.
        """
        self._freeze()
        kind = str(ref_type or "").lower()
        if kind not in {"plate", "drawing"}:
            return False
        if kind in self._visual_kinds_seen:
            return False
        if not self._consume():
            return False
        self._visual_kinds_seen.add(kind)
        return True

    def allow_ai(self, object_id: str | None) -> bool:
        self._freeze()
        if not object_id:
            return False
        if self._selected_object_ids and object_id not in self._selected_object_ids:
            return False
        return self._consume()

    @property
    def raw_findings(self) -> int:
        return len(self._rule_candidates)

    @property
    def deduped_findings(self) -> int:
        return len({make_finding_fingerprint(c) for c in self._rule_candidates})

    @property
    def selected_rule_candidates(self) -> list[CorrectionCandidateData]:
        self._freeze()
        return list(self._selected_rule_candidates or [])

    def summary(self, selected_candidates: int) -> dict[str, Any]:
        self._freeze()
        return {
            "raw_findings": self.raw_findings,
            "deduped_findings": self.deduped_findings,
            "selected_candidates": int(selected_candidates),
            "development_budget": self.max_expensive_operations,
            "expensive_operations": self.expensive_operations,
            "selection_mode": "development_stratified_pre_ai",
        }


class BudgetedRuleEngine:
    def __init__(self, delegate: Any, budget: DevelopmentReviewBudget) -> None:
        self._delegate = delegate
        self._budget = budget

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def _record(self, candidates):
        result = list(candidates)
        self._budget.record_rule_candidates(result)
        return result

    def check_object_bundle_consistency(self, *args, **kwargs):
        return self._record(
            self._delegate.check_object_bundle_consistency(*args, **kwargs)
        )

    def check_object_consistency(self, *args, **kwargs):
        return self._record(self._delegate.check_object_consistency(*args, **kwargs))

    def check_objects_consistency(self, *args, **kwargs):
        return self._record(self._delegate.check_objects_consistency(*args, **kwargs))


class BudgetedAssetReviewPipeline:
    def __init__(self, delegate: Any, budget: DevelopmentReviewBudget) -> None:
        self._delegate = delegate
        self._budget = budget

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    async def review_canonical_reference(self, *args, **kwargs):
        reference = kwargs.get("reference")
        if reference is None and args:
            reference = args[0]
        ref_type = getattr(reference, "ref_type", None)
        if not self._budget.allow_visual(ref_type):
            return []
        return await self._delegate.review_canonical_reference(*args, **kwargs)


class BudgetedAIReviewService:
    def __init__(self, delegate: Any, budget: DevelopmentReviewBudget) -> None:
        self._delegate = delegate
        self._budget = budget

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    async def review_object_bundle(self, *args, **kwargs):
        obj = kwargs.get("archaeology_object")
        if obj is None and args:
            obj = args[0]
        if not self._budget.allow_ai(getattr(obj, "object_id", None)):
            return []
        return await self._delegate.review_object_bundle(*args, **kwargs)

    async def review_object_evidence(self, *args, **kwargs):
        obj = kwargs.get("archaeology_object")
        if obj is None and args:
            obj = args[0]
        if not self._budget.allow_ai(getattr(obj, "object_id", None)):
            return []
        return await self._delegate.review_object_evidence(*args, **kwargs)


class BudgetedProofreadingOrchestratorMixin:
    """Mixin used by the production subclass to publish budget diagnostics."""

    development_budget: DevelopmentReviewBudget

    async def run_proofreading(self, *args, **kwargs):  # type: ignore[override]
        self.development_budget.reset()
        result = await super().run_proofreading(*args, **kwargs)
        summary = dict(result.summary)
        summary.update(self.development_budget.summary(len(result.candidates)))
        review_repo = getattr(self, "review_repo", None)
        if review_repo is not None and hasattr(review_repo, "save_run_summary"):
            review_repo.save_run_summary(result.analysis_run_id, summary)
        return replace(result, summary=summary)
