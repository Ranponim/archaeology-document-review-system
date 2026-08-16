# Canonical Document–Object–Evidence Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `PDFParser / PageAligner / RuleEngine / AssetMatcher / VLM / Neo4j`를 하나의 canonical Document–Object–Evidence 그래프로 연결하고, 고고학자 피드백에서 확인된 Case 6 오매칭이 다시는 발생하지 않는 MVP를 구현한다.

**Architecture:** Deterministic document structure가 identity를 결정하고, `Reference → Plate/Drawing → ArchaeologyObject → Evidence` 경로를 Neo4j에 저장한다. Rule/LLM/VLM은 이 canonical identity를 변경하지 않고 evidence만 생성하며, 모든 CorrectionCandidate는 `pending_review`로 시작한다.

**Tech Stack:** Python 3, FastAPI, Neo4j, RQ/Redis, PyMuPDF, pypdf(보조), Pydantic, httpx, Pillow, React/TypeScript, pytest, Docker Compose

## Global Constraints

- `Links filename number != plate number`를 절대 규칙으로 유지한다.
- `PDF physical page != publication plate number`를 별도 필드로 유지한다.
- 도판 identity는 우선적으로 PDF 내 명시적 `【도판 N】`에서 얻는다.
- 도면 identity도 명시적 publication identifier를 우선한다.
- LLM/VLM은 canonical identity를 생성하거나 덮어쓰지 않는다.
- 모든 `CorrectionCandidate`는 `pending_review`로 시작한다.
- 모든 Candidate는 source-addressable Evidence를 최소 1개 이상 가진다.
- 모든 Evidence는 `source_sha256 + DocumentVersion + Page + bbox/region`으로 역추적 가능해야 한다.
- 원본 파일은 자동 수정하지 않는다.
- canonical resolution이 불확실하면 `ambiguous/unresolved`로 남긴다.
- Case 6 regression test가 실패하면 MVP 전체 FAIL이다.

---

## File Map

### Domain / Contracts

- Modify: `backend/app/domain/document_structure.py` — Page/TextBlock/Caption/Reference/Plate/Panel 구조 타입 확장
- Modify: `backend/app/domain/models.py` — Document/DocumentVersion 역할 정리
- Modify: `backend/app/domain/review_models.py` — Evidence/Candidate/Review 상태 계약 정리
- Create: `backend/app/domain/canonical_models.py` — Reference, Plate, PlatePanel, Drawing, DrawingRegion, ArchaeologyObject 데이터 계약

### Parsing / Resolution

- Modify: `backend/app/services/pdf_parser.py` — bbox/layout/reference/explicit plate identifier 파싱
- Create: `backend/app/services/plate_parser.py` — plate book 전용 파싱
- Create: `backend/app/services/drawing_parser.py` — drawing book 전용 identifier/region 파싱
- Modify: `backend/app/services/page_aligner.py` — 강제 match 방지 및 상태 추가
- Modify: `backend/app/services/asset_matcher.py` — filename matcher → canonical Reference Resolver
- Create: `backend/app/services/object_resolver.py` — ArchaeologyObject 생성/병합 후보

### Analysis

- Modify: `backend/app/services/rule_engine.py` — line diff → Object/Evidence consistency 중심
- Modify: `backend/app/services/vlm_review_service.py` — boolean matcher → structured observer
- Modify: `backend/app/services/ai_review_service.py` — graph evidence 기반 contextual review
- Modify: `backend/app/services/asset_review_pipeline.py` — canonical region만 VLM에 전달

### Graph

- Modify: `backend/app/graph/schema.py` — canonical 노드/인덱스/제약 추가
- Modify: `backend/app/graph/project_repository.py` — DocumentVersion chain 정상화
- Modify: `backend/app/graph/review_repository.py` — Reference/Plate/Object/Evidence/Decision persistence
- Create: `backend/app/graph/canonical_repository.py` — canonical resolution 및 evidence path 조회

### Orchestration / API

- Modify: `backend/app/jobs/review_pipeline.py` — 단일 canonical orchestration
- Modify: `backend/app/jobs/worker.py` — 실제 pipeline 실행
- Modify: `backend/app/api/ai_analysis.py` — AnalysisRun 생성/상태 조회
- Modify: `backend/app/api/projects.py` — document kind/stage/version 업로드
- Modify: `backend/app/api/schemas.py` — stage/kind/candidate/review schemas
- Create: `backend/app/api/review.py` — candidate 조회 및 expert decision API

