from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AIReviewFindingData:
    """Auditable output from an optional AI or VLM semantic review.

    These records can explain what a model checked, but they never replace the
    deterministic graph identity or automatically approve a correction.
    """

    id: str
    source: str
    provider: str
    model: str
    prompt_version: str
    input_hash: str
    confidence: float
    verdict: str
    rationale: str
    proposed_text: str | None
    candidate_id: str | None
    evidence_ids: tuple[str, ...]
    archaeology_object_id: str | None
    reference_corpus_id: str
    analysis_run_id: str

    def __post_init__(self) -> None:
        if self.source not in {"ai", "vlm"}:
            raise ValueError("source must be 'ai' or 'vlm'")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not self.input_hash:
            raise ValueError("input_hash is required")
        if not self.reference_corpus_id:
            raise ValueError("reference_corpus_id is required")
        if not self.analysis_run_id:
            raise ValueError("analysis_run_id is required")
