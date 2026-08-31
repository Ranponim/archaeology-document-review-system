from __future__ import annotations

from dataclasses import dataclass

from app.services.plate_panel_model_resolver import (
    PlatePanelModelRequest,
    PlatePanelModelResolution,
    PlatePanelModelResolver,
)
from app.services.visual_asset_matcher import VisualAssetMatch


@dataclass(frozen=True, slots=True)
class PlatePanelModelBatchResult:
    resolutions: dict[str, PlatePanelModelResolution]
    deferred_panel_ids: tuple[str, ...]
    attempted_model_reviews: int


class PlatePanelModelBatchReviewer:
    """Run only a bounded, high-value subset of unresolved model reviews."""

    def __init__(
        self,
        resolver: PlatePanelModelResolver,
        *,
        max_reviews: int,
    ) -> None:
        if max_reviews < 0:
            raise ValueError("max_reviews must be non-negative")
        self._resolver = resolver
        self._max_reviews = int(max_reviews)

    @staticmethod
    def _priority(request: PlatePanelModelRequest) -> tuple[float, float, str]:
        scores = sorted(
            (float(candidate.retrieval_score) for candidate in request.candidates),
            reverse=True,
        )
        top = scores[0] if scores else 0.0
        second = scores[1] if len(scores) > 1 else 0.0
        margin = top - second
        # More visually plausible and less ambiguous retrievals give more useful
        # model coverage per bounded call. panel_id makes ordering reproducible.
        return (-top, -margin, request.panel_id)

    def review(
        self,
        *,
        requests: list[PlatePanelModelRequest] | tuple[PlatePanelModelRequest, ...],
        deterministic_matches: dict[str, VisualAssetMatch],
    ) -> PlatePanelModelBatchResult:
        deterministic_requests: list[PlatePanelModelRequest] = []
        no_candidate_requests: list[PlatePanelModelRequest] = []
        reviewable_requests: list[PlatePanelModelRequest] = []

        for request in requests:
            if request.panel_id in deterministic_matches:
                deterministic_requests.append(request)
            elif not request.candidates:
                no_candidate_requests.append(request)
            else:
                reviewable_requests.append(request)

        reviewable_requests.sort(key=self._priority)
        selected = reviewable_requests[: self._max_reviews]
        deferred = reviewable_requests[self._max_reviews :]

        selected_requests = [
            *deterministic_requests,
            *no_candidate_requests,
            *selected,
        ]
        selected_ids = {request.panel_id for request in selected_requests}
        relevant_deterministic = {
            panel_id: match
            for panel_id, match in deterministic_matches.items()
            if panel_id in selected_ids
        }
        resolutions = self._resolver.resolve(
            requests=selected_requests,
            deterministic_matches=relevant_deterministic,
        )

        return PlatePanelModelBatchResult(
            resolutions=resolutions,
            deferred_panel_ids=tuple(request.panel_id for request in deferred),
            attempted_model_reviews=len(selected),
        )
