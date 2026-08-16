import sys
from pathlib import Path

# Ensure backend root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.jobs.review_pipeline import ReviewPipeline
from app.services.pdf_parser import PDFParser
from app.services.rule_engine import RuleEngine

def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").is_dir() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("Could not find repository root containing src/ directory")

REPO_ROOT = _find_repo_root()
PDF_1 = REPO_ROOT / "src/완성까지 가던 교정본들/11.8-본문-1차 교정/11.8-115집 논산 산노리 산17-1번지 유적-본문-1차 교정.pdf"
PDF_3 = REPO_ROOT / "src/완성까지 가던 교정본들/11.21-3차 교정/11.21-115집 논산 산노리 산17-1번지 유적-본문-3차 교정.pdf"

# 1. Multi-version GT comparison (1차 vs 3차)
pipeline = ReviewPipeline(review_repo=None)
pages_1 = pipeline._parser.parse_pdf(PDF_1)
pages_3 = pipeline._parser.parse_pdf(PDF_3)

aligned_rows = pipeline._aligner.align_parallel_ranges({"1차": pages_1, "3차": pages_3})
gt_rule_result = pipeline._rule_engine.analyze_alignment_rows(aligned_rows)
gt_candidates = gt_rule_result.candidates

# 2. Single-version 1차 detection
single_blank_caps = []
for p in pages_1:
    for cap in p.captions:
        if cap.is_blank_reference:
            single_blank_caps.append((p.physical_page, cap.raw_text))

# Calculate recall of blank caption corrections
gt_blank_fixes = [c for c in gt_candidates if c.rule_category == "figure_plate_table_photo_ref" and ("(도면 :" in (c.original_text or "") or "(도판 :" in (c.original_text or ""))]

print(f"• 1차 vs 3차 사람이 수정한 도면/도판 건수: {len(gt_blank_fixes)}건")
print(f"• 1차 단독 시스템이 탐지한 빈칸 캡션 건수: {len(single_blank_caps)}건")

# Check overlap
found_count = 0
for fix in gt_blank_fixes:
    page_num = fix.evidence.physical_page_from
    orig_t = fix.original_text or ""
    # Check if this page had a blank detected in single version
    if any(p == page_num for p, _ in single_blank_caps):
        found_count += 1

recall = (found_count / max(len(gt_blank_fixes), 1)) * 100
print(f"• 사람 교정 내역 대비 시스템 단독 탐지 커버리지(Recall): {recall:.1f}% ({found_count}/{len(gt_blank_fixes)})")
