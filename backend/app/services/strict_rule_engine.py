from __future__ import annotations

from dataclasses import replace

from app.domain.canonical_models import ArchaeologyObjectData
from app.domain.review_models import EvidenceData
from app.services.rule_engine import RuleEngine


class StrictRuleEngine(RuleEngine):
    """Precision-first RuleEngine for production graph evidence.

    Generated rationale is explanatory text, not source evidence. Type parsing
    therefore consumes structured `Evidence.value` (or its raw string form)
    only and never promotes words from rationale into new factual claims.
    """

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
