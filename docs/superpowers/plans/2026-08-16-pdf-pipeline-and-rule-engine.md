# 고고학 문서 분석 파이프라인 및 규칙 엔진 구현 계획 (PDF Ingestion, Alignment, Rule Engine)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고고학 발굴보고서 교정본(PDF 1·2·3차)을 파싱하여 페이지·텍스트 블록을 추출하고, 버전 간 내용 기반 정렬을 수행하며, 규칙 엔진으로 기계적 교정 후보(도면/도판 번호 누락, 띄어쓰기, 괄호, 지층 화살표)를 도출해 Neo4j에 그래프로 적재하고 OpenRouter AI 호출 기반을 마련한다.

**Architecture:** `PDFParser`가 PDF 지면에서 물리/인쇄 페이지, 헤더/본문 블록, 캡션을 추출하고 정규화 지문을 생성한다. `PageAligner`는 가중 Jaccard/n-gram 및 SequenceMatcher로 버전 간 페이지를 1:1 정렬한다. `RuleEngine`은 미기입 참조 및 문맥 표기 오류를 감지하여 `CorrectionCandidate`와 `Evidence`를 생성한다. `PipelineJob`은 이를 통합 실행해 Neo4j에 적재한다. `OpenRouterClient`는 `.env` 설정을 통해 외부 LLM 호출 기반을 제공한다.

**Tech Stack:** Python 3.12, pypdf / PyMuPDF, FastAPI, Neo4j Python Driver (Cypher), Redis RQ, httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-08-15-neo4j-review-mvp-design.md`, `README.md`

## Global Constraints

- 모든 원본 파일은 읽기 전용으로 다루며 절대 수정하거나 이동하지 않는다.
- API 키는 `.env`의 `OPENROUTER_API_KEY`만 읽고, 브라우저 응답이나 Neo4j, 로그에 노출하지 않는다. OpenRouter 엔드포인트는 `https://openrouter.ai/api/v1` (기본값)을 사용한다.
- 고고학 전문가 승인 API 및 자동 문서 수정은 본 계획의 범위 밖이며, 모든 후보는 `pending_review` 상태로 저장된다.
- 테스트는 격리된 환경에서 실행하며, 실제 1차/2차/3차 교정본 표본 30쪽(10개 대응 행)에 대해 기존 기준선(유사도 및 124건 후보)을 검증 통과해야 한다.

---

### Task 1: PDF 지면 구조 파서 (PDFParser)

**Files:**
- Create: `backend/app/domain/document_structure.py`
- Create: `backend/app/services/pdf_parser.py`
- Create: `backend/tests/test_pdf_parser.py`

**Interfaces:**
- Produces: `ParsedPage(physical_page: int, printed_page: int | None, header: str, raw_text: str, normalized_text: str, text_blocks: list[TextBlockData], captions: list[CaptionData])`
- Produces: `PDFParser.parse_pdf(file_path: Path) -> list[ParsedPage]`
- Produces: `PDFParser.parse_page_range(file_path: Path, start_page: int, end_page: int) -> list[ParsedPage]`

- [ ] **Step 1: 실패 단위 테스트 작성**

```python
def test_pdf_parser_extracts_clean_text_and_printed_page(tmp_path):
    # Tests that PDFParser parses header, separates printed page numbers, and normalizes text
```

- [ ] **Step 2: 실패 확인**

Run: `cd .worktrees/windows-docker-foundation/backend && .venv/bin/python -m pytest tests/test_pdf_parser.py -v`

- [ ] **Step 3: PDFParser 구현**

`pypdf`를 사용하여 페이지별 텍스트를 추출하고, 헤더(`백제문화유산연구원 | 101`, `102 | 문화유적 보고서` 등)에서 인쇄 페이지 번호를 파싱하며, 본문 문단과 `① 유구(도면 : , 도판 : )` 형태의 캡션/참조 라인을 분리하고 `normalized_text`를 생성한다.

- [ ] **Step 4: 실제 1·2·3차 교정 PDF 표본 30쪽 파싱 테스트 통과 확인**

