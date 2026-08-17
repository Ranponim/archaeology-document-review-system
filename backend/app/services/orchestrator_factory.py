"""Production orchestrator assembly (plan Task 11 / anti-pattern #14)."""
import os

from app.graph.audited_review_repository import AuditedReviewRepository
from app.graph.canonical_repository import CanonicalRepository
from app.graph.project_repository import ProjectRepository
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
from app.services.proofreading_orchestrator import ProofreadingOrchestrator
from app.services.rule_engine import RuleEngine
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
    """Assemble the complete production orchestrator with every collaborator.

    In development mode the complete graph and cheap RuleEngine scan still run,
    while a shared budget coordinator limits expensive VLM/LLM operations before
    they execute. Production has no implicit candidate cap.
    """
    project_repo = ProjectRepository(driver)
    canonical_repo = CanonicalRepository(driver)
    review_repo = AuditedReviewRepository(driver)
    vlm_service = VLMReviewService()
    ai_service = AIReviewService()
    rule_engine = RuleEngine()

    budget_value = _development_candidate_budget()
    if budget_value is not None:
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
                AssetReviewPipeline(vlm_service=vlm_service),
                budget,
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