### UI

- Modify: `frontend/src/api.ts` — analyze/candidate/review endpoints
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` — analysis 및 candidate entry
- Create: `frontend/src/pages/ReviewPage.tsx` — evidence split view

### Tests / Fixtures

- Create: `backend/tests/fixtures/golden/` — expert-verified golden fixtures
- Create: `backend/tests/test_canonical_plate_resolution.py`
- Create: `backend/tests/test_case6_regression.py`
- Modify: `backend/tests/test_rule_engine.py`
- Modify: `backend/tests/test_review_pipeline_e2e.py`
- Modify: `backend/tests/test_vlm_review_service.py`
- Modify: `backend/tests/test_review_repository.py`

---

# P0 — Identity Correctness

## Task 1: Canonical Domain Contracts

**Files:**
- Create: `backend/app/domain/canonical_models.py`
- Modify: `backend/app/domain/document_structure.py`
- Test: `backend/tests/test_canonical_models.py`

**Interfaces:**
- Produces: `ReferenceData`, `PlateData`, `PlatePanelData`, `DrawingData`, `DrawingRegionData`, `ArchaeologyObjectData`, `ResolutionStatus`
- Consumes: existing `ParsedPage`, `TextBlockData`, `CaptionData`

- [ ] **Step 1: Write failing contract tests**

```python
from app.domain.canonical_models import ReferenceData, PlateData, ResolutionStatus


def test_plate_reference_is_separate_from_physical_page():
    ref = ReferenceData(ref_type="plate", number="45", source_block_id="b1")
    plate = PlateData(
        plate_id="plate_45",
        number="45",
        physical_page=47,
        title="1지점 청동기시대 6호 석관묘",
        bbox=(10.0, 20.0, 500.0, 700.0),
        source_sha256="abc",
    )
    assert ref.number == "45"
    assert plate.number == "45"
    assert plate.physical_page == 47
    assert ResolutionStatus.RESOLVED.value == "resolved"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
pytest backend/tests/test_canonical_models.py -v
```

Expected: import/type failures because canonical models do not exist.

- [ ] **Step 3: Implement minimal immutable dataclasses or Pydantic models**

Required enum values:

```text
resolved
ambiguous
missing
unresolved
```

- [ ] **Step 4: Add bbox and source provenance fields to parsed structures**

`TextBlockData` and `CaptionData` must be able to carry:

```text
bbox
source_sha256
```

- [ ] **Step 5: Run tests**

```bash
pytest backend/tests/test_canonical_models.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domain backend/tests/test_canonical_models.py
git commit -m "feat: add canonical document object contracts"
```

---

## Task 2: Fix Document / DocumentVersion Model

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/graph/project_repository.py`
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/projects.py`
- Test: `backend/tests/test_project_repository.py`

**Interfaces:**
- Produces: one `Document` with multiple `DocumentVersion(stage=...)`
- Stage values must support at least `1차`, `2차`, `3차`, `final`
- Document kind must support `report_body`, `plate_book`, `drawing_book`

- [ ] **Step 1: Write failing repository test**

Test that uploading 1차 and 2차 of the same report creates one Document and two DocumentVersion nodes.

- [ ] **Step 2: Verify failure**

```bash
pytest backend/tests/test_project_repository.py -v
```

- [ ] **Step 3: Change repository contract**

Required logical behavior:

```text
Project
 └─ Document(kind=report_body)
     ├─ DocumentVersion(stage=1차)
     └─ DocumentVersion(stage=2차)
```

- [ ] **Step 4: Add PRECEDES relation**

For ordered stages:

```text
1차 → 2차 → 3차 → final
```

- [ ] **Step 5: Run repository tests**

- [ ] **Step 6: Commit**

```bash
git commit -am "fix: model document versions under one document"
```

---

## Task 3: PyMuPDF Structural Parser

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/services/pdf_parser.py`
- Create: `backend/tests/test_pdf_parser_layout.py`

**Interfaces:**
- `parse_pdf(path, mode="report_body") -> list[ParsedPage]`
- Each block must include bbox and source hash

- [ ] **Step 1: Add failing bbox test**

Fixture page must assert at least one block has a non-null bbox.

- [ ] **Step 2: Verify failure**

