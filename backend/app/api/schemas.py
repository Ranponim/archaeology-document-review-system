from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    progress_stage: str | None = Field(default=None, alias="progressStage")
    progress_message: str | None = Field(default=None, alias="progressMessage")
    current_page: int | None = Field(default=None, alias="currentPage")
    total_pages: int | None = Field(default=None, alias="totalPages")


class ProjectDetailResponse(ProjectResponse):
    documents: list[DocumentResponse] = Field(default_factory=list, alias="documents")
    document_versions: list[DocumentVersionResponse] = Field(alias="documentVersions")
    analysis_runs: list[AnalysisRunResponse] = Field(alias="analysisRuns")


class ErrorResponse(ApiModel):
    code: Literal["input_error", "server_error"]
    request_id: str


# =============================================================================
# Review & Audit Schemas
# =============================================================================

class EvidenceResponse(ApiModel):
    id: str
    kind: str | None = None
    source_sha256: str | None = Field(default=None, alias="sourceSha256")
    document_version_id: str | None = Field(default=None, alias="documentVersionId")
    page_id: str | None = Field(default=None, alias="pageId")
    region_id: str | None = Field(default=None, alias="regionId")
    bbox: list[float] | tuple[float, float, float, float] | None = None
    method: str = "rule"
    analysis_run_id: str | None = Field(default=None, alias="analysisRunId")
    value: Any = ""
    rationale: str | None = None
    confidence: float = 1.0
    version_from: str | None = Field(default=None, alias="versionFrom")
    version_to: str | None = Field(default=None, alias="versionTo")
    physical_page_from: int | None = Field(default=None, alias="physicalPageFrom")
    physical_page_to: int | None = Field(default=None, alias="physicalPageTo")
    printed_page_from: int | None = Field(default=None, alias="printedPageFrom")
    printed_page_to: int | None = Field(default=None, alias="printedPageTo")
    rule_name: str | None = Field(default=None, alias="ruleName")


class ReviewDecisionResponse(ApiModel):
    id: str
    candidate_id: str = Field(alias="candidateId")
    decision_status: str = Field(alias="decisionStatus")
    decision: str | None = None
    note: str = ""
    rationale: str | None = None
    reviewer: str = ""
    modified_text: str | None = Field(default=None, alias="modifiedText")
    previous_decision_id: str | None = Field(default=None, alias="previousDecisionId")
    created_at: str | None = Field(default=None, alias="createdAt")

    @model_validator(mode="before")
    @classmethod
    def normalize_decision_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            status = data.get("decision_status") or data.get("decisionStatus") or data.get("decision") or ""
            data.setdefault("decision_status", status)
            data.setdefault("decision", status)
            note = data.get("note") or data.get("rationale") or ""
            data.setdefault("note", note)
            data.setdefault("rationale", note)
            cid = data.get("candidate_id") or data.get("candidateId") or ""
            data.setdefault("candidate_id", cid)
        return data


