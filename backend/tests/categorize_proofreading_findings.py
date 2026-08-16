from pathlib import Path
import json
import re
from app.jobs.review_pipeline import ReviewPipeline

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

pipeline = ReviewPipeline(review_repo=None)
pages_1 = pipeline._parser.parse_pdf(SRC_PDF_1)
pages_2 = pipeline._parser.parse_pdf(SRC_PDF_2)
pages_3 = pipeline._parser.parse_pdf(SRC_PDF_3)

aligned_rows = pipeline._aligner.align_parallel_ranges({
    "1차": pages_1,
    "2차": pages_2,
    "3차": pages_3
})

rule_result = pipeline._rule_engine.analyze_alignment_rows(aligned_rows)
candidates = rule_result.candidates

# Extract focused, high-precision concrete proofreading examples
findings = {
    "도면/도판 번호 누락 및 채움": [],
    "유구 번호 재부여/명칭 수정": [],
    "지층 순서 및 토층(보강토/생토) 표기": [],
    "띄어쓰기 및 맞춤법/문맥 교정": [],
    "축척 및 도면 범례 표기": []
}

for c in candidates:
    orig = c.original_text or ""
    prop = c.proposed_text or ""
    
    if "(도면 : ," in orig or "(도판 : ," in orig:
        if prop and ("(도면 :" in prop or "(도판 :" in prop):
            findings["도면/도판 번호 누락 및 채움"].append(c)
    elif any(term in orig for term in ["호 토광묘", "호 주거지", "호 석관묘", "호 수혈유구"]):
        m1 = re.findall(r"(\d+)호\s*(토광묘|주거지|석관묘|수혈유구)", orig)
        m2 = re.findall(r"(\d+)호\s*(토광묘|주거지|석관묘|수혈유구)", prop)
        if m1 and m2 and m1 != m2:
            findings["유구 번호 재부여/명칭 수정"].append(c)
        elif orig.replace(" ", "") == prop.replace(" ", ""):
            findings["띄어쓰기 및 맞춤법/문맥 교정"].append(c)
    elif "→" in orig or "→" in prop or "보강토" in prop or "생토" in prop:
        findings["지층 순서 및 토층(보강토/생토) 표기"].append(c)
    elif "1/40" in orig or "1/60" in orig or "축척" in orig:
        findings["축척 및 도면 범례 표기"].append(c)
    elif orig.replace(" ", "") == prop.replace(" ", ""):
        findings["띄어쓰기 및 맞춤법/문맥 교정"].append(c)

print("=" * 80)
print("발굴보고서 실제 교정 대상 집계:")
for k, v in findings.items():
    print(f"  • {k}: {len(v)}건")

print("\n" + "=" * 80)
for k, v in findings.items():
    print(f"\n### {k} (대표 사례)")
    for idx, c in enumerate(v[:3]):
        ev = c.evidence
        print(f"[{idx+1}] ({ev.version_from} p.{ev.physical_page_from} -> {ev.version_to} p.{ev.physical_page_to})")
        print(f"    - 원본: {(c.original_text or '')[:140]}")
        print(f"    - 교정: {(c.proposed_text or '')[:140]}")
