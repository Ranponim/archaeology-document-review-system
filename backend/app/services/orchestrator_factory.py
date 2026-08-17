"""Production orchestrator assembly (plan Task 11 / anti-pattern #14)."""
import os

from app.graph.canonical_repository import CanonicalRepository
from app.graph.production_review_repository import ProductionReviewRepository
from app.graph.review_project_repository import ReviewProjectRepository
from app.services.ai_review_service import AIReviewService
from app.services.asset_review_pipeline import AssetReviewPipeline
from app.services.budgeted_orchestrator import BudgetedProofreadingOrchestrator
from app.services.development_review_control import (
    BudgetedAIReviewService,
    BudgetedAssetReviewPipeline,
    BudgetedRuleEngine,
    DevelopmentReviewBudget,
)
from app.services.drawing_parser import DrawingParser
from app.services.object_resolver import ObjectResolver
from app.services.pdf_parser import PDFParser
from app.services.plate_parser import PlateParser
from app.services import proofreading_orchestrator as proofreading_orchestrator_module
from app.services.proofreading_orchestrator import ProofreadingOrchestrator
from app.services.review_budget import select_development_candidates
from app.services.round_stage_ordering import ordered_round_stage_versions
from app.services.strict_rule_engine import StrictRuleEngine
from app.services.vlm_review_service import VLMReviewService


def _development_candidate_budget() -> int | None:
    raw = os.environ.get("DEVELOPMENT_CANDIDATE_BUDGET") or os.environ.get(
        "CANDIDATE_BUDGET"
    )
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value > 0:
            return value
    if os.environ.get("REVIEW_MODE", "").strip().lower() == "development":
        return 10
    return None


def build_proofreading_orchestrator(driver) -> ProofreadingOrchestrator:
    # Compatibility seams for the legacy orchestrator. Production assembly is
    # ReviewRound-aware even though the base class still exposes old helpers.
    proofreading_orchestrator_module._ordered_stage_versions = ordered_round_stage_versions

    project_repo = ReviewProjectRepository(driver)
    canonical_repo = CanonicalRepository(driver)
    review_repo = ProductionReviewRepository(driver)
    vlm_service = VLMReviewService()
    ai_service = AIReviewService()
    rule_engine = StrictRuleEngine()

    budget_value = _development_candidate_budget()
    if budget_value is not None:
        # The final materialized/UI sample must use the same deterministic,
        # category-balanced strategy as the pre-AI budget rather than a simple
        # severity sort + slice that can omit plate/drawing paths entirely.
        proofreading_orchestrator_module.prioritize_and_cap_candidates = (
            select_development_candidates
        )
        budget = DevelopmentReviewBudget(max_expensive_operations=budget_value)
        return BudgetedProofreadingOrchestrator(
            project_repo=project_repo,
            canonical_repo=canonical_repo,
            review_repo=review_repo,
            pdf_parser=PDFParser(),
            plate_parser=PlateParser(),
            drawing_parser=DrawingParser(),
            object_resolver=ObjectResolver(),
            rule_engine=BudgetedRuleEngine(rule_engine, budget),
            asset_review_pipeline=BudgetedAssetReviewPipeline(
                AssetReviewPipeline(vlm_service=vlm_service), budget
            ),
            vlm_service=vlm_service,
            ai_review_service=BudgetedAIReviewService(ai_service, budget),
            max_candidates=budget_value,
            development_budget=budget,
        )

    return ProofreadingOrchestrator(
        project_repo=project_repo,
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        pdf_parser=PDFParser(),
        plate_parser=PlateParser(),
        drawing_parser=DrawingParser(),
        object_resolver=ObjectResolver(),
        rule_engine=rule_engine,
        vlm_service=vlm_service,
        ai_review_service=ai_service,
    )