class ReviewDecisionRequest(ApiModel):
    decision: str
    reviewer: str = Field(min_length=1)
    rationale: str | None = ""
    note: str | None = ""
    modified_text: str | None = Field(default=None, alias="modifiedText")

    @field_validator("reviewer")
    @classmethod
    def reviewer_not_empty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Reviewer cannot be empty")
        return s

    @field_validator("decision")
    @classmethod
    def decision_valid(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in ("accepted", "rejected", "modified", "deferred"):
            raise ValueError(f"Invalid decision: {v}")
        return s


class CandidateResponse(ApiModel):
    id: str
    category: str = ""
    rule_category: str | None = Field(default=None, alias="ruleCategory")
    change_type: str = Field(default="modified", alias="changeType")
    status: str = "pending_review"
    original_text: str | None = Field(default=None, alias="originalText")
    proposed_text: str | None = Field(default=None, alias="proposedText")
    evidence: dict[str, Any] | EvidenceResponse | None = Field(default_factory=dict)
    evidences: list[EvidenceResponse | dict[str, Any]] = Field(default_factory=list)
    archaeology_object_id: str | None = Field(default=None, alias="archaeologyObjectId")
    confidence: float = 1.0
    severity: str = "medium"
    decisions: list[ReviewDecisionResponse | dict[str, Any]] = Field(default_factory=list)
    latest_decision: ReviewDecisionResponse | dict[str, Any] | None = Field(
        default=None, alias="latestDecision"
    )

    @model_validator(mode="before")
    @classmethod
    def sync_category_and_rule_category(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cand_id = data.get("id") or data.get("candidate_id") or ""
            data["id"] = cand_id
            cat = data.get("category") or data.get("rule_category") or ""
            data["category"] = cat
            data["rule_category"] = cat
            if "evidences" in data and not data.get("evidence") and data["evidences"]:
                data["evidence"] = data["evidences"][0]
            elif "evidence" in data and not data.get("evidences") and data["evidence"]:
                data["evidences"] = [data["evidence"]]
        return data


class CandidateListResponse(ApiModel):
    project_id: str = Field(alias="projectId")
    total: int
    candidates: list[CandidateResponse]


class TraceabilityResponse(ApiModel):
    candidate_id: str = Field(alias="candidateId")
    candidate: CandidateResponse | dict[str, Any] | None = None
    archaeology_object: dict[str, Any] | None = Field(default=None, alias="archaeologyObject")
    evidence: list[EvidenceResponse | dict[str, Any]] | EvidenceResponse | dict[str, Any] | None = None
    evidence_chain: list[dict[str, Any]] = Field(default_factory=list, alias="evidenceChain")
    document_version_id: str | None = Field(default=None, alias="documentVersionId")
    page_id: str | None = Field(default=None, alias="pageId")
    bbox: list[float] | tuple[float, float, float, float] | None = None
    source_sha256: str | None = Field(default=None, alias="sourceSha256")
    decisions: list[ReviewDecisionResponse | dict[str, Any]] = Field(default_factory=list)
    latest_decision: ReviewDecisionResponse | dict[str, Any] | None = Field(
        default=None, alias="latestDecision"
    )
    canonical_path: list[dict[str, Any]] = Field(default_factory=list, alias="canonicalPath")

    @model_validator(mode="before")
    @classmethod
    def populate_traceability_helpers(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cid = data.get("candidate_id") or data.get("candidateId") or ""
            if not cid and data.get("candidate"):
                cand = data["candidate"]
                cid = cand.get("id") if isinstance(cand, dict) else getattr(cand, "id", "")
            data["candidate_id"] = cid

            # Populate shortcuts if evidence chain or evidence is present
            ev_list = data.get("evidence") or []
            if isinstance(ev_list, list) and ev_list:
                first_ev = ev_list[0]
                if isinstance(first_ev, dict):
                    data.setdefault("document_version_id", first_ev.get("document_version_id"))
                    data.setdefault("page_id", first_ev.get("page_id"))
                    data.setdefault("bbox", first_ev.get("bbox"))
                    data.setdefault("source_sha256", first_ev.get("source_sha256"))
        return data


class RunTriggerRequest(ApiModel):
    body_version_id: str | None = Field(default=None, alias="bodyVersionId")
    plate_version_id: str | None = Field(default=None, alias="plateVersionId")
    drawing_version_id: str | None = Field(default=None, alias="drawingVersionId")
    body_pdf_path: str | None = Field(default=None, alias="bodyPdfPath")
    plate_pdf_path: str | None = Field(default=None, alias="platePdfPath")
    drawing_pdf_path: str | None = Field(default=None, alias="drawingPdfPath")
    enable_vlm: bool = Field(default=True, alias="enableVlm")
    enable_ai_review: bool = Field(default=True, alias="enableAiReview")
    version_stage: str = Field(default="1차", alias="versionStage")


class RunTriggerResponse(ApiModel):
    run_id: str = Field(alias="runId")
    project_id: str = Field(alias="projectId")
    status: str
    pages_parsed: int = Field(default=0, alias="pagesParsed")
    objects_resolved: int = Field(default=0, alias="objectsResolved")
    references_resolved: int = Field(default=0, alias="referencesResolved")
    candidates_count: int = Field(default=0, alias="candidatesCount")
    summary: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReviewMetricsResponse(ApiModel):
    project_id: str = Field(alias="projectId")
    total_candidates: int = Field(default=0, alias="totalCandidates")
    pending_candidates: int = Field(default=0, alias="pendingCandidates")
    accepted_candidates: int = Field(default=0, alias="acceptedCandidates")
    rejected_candidates: int = Field(default=0, alias="rejectedCandidates")
    modified_candidates: int = Field(default=0, alias="modifiedCandidates")
    deferred_candidates: int = Field(default=0, alias="deferredCandidates")
    by_category: dict[str, int] = Field(default_factory=dict, alias="byCategory")
    by_severity: dict[str, int] = Field(default_factory=dict, alias="bySeverity")
    by_status: dict[str, int] = Field(default_factory=dict, alias="byStatus")
    completion_rate: float = Field(default=0.0, alias="completionRate")
    accuracy_rate: float = Field(default=0.0, alias="accuracyRate")


# =============================================================================
# Visual Asset Delivery Schemas (review §10 / Phase P0-D)
# =============================================================================


class VisualAssetMetadata(ApiModel):
    """Metadata contract for one renderable visual asset (review §10).

    `imageUrl` is a relative API path to the render route — never a server
    filesystem path (anti-pattern #15). `bbox` is normalized (0..1, PDF
    top-left origin) for plate panels / drawing regions so the frontend can
    overlay a highlight using renderWidth/renderHeight.
    """

    asset_type: str = Field(alias="assetType")
    image_url: str = Field(alias="imageUrl")
    document_version_id: str | None = Field(default=None, alias="documentVersionId")
    source_sha256: str | None = Field(default=None, alias="sourceSha256")
    physical_page: int | None = Field(default=None, alias="physicalPage")
    printed_identifier: str | None = Field(default=None, alias="printedIdentifier")
    region_id: str | None = Field(default=None, alias="regionId")
    bbox: list[float] | None = None
    caption: str | None = None
    render_width: int | None = Field(default=None, alias="renderWidth")
    render_height: int | None = Field(default=None, alias="renderHeight")
    content_type: str = Field(default="image/png", alias="contentType")


class CandidateVisualBundle(ApiModel):
    """Mandatory Test D: one candidate's source body page + canonical visual
    asset together, so the frontend can render both images and highlight both
    bboxes without opening external files."""

    candidate_id: str = Field(alias="candidateId")
    source: VisualAssetMetadata | None = None
    canonical: VisualAssetMetadata | None = None