- [ ] **Step 3: Add `pymupdf` runtime dependency**

Also ensure `httpx` and `Pillow` are declared because current AI/VLM paths import them.

- [ ] **Step 4: Implement layout extraction with PyMuPDF**

Use pypdf only as fallback/helper. Preserve:

```text
physical_page
printed_page
raw_text
normalized_text
bbox
```

- [ ] **Step 5: Extend reference parsing**

Support:

```text
도판 : 45
도판 : 45·46
도판 : 22~28
도면 : 16~22
```

Return one or more `ReferenceData` items, not a single raw number field.

- [ ] **Step 6: Run parser tests**

- [ ] **Step 7: Commit**

```bash
git commit -am "feat: extract pdf layout and structured references"
```

---

## Task 4: Plate Book Parser and Explicit Identifier Index

**Files:**
- Create: `backend/app/services/plate_parser.py`
- Create: `backend/tests/test_plate_parser.py`
- Create: `backend/tests/fixtures/golden/plate_45_fixture.pdf` or equivalent licensed/synthetic fixture

**Interfaces:**
- `PlateParser.parse(path) -> list[PlateData]`
- `PlateData.number` comes from explicit `【도판 N】`

- [ ] **Step 1: Write physical-page separation test**

Fixture must contain:

```text
physical_page = 47
explicit identifier = 【도판 45】
```

Expected:

```python
assert plate.number == "45"
assert plate.physical_page == 47
```

- [ ] **Step 2: Verify failure**

- [ ] **Step 3: Implement explicit identifier extraction**

Regex must recognize at minimum:

```text
【도판 45】
[도판 45]
```

but preserve the exact source text in Evidence/provenance.

- [ ] **Step 4: Parse plate title and numbered panel captions**

At minimum recognize panel labels `①` through `⑳` and store bbox.

- [ ] **Step 5: Build in-memory/indexable mapping**

```python
plates_by_number: dict[str, PlateData]
```

- [ ] **Step 6: Run tests and commit**

```bash
git commit -am "feat: parse explicit plate identifiers and panels"
```

---

## Task 5: Case 6 Regression — Filename Trap

**Files:**
- Create: `backend/tests/test_case6_regression.py`
- Create: `backend/tests/fixtures/golden/case6.yaml`
- Modify: `backend/app/services/asset_matcher.py`

**Interfaces:**
- `resolve_reference(reference, graph/index) -> ResolutionResult`
- No API may infer plate identity from Links filename numbers.

- [ ] **Step 1: Write failing Case 6 test**

Fixture:

```yaml
body_text: "1지점 청동기시대 6호 석관묘 ... 도판 : 45ㆍ46"
plate_explicit_identifier: "【도판 45】"
plate_title: "1지점 청동기시대 6호 석관묘"
forbidden_link_filename: "4. 조사 후_45.JPG"
```

Test assertions:

```python
assert result.status == "resolved"
assert result.target.number == "45"
assert result.target.source_kind == "plate_pdf"
assert "4. 조사 후_45.JPG" not in result.identity_evidence
```

- [ ] **Step 2: Verify current implementation fails or is capable of violating invariant**

- [ ] **Step 3: Remove numeric filename fallback from canonical plate resolution**

Existing filename index may remain only under provenance-specific methods and must not be called by `resolve_reference`.

- [ ] **Step 4: Add missing-reference safety test**

If `【도판 91】` is absent but `_91.JPG` exists:

```python
assert result.status in {"missing", "unresolved"}
assert result.target is None
```

- [ ] **Step 5: Run the mandatory gate**

```bash
pytest backend/tests/test_case6_regression.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git commit -am "fix: make publication identifiers canonical for plate resolution"
```

**Reviewer Gate:** If this task fails, stop implementation. Do not tune VLM or continue to AI tasks.

---

## Task 6: Neo4j Canonical Schema

**Files:**
- Modify: `backend/app/graph/schema.py`
- Create: `backend/app/graph/canonical_repository.py`
- Modify: `backend/app/graph/review_repository.py`
- Test: `backend/tests/test_canonical_repository.py`

**Interfaces:**
- Persist nodes: `Reference`, `Plate`, `PlatePanel`, `Drawing`, `DrawingRegion`, `ArchaeologyObject`, `OriginalAsset`, `ReviewDecision`
- Persist relations: `REFERENCES`, `RESOLVES_TO`, `HAS_PANEL`, `MENTIONS`, `DEPICTS`, `ABOUT`, `SUPPORTED_BY`, `HAS_DECISION`, `ALIGNED_TO`

