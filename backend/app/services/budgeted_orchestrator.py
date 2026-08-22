from app.services.development_review_control import BudgetedProofreadingOrchestratorMixin
from app.services.graph_first_review_round_orchestrator import GraphFirstReviewRoundOrchestrator


class BudgetedProofreadingOrchestrator(
    BudgetedProofreadingOrchestratorMixin,
    GraphFirstReviewRoundOrchestrator,
):
    """Graph-first ReviewRound orchestrator with development-budget diagnostics."""

    def __init__(self, *args, development_budget, **kwargs):
        self.development_budget = development_budget
        super().__init__(*args, **kwargs)