Run: `cd .worktrees/windows-docker-foundation/backend && .venv/bin/python -m pytest tests/test_pdf_parser.py -v`

- [ ] **Step 5: 커밋**

```bash
git add backend/app/domain/document_structure.py backend/app/services/pdf_parser.py backend/tests/test_pdf_parser.py
git commit -m "feat: add PDF structure parser for archaeology reports"
```

---

### Task 2: 버전 간 내용 기반 페이지 정렬기 (PageAligner)

**Files:**
- Create: `backend/app/services/page_aligner.py`
- Create: `backend/tests/test_page_aligner.py`

**Interfaces:**
- Consumes: `list[ParsedPage]` from Task 1
- Produces: `AlignedPageRow(row_id: int, pages: dict[str, ParsedPage], similarity_score: float, sequence_matcher_ratio: float)`
- Produces: `PageAligner.align_versions(version_pages: dict[str, list[ParsedPage]], window_size: int = 10) -> list[AlignedPageRow]`

- [ ] **Step 1: 실패 정렬 알고리즘 테스트 작성**

가중 선택기(Jaccard 45% + 4-gram n-gram 55%)와 SequenceMatcher 유사도 공식을 테스트하고, 페이지 번호가 어긋난 경우 내용 기반 매핑 검증.

- [ ] **Step 2: 실패 확인**

Run: `cd .worktrees/windows-docker-foundation/backend && .venv/bin/python -m pytest tests/test_page_aligner.py -v`

- [ ] **Step 3: PageAligner 구현**

단어 집합 Jaccard + 4-gram 문자 집합 Jaccard 가중합 계산기 및 difflib 기반 SequenceMatcher 감사 점수 계산 로직을 구현하고, 슬라이딩 윈도우 방식으로 최적의 1:1:1 대응 행을 도출한다.

- [ ] **Step 4: 실제 1차(p.105-114), 2차(p.111-120), 3차(p.126-135) 정렬 검증**

가중 선택기 텍스트 성분 및 SequenceMatcher 감사값 산출이 README 기준선과 일치하는지 테스트.

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/page_aligner.py backend/tests/test_page_aligner.py
git commit -m "feat: add content-based page aligner across document versions"
```

---

### Task 3: 기계적/규칙 기반 교정 후보 추출 엔진 (RuleEngine)

**Files:**
- Create: `backend/app/services/rule_engine.py`
- Create: `backend/tests/test_rule_engine.py`

**Interfaces:**
- Consumes: `AlignedPageRow` from Task 2
- Produces: `RuleCheckResult(candidates: list[CorrectionCandidateData], summary: dict[str, int])`
- Produces: `RuleEngine.compare_pages(page_a: ParsedPage, page_b: ParsedPage, stage_a: str, stage_b: str) -> list[CorrectionCandidateData]`
- Produces: `RuleEngine.analyze_alignment_rows(rows: list[AlignedPageRow]) -> RuleCheckResult`

- [ ] **Step 1: 실패 규칙 엔진 테스트 작성**

도면/도판 번호 미기입 감지, 띄어쓰기/부호 수정, 화살표 공백 정규화, 유구 식별자 비교 테스트 작성.

- [ ] **Step 2: 실패 확인**

Run: `cd .worktrees/windows-docker-foundation/backend && .venv/bin/python -m pytest tests/test_rule_engine.py -v`

- [ ] **Step 3: RuleEngine 구현**

1) 도면/도판 참조 번호 정규식 매칭 및 `(도면 : , 도판 : )` $\rightarrow$ `(도면 : 57, 도판 : 85)` 감지 (카테고리: `figure_plate_table_photo_ref`).
2) 띄어쓰기, 문맥 부호, 괄호 짝, `→` 공백 감지 (카테고리: `annotation_resolution`).
3) 유구·유물 식별자 변경 감지 (카테고리: `feature_or_artifact_id`).
4) 변경 유형(`added`, `deleted`, `modified`, `moved`) 자동 분류 및 근거(`Evidence`) 첨부.

- [ ] **Step 4: 1차↔2차, 2차↔3차, 1차↔3차 124건 후보 표본 일치 검증**

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/rule_engine.py backend/tests/test_rule_engine.py
git commit -m "feat: add rule-based proofreading discrepancy engine"
```

