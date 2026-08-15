from pathlib import Path
import pytest
from app.jobs.review_pipeline import ReviewPipeline, ReviewPipelineSummary
from app.domain.models import DocumentVersion


def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").is_dir() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("Could not find repository root containing src/ directory")


REPO_ROOT = _find_repo_root()
SRC_PDF_1 = REPO_ROOT / "src/완성까지 가던 교정본들/11.8-본문-1차 교정/11.8-115집 논산 산노리 산17-1번지 유적-본문-1차 교정.pdf"
SRC_PDF_2 = REPO_ROOT / "src/완성까지 가던 교정본들/11.19-2차 교정/11.19-115집 논산 산노리 산17-1번지 유적-본문-2차 교정.pdf"
SRC_PDF_3 = REPO_ROOT / "src/완성까지 가던 교정본들/11.21-3차 교정/11.21-115집 논산 산노리 산17-1번지 유적-본문-3차 교정.pdf"


def test_review_pipeline_e2e_on_sample_ranges():
    pipeline = ReviewPipeline(review_repo=None)
    
    version_files = {
        "1차": (SRC_PDF_1, 105, 114),
        "2차": (SRC_PDF_2, 111, 120),
        "3차": (SRC_PDF_3, 126, 135),
    }
    
    summary = pipeline.run_sample_pipeline(
        project_id="proj_test_sannori",
        version_ranges=version_files
    )
    
    assert isinstance(summary, ReviewPipelineSummary)
    assert summary.status == "completed"
    assert summary.total_pages_parsed == 30
    assert summary.aligned_rows_count == 10
    assert summary.total_candidates > 50
    assert "figure_plate_table_photo_ref" in summary.category_counts
    assert "annotation_resolution" in summary.category_counts
