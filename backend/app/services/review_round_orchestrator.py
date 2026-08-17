from __future__ import annotations

from app.services.page_aligner import PageAligner
from app.services.proofreading_orchestrator import ProofreadingOrchestrator


class ReviewRoundProofreadingOrchestrator(ProofreadingOrchestrator):
    """Production orchestration semantics for ReviewRound-driven projects.

    DocumentVersions are immutable source assets. ReviewRound PRECEDES owns
    revision order; page alignment may connect pages with ALIGNED_TO but must
    never manufacture DocumentVersion PRECEDES from human stage labels.
    """

    def persist_version_alignment(
        self,
        project_id: str,
        version_pages,
        version_ids,
        run_id: str,
    ) -> None:
        if self.review_repo is None or not version_pages:
            return

        rows = PageAligner().align_parallel_ranges(version_pages)
        self.review_repo.save_aligned_pages(
            rows,
            version_pages,
            run_id,
            version_ids=version_ids,
        )
