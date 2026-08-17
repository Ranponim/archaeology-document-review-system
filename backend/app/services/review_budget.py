from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Iterable

from app.domain.review_models import CorrectionCandidateData


_BUCKET_ORDER: tuple[str, ...] = (
    "visual_plate",
    "visual_drawing",
    "numeric_value",
    "feature_or_artifact_id",
    "figure_plate_table_photo_ref",
    "annotation_resolution",
    "direction_period_term",
    "site_or_area_name",
)

_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def _candidate_search_text(candidate: CorrectionCandidateData) -> str:
    parts: list[str] = []
    for text in (candidate.original_text, candidate.proposed_text):
        if text:
            parts.append(str(text))
    for evidence in candidate.evidences:
        value = evidence.value
        if isinstance(value, str):
            parts.append(value)
        elif value not in (None, ""):
            try:
                parts.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
            except TypeError:
                parts.append(str(value))
        if evidence.rationale:
            parts.append(str(evidence.rationale))
    return " ".join(parts).lower()


def candidate_sampling_bucket(candidate: CorrectionCandidateData) -> str:
    """Return a stable development-sampling bucket for one finding.

    Plate and drawing references receive separate buckets so a development
    budget cannot accidentally consume every slot with numeric/text findings
    while leaving the visual review paths untested.
    """
    text = _candidate_search_text(candidate)
    if "도판" in text or "plate" in text:
        return "visual_plate"
    if "도면" in text or "drawing" in text:
        return "visual_drawing"
    return str(candidate.rule_category or "unknown")


def _candidate_sort_key(candidate: CorrectionCandidateData) -> tuple[int, float, str]:
    return (
        _SEVERITY_ORDER.get(str(candidate.severity).lower(), 2),
        -float(candidate.confidence),
        str(candidate.candidate_id),
    )


def select_development_candidates(
    candidates: Iterable[CorrectionCandidateData],
    max_candidates: int | None,
) -> list[CorrectionCandidateData]:
    """Deterministically choose a category-balanced development sample.

    The first pass takes one candidate from every available bucket in the
    explicit bucket order. Remaining slots are filled by global
    severity/confidence/id priority. Reversing the input list therefore does
    not change the selected sample.
    """
    ordered = sorted(list(candidates), key=_candidate_sort_key)
    if max_candidates is None or max_candidates <= 0 or len(ordered) <= max_candidates:
        return ordered

    buckets: dict[str, list[CorrectionCandidateData]] = defaultdict(list)
    for candidate in ordered:
        buckets[candidate_sampling_bucket(candidate)].append(candidate)

    selected: list[CorrectionCandidateData] = []
    selected_ids: set[str] = set()

    ordered_bucket_names = [name for name in _BUCKET_ORDER if buckets.get(name)]
    ordered_bucket_names.extend(
        sorted(name for name in buckets if name not in _BUCKET_ORDER)
    )

    for bucket_name in ordered_bucket_names:
        if len(selected) >= max_candidates:
            break
        candidate = buckets[bucket_name][0]
        selected.append(candidate)
        selected_ids.add(candidate.candidate_id)

    if len(selected) < max_candidates:
        for candidate in ordered:
            if candidate.candidate_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.candidate_id)
            if len(selected) >= max_candidates:
                break

    return selected


def make_finding_fingerprint(candidate: CorrectionCandidateData) -> str:
    payload = "|".join(
        [
            str(candidate.rule_category or ""),
            str(candidate.change_type or ""),
            str(candidate.archaeology_object_id or ""),
            str(candidate.original_text or ""),
            str(candidate.proposed_text or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def make_run_candidate_id(run_id: str, candidate: CorrectionCandidateData) -> str:
    run_token = str(run_id).replace(" ", "_")
    return f"cand_{run_token}_{make_finding_fingerprint(candidate)}"
