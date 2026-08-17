from dataclasses import dataclass, field
from typing import Any, Literal

RuleCategory = Literal[
    "figure_plate_table_photo_ref",
    "annotation_resolution",
    "feature_or_artifact_id",
    "numeric_value",
    "site_or_area_name",
    "direction_period_term",
]

RuleCategory = Literal[
    "figure_plate_table_photo_ref",
    "annotation_resolution",
    "feature_or_artifact_id",
    "numeric_value",
    "site_or_area_name",
    "direction_period_term",
]

ChangeType = Literal["added", "deleted", "modified", "moved"]
ReviewStatus = Literal[
    "confirmed",
    "layout_noise",
    "manual_review",
    "unresolved",
    "pending_review",
]

ReviewDecisionValue = Literal["accepted", "rejected", "modified", "deferred"]

EvidenceKind = Literal[
    "text_claim",
    "reference",
    "plate_caption",
    "drawing_caption",
    "vlm_observation",
    "rule_finding",
    "version_change",
]

DOCUMENT_BOUND_KINDS: frozenset[str] = frozenset({
    "text_claim",
    "reference",
    "plate_caption",
    "drawing_caption",
    "vlm_observation",
    "rule_finding",
    "version_change",
})


@dataclass(frozen=True, slots=True)
class EvidenceData:
    id: str = ""
    kind: EvidenceKind | str | None = None
    source_sha256: str | None = None
    document_version_id: str | None = None
    page_id: str | None = None
    region_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    method: str = "rule"
    analysis_run_id: str | None = None
    value: Any = ""
    rationale: str | None = None
    confidence: float = 1.0
    version_from: str | None = None
    version_to: str | None = None
    physical_page_from: int | None = None
    physical_page_to: int | None = None
    printed_page_from: int | None = None
    printed_page_to: int | None = None
    rule_name: str | None = None

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")
        if self.kind is not None and self.kind in DOCUMENT_BOUND_KINDS:
            if not self.source_sha256 or not str(self.source_sha256).strip():
                raise ValueError(f"source_sha256 is required for document-bound evidence kind '{self.kind}'")
            if not self.document_version_id or not str(self.document_version_id).strip():
                raise ValueError(f"document_version_id is required for document-bound evidence kind '{self.kind}'")
            if not self.page_id or not str(self.page_id).strip():
                raise ValueError(f"page_id is required for document-bound evidence kind '{self.kind}'")


@dataclass(frozen=True, slots=True)
class CorrectionCandidateData:
    candidate_id: str
    rule_category: RuleCategory | str
    change_type: ChangeType | str = "modified"
    status: ReviewStatus | str = "pending_review"
    original_text: str | None = None
    proposed_text: str | None = None
    evidence: EvidenceData | None = None
    evidence_list: list[EvidenceData] = field(default_factory=list)
    archaeology_object_id: str | None = None
    confidence: float = 1.0
    analysis_run_id: str | None = None
    severity: str = "medium"
    finding_fingerprint: str | None = None

    @property
    def evidences(self) -> list[EvidenceData]:
        res: list[EvidenceData] = []
        if self.evidence is not None:
            res.append(self.evidence)
        for ev in self.evidence_list:
            if ev not in res:
                res.append(ev)
        return res


@dataclass(frozen=True, slots=True)
class RuleCheckResult:
    candidates: list[CorrectionCandidateData]
    summary: dict[str, dict[str, int] | int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReviewDecisionData:
    id: str
    candidate_id: str
    decision_status: ReviewDecisionValue | str
    note: str = ""
    reviewer: str = ""
    modified_text: str | None = None
    previous_decision_id: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        if self.decision_status not in ("accepted", "rejected", "modified", "deferred"):
            raise ValueError(
                f"decision_status must be one of accepted|rejected|modified|deferred, "
                f"got {self.decision_status!r}"
            )


Evidence = EvidenceData
CorrectionCandidate = CorrectionCandidateData
