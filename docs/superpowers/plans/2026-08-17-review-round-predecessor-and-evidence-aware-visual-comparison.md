# ReviewRound Predecessor + Evidence-Aware Visual Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ReviewRound PRECEDES`를 이전 본문 비교의 유일한 authority로 만들고, 후보 화면이 실제 Evidence 종류에 따라 `version_change / plate_reference / drawing_reference / text_evidence` 중 하나의 비교 UI를 정확히 표시하도록 한다.

**Architecture:** ReviewRound 실행 경로에서는 이전 body를 stage 문자열로 재검색하지 않고 Graph의 predecessor Round가 가리키는 명시적 `DocumentVersion`으로 해결한다. Visual bundle은 candidate-specific Graph evidence를 읽어 비교 유형과 양쪽 evidence metadata를 반환하고, frontend는 해당 유형에 맞는 패널만 렌더한다. Canonical visual target은 기존 `Reference -> RESOLVES_TO` fail-closed 원칙을 유지한다.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, Neo4j 5.26, pytest/anyio, React + TypeScript, Vitest/Testing Library, PyMuPDF/Pillow, GitHub Actions.

## Global Constraints

- `DocumentVersion.stage`는 compatibility/display metadata일 뿐 revision identity가 아니다.
- ReviewRound revision order는 `ReviewRound -[:PRECEDES]-> ReviewRound` 관계가 유일한 authority다.
- filename 숫자 suffix는 도판/도면 identity에 사용하지 않는다.
- Graph identity가 불명확하면 unrelated asset을 선택하지 않고 fail-closed 한다.
- `numeric_value` category만으로 `version_change`를 추측하지 않는다. 실제 `version_change` Evidence provenance가 있어야 한다.
- `figure_plate_table_photo_ref` category만으로 visual mode를 추측하지 않는다. exact Graph `Reference -> RESOLVES_TO` target이 있어야 한다.
- VLM 섹션은 실제 `Evidence.kind == "vlm_observation"`인 경우에만 표시한다.
- 기존 `VisualAssetPane`를 재사용하며 범용 N-way evidence viewer는 만들지 않는다.
- 개발 budget 및 후보 ID/프로젝트 격리, Case 6 규칙을 훼손하지 않는다.

---

## File Structure

### Backend

- Modify: `backend/app/graph/review_project_repository.py`
  - project-scoped immediate predecessor ReviewRound 조회 API 추가.
- Modify: `backend/app/jobs/run_inputs.py`
  - ReviewRound 전용 explicit previous/current body parsing helper 추가.
  - legacy stage resolver는 legacy queued job에만 남김.
- Modify: `backend/app/jobs/worker.py`
  - current + predecessor Round를 Graph에서 resolve하고 explicit body pair를 alignment에 전달.
- Modify: `backend/app/domain/review_models.py`
  - 필요 시 version-change Evidence의 이전/현재 page/version provenance를 명시하는 최소 필드 추가.
- Modify: `backend/app/graph/strict_asset_repository.py`
  - candidate evidence chain에 version-change 양쪽 provenance와 exact reference metadata를 포함.
- Modify: `backend/app/services/strict_visual_asset_service.py`
  - `comparison_type`, `comparison`, `reference`, `render_status` contract 생성.
- Modify: `backend/app/api/schemas.py`
  - visual bundle response schema 확장.

### Frontend

- Modify: `frontend/src/api.ts`
  - comparison mode / comparison asset / reference / render status 타입 추가.
- Modify: `frontend/src/components/SplitViewInspector.tsx`
  - comparison-type switch로 right pane 의미를 결정.
  - unconditional plate placeholder와 fake VLM fallback 제거.
- Modify only if necessary: `frontend/src/components/VisualAssetPane.tsx`
  - resolved-target-but-render-missing metadata를 표시할 수 있는 최소 prop 지원.

### Tests