- [ ] **Step 1: Write integration-capable repository tests**

Tests must validate actual Cypher shape, not only Python payload construction.

- [ ] **Step 2: Add constraints**

Unique IDs for all new node types.

- [ ] **Step 3: Add indexes**

At minimum:

```text
Plate.number
DrawingRegion.number
ArchaeologyObject.canonical_name
Reference.ref_type + Reference.number
```

- [ ] **Step 4: Implement canonical persistence**

- [ ] **Step 5: Ensure `ensure_schema()` runs at application/worker startup**

- [ ] **Step 6: Run tests and commit**

---

# P1 — Object / Evidence

## Task 7: ArchaeologyObject Resolver

**Files:**
- Create: `backend/app/services/object_resolver.py`
- Create: `backend/tests/test_object_resolver.py`

**Interfaces:**
- `resolve_mentions(blocks, captions) -> ObjectResolutionResult[]`
- Must produce candidate/semantic_review rather than unsafe merge when ambiguous

- [ ] **Step 1: Write tests for normalized object identity**

Examples:

```text
1지점 청동기시대 6호 석관묘
1지점 청동기 6호 석관묘
```

may resolve to the same object if context is sufficient.

- [ ] **Step 2: Write ambiguity test**

`2호 토광묘` without site/period in a document containing multiple 2호 토광묘 objects must not auto-merge.

- [ ] **Step 3: Implement deterministic field extraction and conservative merge**

- [ ] **Step 4: Persist candidate relations with method/confidence/status**

- [ ] **Step 5: Commit**

---

## Task 8: PageAligner Safety

**Files:**
- Modify: `backend/app/services/page_aligner.py`
- Modify: `backend/tests/test_page_aligner.py`

**Interfaces:**
- Alignment result gains `status`

- [ ] **Step 1: Write unrelated-page rejection test**

Two unrelated equal-count pages must not be forced into an `exact/probable` match.

- [ ] **Step 2: Verify failure under current `gap_cost=1` design**

- [ ] **Step 3: Introduce acceptance threshold / revised scoring**

A low similarity diagonal must be allowed to become insertion+deletion or `unmatched`.

- [ ] **Step 4: Persist `ALIGNED_TO` only for accepted matches; store manual/unmatched audit rows separately as needed**

- [ ] **Step 5: Run tests and commit**

---

## Task 9: Evidence Model and Traceability

**Files:**
- Modify: `backend/app/domain/review_models.py`
- Modify: `backend/app/graph/review_repository.py`
- Create: `backend/tests/test_evidence_traceability.py`

**Interfaces:**
- Every Evidence requires source-addressable provenance

- [ ] **Step 1: Write failing Evidence validation test**

Creating Evidence without `source_sha256`, `document_version_id`, `page_id`, and either `bbox` or region identifier must fail validation unless evidence kind is explicitly run-level metadata.

- [ ] **Step 2: Implement Evidence schema**

Required fields:

```text
kind
source_sha256
document_version_id
page_id
region_id/bbox
method
analysis_run_id
value/rationale
```

- [ ] **Step 3: Link Evidence to actual source nodes in Neo4j**

Do not store only page numbers as detached scalar strings.

- [ ] **Step 4: Add Candidate→Evidence→Source traversal test**

- [ ] **Step 5: Commit**

---

## Task 10: RuleEngine as Object/Evidence Consistency Engine

**Files:**
- Modify: `backend/app/services/rule_engine.py`
- Modify: `backend/tests/test_rule_engine.py`

**Interfaces:**
- Consumes graph/object evidence collections
- Produces only `pending_review` candidates

- [ ] **Step 1: Add numeric unit conflict test**

```text
275cm vs 2.45m → conflict
275cm vs 2.75m → no conflict
```

- [ ] **Step 2: Add identity/reference conflict tests**

Examples:

```text
본문 says 도판 45, resolved plate title refers to different object → candidate
same object, same plate → no candidate
```

- [ ] **Step 3: Add period/direction/name tests**

- [ ] **Step 4: Change all generated candidate statuses to `pending_review`**

- [ ] **Step 5: Retain line diff only as `version_change` evidence**

