from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator


class DrawingReviewCandidateResponse(BaseModel):
    candidate_id: str
    publication_kind: str
    number: str
    caption: str
    image_url: str | None
    local_score: float
    evidence_summary: list[str]
    contradiction_summary: list[str]


class DrawingReviewCaseResponse(BaseModel):
    source_asset_id: str
    source_name: str
    source_image_url: str | None
    source_text: str
    codex_candidate_id: str | None
    codex_confidence: float | None
    codex_summary: str | None
    candidates: list[DrawingReviewCandidateResponse]


class DrawingReviewResolveRequest(BaseModel):
    action: Literal["approve", "choose", "none"]
    candidate_id: str | None = None
    reviewer: str = "human"

    @model_validator(mode="after")
    def validate_candidate_selection(self):
        if self.action in {"approve", "choose"} and not self.candidate_id:
            raise ValueError(f"{self.action} requires candidate_id")
        if self.action == "none" and self.candidate_id is not None:
            raise ValueError("none requires candidate_id to be null")
        return self


class DrawingReviewResolveResponse(BaseModel):
    source_asset_id: str
    action: Literal["approve", "choose", "none"]
    candidate_id: str | None
    final_status: Literal["HUMAN_VERIFIED", "HUMAN_UNRESOLVED"]