- Modify: `backend/tests/test_worker_review_round_authority.py`
- Modify/Create: `backend/tests/test_review_round_repository.py`
- Modify/Create: `backend/tests/test_strict_visual_bundle.py`
- Add: `backend/tests/test_review_round_predecessor_alignment.py`
- Add/Modify real Neo4j suite: `backend/tests/test_real_neo4j_remediation.py` or repository's current real-Neo4j remediation suite
- Modify frontend tests covering `SplitViewInspector` / visual bundle modes.
- Update: `docs/superpowers/reviews/2026-08-17-post-remediation-evaluation-handoff.md`
  - verifier-specific V13/V14 gates appended.

---

### Task 1: Project-scoped predecessor ReviewRound repository API

**Files:**
- Modify: `backend/app/graph/review_project_repository.py`
- Test: `backend/tests/test_review_round_repository.py`

**Interfaces:**
- Consumes: existing `ReviewRound` dataclass and `ReviewProjectRepository`.
- Produces:

```python
def get_previous_review_round(
    self,
    project_id: str,
    round_id: str,
) -> ReviewRound | None:
    ...
```

- [ ] **Step 1: Write failing repository contract tests**

Add tests that inspect the generated Cypher and result mapping. Minimum assertions:

```python
def test_get_previous_review_round_uses_precedes_and_project_scope():
    driver = FakeNeo4jDriver(responses=[[{
        "id": "round_3",
        "project_id": "p1",
        "sequence": 3,
        "status": "approved",
        "notes": None,
        "created_at": "2026-08-17T10:00:00Z",
        "approved_at": "2026-08-17T11:00:00Z",
        "body_version_id": "body_v2",
        "plate_version_id": "plate_v1",
        "drawing_version_id": "drawing_v1",
    }]])
    repo = ReviewProjectRepository(driver)

    previous = repo.get_previous_review_round("p1", "round_4")

    assert previous is not None
    assert previous.id == "round_3"
    assert previous.body_version_id == "body_v2"
    query = driver.queries[0]["query"]
    assert "(previous:ReviewRound)-[:PRECEDES]->(current:ReviewRound" in query
    assert "HAS_REVIEW_ROUND" in query
    assert "version.stage" not in query
```

Also add no-predecessor case returning `None`.

- [ ] **Step 2: Verify RED**

Run:

```bash
cd backend
pytest -q tests/test_review_round_repository.py -k previous_review_round
```

Expected: FAIL because `get_previous_review_round` does not exist.

- [ ] **Step 3: Implement minimal repository method**

Use project-scoped Cypher:

```cypher
MATCH (project:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->
      (current:ReviewRound {id: $round_id})
OPTIONAL MATCH (previous:ReviewRound)-[:PRECEDES]->(current)
WHERE previous IS NULL OR (project)-[:HAS_REVIEW_ROUND]->(previous)
OPTIONAL MATCH (previous)-[:USES_BODY_VERSION]->(body:DocumentVersion)
OPTIONAL MATCH (previous)-[:USES_PLATE_VERSION]->(plate:DocumentVersion)
OPTIONAL MATCH (previous)-[:USES_DRAWING_VERSION]->(drawing:DocumentVersion)
RETURN previous.id AS id,
       previous.projectId AS project_id,
       previous.sequence AS sequence,
       previous.status AS status,
       previous.notes AS notes,
       previous.createdAt AS created_at,
       previous.approvedAt AS approved_at,
       body.id AS body_version_id,
       plate.id AS plate_version_id,
       drawing.id AS drawing_version_id
```

If `id` is null, return `None`.

- [ ] **Step 4: Verify GREEN**

```bash
cd backend
pytest -q tests/test_review_round_repository.py -k previous_review_round
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/review_project_repository.py backend/tests/test_review_round_repository.py
git commit -m "feat(round): resolve predecessor from review lineage"
```

---

### Task 2: Explicit previous/current body alignment for ReviewRound runs

**Files:**
- Modify: `backend/app/jobs/run_inputs.py`
- Modify: `backend/app/jobs/worker.py`
- Modify: `backend/tests/test_worker_review_round_authority.py`
- Add: `backend/tests/test_review_round_predecessor_alignment.py`

**Interfaces:**
- Consumes: `ReviewRound`, `VersionInput`, `ReviewProjectRepository.get_previous_review_round()`.
- Produces:

