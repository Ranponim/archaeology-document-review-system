from pathlib import Path
from typing import Annotated, Any
import uuid
from fastapi import APIRouter, Depends, Request, status
from starlette.concurrency import run_in_threadpool

from app.api.projects import (
    ProjectRepositoryPort,
    ServerOperationError,
    _run_repository,
    get_project_repository,
)
from app.api.schemas import (
    CandidateListResponse,
    CandidateResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewMetricsResponse,
    RunTriggerRequest,
    RunTriggerResponse,
    TraceabilityResponse,
)
from app.config import DATA_ROOT
from app.graph.project_repository import DocumentVersionNotFoundError
from app.graph.review_repository import ReviewRepository
from app.services.proofreading_orchestrator import ProofreadingOrchestrator


class CandidateNotFoundError(RuntimeError):
    def __init__(self, candidate_id: str):
        super().__init__(f"Candidate {candidate_id} not found")
        self.candidate_id = candidate_id


router = APIRouter(prefix="/api/v1/projects", tags=["reviews"])


def get_review_repository(request: Request) -> Any:
    repo = getattr(request.app.state, "review_repository", None)
    if repo is None:
        driver = getattr(request.app.state, "neo4j_driver", None)
        if driver is not None:
            repo = ReviewRepository(driver)
            request.app.state.review_repository = repo
    return repo


def get_orchestrator(request: Request) -> Any:
    orch = getattr(request.app.state, "orchestrator", None)
    if orch is None:
        rev_repo = get_review_repository(request)
        orch = ProofreadingOrchestrator(review_repo=rev_repo)
    return orch


# =============================================================================
# 1. POST /api/v1/projects/{project_id}/runs
# =============================================================================



@router.post(
    "/{project_id}/runs",
    response_model=RunTriggerResponse,
    status_code=status.HTTP_200_OK,
)
async def trigger_proofreading_run(
    project_id: str,
    payload: RunTriggerRequest,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    orchestrator: Annotated[Any, Depends(get_orchestrator)],
    review_repository: Annotated[Any, Depends(get_review_repository)],
) -> RunTriggerResponse:
    # Ensure project exists
    await _run_repository(project_repository.get_project, project_id)

    # Authoritatively resolve body DocumentVersion input
    body_version = await _run_repository(
        project_repository.resolve_version_input,
        project_id,
        "report_body",
        payload.version_stage,
        payload.body_version_id,
    )
    if body_version is None:
        if payload.body_version_id:
            raise DocumentVersionNotFoundError(
                f"DocumentVersion '{payload.body_version_id}' not found for project '{project_id}'"
            )
        raise DocumentVersionNotFoundError(
            f"No 'report_body' DocumentVersion found for project '{project_id}'"
        )

    # Validate plate_version_id if specified
    plate_version_id = payload.plate_version_id
    if plate_version_id:
        plate_version = await _run_repository(
            project_repository.get_document_version_by_id,
            plate_version_id,
        )
        if plate_version is None:
            raise DocumentVersionNotFoundError(
                f"DocumentVersion '{plate_version_id}' not found for project '{project_id}'"
            )

    # Validate drawing_version_id if specified
    drawing_version_id = payload.drawing_version_id
    if drawing_version_id:
        drawing_version = await _run_repository(
            project_repository.get_document_version_by_id,
            drawing_version_id,
        )
        if drawing_version is None:
            raise DocumentVersionNotFoundError(
                f"DocumentVersion '{drawing_version_id}' not found for project '{project_id}'"
            )

    orch = orchestrator
    if orch is None:
        orch = ProofreadingOrchestrator(
            review_repo=review_repository,
            project_repo=project_repository,
        )

    body_pdf_path = payload.body_pdf_path
    if body_pdf_path is None and body_version.uri:
        candidate_path = DATA_ROOT / body_version.uri
        if candidate_path.is_file():
            body_pdf_path = candidate_path
        elif Path(body_version.uri).is_file():
            body_pdf_path = Path(body_version.uri)

    res = await orch.run_proofreading(
        project_id=project_id,
        body_version_id=body_version.version_id,
        plate_version_id=plate_version_id,
        drawing_version_id=drawing_version_id,
        body_pdf_path=body_pdf_path,
        plate_pdf_path=payload.plate_pdf_path,
        drawing_pdf_path=payload.drawing_pdf_path,
        enable_vlm=payload.enable_vlm,
        enable_ai_review=payload.enable_ai_review,
        version_stage=payload.version_stage,
    )

    return RunTriggerResponse(
        run_id=res.analysis_run_id,
        project_id=res.project_id,
        status=res.status,
        pages_parsed=res.pages_parsed,
        objects_resolved=res.objects_resolved,
        references_resolved=res.references_resolved,
        candidates_count=len(res.candidates),
        summary=res.summary,
        errors=res.errors,
    )



