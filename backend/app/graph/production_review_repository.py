from app.graph.audited_review_repository import AuditedReviewRepository
from app.services.rule_engine import classify_severity_from_category


class ProductionReviewRepository(AuditedReviewRepository):
    """Final production boundary for candidate normalization and audit storage."""

    def _candidate_to_param(self, cand):
        param = super()._candidate_to_param(cand)
        inferred = classify_severity_from_category(str(cand.rule_category))
        current = str(getattr(cand, "severity", "medium") or "medium").lower()
        # Existing orchestrator compatibility can drop severity back to the
        # dataclass default. Restore only categories whose domain policy is
        # explicitly higher risk; preserve explicit low/critical decisions.
        if current == "medium" and inferred == "high":
            param["severity"] = "high"
        else:
            param["severity"] = current
        return param
