from collections.abc import Callable
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
from app.api.assets import get_visual_asset_service
from app.api.schemas import (
    CandidateListResponse,
    CandidateResponse,
    CandidateVisualBundle,
    CreateReviewRoundRequest,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewMetricsResponse,
    ReviewRoundListResponse,
    ReviewRoundResponse,
    RunTriggerRequest,
    RunTriggerResponse,
    TraceabilityResponse,
)
from app.graph.project_repository import (
    DocumentVersionNotFoundError,
    ReviewRoundNotFoundError,
)
from app.graph.review_repository import ReviewRepository
from app.services.orchestrator_factory import build_proofreading_orchestrator
from app.services.review_round_execution import resolve_review_round_inputs
from app.services.visual_asset_service import VisualAssetService


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


def get_run_enqueuer(request: Request) -> Callable[[str], str]:
    return request.app.state.run_enqueuer


def get_orchestrator(request: Request) -> Any:
    orch = getattr(request.app.state, "orchestrator", None)
    if orch is None:
        driver = getattr(request.app.state, "neo4j_driver", None)
        if driver is not None:
            orch = build_proofreading_orchestrator(driver)
            request.app.state.orchestrator = orch
    return orch


async def _resolve_version_for_kind(
    project_repository: ProjectRepositoryPort,
    project_id: str,
    kind: str,
    version_id: str | None,
    *,
    stage: str | None = None,
    required: bool,
):
    if not version_id and not stage:
        if required:
            raise DocumentVersionNotFoundError(
                f"Review input requires a '{kind}' DocumentVersion"
            )
        return None
    resolved = await _run_repository(
        project_repository.resolve_version_input,
        project_id,
        kind,
        stage,
        version_id,
    )
    if resolved is None:
        raise DocumentVersionNotFoundError(
            f"DocumentVersion '{version_id or stage}' is not a '{kind}' version owned by "
            f"project '{project_id}'"
        )
    return resolved


# =============================================================================
# 1. POST /api/v1/projects/{project_id}/runs
# =============================================================================


