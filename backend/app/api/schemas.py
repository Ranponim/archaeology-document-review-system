from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ProjectCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    internal_code: str | None = Field(
        default=None,
        alias="internalCode",
        max_length=100,
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Project name must not be blank")
        return normalized

    @field_validator("internal_code")
    @classmethod
    def normalize_internal_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProjectResponse(ApiModel):
    id: str
    name: str
    internal_code: str | None = Field(alias="internalCode")


class UploadResponse(ApiModel):
    document_version_id: str = Field(alias="documentVersionId")
    analysis_run_id: str = Field(alias="analysisRunId")


class RetryAnalysisRunResponse(ApiModel):
    analysis_run_id: str = Field(alias="analysisRunId")
    status: Literal["queued", "running"]


class DocumentResponse(ApiModel):
    id: str
    project_id: str = Field(alias="projectId")
    kind: str = "report_body"
    title: str = ""


class DocumentVersionResponse(ApiModel):
    id: str
    document_id: str = Field(alias="documentId")
    original_name: str = Field(alias="originalName")
    mime_type: str = Field(alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes")
    stage: str


class AnalysisRunResponse(ApiModel):
    id: str
    status: str
    step: str
    document_version_id: str = Field(alias="documentVersionId")
    error_code: str | None = Field(default=None, alias="errorCode")
    retryable: bool = False


class ProjectDetailResponse(ProjectResponse):
    documents: list[DocumentResponse] = Field(default_factory=list, alias="documents")
    document_versions: list[DocumentVersionResponse] = Field(alias="documentVersions")
    analysis_runs: list[AnalysisRunResponse] = Field(alias="analysisRuns")


class ErrorResponse(ApiModel):
    code: Literal["input_error", "server_error"]
    request_id: str


class AIAnalyzeRequest(ApiModel):
    version_id: str | None = Field(default=None, alias="versionId")
    model: str = Field(default="openai/gpt-5.6-luna")


class AIAnalyzeResponse(ApiModel):
    analysis_run_id: str = Field(alias="analysisRunId")
    status: str
    model: str


class CandidateResponse(ApiModel):
    id: str
    category: str
    change_type: str = Field(alias="changeType")
    status: str
    original_text: str | None = Field(default=None, alias="originalText")
    proposed_text: str | None = Field(default=None, alias="proposedText")
    evidence: dict[str, Any] = Field(default_factory=dict)


class CandidateListResponse(ApiModel):
    project_id: str = Field(alias="projectId")
    total: int
    candidates: list[CandidateResponse]
