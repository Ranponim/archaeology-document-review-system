"""Production orchestrator assembly (plan Task 11 / anti-pattern #14)."""
from app.graph.canonical_repository import CanonicalRepository
from app.graph.project_repository import ProjectRepository
from app.graph.strict_review_repository import StrictReviewRepository
from app.services.ai_review_service import AIReviewService
from app.services.drawing_parser import DrawingParser
from app.services.object_resolver import ObjectResolver
from app.services.pdf_parser import PDFParser
from app.services.plate_parser import PlateParser
from app.services.proofreading_orchestrator import ProofreadingOrchestrator
from app.services.rule_engine import RuleEngine
from app.services.vlm_review_service import VLMReviewService


def build_proofreading_orchestrator(driver) -> ProofreadingOrchestrator:
    """Assemble the complete production orchestrator with every collaborator.

    The production app must never construct a reduced
    ProofreadingOrchestrator(review_repo=...) and still claim graph-backed
    analysis (plan §9 anti-pattern #14).
    """
    return ProofreadingOrchestrator(
        project_repo=ProjectRepository(driver),
        canonical_repo=CanonicalRepository(driver),
        review_repo=StrictReviewRepository(driver),
        pdf_parser=PDFParser(),
        plate_parser=PlateParser(),
        drawing_parser=DrawingParser(),
        object_resolver=ObjectResolver(),
        rule_engine=RuleEngine(),
        vlm_service=VLMReviewService(),
        ai_review_service=AIReviewService(),
    )