---

### Task 4: Neo4j 검수 스키마 및 그래프 적재 (ReviewRepository)

**Files:**
- Modify: `backend/app/graph/schema.py`
- Create: `backend/app/graph/review_repository.py`
- Create: `backend/tests/test_review_repository.py`

**Interfaces:**
- Produces: `ReviewRepository.save_page_blocks(version_id: str, pages: list[ParsedPage]) -> None`
- Produces: `ReviewRepository.save_alignment_and_candidates(project_id: str, rows: list[AlignedPageRow], candidates: list[CorrectionCandidateData]) -> None`
- Produces: `ReviewRepository.get_candidates_for_project(project_id: str) -> list[dict]`

- [ ] **Step 1: 실패 리포지토리 테스트 작성 (고립된 Neo4j 테스트 환경)**

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: ReviewRepository Cypher 쿼리 구현**

`(:Page)`, `(:TextBlock)`, `(:Caption)`, `(:CorrectionCandidate)`, `(:Evidence)` 노드 및 관계(`HAS_PAGE`, `HAS_BLOCK`, `ALIGNED_TO`, `SUPPORTED_BY`) 저장 로직 구현.

- [ ] **Step 4: 테스트 통과 확인**

- [ ] **Step 5: 커밋**

```bash
git add backend/app/graph/schema.py backend/app/graph/review_repository.py backend/tests/test_review_repository.py
git commit -m "feat: persist document pages, alignment and correction candidates to Neo4j"
```

---

### Task 5: OpenRouter AI 분석 클라이언트 기반 (OpenRouterClient)

**Files:**
- Create: `backend/app/services/openrouter_client.py`
- Create: `backend/tests/test_openrouter_client.py`

**Interfaces:**
- Consumes: `.env`의 `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` (default: `https://openrouter.ai/api/v1`)
- Produces: `OpenRouterClient.analyze_text_discrepancy(prompt: str, context: dict) -> dict`
- Produces: `OpenRouterClient.health_check() -> bool`

- [ ] **Step 1: 실패 클라이언트 테스트 작성 (mocking & config 검증)**

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: OpenRouterClient 구현**

`httpx.AsyncClient` 기반으로 OpenRouter API 호출 인터페이스를 구현하고, 토큰/타임아웃 처리, 에러 시 내부 키 은닉 및 재시도 가능 에러 분류 로직 작성.

- [ ] **Step 4: 테스트 통과 확인**

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/openrouter_client.py backend/tests/test_openrouter_client.py
git commit -m "feat: add OpenRouter client foundation for LLM review analysis"
```

---

### Task 6: 파이프라인 통합 및 실제 보고서 E2E 검증

**Files:**
- Create: `backend/app/jobs/review_pipeline.py`
- Create: `backend/tests/test_review_pipeline_e2e.py`

**Interfaces:**
- Produces: `run_document_review_pipeline(project_id: str, version_ids: list[str]) -> ReviewPipelineSummary`

- [ ] **Step 1: E2E 파이프라인 검증 테스트 작성**

실제 1·2·3차 교정 PDF 파일들을 입력하여 파싱 $\rightarrow$ 정렬 $\rightarrow$ 규칙 검사 $\rightarrow$ 그래프 적재가 완전 무결하게 수행되는지 검증.

- [ ] **Step 2: 파이프라인 오케스트레이션 구현 및 실행**

- [ ] **Step 3: 실제 산노리 유적 교정본 데이터 전수 검증 통과 확인**

- [ ] **Step 4: 커밋**

```bash
git add backend/app/jobs/review_pipeline.py backend/tests/test_review_pipeline_e2e.py
git commit -m "feat: integrate end-to-end review pipeline and verify on real documents"
```
