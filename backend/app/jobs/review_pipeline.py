from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from app.services.pdf_parser import PDFParser
from app.services.page_aligner import PageAligner
from app.services.rule_engine import RuleEngine
from app.graph.review_repository import ReviewRepository
from app.domain.document_structure import ParsedPage


@dataclass(frozen=True, slots=True)
class ReviewPipelineSummary:
    project_id: str
    status: str
    total_pages_parsed: int
    aligned_rows_count: int
    total_candidates: int
    category_counts: dict[str, int] = field(default_factory=dict)
    change_type_counts: dict[str, int] = field(default_factory=dict)


class ReviewPipeline:
    def __init__(
        self,
        review_repo: ReviewRepository | None = None,
        pdf_parser: PDFParser | None = None,
        page_aligner: PageAligner | None = None,
        rule_engine: RuleEngine | None = None,
    ) -> None:
        self._repo = review_repo
        self._parser = pdf_parser or PDFParser()
        self._aligner = page_aligner or PageAligner()
        self._rule_engine = rule_engine or RuleEngine()

    def run_sample_pipeline(
        self,
        project_id: str,
        version_ranges: dict[str, tuple[Path, int, int]],
    ) -> ReviewPipelineSummary:
        """Parses specified page ranges for each version, aligns them, and generates candidates."""
        version_pages: dict[str, list[ParsedPage]] = {}
        total_pages = 0

        # 1. Parse pages for each version
        for stage, (pdf_path, start_p, end_p) in version_ranges.items():
            pages = self._parser.parse_page_range(pdf_path, start_p, end_p)
            version_pages[stage] = pages
            total_pages += len(pages)

            if self._repo is not None:
                version_id = f"{project_id}_{stage}"
                self._repo.save_pages_and_blocks(version_id, pages)

        # 2. Align parallel pages across versions
        aligned_rows = self._aligner.align_parallel_ranges(version_pages)

        # 3. Run rule-based discrepancy analysis
        rule_result = self._rule_engine.analyze_alignment_rows(aligned_rows)

        # 4. Save candidates to Neo4j if repository is configured
        if self._repo is not None:
            self._repo.save_candidates(project_id, rule_result.candidates)

        rule_counts = rule_result.summary.get("rule", {})
        change_counts = rule_result.summary.get("change_type", {})

        return ReviewPipelineSummary(
            project_id=project_id,
            status="completed",
            total_pages_parsed=total_pages,
            aligned_rows_count=len(aligned_rows),
            total_candidates=len(rule_result.candidates),
            category_counts=rule_counts if isinstance(rule_counts, dict) else {},
            change_type_counts=change_counts if isinstance(change_counts, dict) else {},
        )

    def run_full_pipeline(
        self,
        project_id: str,
        version_files: dict[str, Path],
    ) -> ReviewPipelineSummary:
        """Parses full PDFs for all versions, performs sliding alignment, and generates candidates."""
        version_pages: dict[str, list[ParsedPage]] = {}
        total_pages = 0

        for stage, pdf_path in version_files.items():
            pages = self._parser.parse_pdf(pdf_path)
            version_pages[stage] = pages
            total_pages += len(pages)

            if self._repo is not None:
                version_id = f"{project_id}_{stage}"
                self._repo.save_pages_and_blocks(version_id, pages)

        aligned_rows = self._aligner.align_parallel_ranges(version_pages)
        rule_result = self._rule_engine.analyze_alignment_rows(aligned_rows)

        if self._repo is not None:
            self._repo.save_candidates(project_id, rule_result.candidates)

        rule_counts = rule_result.summary.get("rule", {})
        change_counts = rule_result.summary.get("change_type", {})

        return ReviewPipelineSummary(
            project_id=project_id,
            status="completed",
            total_pages_parsed=total_pages,
            aligned_rows_count=len(aligned_rows),
            total_candidates=len(rule_result.candidates),
            category_counts=rule_counts if isinstance(rule_counts, dict) else {},
            change_type_counts=change_counts if isinstance(change_counts, dict) else {},
        )