# =============================================================================
# 2. GET /api/v1/projects/{project_id}/candidates
# =============================================================================

@router.get(
    "/{project_id}/candidates",
    response_model=CandidateListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_candidates(
    project_id: str,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    review_repository: Annotated[Any, Depends(get_review_repository)],
    status: str | None = None,
    rule_category: str | None = None,
    archaeology_object_id: str | None = None,
    severity: str | None = None,
) -> CandidateListResponse:
    await _run_repository(project_repository.get_project, project_id)

    if review_repository is None:
        return CandidateListResponse(project_id=project_id, total=0, candidates=[])

    raw_candidates = await run_in_threadpool(
        review_repository.get_candidates,
        project_id=project_id,
        status=status,
        rule_category=rule_category,
        archaeology_object_id=archaeology_object_id,
        severity=severity,
    )
    candidates = [CandidateResponse.model_validate(c) for c in raw_candidates]
    return CandidateListResponse(
        project_id=project_id,
        total=len(candidates),
        candidates=candidates,
    )


# =============================================================================
# 3. POST /api/v1/projects/{project_id}/candidates/{candidate_id}/decision
# =============================================================================

@router.post(
    "/{project_id}/candidates/{candidate_id}/decision",
    response_model=ReviewDecisionResponse,
    status_code=status.HTTP_200_OK,
)
async def record_candidate_decision(
    project_id: str,
    candidate_id: str,
    payload: ReviewDecisionRequest,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    review_repository: Annotated[Any, Depends(get_review_repository)],
) -> ReviewDecisionResponse:
    await _run_repository(project_repository.get_project, project_id)

    if review_repository is None:
        raise ServerOperationError("Review repository not configured")

    candidate = await run_in_threadpool(review_repository.get_candidate, candidate_id)
    if not candidate:
        raise CandidateNotFoundError(candidate_id)

    decision_id = f"dec_{uuid.uuid4().hex[:12]}"
    note = payload.rationale or payload.note or ""

    await run_in_threadpool(
        review_repository.save_review_decision,
        decision_id=decision_id,
        candidate_id=candidate_id,
        decision_status=payload.decision,
        note=note,
        reviewer=payload.reviewer,
        modified_text=payload.modified_text,
    )

    updated_cand = await run_in_threadpool(review_repository.get_candidate, candidate_id)
    prev_id = None
    if updated_cand and updated_cand.get("decisions"):
        for d in updated_cand["decisions"]:
            if d.get("id") == decision_id:
                return ReviewDecisionResponse.model_validate(d)
        latest = updated_cand["decisions"][-1]
        prev_id = latest.get("previous_decision_id")

    return ReviewDecisionResponse(
        id=decision_id,
        candidate_id=candidate_id,
        decision_status=payload.decision,
        decision=payload.decision,
        note=note,
        rationale=note,
        reviewer=payload.reviewer,
        modified_text=payload.modified_text,
        previous_decision_id=prev_id,
    )


# =============================================================================
# 4. GET /api/v1/projects/{project_id}/candidates/{candidate_id}/traceability
# =============================================================================

@router.get(
    "/{project_id}/candidates/{candidate_id}/traceability",
    response_model=TraceabilityResponse,
    status_code=status.HTTP_200_OK,
)
async def get_candidate_traceability(
    project_id: str,
    candidate_id: str,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    review_repository: Annotated[Any, Depends(get_review_repository)],
) -> TraceabilityResponse:
    await _run_repository(project_repository.get_project, project_id)

    if review_repository is None:
        raise CandidateNotFoundError(candidate_id)

    trace_data = await run_in_threadpool(
        review_repository.get_candidate_traceability, candidate_id
    )
    if not trace_data or not trace_data.get("candidate"):
        raise CandidateNotFoundError(candidate_id)

    return TraceabilityResponse.model_validate(trace_data)


# =============================================================================
# 5. GET /api/v1/projects/{project_id}/metrics
# =============================================================================

@router.get(
    "/{project_id}/metrics",
    response_model=ReviewMetricsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_project_review_metrics(
    project_id: str,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    review_repository: Annotated[Any, Depends(get_review_repository)],
) -> ReviewMetricsResponse:
    await _run_repository(project_repository.get_project, project_id)

    if review_repository is None:
        return ReviewMetricsResponse(project_id=project_id)

    metrics_data = await run_in_threadpool(
        review_repository.get_metrics, project_id
    )
    return ReviewMetricsResponse.model_validate(metrics_data)
