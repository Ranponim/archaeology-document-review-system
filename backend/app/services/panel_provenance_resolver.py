from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.services.panel_provenance_vlm import PanelProvenanceVLMResolver
from app.services.visual_asset_matcher import VisualPanelAssessment


@dataclass(frozen=True, slots=True)
class PanelProvenanceDecision:
    status: str
    source_asset_id: str | None
    confidence: float
    final_verified: bool
    reviewed_candidate_ids: tuple[str, ...] = ()


class PanelProvenanceResolver:
    """Route deterministic panel assessments through a fail-closed VLM gate.

    Deterministic VERIFIED results remain final. VLM-supported results are only
    review suggestions and can never be promoted to final provenance here.
    """

    _VLM_ELIGIBLE = frozenset({"BELOW_SCORE", "AMBIGUOUS_MARGIN"})

    def __init__(
        self,
        *,
        vlm: PanelProvenanceVLMResolver,
        minimum_vlm_confidence: float = 0.90,
    ) -> None:
        if not 0.0 <= minimum_vlm_confidence <= 1.0:
            raise ValueError("minimum_vlm_confidence must be between 0 and 1")
        self._vlm = vlm
        self._minimum_vlm_confidence = float(minimum_vlm_confidence)

    @staticmethod
    def _unresolved(reviewed: tuple[str, ...] = ()) -> PanelProvenanceDecision:
        return PanelProvenanceDecision(
            status="UNRESOLVED",
            source_asset_id=None,
            confidence=0.0,
            final_verified=False,
            reviewed_candidate_ids=reviewed,
        )

    async def resolve(
        self,
        *,
        assessment: VisualPanelAssessment,
        panel_bytes: bytes,
        candidate_images: Mapping[str, bytes],
    ) -> PanelProvenanceDecision:
        if assessment.status == "VERIFIED" and assessment.match is not None:
            return PanelProvenanceDecision(
                status="DETERMINISTIC_VERIFIED",
                source_asset_id=assessment.match.source_asset_id,
                confidence=assessment.match.score,
                final_verified=True,
            )

        if assessment.status not in self._VLM_ELIGIBLE:
            return self._unresolved()

        reviewed: list[str] = []
        supported: list[tuple[str, float]] = []
        for candidate in assessment.candidates:
            image_bytes = candidate_images.get(candidate.source_asset_id)
            if image_bytes is None:
                continue
            reviewed.append(candidate.source_asset_id)
            result = await self._vlm.compare(
                panel_bytes=panel_bytes,
                candidate_bytes=image_bytes,
            )
            if (
                result.verdict == "SAME_SOURCE"
                and result.confidence >= self._minimum_vlm_confidence
                and not result.contradictions
            ):
                supported.append((candidate.source_asset_id, result.confidence))

        reviewed_tuple = tuple(reviewed)
        if len(supported) != 1:
            return self._unresolved(reviewed_tuple)

        source_asset_id, confidence = supported[0]
        return PanelProvenanceDecision(
            status="AI_SUPPORTED_REVIEW",
            source_asset_id=source_asset_id,
            confidence=confidence,
            final_verified=False,
            reviewed_candidate_ids=reviewed_tuple,
        )
