from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.canonical_models import DrawingData, EvidenceLevel


@dataclass(frozen=True, slots=True)
class ContextFact:
    kind: str
    value: str
    normalized_value: str
    source_kind: str
    source_node_id: str | None = None
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedDrawingContext:
    raw_text: str
    tokens: tuple[str, ...]
    facts: tuple[ContextFact, ...]


@dataclass(frozen=True, slots=True)
class BodyDrawingContext:
    number: str
    raw_texts: tuple[str, ...]
    source_node_ids: tuple[str, ...] = ()
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class DrawingSourceObservation:
    source_asset_id: str
    source_sha256: str
    original_name: str
    raw_text: str = ""
    internal_numbers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DrawingCandidateEvidence:
    id: str
    candidate_id: str
    family: str
    method: str
    value: str
    normalized_value: str
    score: float
    supports: bool = True
    source_node_id: str | None = None
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class DrawingCandidateResult:
    candidate_id: str
    reference_corpus_id: str
    source_asset_id: str
    source_sha256: str
    candidate_number: str
    status: str = "candidate"
    evidence_level: EvidenceLevel = EvidenceLevel.HEURISTIC
    resolver_version: str = "drawing-evidence-v1"
    score: float = 0.0
    runner_up_score: float = 0.0
    margin: float = 0.0
    evidence_families: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    has_hard_contradiction: bool = False


@dataclass(frozen=True, slots=True)
class DrawingEvidenceResolution:
    canonical_drawings: tuple[DrawingData, ...] = ()
    candidates: tuple[DrawingCandidateResult, ...] = ()
    evidence: tuple[DrawingCandidateEvidence, ...] = ()
    context_facts: tuple[ContextFact, ...] = ()
    unresolved_source_ids: tuple[str, ...] = ()
    ambiguous_source_ids: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
