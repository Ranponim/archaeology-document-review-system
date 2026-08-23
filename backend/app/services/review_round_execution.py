from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.reference_corpus import ReferenceCorpusStatus
from app.graph.project_repository import (
    DocumentVersionNotFoundError,
    ReviewRoundNotFoundError,
)
from app.graph.reference_corpus_repository import ReferenceCorpusRepository


@dataclass(frozen=True, slots=True)
class ResolvedReviewRoundInputs:
    review_round: Any
    body: Any
    reference_corpus: Any | None
    plate: Any | None
    drawing: Any | None
    mode: str
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


def _resolve_ready_reference_corpus(
    repository: Any,
    project_id: str,
    corpus_id: str,
) -> Any:
    getter = getattr(repository, "get_reference_corpus", None)
    if callable(getter):
        corpus = getter(project_id, corpus_id)
    else:
        driver = getattr(repository, "_driver", None)
        database = getattr(repository, "_database", None)
        if driver is None:
            raise ValueError("reference corpus repository is unavailable")
        corpus = ReferenceCorpusRepository(driver, database).get(project_id, corpus_id)

    if corpus is None:
        raise ValueError("reference corpus does not belong to project")
    status = getattr(corpus, "status", None)
    status_value = status.value if isinstance(status, ReferenceCorpusStatus) else str(status or "")
    if status_value.lower() != ReferenceCorpusStatus.READY.value:
        raise ValueError("ReviewRound reference corpus must remain READY at execution time")
    return corpus


def resolve_review_round_inputs(
    repository: Any,
    project_id: str,
    round_id: str,
) -> ResolvedReviewRoundInputs:
    """Resolve graph-resident authoritative inputs for one ReviewRound.

    Body-only rounds carry text-proofreading authority only. Graph-first visual
    rounds use one body DocumentVersion plus one READY ReferenceCorpus.
    Historical rounds may still reference plate/drawing DocumentVersions. The
    visual authority modes never mix, and corpus mode never resolves visual PDFs.
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
    reference_corpus_id = getattr(review_round, "reference_corpus_id", None)
    plate_version_id = getattr(review_round, "plate_version_id", None)
    drawing_version_id = getattr(review_round, "drawing_version_id", None)

    if reference_corpus_id:
        if plate_version_id or drawing_version_id:
            raise ValueError("mixed ReferenceCorpus and legacy visual PDF authority is not allowed")
        reference_corpus = _resolve_ready_reference_corpus(
            repository,
            project_id,
            reference_corpus_id,
        )
        plate = None
        drawing = None
        mode = "reference_corpus"
    elif not plate_version_id and not drawing_version_id:
        reference_corpus = None
        plate = None
        drawing = None
        mode = "body_only"
    else:
        reference_corpus = None
        plate = _resolve_required_version(
            repository,
            project_id,
            "plate_book",
            plate_version_id,
            required=True,
        )
        drawing = _resolve_required_version(
            repository,
            project_id,
            "drawing_book",
            drawing_version_id,
            required=True,
        )
        mode = "legacy_visual_pdf"

    sequence = int(review_round.sequence)
    compatibility_stage = f"{sequence}차"
    return ResolvedReviewRoundInputs(
        review_round=review_round,
        body=body,
        reference_corpus=reference_corpus,
        plate=plate,
        drawing=drawing,
        mode=mode,
        compatibility_stage=compatibility_stage,
    )