```python
async def resolve_round_body_versions_for_alignment(
    *,
    project_repository,
    project_id: str,
    current_round,
    previous_round,
    current_body: VersionInput,
    previous_body: VersionInput | None,
    current_pdf_path: str | None,
    pdf_parser,
) -> tuple[dict[str, list[ParsedPage]], dict[str, str]]:
    ...
```

Return keys are fixed semantic roles:

```python
{"previous": [...], "current": [...]}
{"previous": "body_v2", "current": "body_v3"}
```

For first round, only `current` is present.

- [ ] **Step 1: Write failing pure alignment test**

Create fixture where both VersionInputs use `stage="source"`:

```python
previous = VersionInput(... version_id="body_v2", stage="source", uri="body-v2.pdf")
current = VersionInput(... version_id="body_v3", stage="source", uri="body-v3.pdf")
```

Assert helper parses exactly explicit IDs and never invokes `resolve_version_input(..., stage="3차")`.

- [ ] **Step 2: Verify RED**

```bash
cd backend
pytest -q tests/test_review_round_predecessor_alignment.py
```

Expected: FAIL because helper does not exist.

- [ ] **Step 3: Implement helper without stage lookup**

Implementation rules:

```python
pairs = [("previous", previous_body), ("current", current_body)]
```

For each non-null explicit VersionInput:
- resolve stored PDF from that exact VersionInput;
- parse with `version_id=version.version_id`;
- store semantic key and exact version ID;
- do not call `body_stages_for_round`.

- [ ] **Step 4: Make worker choose predecessor Graph path**

When `review_round_id` exists:

```python
current_round = resolved_round.review_round
previous_round = project_repo.get_previous_review_round(project_id, review_round_id)
previous_body = None
if previous_round and previous_round.body_version_id:
    previous_body = project_repo.resolve_version_input(
        project_id,
        "report_body",
        None,
        previous_round.body_version_id,
    )
```

Then call `resolve_round_body_versions_for_alignment(...)`.

Legacy jobs without `review_round_id` continue calling existing `resolve_body_versions_for_alignment(...)`.

- [ ] **Step 5: Replace the monkeypatched worker test with a real authority assertion**

Update `test_worker_review_round_authority.py` so the fake project repository exposes `get_previous_review_round()` and resolves both `body_v2`/`body_v3`, while all `stage` values are `source`.

Assert orchestrator receives:

```python
assert call["version_ids"] == {
    "previous": "body_v2",
    "current": "body_v3",
}
```

and `resolve_version_input` was never called with a stage-only lookup.

- [ ] **Step 6: Verify targeted GREEN**

```bash
cd backend
pytest -q \
  tests/test_review_round_predecessor_alignment.py \
  tests/test_worker_review_round_authority.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/jobs/run_inputs.py backend/app/jobs/worker.py \
  backend/tests/test_review_round_predecessor_alignment.py \
  backend/tests/test_worker_review_round_authority.py
git commit -m "fix(round): compare bodies via predecessor round"
```

---

### Task 3: Real Neo4j regression for reuse and unbounded rounds

**Files:**
- Modify: current real-Neo4j remediation suite, preferably `backend/tests/test_real_neo4j_remediation.py`

**Interfaces:**
- Consumes: ReviewRound creation/repository APIs from Tasks 1–2.
- Produces: integration evidence proving stage-independent predecessor resolution.

- [ ] **Step 1: Add real Graph fixture**

Create document versions with all stage values equal to `source`:

```text
body v1
body v2
body v3
body v4
plate p1/p2
drawing d1/d2
```

Create:

```text
Round1 -> v1,p1,d1
Round2 -> v2,p1,d1
Round3 -> v2,p1,d1
Round4 -> v3,p2,d1
Round5 -> v4,p2,d2
```

- [ ] **Step 2: Add assertions**

```python
assert repo.get_previous_review_round(project_id, round4.id).id == round3.id
assert repo.get_previous_review_round(project_id, round4.id).body_version_id == body_v2
assert repo.get_previous_review_round(project_id, round5.id).body_version_id == body_v3
```

Also assert there is no dependency on `DocumentVersion.stage` by setting every stage to `source`.

- [ ] **Step 3: Run real Neo4j targeted suite**

