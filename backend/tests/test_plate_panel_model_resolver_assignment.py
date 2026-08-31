from __future__ import annotations

from app.services.plate_panel_model_resolver import (
    PlatePanelModelCandidate,
    PlatePanelModelDecision,
    PlatePanelModelRequest,
    PlatePanelModelResolver,
)
from app.services.visual_asset_matcher import VisualAssetMatch


class FakeClient:
    def resolve(self, request: PlatePanelModelRequest) -> PlatePanelModelDecision:
        return PlatePanelModelDecision(
            verdict="match",
            candidate_id="shared",
            confidence=0.99,
            rationale="looks identical",
        )


def test_model_cannot_take_source_already_verified_in_same_pdf() -> None:
    candidates = (
        PlatePanelModelCandidate(
            source_asset_id="shared",
            image_path="/images/shared.jpg",
            retrieval_score=0.91,
        ),
    )
    deterministic_request = PlatePanelModelRequest(
        panel_id="deterministic-panel",
        pdf_path="plate.pdf",
        physical_page=1,
        bbox=(0.0, 0.0, 0.5, 0.5),
        candidates=candidates,
    )
    model_request = PlatePanelModelRequest(
        panel_id="model-panel",
        pdf_path="plate.pdf",
        physical_page=1,
        bbox=(0.5, 0.0, 1.0, 0.5),
        candidates=candidates,
    )

    results = PlatePanelModelResolver(FakeClient(), auto_confidence=0.95).resolve(
        requests=[deterministic_request, model_request],
        deterministic_matches={
            "deterministic-panel": VisualAssetMatch(
                source_asset_id="shared",
                score=0.99,
            )
        },
    )

    assert results["deterministic-panel"].status == "DETERMINISTIC_VERIFIED"
    assert results["deterministic-panel"].selected_source_asset_id == "shared"
    assert results["model-panel"].status == "REVIEW_REQUIRED"
    assert results["model-panel"].gate_reason == "assignment_conflict"
