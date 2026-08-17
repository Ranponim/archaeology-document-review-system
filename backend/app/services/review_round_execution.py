from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.graph.project_repository import (
    DocumentVersionNotFoundError,
    ReviewRoundNotFoundError,
)


@dataclass(frozen=True, slots=True)
class ResolvedReviewRoundInputs:
    review_round: Any
    body: Any
    plate: Any | None
    drawing: Any | None
    compatibility_stage: str


def _resolve_required_version(
    repository: Any,
    project_id: str,
    kind: str,
    version_id: str | None,
    *,
    required: bool,
) -> Any | None:
    if not version_id:
        if required:
            raise DocumentVersionNotFoundError(
                f"ReviewRound requires a '{kind}' DocumentVersion"
            )
        return None

    version = repository.resolve_version_input(
        project_id,
        kind,
        None,
        version_id,
    )
    if version is None:
        raise DocumentVersionNotFoundError(
            f"DocumentVersion '{version_id}' is not a '{kind}' version owned by "
            f"project '{project_id}'"
        )
    return version


def resolve_review_round_inputs(
    repository: Any,
    project_id: str,
    round_id: str,
) -> ResolvedReviewRoundInputs:
    """Resolve the authoritative document set for one review round.

    Direct body/plate/drawing ids from an HTTP request are intentionally not
    accepted here. The ReviewRound graph node owns that selection, and every
    referenced version is re-resolved through the project+kind boundary before
    a run can be created.
    """
    review_round = repository.get_review_round(project_id, round_id)
    if review_round is None:
        raise ReviewRoundNotFoundError(
            f"Review round '{round_id}' not found in project '{project_id}'"
        )

    body = _resolve_required_version(
        repository,
        project_id,
        "report_body",
        review_round.body_version_id,
        required=True,
    )
    plate = _resolve_required_version(
        repository,
        project_id,
        "plate_book",
        review_round.plate_version_id,
        required=False,
    )
    drawing = _resolve_required_version(
        repository,
        project_id,
        "drawing_book",
        review_round.drawing_version_id,
        required=False,
    )

    sequence = int(review_round.sequence)
    compatibility_stage = f"{sequence}차"
    return ResolvedReviewRoundInputs(
        review_round=review_round,
        body=body,
        plate=plate,
        drawing=drawing,
        compatibility_stage=compatibility_stage,
    )
