from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from app.services.visual_asset_matcher import VisualAssetMatch


@dataclass(frozen=True, slots=True)
class PlatePanelModelCandidate:
    source_asset_id: str
    image_path: str | Path
    retrieval_score: float


@dataclass(frozen=True, slots=True)
class PlatePanelModelRequest:
    panel_id: str
    pdf_path: str | Path
    physical_page: int
    bbox: tuple[float, float, float, float]
    candidates: tuple[PlatePanelModelCandidate, ...]


@dataclass(frozen=True, slots=True)
class PlatePanelModelDecision:
    verdict: str
    candidate_id: str | None
    confidence: float
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class PlatePanelModelResolution:
    panel_id: str
    status: str
    selected_source_asset_id: str | None
    confidence: float
    gate_reason: str
    rationale: str = ""


class PlatePanelModelClient(Protocol):
    def resolve(self, request: PlatePanelModelRequest) -> PlatePanelModelDecision: ...


class PlatePanelModelResolver:
    """Closed-world second-stage resolver for deterministic panel retrieval.

    Deterministic verified matches always win and never invoke the model. Model
    selections can only auto-resolve to an ID supplied in the request, must meet
    the configured confidence threshold, and remain fail-closed on same-PDF
    assignment conflicts. Reuse across distinct PDF revisions is allowed.
    """

    def __init__(
        self,
        client: PlatePanelModelClient,
        *,
        auto_confidence: float = 0.95,
    ) -> None:
        if not 0.0 <= auto_confidence <= 1.0:
            raise ValueError("auto_confidence must be between 0 and 1")
        self._client = client
        self._auto_confidence = float(auto_confidence)

    @staticmethod
    def _pdf_identity(value: str | Path) -> str:
        return str(value).replace("\\", "/").casefold()

    def _resolve_model_request(
        self,
        request: PlatePanelModelRequest,
    ) -> PlatePanelModelResolution:
        if not request.candidates:
            return PlatePanelModelResolution(
                panel_id=request.panel_id,
                status="UNRESOLVED",
                selected_source_asset_id=None,
                confidence=0.0,
                gate_reason="no_candidates",
            )

        try:
            decision = self._client.resolve(request)
        except Exception as exc:
            return PlatePanelModelResolution(
                panel_id=request.panel_id,
                status="UNRESOLVED",
                selected_source_asset_id=None,
                confidence=0.0,
                gate_reason="model_error",
                rationale=str(exc),
            )

        verdict = str(decision.verdict or "").strip().lower()
        confidence = max(0.0, min(1.0, float(decision.confidence)))
        allowed_ids = {candidate.source_asset_id for candidate in request.candidates}
        candidate_id = str(decision.candidate_id or "").strip() or None

        if verdict == "none":
            return PlatePanelModelResolution(
                panel_id=request.panel_id,
                status="UNRESOLVED",
                selected_source_asset_id=None,
                confidence=confidence,
                gate_reason="model_no_match",
                rationale=decision.rationale,
            )

        if verdict == "ambiguous":
            return PlatePanelModelResolution(
                panel_id=request.panel_id,
                status="REVIEW_REQUIRED",
                selected_source_asset_id=None,
                confidence=confidence,
                gate_reason="model_ambiguous",
                rationale=decision.rationale,
            )

        if verdict != "match":
            return PlatePanelModelResolution(
                panel_id=request.panel_id,
                status="REVIEW_REQUIRED",
                selected_source_asset_id=None,
                confidence=confidence,
                gate_reason="invalid_model_verdict",
                rationale=decision.rationale,
            )

        if candidate_id not in allowed_ids:
            return PlatePanelModelResolution(
                panel_id=request.panel_id,
                status="REVIEW_REQUIRED",
                selected_source_asset_id=None,
                confidence=confidence,
                gate_reason="candidate_outside_closed_world",
                rationale=decision.rationale,
            )

        if confidence < self._auto_confidence:
            return PlatePanelModelResolution(
                panel_id=request.panel_id,
                status="REVIEW_REQUIRED",
                selected_source_asset_id=candidate_id,
                confidence=confidence,
                gate_reason="confidence_below_threshold",
                rationale=decision.rationale,
            )

        return PlatePanelModelResolution(
            panel_id=request.panel_id,
            status="MODEL_VERIFIED",
            selected_source_asset_id=candidate_id,
            confidence=confidence,
            gate_reason="model_verified",
            rationale=decision.rationale,
        )

    def resolve(
        self,
        *,
        requests: list[PlatePanelModelRequest] | tuple[PlatePanelModelRequest, ...],
        deterministic_matches: dict[str, VisualAssetMatch],
    ) -> dict[str, PlatePanelModelResolution]:
        request_by_id = {request.panel_id: request for request in requests}
        results: dict[str, PlatePanelModelResolution] = {}

        for request in requests:
            deterministic = deterministic_matches.get(request.panel_id)
            if deterministic is not None:
                results[request.panel_id] = PlatePanelModelResolution(
                    panel_id=request.panel_id,
                    status="DETERMINISTIC_VERIFIED",
                    selected_source_asset_id=deterministic.source_asset_id,
                    confidence=deterministic.score,
                    gate_reason="deterministic_verified",
                    rationale=deterministic.method,
                )
                continue
            results[request.panel_id] = self._resolve_model_request(request)

        occupied: set[tuple[str, str]] = set()
        for panel_id, deterministic in deterministic_matches.items():
            request = request_by_id.get(panel_id)
            if request is None:
                continue
            occupied.add(
                (self._pdf_identity(request.pdf_path), deterministic.source_asset_id)
            )

        model_assignments: dict[tuple[str, str], list[str]] = defaultdict(list)
        for panel_id, resolution in results.items():
            if resolution.status != "MODEL_VERIFIED":
                continue
            request = request_by_id[panel_id]
            source_asset_id = resolution.selected_source_asset_id
            if source_asset_id is None:
                continue
            model_assignments[
                (self._pdf_identity(request.pdf_path), source_asset_id)
            ].append(panel_id)

        conflicting_panel_ids: set[str] = set()
        for key, panel_ids in model_assignments.items():
            if key in occupied or len(panel_ids) > 1:
                conflicting_panel_ids.update(panel_ids)

        for panel_id in conflicting_panel_ids:
            resolution = results[panel_id]
            results[panel_id] = replace(
                resolution,
                status="REVIEW_REQUIRED",
                gate_reason="assignment_conflict",
            )

        return results
