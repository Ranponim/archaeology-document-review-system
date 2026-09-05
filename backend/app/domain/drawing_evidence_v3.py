from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Literal

from app.domain.drawing_evidence import ContextFact

CodexVerdict = Literal["match", "ambiguous", "none"]
DrawingV3Status = Literal["AUTO_VERIFIED", "REVIEW_REQUIRED", "UNRESOLVED"]


@dataclass(frozen=True, slots=True)
class DrawingV3Evidence:
    id: str
    family: str
    method: str
    value: str
    supports: bool = True
    weak: bool = False


@dataclass(frozen=True, slots=True)
class DrawingVisualRegion:
    region_id: str
    image_path: str
    page: int | None
    bbox: tuple[float, float, float, float] | None
    confidence: float
    source_sha256: str | None = None


def drawing_visual_support_id(
    source_asset_id: str,
    source_region_id: str,
    candidate_id: str,
    candidate_region_id: str,
) -> str:
    """Return the closed-world support ID for one submitted visual pair."""
    payload = "\0".join(
        (source_asset_id, source_region_id, candidate_id, candidate_region_id)
    ).encode("utf-8")
    return "drawing-v3-visual-support:" + hashlib.sha256(payload).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class BodyDrawingEvidencePacket:
    publication_kind: str
    number: str
    raw_texts: tuple[str, ...]
    source_node_ids: tuple[str, ...]
    source_sha256: str | None
    document_version_id: str | None
    physical_page: int | None
    source_bbox: tuple[float, float, float, float] | None
    visual_regions: tuple[DrawingVisualRegion, ...]


@dataclass(frozen=True, slots=True)
class DrawingSourceEvidencePacket:
    source_asset_id: str
    source_sha256: str
    original_name: str
    source_path: str
    raw_text: str
    publication_kind: str | None
    internal_numbers: tuple[str, ...]
    facts: tuple[ContextFact, ...]
    visual_regions: tuple[DrawingVisualRegion, ...]
    evidence: tuple[DrawingV3Evidence, ...]


@dataclass(frozen=True, slots=True)
class DrawingCandidatePacket:
    candidate_id: str
    publication_kind: str
    number: str
    raw_texts: tuple[str, ...]
    facts: tuple[ContextFact, ...]
    visual_regions: tuple[DrawingVisualRegion, ...]
    local_score: float
    evidence: tuple[DrawingV3Evidence, ...]
    hard_contradiction: bool
    strong_contradiction_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CodexDrawingDecision:
    run_id: str
    model: str
    verdict: CodexVerdict
    candidate_id: str | None
    confidence: float
    cited_support_ids: tuple[str, ...]
    cited_contradiction_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    summary: str
    cited_visual_support_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DrawingV3SourceResult:
    source_asset_id: str
    status: DrawingV3Status
    candidates: tuple[DrawingCandidatePacket, ...]
    decision: CodexDrawingDecision | None
    selected_candidate_id: str | None
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DrawingV3Resolution:
    source_results: tuple[DrawingV3SourceResult, ...]
    diagnostics: dict[str, object] = field(default_factory=dict)
