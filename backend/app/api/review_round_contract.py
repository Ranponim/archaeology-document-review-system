from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from app.api.schemas import ApiModel


class CreateReviewRoundRequest(ApiModel):
    body_version_id: str = Field(alias="bodyVersionId")
    reference_corpus_id: str | None = Field(default=None, alias="referenceCorpusId")
    plate_version_id: str | None = Field(default=None, alias="plateVersionId")
    drawing_version_id: str | None = Field(default=None, alias="drawingVersionId")
    notes: str | None = None

    @model_validator(mode="after")
    def reject_mixed_authority(self):
        if self.reference_corpus_id and (
            self.plate_version_id is not None or self.drawing_version_id is not None
        ):
            raise ValueError("mixed ReferenceCorpus and legacy visual PDF authority is not allowed")
        return self


class ReviewRoundResponse(ApiModel):
    id: str
    project_id: str = Field(alias="projectId")
    sequence: int
    status: str
    body_version_id: str | None = Field(default=None, alias="bodyVersionId")
    reference_corpus_id: str | None = Field(default=None, alias="referenceCorpusId")
    plate_version_id: str | None = Field(default=None, alias="plateVersionId")
    drawing_version_id: str | None = Field(default=None, alias="drawingVersionId")
    created_at: str | None = Field(default=None, alias="createdAt")
    approved_at: str | None = Field(default=None, alias="approvedAt")
    notes: str | None = None

    @field_validator("created_at", "approved_at", mode="before")
    @classmethod
    def serialize_datetime_fields(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)


class ReviewRoundListResponse(ApiModel):
    items: list[ReviewRoundResponse]