@router.post(
    "/{project_id}/runs",
    response_model=RunTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_proofreading_run(
    project_id: str,
    payload: RunTriggerRequest,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    review_repository: Annotated[Any, Depends(get_review_repository)],
    run_enqueuer: Annotated[Callable[[str], str], Depends(get_run_enqueuer)],
) -> RunTriggerResponse:
    """Create a queued AnalysisRun and enqueue the canonical proofreading job.

    When `reviewRoundId` is supplied, the ReviewRound graph node is the sole
    authority for body/plate/drawing inputs. Direct version ids remain only as
    a compatibility path for old clients.
    """
    await _run_repository(project_repository.get_project, project_id)

    warnings: list[str] = []
    review_round_id = payload.review_round_id

    if review_round_id:
        resolved = await _run_repository(
            resolve_review_round_inputs,
            project_repository,
            project_id,
            review_round_id,
        )
        body_version = resolved.body
        plate_version = resolved.plate
        drawing_version = resolved.drawing
        version_stage = resolved.compatibility_stage
        if payload.body_version_id or payload.plate_version_id or payload.drawing_version_id:
            warnings.append(
                "reviewRoundId is authoritative; direct body/plate/drawing version ids were ignored"
            )
    else:
        body_version = await _resolve_version_for_kind(
            project_repository,
            project_id,
            "report_body",
            payload.body_version_id,
            stage=payload.version_stage,
            required=True,
        )
        plate_version = await _resolve_version_for_kind(
            project_repository,
            project_id,
            "plate_book",
            payload.plate_version_id,
            required=False,
        )
        drawing_version = await _resolve_version_for_kind(
            project_repository,
            project_id,
            "drawing_book",
            payload.drawing_version_id,
            required=False,
        )
        version_stage = payload.version_stage

    if review_repository is None:
        raise ServerOperationError("Review repository not configured")

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    await run_in_threadpool(
        review_repository.create_analysis_run,
        project_id=project_id,
        run_id=run_id,
        review_round_id=review_round_id,
        body_version_id=body_version.version_id,
        plate_version_id=(plate_version.version_id if plate_version is not None else None),
        drawing_version_id=(drawing_version.version_id if drawing_version is not None else None),
        body_pdf_path=payload.body_pdf_path,
        plate_pdf_path=payload.plate_pdf_path,
        drawing_pdf_path=payload.drawing_pdf_path,
        enable_vlm=payload.enable_vlm,
        enable_ai_review=payload.enable_ai_review,
        version_stage=version_stage,
    )
    try:
        await run_in_threadpool(run_enqueuer, run_id)
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - Redis details stay private
        try:
            await run_in_threadpool(
                review_repository.save_analysis_run,
                project_id=project_id,
                run_id=run_id,
                status="failed",
                step="analysis",
                error_code="queue_error",
                retryable=True,
            )
        except ServerOperationError:
            pass
        raise ServerOperationError from None

    return RunTriggerResponse(
        run_id=run_id,
        project_id=project_id,
        status="queued",
        review_round_id=review_round_id,
        warnings=warnings,
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
# 3. POST /api/v1/projects/{project_id}/candidates/{candidate_id}/decision(s)
# =============================================================================


@router.post(
    "/{project_id}/candidates/{candidate_id}/decisions",
    response_model=ReviewDecisionResponse,
    status_code=status.HTTP_200_OK,
)
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

    candidate = await run_in_threadpool(
        review_repository.get_candidate, project_id, candidate_id
    )
    if not candidate:
        raise CandidateNotFoundError(candidate_id)

    decision_id = f"dec_{uuid.uuid4().hex[:12]}"
    note = payload.rationale or payload.note or ""

    await run_in_threadpool(
        review_repository.save_review_decision,
        project_id=project_id,
        decision_id=decision_id,
        candidate_id=candidate_id,
        decision_status=payload.decision,
        note=note,
        reviewer=payload.reviewer,
        modified_text=payload.modified_text,
    )

    updated_cand = await run_in_threadpool(
        review_repository.get_candidate, project_id, candidate_id
    )
    prev_id = None
    if updated_cand and updated_cand.get("decisions"):
        for d in updated_cand["decisions"]:
            if d.get("id") == decision_id:
                record = dict(d)
                record.setdefault("candidate_id", candidate_id)
                record.setdefault("decision", record.get("decision_status"))
                record.setdefault("note", record.get("note") or note)
                return ReviewDecisionResponse.model_validate(record)
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
        review_repository.get_candidate_traceability, project_id, candidate_id
    )
    if not trace_data or not trace_data.get("candidate"):
        raise CandidateNotFoundError(candidate_id)

    return TraceabilityResponse.model_validate(trace_data)


# =============================================================================
# 5. GET /api/v1/projects/{project_id}/candidates/{candidate_id}/visual-bundle
# =============================================================================


@router.get(
    "/{project_id}/candidates/{candidate_id}/visual-bundle",
    response_model=CandidateVisualBundle,
    status_code=status.HTTP_200_OK,
)
async def get_candidate_visual_bundle(
    project_id: str,
    candidate_id: str,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
    review_repository: Annotated[Any, Depends(get_review_repository)],
    visual_asset_service: Annotated[VisualAssetService, Depends(get_visual_asset_service)],
) -> CandidateVisualBundle:
    """Return one candidate's source page and exact/fail-closed canonical asset."""
    await _run_repository(project_repository.get_project, project_id)

    if review_repository is None:
        raise CandidateNotFoundError(candidate_id)
    candidate = await run_in_threadpool(
        review_repository.get_candidate, project_id, candidate_id
    )
    if not candidate:
        raise CandidateNotFoundError(candidate_id)

    bundle = await run_in_threadpool(
        visual_asset_service.get_candidate_visual_bundle,
        candidate_id,
        project_id,
    )
    if not bundle:
        raise CandidateNotFoundError(candidate_id)
    return CandidateVisualBundle.model_validate(bundle)


# =============================================================================
# 6. GET /api/v1/projects/{project_id}/metrics
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


# =============================================================================
# 7. Review Round Endpoints (Review 1)
# =============================================================================


@router.post(
    "/{project_id}/rounds",
    response_model=ReviewRoundResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review_round(
    project_id: str,
    payload: CreateReviewRoundRequest,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> ReviewRoundResponse:
    await _run_repository(project_repository.get_project, project_id)

    body = await _resolve_version_for_kind(
        project_repository,
        project_id,
        "report_body",
        payload.body_version_id,
        required=True,
    )
    plate = await _resolve_version_for_kind(
        project_repository,
        project_id,
        "plate_book",
        payload.plate_version_id,
        required=False,
    )
    drawing = await _resolve_version_for_kind(
        project_repository,
        project_id,
        "drawing_book",
        payload.drawing_version_id,
        required=False,
    )

    round_obj = await _run_repository(
        project_repository.create_review_round,
        project_id,
        body.version_id,
        plate.version_id if plate is not None else None,
        drawing.version_id if drawing is not None else None,
        payload.notes,
    )
    return ReviewRoundResponse(
        id=round_obj.id,
        project_id=round_obj.project_id,
        sequence=round_obj.sequence,
        status=round_obj.status,
        body_version_id=round_obj.body_version_id,
        plate_version_id=round_obj.plate_version_id,
        drawing_version_id=round_obj.drawing_version_id,
        created_at=str(round_obj.created_at) if round_obj.created_at is not None else None,
        approved_at=str(round_obj.approved_at) if round_obj.approved_at is not None else None,
        notes=round_obj.notes,
    )


@router.get(
    "/{project_id}/rounds",
    response_model=ReviewRoundListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_review_rounds(
    project_id: str,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> ReviewRoundListResponse:
    await _run_repository(project_repository.get_project, project_id)
    rounds = await _run_repository(project_repository.list_review_rounds, project_id)
    return ReviewRoundListResponse(
        items=[
            ReviewRoundResponse(
                id=r.id,
                project_id=r.project_id,
                sequence=r.sequence,
                status=r.status,
                body_version_id=r.body_version_id,
                plate_version_id=r.plate_version_id,
                drawing_version_id=r.drawing_version_id,
                created_at=str(r.created_at) if r.created_at is not None else None,
                approved_at=str(r.approved_at) if r.approved_at is not None else None,
                notes=r.notes,
            )
            for r in rounds
        ]
    )


@router.get(
    "/{project_id}/rounds/{round_id}",
    response_model=ReviewRoundResponse,
    status_code=status.HTTP_200_OK,
)
async def get_review_round(
    project_id: str,
    round_id: str,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> ReviewRoundResponse:
    await _run_repository(project_repository.get_project, project_id)
    round_obj = await _run_repository(
        project_repository.get_review_round, project_id, round_id
    )
    if round_obj is None:
        raise ReviewRoundNotFoundError(
            f"Review round {round_id} not found in project {project_id}"
        )
    return ReviewRoundResponse(
        id=round_obj.id,
        project_id=round_obj.project_id,
        sequence=round_obj.sequence,
        status=round_obj.status,
        body_version_id=round_obj.body_version_id,
        plate_version_id=round_obj.plate_version_id,
        drawing_version_id=round_obj.drawing_version_id,
        created_at=str(round_obj.created_at) if round_obj.created_at is not None else None,
        approved_at=str(round_obj.approved_at) if round_obj.approved_at is not None else None,
        notes=round_obj.notes,
    )


@router.post(
    "/{project_id}/rounds/{round_id}/approve",
    response_model=ReviewRoundResponse,
    status_code=status.HTTP_200_OK,
)
async def approve_review_round(
    project_id: str,
    round_id: str,
    project_repository: Annotated[ProjectRepositoryPort, Depends(get_project_repository)],
) -> ReviewRoundResponse:
    await _run_repository(project_repository.get_project, project_id)
    current = await _run_repository(
        project_repository.get_review_round, project_id, round_id
    )
    if current is None:
        raise ReviewRoundNotFoundError(
            f"Review round {round_id} not found in project {project_id}"
        )
    if current.status == "approved" and current.approved_at is not None:
        round_obj = current
    else:
        round_obj = await _run_repository(
            project_repository.approve_review_round, project_id, round_id
        )
    return ReviewRoundResponse(
        id=round_obj.id,
        project_id=round_obj.project_id,
        sequence=round_obj.sequence,
        status=round_obj.status,
        body_version_id=round_obj.body_version_id,
        plate_version_id=round_obj.plate_version_id,
        drawing_version_id=round_obj.drawing_version_id,
        created_at=str(round_obj.created_at) if round_obj.created_at is not None else None,
        approved_at=str(round_obj.approved_at) if round_obj.approved_at is not None else None,
        notes=round_obj.notes,
    )
