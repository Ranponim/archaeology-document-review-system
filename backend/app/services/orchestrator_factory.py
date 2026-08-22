"""Production orchestrator assembly for ReviewRound-authoritative analysis."""
import os

from app.graph.corpus_object_repository import CorpusObjectGraphRepository
from app.graph.coverage_canonical_repository import CoverageCanonicalRepository
from app.graph.graph_review_repository import GraphReviewRepository
from app.graph.optional_ai_review_repository import OptionalAIReviewRepository
from app.graph.production_review_repository import ProductionReviewRepository
from app.graph.review_project_repository import ReviewProjectRepository
from app.services.ai_review_service import AIReviewService
from app.services.asset_review_pipeline import AssetReviewPipeline
from app.services.budgeted_orchestrator import BudgetedProofreadingOrchestrator
from app.services.corpus_object_linker import CorpusObjectLinker
from app.services.development_review_control import (
    BudgetedAIReviewService,
    BudgetedAssetReviewPipeline,
    BudgetedRuleEngine,
    DevelopmentReviewBudget,
)
from app.services.drawing_parser import DrawingParser
from app.services.graph_rules import GraphRuleEngine
from app.services.object_resolver import ObjectResolver
from app.services.optional_graph_review import OptionalGraphReviewDispatcher
from app.services.optional_review_orchestrator import (
    OptionalGraphFirstReviewRoundOrchestrator,
)
from app.services.plate_parser import PlateParser
from app.services import proofreading_orchestrator as proofreading_orchestrator_module
from app.services.proofreading_orchestrator import ProofreadingOrchestrator
from app.services.review_budget import select_development_candidates
from app.services.strict_rule_engine import StrictRuleEngine
from app.services.visual_reference_pdf_parser import VisualReferencePDFParser
from app.services.vlm_review_service import VLMReviewService


proofreading_orchestrator_module.prioritize_and_cap_candidates = (
    select_development_candidates
)


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
    project_repo = ReviewProjectRepository(driver)
    canonical_repo = CoverageCanonicalRepository(driver)
    review_repo = ProductionReviewRepository(driver)
    graph_review_repo = GraphReviewRepository(driver)
    corpus_object_linker = CorpusObjectLinker(CorpusObjectGraphRepository(driver))
    graph_rule_engine = GraphRuleEngine(graph_review_repo)
    vlm_service = VLMReviewService()
    ai_service = AIReviewService()
    optional_dispatcher = OptionalGraphReviewDispatcher(
        ai_reviewer=ai_service,
        vlm_reviewer=vlm_service,
    )
    optional_review_repo = OptionalAIReviewRepository(driver)
    rule_engine = StrictRuleEngine()

    common_graph_kwargs = {
        "graph_rule_engine": graph_rule_engine,
        "corpus_object_linker": corpus_object_linker,
        "optional_review_dispatcher": optional_dispatcher,
        "optional_review_repository": optional_review_repo,
    }

    budget_value = _development_candidate_budget()
    if budget_value is not None:
        budget = DevelopmentReviewBudget(max_expensive_operations=budget_value)
        return BudgetedProofreadingOrchestrator(
            project_repo=project_repo,
            canonical_repo=canonical_repo,
            review_repo=review_repo,
            pdf_parser=VisualReferencePDFParser(),
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
            **common_graph_kwargs,
        )

    return OptionalGraphFirstReviewRoundOrchestrator(
        project_repo=project_repo,
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        pdf_parser=VisualReferencePDFParser(),
        plate_parser=PlateParser(),
        drawing_parser=DrawingParser(),
        object_resolver=ObjectResolver(),
        rule_engine=rule_engine,
        vlm_service=vlm_service,
        ai_review_service=ai_service,
        **common_graph_kwargs,
    )