Use the same environment as `.github/workflows/remediation-ci.yml` and run the specific test.

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_real_neo4j_remediation.py
git commit -m "test(round): prove predecessor reuse on real neo4j"
```

---

### Task 4: Extend visual bundle contract with comparison semantics

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/graph/strict_asset_repository.py`
- Modify: `backend/app/services/strict_visual_asset_service.py`
- Modify: `backend/tests/test_strict_visual_bundle.py`

**Interfaces:**
- Produces response keys:

```python
{
    "candidate_id": str,
    "comparison_type": "version_change" | "plate_reference" | "drawing_reference" | "text_evidence",
    "source": dict | None,
    "comparison": dict | None,
    "canonical": dict | None,
    "reference": dict | None,
    "render_status": "ready" | "missing_render" | "not_applicable",
    "unresolved_reason": str | None,
}
```

- [ ] **Step 1: Write failing mode tests**

Extend `test_strict_visual_bundle.py` with four fixtures:

```text
version_change evidence -> version_change
exact Plate45 Reference -> plate_reference
exact Drawing30 Reference -> drawing_reference
plain rule finding -> text_evidence
```

For `version_change`, include evidence data with:

```python
{
  "kind": "version_change",
  "version_from": "body_v2",
  "version_to": "body_v3",
  "physical_page_from": 10,
  "physical_page_to": 11,
}
```

The repository fixture must expose enough version/page metadata for both sides.

- [ ] **Step 2: Write failing render-state test**

Resolved Plate45 + existing graph target but missing render must produce:

```python
assert result["comparison_type"] == "plate_reference"
assert result["canonical"]["region_id"] == "plate_45"
assert result["render_status"] == "missing_render"
assert result["unresolved_reason"] == "render_unavailable"
```

It must not become `no_canonical_reference_target`.

- [ ] **Step 3: Verify RED**

```bash
cd backend
pytest -q tests/test_strict_visual_bundle.py
```

Expected: new tests fail because fields/modes are not implemented.

- [ ] **Step 4: Extend repository rows without weakening identity**

Keep canonical query anchored to:

```text
Candidate -> ABOUT Object
source -> MENTIONS Object
source -> REFERENCES Reference -> RESOLVES_TO target
```

Include:
- Reference properties including `id/ref_type/number`;
- target owning DocumentVersion;
- Evidence `version_from/version_to`, page provenance and FROM_VERSION path data needed for version-change rendering.

Do not add `Object <- DEPICTS - first asset` fallback.

- [ ] **Step 5: Implement comparison classification**

Priority:

```python
if exact drawing target:
    comparison_type = "drawing_reference"
elif exact plate target:
    comparison_type = "plate_reference"
elif version_change provenance is complete:
    comparison_type = "version_change"
else:
    comparison_type = "text_evidence"
```

Canonical visual classification uses Graph-resolved target label, not category strings.

- [ ] **Step 6: Build `comparison` side for version change**

Use previous/current document/page provenance from evidence. Render both body PDF pages when available. `source` and `comparison` must explicitly identify which version each belongs to.

For missing page provenance, return metadata without pretending a visual exists and set precise status/reason.

- [ ] **Step 7: Extend Pydantic schemas**

Add:

```python
ComparisonType = Literal[
    "version_change", "plate_reference", "drawing_reference", "text_evidence"
]
RenderStatus = Literal["ready", "missing_render", "not_applicable"]

class VisualReferenceMetadata(ApiModel):
    type: str
    number: str
    reference_id: str | None = Field(default=None, alias="referenceId")
    target_id: str | None = Field(default=None, alias="targetId")
```

Extend `CandidateVisualBundle` with comparison fields.

- [ ] **Step 8: Verify backend GREEN**

```bash
cd backend
pytest -q tests/test_strict_visual_bundle.py
python -m compileall -q app
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/schemas.py \
  backend/app/graph/strict_asset_repository.py \
  backend/app/services/strict_visual_asset_service.py \
  backend/tests/test_strict_visual_bundle.py
git commit -m "feat(visual): expose evidence-aware comparison modes"
```

---

