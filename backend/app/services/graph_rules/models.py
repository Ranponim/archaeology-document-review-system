from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphRuleFinding:
    rule_code: str
    severity: str
    source_block_id: str | None
    archaeology_object_id: str | None
    reference_corpus_id: str
    canonical_target_ids: tuple[str, ...]
    original_text: str | None
    proposed_text: str | None
    rationale: str
    evidence_ids: tuple[str, ...]
    requires_ai: bool = False


@dataclass(frozen=True, slots=True)
class GraphBodyRegion:
    source_block_id: str
    text: str
    semantic_topics: tuple[str, ...] = ()


class CorpusIntegrityError(ValueError):
    def __init__(self, error_codes: tuple[str, ...] | list[str]):
        self.error_codes = tuple(str(code) for code in error_codes)
        super().__init__(
            "ReferenceCorpus integrity validation failed: "
            + ", ".join(self.error_codes)
        )
