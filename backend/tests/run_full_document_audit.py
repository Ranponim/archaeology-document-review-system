import time
from pathlib import Path
import json
from app.jobs.review_pipeline import ReviewPipeline, ReviewPipelineSummary
from app.services.pdf_parser import PDFParser
from app.services.page_aligner import PageAligner
from app.services.rule_engine import RuleEngine

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

print("=" * 80)
print("고고학 발굴보고서 교정본 전체 페이지 전수 분석 및 동작 검증")
print("=" * 80)

start_time = time.time()

pipeline = ReviewPipeline(review_repo=None)
version_files = {
    "1차": SRC_PDF_1,
    "2차": SRC_PDF_2,
    "3차": SRC_PDF_3,
}

print("1. 전체 PDF 파싱 및 텍스트 추출 중...")
parse_start = time.time()
pages_1 = pipeline._parser.parse_pdf(SRC_PDF_1)
pages_2 = pipeline._parser.parse_pdf(SRC_PDF_2)
pages_3 = pipeline._parser.parse_pdf(SRC_PDF_3)
parse_elapsed = time.time() - parse_start

print(f"   - 1차 교정본: {len(pages_1)}쪽 파싱 완료")
print(f"   - 2차 교정본: {len(pages_2)}쪽 파싱 완료")
print(f"   - 3차 교정본: {len(pages_3)}쪽 파싱 완료")
print(f"   - 총 파싱 쪽수: {len(pages_1) + len(pages_2) + len(pages_3)}쪽 (소요시간: {parse_elapsed:.2f}초)")

print("\n2. 전수 페이지 자동 정렬 및 유사도 분석 중...")
align_start = time.time()
aligned_rows = pipeline._aligner.align_parallel_ranges({
    "1차": pages_1,
    "2차": pages_2,
    "3차": pages_3
})
align_elapsed = time.time() - align_start
print(f"   - 생성된 1:1:1 대응 행 수: {len(aligned_rows)}개 행 (소요시간: {align_elapsed:.2f}초)")

print("\n3. 전수 규칙 기반 교정 차이점 및 오류 후보 추출 중...")
rule_start = time.time()
rule_result = pipeline._rule_engine.analyze_alignment_rows(aligned_rows)
rule_elapsed = time.time() - rule_start

total_elapsed = time.time() - start_time

print(f"   - 추출 완료 (소요시간: {rule_elapsed:.2f}초)")
print(f"   - 전체 실행 총 소요시간: {total_elapsed:.2f}초")

print("\n" + "=" * 80)
print("전수 검증 분석 결과 통계")
print("=" * 80)
print(f"▶ 총 추출된 교정 후보 건수: {len(rule_result.candidates):,}건")
print("\n▶ 규칙 카테고리별 분포:")
for cat, count in rule_result.summary.get("rule", {}).items():
    print(f"   • {cat:30s}: {count:,}건")

print("\n▶ 변경 유형별 분포:")
for ch_type, count in rule_result.summary.get("change_type", {}).items():
    print(f"   • {ch_type:30s}: {count:,}건")

print("\n▶ 대표 교정 후보 발췌 샘플 (유적의 여러 섹션별):")
samples = rule_result.candidates
step = max(1, len(samples) // 8)
for i in range(0, min(len(samples), step * 8), step):
    c = samples[i]
    ev = c.evidence
    print(f"\n[후보 #{i+1}] ({ev.version_from} -> {ev.version_to}) | {c.rule_category} | {c.change_type}")
    print(f"   - 위치: {ev.version_from} p.{ev.physical_page_from} (인쇄 {ev.printed_page_from}) -> {ev.version_to} p.{ev.physical_page_to} (인쇄 {ev.printed_page_to})")
    if c.original_text:
        print(f"   - 원문: {c.original_text[:120]}...")
    if c.proposed_text:
        print(f"   - 제안: {c.proposed_text[:120]}...")

print("\n" + "=" * 80)
print("전체 페이지 전수 분석 완료.")
print("=" * 80)