### Task 5: Frontend comparison-mode rendering and truthful VLM display

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/SplitViewInspector.tsx`
- Modify only if required: `frontend/src/components/VisualAssetPane.tsx`
- Modify/Add: existing frontend tests for SplitViewInspector.

**Interfaces:**
- Consumes backend `CandidateVisualBundle` comparison fields from Task 4.

- [ ] **Step 1: Add TypeScript contract**

```ts
export type CandidateComparisonType =
  | 'version_change'
  | 'plate_reference'
  | 'drawing_reference'
  | 'text_evidence';

export type VisualRenderStatus = 'ready' | 'missing_render' | 'not_applicable';

export type CandidateVisualBundle = {
  candidateId: string;
  comparisonType: CandidateComparisonType;
  source?: VisualAssetMetadata | null;
  comparison?: VisualAssetMetadata | null;
  canonical?: VisualAssetMetadata | null;
  reference?: {
    type: string;
    number: string;
    referenceId?: string | null;
    targetId?: string | null;
  } | null;
  renderStatus: VisualRenderStatus;
  unresolvedReason?: string | null;
};
```

- [ ] **Step 2: Write failing numeric version-change test**

Fixture:

```text
original = 길이 220cm
proposed = 길이 210cm
comparisonType = version_change
source = body_v2 page render
comparison = body_v3 page render
canonical = null
```

Assertions:

```text
본문 수정본 간 비교 visible
이전 본문 / 현재 본문 labels visible
표준 도판 / 사진 absent
해당 에셋 렌더 없음 absent
```

- [ ] **Step 3: Write failing plate/drawing/text tests**

Plate:
- `본문 ↔ 도판 45` label;
- canonical target id and image shown.

Drawing:
- `본문 ↔ 도면 30` label;
- drawing render shown.

Text evidence:
- `규칙 기반 본문 Evidence` label;
- no visual placeholder.

- [ ] **Step 4: Write failing VLM truthfulness test**

Without evidence kind `vlm_observation`:

```text
VLM 비전 분석 관찰 소견 absent
```

With actual `vlm_observation`:

```text
VLM 비전 분석 관찰 소견 visible
actual rationale/value visible
```

- [ ] **Step 5: Verify frontend RED**

```bash
cd frontend
npm test -- --run
```

Expected: new comparison-mode tests fail.

- [ ] **Step 6: Implement comparison renderer switch**

Inside `SplitViewInspector` derive:

```ts
const comparisonType = visualBundle?.comparisonType ?? 'text_evidence';
```

Render mode-specific header and panes. Do not show canonical plate placeholder unless mode is `plate_reference`.

For missing render with resolved canonical metadata, show:

```text
도판 45는 Graph에서 정상 연결됨
이미지 렌더를 생성하지 못했습니다
Target: plate_45
DocumentVersion: ...
Physical page: ...
```

- [ ] **Step 7: Remove fake VLM fallback**

Build:

```ts
const vlmEvidence = allEvidences.find((ev) => ev.kind === 'vlm_observation');
```

Render VLM box only when `vlmEvidence` exists. Never fallback to generic rule rationale or fabricated sentence.

- [ ] **Step 8: Verify frontend GREEN**

```bash
cd frontend
npm run typecheck
npm test -- --run
npm run build
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api.ts \
  frontend/src/components/SplitViewInspector.tsx \
  frontend/src/components/VisualAssetPane.tsx \
  frontend/src/**/*.test.*
