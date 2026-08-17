from app.services.development_review_control import BudgetedProofreadingOrchestratorMixin
from app.services.proofreading_orchestrator import ProofreadingOrchestrator


class BudgetedProofreadingOrchestrator(BudgetedProofreadingOrchestratorMixin, ProofreadingOrchestrator):
    """Proofreading orchestrator that publishes development-budget diagnostics."""

    def __init__(self, *args, development_budget, **kwargs):
        self.development_budget = development_budget
        super().__init__(*args, **kwargs)