Do not treat every text difference as confirmed error.

- [ ] **Step 6: Commit**

---

# P2 — AI Interpretation

## Task 11: VLM Observer Contract

**Files:**
- Modify: `backend/app/services/vlm_review_service.py`
- Modify: `backend/tests/test_vlm_review_service.py`

**Interfaces:**
- Replace boolean-centric `VLMReviewResult.is_match` contract with structured observation verdicts

- [ ] **Step 1: Write site-same/feature-different negative test**

Input expectation:

```text
expected: 2지점 2호 토광묘
observed: 2지점 25호 토광묘
```

Expected: `CONTRADICTED` or `PARTIAL`, never `SUPPORTED`.

- [ ] **Step 2: Write unobservable-claim test**

Single front image cannot confirm backside processing. Expected claim goes to `unobservable_claims`.

- [ ] **Step 3: Define Pydantic response schema**

Fields:

```text
status
observations
supported_claims
contradicted_claims
unobservable_claims
confidence
rationale
```

- [ ] **Step 4: Remove fallback trust in arbitrary AI `is_match`**

- [ ] **Step 5: Fix test client image plumbing**

Mock client must receive actual processed image bytes, not `b""`.

- [ ] **Step 6: Include model/prompt/preprocessor versions in cache key**

- [ ] **Step 7: Commit**

---

## Task 12: Canonical Asset Review Pipeline

**Files:**
- Modify: `backend/app/services/asset_review_pipeline.py`
- Modify: `backend/app/services/image_processor.py`
- Test: `backend/tests/test_asset_review_pipeline.py`

**Interfaces:**
- Consumes `PlatePanel`/`DrawingRegion` only
- Never consumes an arbitrary filename selected by numeric coincidence

- [ ] **Step 1: Write test asserting VLM input source is canonical region**

- [ ] **Step 2: Reject empty/undecodable bytes before VLM**

- [ ] **Step 3: Render PDF/AI-derived supported regions to explicit image MIME before VLM**

For MVP, PDF regions are mandatory; unsupported AI/DWG must become `conversion_error/manual_review` rather than mislabeled JPEG.

- [ ] **Step 4: Remove auto-promotion from VLM match to `exact`**

- [ ] **Step 5: Commit**

---

## Task 13: Contextual LLM Review from Graph Evidence

**Files:**
- Modify: `backend/app/services/ai_review_service.py`
- Modify: `backend/tests/test_ai_review_service.py`

**Interfaces:**
- LLM input = target block + neighbor context + same-object evidence + resolved captions + deterministic conflicts

- [ ] **Step 1: Write test ensuring unrelated whole-document text is not sent**

- [ ] **Step 2: Build bounded review context object**

- [ ] **Step 3: Produce only Evidence + pending Candidate suggestions**

- [ ] **Step 4: Commit**

---

# P3 — Orchestration / Review

## Task 14: Real ReviewPipeline Orchestration

**Files:**
- Modify: `backend/app/jobs/review_pipeline.py`
- Modify: `backend/app/jobs/worker.py`
- Modify: `backend/app/api/ai_analysis.py`
- Modify: `backend/tests/test_review_pipeline_e2e.py`

**Interfaces:**
- `/analyze` must create an AnalysisRun and execute the full canonical pipeline

- [ ] **Step 1: Write failing E2E test**

A sample project analysis must persist at least:

```text
Page
Reference
resolved Plate/Drawing target
Evidence
CorrectionCandidate or explicit clean result
AnalysisRun status
```

- [ ] **Step 2: Remove no-op completion path**

- [ ] **Step 3: Wire ordered phases from design**

- [ ] **Step 4: Use real DocumentVersion IDs, never synthetic `{project_id}_{stage}` IDs**

- [ ] **Step 5: Run E2E tests and commit**

---

## Task 15: Expert Review API and Decision History

**Files:**
- Create: `backend/app/api/review.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/graph/review_repository.py`
- Test: `backend/tests/test_review_api.py`

**Interfaces:**
- GET project candidates
- POST decision: accepted/rejected/modified/deferred

- [ ] **Step 1: Add candidate list test**

The current TODO empty-list behavior must be replaced.

- [ ] **Step 2: Add append-only decision test**

Second decision creates a new ReviewDecision referencing the previous decision rather than overwriting it.