git commit -m "fix(frontend): render candidates by evidence comparison type"
```

---

### Task 6: Live render/E2E and high-volume budget verification upgrades

**Files:**
- Modify: `scripts/run_live_10_api_validation.py`
- Modify/Add backend tests as needed for fixture generation.

**Interfaces:**
- Consumes comparison contract from Task 4 and UI behavior from Task 5.
- Produces verifiable console assertions for the next evaluation agent.

- [ ] **Step 1: Make live uploads match frontend semantics**

All uploaded DocumentVersions in the ReviewRound path use `stage=source`; do not create artificial `1차/2차` stages merely to make predecessor comparison pass.

- [ ] **Step 2: Add Round reuse scenario**

Live fixture sequence at minimum:

```text
R1 body v1
R2 body v2
R3 body v2 reuse
R4 body v3
```

Assert R4 diagnostics/alignment provenance identifies previous `body v2`, current `body v3`.

- [ ] **Step 3: Add visual-mode fixtures**

Ensure at least one exact plate reference and one exact drawing reference resolve to raster-backed PDF pages. Assert visual bundle returns correct mode, target id, render URL, HTTP 200, `Content-Type: image/*`, non-zero bytes.

- [ ] **Step 4: Add numeric version-change fixture**

Create body revision:

```text
v2: 길이 220cm
v3: 길이 210cm
```

Assert candidate visual bundle is `version_change` and never `plate_reference`.

- [ ] **Step 5: Add high-volume budget stress fixture**

Generate >= 50 cheap deterministic findings under:

```text
REVIEW_MODE=development
DEVELOPMENT_CANDIDATE_BUDGET=10
```

Assert:

```python
raw_findings >= 50
selected_candidates <= 10
expensive_operations <= 10
```

If AI/VLM are disabled, explicitly report `actual_ai_calls=0`, `actual_vlm_calls=0`; do not call this external semantic validation PASS.

- [ ] **Step 6: Execute live validator**

Run against Docker dev stack and capture output in the verification report or workflow artifact.

- [ ] **Step 7: Commit**

```bash
git add scripts/run_live_10_api_validation.py backend/tests
git commit -m "test(e2e): verify round lineage and comparison renders"
```

---

### Task 7: Update independent verifier handoff

**Files:**
- Modify: `docs/superpowers/reviews/2026-08-17-post-remediation-evaluation-handoff.md`

**Interfaces:**
- Produces new mandatory independent gates V13 and V14.

- [ ] **Step 1: Append V13 — ReviewRound predecessor authority**

Require verifier to provide:

```text
projectId
round1..round5 IDs
body v1..v4 IDs
all DocumentVersion.stage values
Cypher or repository output proving PRECEDES
R4 previous=v2/current=v3
R5 previous=v3/current=v4
```

A unit test with `resolve_body_versions_for_alignment` monkeypatched is not sufficient.

- [ ] **Step 2: Append V14 — Evidence-aware Split View**

Require one concrete candidate for each mode:

```text
version_change
plate_reference
drawing_reference
text_evidence
```

For each record:

```text
projectId
roundId
analysisRunId
candidateId
visual-bundle JSON
source/comparison/canonical version IDs
reference id/number/target id when applicable
render HTTP status and byte length
browser screenshot
```

For numeric example, require `길이 220cm -> 길이 210cm` to show previous/current body evidence and **no plate placeholder**.

- [ ] **Step 3: Add VLM negative UI requirement**

Require screenshot/test proving a rule-only candidate has no VLM observation block, and a true `vlm_observation` candidate does.

- [ ] **Step 4: Reinforce high-volume budget evidence**

Require `raw_findings >= 50` in actual pipeline; a 5-finding run is insufficient.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/reviews/2026-08-17-post-remediation-evaluation-handoff.md
git commit -m "docs(review): add predecessor and comparison verification gates"
```

---

### Task 8: Full verification and push gate

**Files:** none unless failures require focused fixes.

- [ ] **Step 1: Backend compile + hermetic**

Run the exact `backend-hermetic` commands from `.github/workflows/remediation-ci.yml`.

Expected: 0 failures.

- [ ] **Step 2: Real Neo4j gate**

Run the exact `neo4j-e2e` job commands from the workflow.

Expected: 0 failures and new predecessor regression included.

- [ ] **Step 3: Frontend gate**

```bash
cd frontend
npm ci
npm run typecheck
npm test -- --run
npm run build
```

Expected: all PASS.

- [ ] **Step 4: Review diff against invariants**

Confirm:

```text
ReviewRound production path does not stage-lookup previous body
No first-DEPICTS visual fallback introduced
No filename suffix identity introduced
Non-visual candidates do not show plate placeholder
VLM UI requires vlm_observation Evidence
```

- [ ] **Step 5: Push and verify GitHub Actions**

Push `review-remediation-20260817` and verify latest Actions jobs:

```text
backend-hermetic success
neo4j-e2e success
frontend success
```

Do not claim completion until those fresh results are read.
