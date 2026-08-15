from dataclasses import dataclass, field
from typing import Literal

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


@dataclass(frozen=True, slots=True)
class EvidenceData:
    version_from: str
    version_to: str
    physical_page_from: int | None
    physical_page_to: int | None
    printed_page_from: int | None
    printed_page_to: int | None
    rule_name: str
    rationale: str


@dataclass(frozen=True, slots=True)
class CorrectionCandidateData:
    candidate_id: str
    rule_category: RuleCategory
    change_type: ChangeType
    status: ReviewStatus
    original_text: str | None
    proposed_text: str | None
    evidence: EvidenceData


@dataclass(frozen=True, slots=True)
class RuleCheckResult:
    candidates: list[CorrectionCandidateData]
    summary: dict[str, dict[str, int] | int] = field(default_factory=dict)