- [ ] **Step 3: Implement APIs and persistence**

- [ ] **Step 4: Commit**

---

## Task 16: Evidence Review UI

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Create: `frontend/src/pages/ReviewPage.tsx`

**Interfaces:**
- Candidate list + source evidence + related plate/drawing + decisions

- [ ] **Step 1: Add API client methods**

- [ ] **Step 2: Render split view**

At minimum show:

```text
original/proposed text
source page render
bbox highlight metadata
resolved plate/drawing panel
Evidence rationale
AI observation
accept/reject/modify/defer
```

- [ ] **Step 3: Ensure UI never labels VLM confidence as expert confirmation**

- [ ] **Step 4: Commit**

---

# Final MVP Verification

## Task 17: Golden Dataset Lock and Mandatory Gate Suite

**Files:**
- Populate: `backend/tests/fixtures/golden/`
- Create: `backend/tests/test_mvp_golden_gate.py`

**Interfaces:**
- Only expert-verified fixtures may be used for final pass/fail ground truth

- [ ] **Step 1: Mark legacy 10-case records**

Each legacy case must be classified as:

```text
VALID_GROUND_TRUTH
INVALID_GROUND_TRUTH_MAPPING
NEEDS_REVALIDATION
```

Case 6 = `INVALID_GROUND_TRUTH_MAPPING`.

- [ ] **Step 2: Build expert-verified golden YAML records**

Required fields include source hashes, body reference, canonical explicit identifier, target page, title, panels, forbidden filename matches, expert note.

- [ ] **Step 3: Run deterministic identity suite with AI disabled**

```bash
pytest backend/tests/test_case6_regression.py backend/tests/test_canonical_plate_resolution.py backend/tests/test_mvp_golden_gate.py -v
```

Expected: 100% PASS.

- [ ] **Step 4: Enforce zero false canonical mappings**

```text
Canonical Reference Precision = 1.00 on golden set
Filename-number false mapping = 0
```

If a target cannot be found, unresolved is acceptable. A wrong target is not.

- [ ] **Step 5: Run full backend suite**

```bash
pytest backend/tests -v
```

- [ ] **Step 6: Run Compose contract tests**

```bash
pytest tests/compose -v
```

- [ ] **Step 7: Run one real end-to-end project and inspect graph path**

Required path:

```text
Body Text
→ Reference
→ Plate/Drawing
→ Region
→ ArchaeologyObject
→ Evidence
→ Candidate
→ ReviewDecision
```

- [ ] **Step 8: Verify all final fail conditions**

MVP fails if any occurs:

```text
Links filename number interpreted as plate/drawing number
physical page interpreted as publication number
Case 6 selects unrelated _45.JPG
VLM/LLM changes canonical identity
candidate without source-addressable Evidence
automatic accepted candidate
non-deterministic canonical resolution
filename inference creates confirmed relation without explicit reference
```

- [ ] **Step 9: Commit the golden dataset and gate tests**

```bash
git add backend/tests/fixtures/golden backend/tests/test_mvp_golden_gate.py
git commit -m "test: lock expert verified mvp golden gates"
```

---

# Execution Order and Stop Gates

Implement strictly in this order:

```text
Task 1 → 2 → 3 → 4 → 5
                       │
                       └─ Case 6 FAIL? STOP

Task 6 → 7 → 8 → 9 → 10

Task 11 → 12 → 13

Task 14 → 15 → 16

Task 17 final gate
```

Do not begin VLM tuning before Task 5 passes.

Do not declare MVP complete unless Task 17 passes with expert-verified fixtures.

---

# Final Definition of Done

The implementation is complete only when all of the following are true:

1. `Reference(plate,N)` resolves from explicit `【도판 N】`, not Links filename.
2. Case 6 regression passes and `_45.JPG` is never selected as identity evidence.
3. physical page and publication number remain distinct.
4. one Document owns multiple DocumentVersions.
5. Page alignment can reject unrelated pages.
6. ArchaeologyObject connects body/plate/drawing evidence.
7. RuleEngine creates evidence-backed `pending_review` candidates.
8. VLM produces observations, not identity decisions.
9. Candidate→Evidence→source region traversal works in Neo4j.
10. `/analyze` executes the real pipeline.
11. expert decisions are append-only and auditable.
12. the expert-verified Golden Dataset achieves zero wrong canonical mappings.
