# Codex-first Drawing Evidence v3 Review UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a fast human-review workflow for v3 `REVIEW_REQUIRED` drawing identities, persist the reviewer’s decision as gold provenance, and allow a human-approved target to become canonical without weakening Codex/deterministic safety rules.

**Architecture:** The backend exposes a small drawing-review API backed by the v3 Neo4j provenance created by the Core plan. The frontend adds a review panel to the existing Graph-first project detail page showing the source render, Codex choice, alternative candidate crops/captions, evidence highlights, and three explicit actions: approve a candidate, choose another candidate, or mark none. Human decisions persist separately from Codex decisions and become gold feedback.

**Tech Stack:** FastAPI/Pydantic, Neo4j repository, React/TypeScript, existing frontend API helpers, Vitest/Testing Library, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-codex-first-drawing-evidence-v3-design.md`

## Global Constraints

- This plan depends on `docs/superpowers/plans/2026-08-26-codex-first-drawing-evidence-v3-core.md` through Task 6; do not implement the UI against invented backend data.
- Human review is required only for v3 review cases; do not change existing proofreading-review semantics.
- Human approval is explicit and auditable; no page load or candidate highlight can mutate canonical identity.
- `approve/choose` may create a human-verified TARGETS relation only after the selected candidate exists in the persisted v3 candidate set.
- `none` must never create TARGETS.
- Store the original Codex decision unchanged; human resolution is a separate node/event linked to it.
- Human feedback records algorithm/resolver version, Codex model/run ID, selected/rejected candidate IDs, reviewer label, and timestamp.
- Review UI must show images and concise evidence, not require the reviewer to understand Neo4j internals.
- v3 automatic production rollout remains separately gated; human review does not imply `DRAWING_EVIDENCE_V3_AUTO_PROMOTE=true`.

---

## File Structure

### Backend

- Create: `backend/app/api/drawing_review_contract.py` — Pydantic request/response schemas.
- Create: `backend/app/api/drawing_reviews.py` — GET review queue and POST resolution endpoints.
- Modify: `backend/app/graph/drawing_evidence_repository.py` — query review cases and persist `HumanDrawingResolution`/human-verified TARGETS.
- Modify: `backend/app/main.py` — register router.
- Create: `backend/tests/test_drawing_reviews_api.py` — API contract and mutation tests.
- Extend: `backend/tests/test_drawing_evidence_repository_v3.py` — persistence safety tests.

### Frontend

- Create: `frontend/src/drawingReviewApi.ts` — typed review API calls.
- Create: `frontend/src/drawingReviewApi.test.ts` — request/response contract tests.
- Create: `frontend/src/components/DrawingIdentityReviewPanel.tsx` — review queue and candidate comparison UI.
- Create: `frontend/src/components/DrawingIdentityReviewPanel.test.tsx` — behavior tests.
- Create: `frontend/src/components/DrawingIdentityReviewPanel.css` — compact side-by-side review layout.
- Modify: `frontend/src/pages/GraphFirstProjectDetailPage.tsx` — mount review panel in project detail flow.
- Extend: `frontend/src/pages/ProjectDetailPage.test.tsx` or add `frontend/src/pages/GraphFirstProjectDetailPage.test.tsx` for integration coverage.

---

### Task 1: Define drawing review API contracts

**Files:**
- Create: `backend/app/api/drawing_review_contract.py`
- Test: `backend/tests/test_drawing_reviews_api.py`

**Interfaces:**
- Produces `DrawingReviewCaseResponse`, `DrawingReviewCandidateResponse`, `DrawingReviewResolveRequest`, and `DrawingReviewResolveResponse`.
- Review action is one of `approve`, `choose`, `none`.

- [ ] **Step 1: Write failing schema tests**

```python
from app.api.drawing_review_contract import DrawingReviewResolveRequest


def test_review_resolution_requires_candidate_for_approve_or_choose():
    req = DrawingReviewResolveRequest(action="approve", candidate_id="candidate:drawing:52", reviewer="human")
    assert req.candidate_id == "candidate:drawing:52"


def test_review_none_accepts_null_candidate():
    req = DrawingReviewResolveRequest(action="none", candidate_id=None, reviewer="human")
    assert req.candidate_id is None
```

Add validation tests that `approve`/`choose` with null candidate fail and `none` with a candidate fails.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_reviews_api.py`

Expected: module import failure.

- [ ] **Step 3: Implement explicit Pydantic models**

```python
class DrawingReviewCandidateResponse(BaseModel):
    candidate_id: str
    publication_kind: str
    number: str
    caption: str
    image_url: str | None
    local_score: float
    evidence_summary: list[str]
    contradiction_summary: list[str]

class DrawingReviewCaseResponse(BaseModel):
    source_asset_id: str
    source_name: str
    source_image_url: str | None
    source_text: str
    codex_candidate_id: str | None
    codex_confidence: float | None
    codex_summary: str | None
    candidates: list[DrawingReviewCandidateResponse]

class DrawingReviewResolveRequest(BaseModel):
    action: Literal["approve", "choose", "none"]
    candidate_id: str | None = None
    reviewer: str = "human"
```

Use `model_validator` to enforce the candidate/action rules.

- [ ] **Step 4: Run schema tests**

Run: `cd backend && pytest -q tests/test_drawing_reviews_api.py -k contract`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/drawing_review_contract.py backend/tests/test_drawing_reviews_api.py
git commit -m "feat: add drawing review API contracts"
```

---

### Task 2: Query review cases and persist human gold resolutions

**Files:**
- Modify: `backend/app/graph/drawing_evidence_repository.py`
- Test: `backend/tests/test_drawing_evidence_repository_v3.py`

**Interfaces:**
- Produces `list_v3_review_cases(project_id: str) -> list[dict]`.
- Produces `resolve_v3_review(project_id: str, source_asset_id: str, action: str, candidate_id: str | None, reviewer: str) -> dict`.

- [ ] **Step 1: Write failing repository tests**

Test fixture contains one `CodexDecision(finalStatus="REVIEW_REQUIRED")` with three candidates. Assert list returns source + Codex metadata + three candidates. Mutation tests assert:

```python
result = repo.resolve_v3_review(
    "project-1", "asset-1", action="choose",
    candidate_id="candidate:drawing:53", reviewer="reviewer-1",
)
assert result["final_status"] == "HUMAN_VERIFIED"
```

Also assert `candidate:drawing:999` is rejected and `action="none"` creates no TARGETS.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_repository_v3.py -k human`

Expected: methods missing.

- [ ] **Step 3: Implement review queue query**

Query only the latest unresolved/review-required v3 decision per source in the project. Return persisted source visual reference, source text/metadata, Codex candidate/confidence/summary, candidate IDs/numbers/kinds, crop references, and evidence/contradiction summaries. Keep candidate ordering stable: Codex-selected first when present, then local score descending.

- [ ] **Step 4: Implement immutable human resolution event**

Persist:

```text
(OriginalAsset)-[:HAS_HUMAN_RESOLUTION]->(HumanDrawingResolution)
(HumanDrawingResolution)-[:REVIEWS]->(CodexDecision)
(HumanDrawingResolution)-[:SELECTED]->(DrawingCandidate)   # approve/choose only
(HumanDrawingResolution)-[:REJECTED]->(DrawingCandidate)   # alternatives
```

Properties include `action`, `reviewer`, `resolverVersion="drawing-evidence-v3"`, Codex run/model snapshot, and `createdAt`. For `approve/choose`, verify the selected candidate is connected to the source’s submitted v3 decision before creating a human-verified TARGETS relation. For `none`, record all candidates rejected and create no TARGETS.

- [ ] **Step 5: Run repository tests**

Run: `cd backend && pytest -q tests/test_drawing_evidence_repository_v3.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/graph/drawing_evidence_repository.py backend/tests/test_drawing_evidence_repository_v3.py
git commit -m "feat: persist human drawing resolutions"
```

---

### Task 3: Expose review queue and resolution endpoints

**Files:**
- Create: `backend/app/api/drawing_reviews.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_drawing_reviews_api.py`

**Interfaces:**
- GET `/projects/{project_id}/drawing-reviews` -> `list[DrawingReviewCaseResponse]`.
- POST `/projects/{project_id}/drawing-reviews/{source_asset_id}/resolve` with `DrawingReviewResolveRequest` -> `DrawingReviewResolveResponse`.

- [ ] **Step 1: Write failing endpoint tests**

Use FastAPI TestClient with dependency-injected fake repository. Assert GET returns the queue. Assert POST calls repository with exact project/source/action/candidate/reviewer. Assert invalid candidate repository error maps to HTTP 409, missing review case to 404, malformed action to 422.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_reviews_api.py`

Expected: routes missing.

- [ ] **Step 3: Implement router**

```python
router = APIRouter(prefix="/projects/{project_id}/drawing-reviews", tags=["drawing-reviews"])

@router.get("", response_model=list[DrawingReviewCaseResponse])
def list_drawing_reviews(project_id: str, repository=Depends(get_drawing_evidence_repository)):
    return repository.list_v3_review_cases(project_id)

@router.post("/{source_asset_id}/resolve", response_model=DrawingReviewResolveResponse)
def resolve_drawing_review(project_id: str, source_asset_id: str, request: DrawingReviewResolveRequest, repository=Depends(get_drawing_evidence_repository)):
    return repository.resolve_v3_review(project_id, source_asset_id, request.action, request.candidate_id, request.reviewer)
```

Register the router in `main.py` using the project’s existing API registration style.

- [ ] **Step 4: Run backend API tests**

Run: `cd backend && pytest -q tests/test_drawing_reviews_api.py tests/test_drawing_evidence_repository_v3.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/drawing_reviews.py backend/app/main.py backend/tests/test_drawing_reviews_api.py
git commit -m "feat: expose drawing identity review API"
```

---

### Task 4: Add typed frontend review API

**Files:**
- Create: `frontend/src/drawingReviewApi.ts`
- Create: `frontend/src/drawingReviewApi.test.ts`

**Interfaces:**
- Produces TypeScript types mirroring backend responses.
- Produces `fetchDrawingReviews(projectId: string): Promise<DrawingReviewCase[]>`.
- Produces `resolveDrawingReview(projectId: string, sourceAssetId: string, input: DrawingReviewResolutionInput): Promise<DrawingReviewResolution>`.

- [ ] **Step 1: Write failing fetch tests**

```ts
it('loads drawing review cases', async () => {
  mockFetchJson([{ source_asset_id: 'asset-1', candidates: [] }])
  const rows = await fetchDrawingReviews('project-1')
  expect(rows[0].source_asset_id).toBe('asset-1')
})

it('posts an explicit human choice', async () => {
  await resolveDrawingReview('project-1', 'asset-1', {
    action: 'choose', candidate_id: 'candidate:drawing:53', reviewer: 'human'
  })
  expect(lastRequest.method).toBe('POST')
})
```

- [ ] **Step 2: Run and verify RED**

Run: `cd frontend && npm test -- --run src/drawingReviewApi.test.ts`

Expected: module missing.

- [ ] **Step 3: Implement API functions using existing project fetch/error conventions**

Keep wire names in backend snake_case unless the existing API layer explicitly maps them; do not silently rename only this endpoint. Encode project/source IDs with `encodeURIComponent`.

- [ ] **Step 4: Run frontend API tests**

Run: `cd frontend && npm test -- --run src/drawingReviewApi.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/drawingReviewApi.ts frontend/src/drawingReviewApi.test.ts
git commit -m "feat: add drawing review frontend API"
```

---

### Task 5: Build the fast candidate comparison panel

**Files:**
- Create: `frontend/src/components/DrawingIdentityReviewPanel.tsx`
- Create: `frontend/src/components/DrawingIdentityReviewPanel.test.tsx`
- Create: `frontend/src/components/DrawingIdentityReviewPanel.css`

**Interfaces:**
- Props: `{ projectId: string }`.
- Loads queue via `fetchDrawingReviews`.
- Mutations via `resolveDrawingReview`.
- After successful resolution, remove the resolved source from the local queue and show the next case.

- [ ] **Step 1: Write RED component tests**

Test behaviors:

```tsx
expect(screen.getByText('Codex 98%')).toBeInTheDocument()
expect(screen.getByRole('button', { name: /도면 52 승인/ })).toBeInTheDocument()
expect(screen.getByRole('button', { name: /모두 아님/ })).toBeInTheDocument()
```

Click a non-Codex candidate and assert POST action=`choose`; click Codex-selected candidate and assert action=`approve`; click 모두 아님 and assert action=`none`, candidate null. Assert no mutation fires merely by selecting/highlighting a card.

- [ ] **Step 2: Run and verify RED**

Run: `cd frontend && npm test -- --run src/components/DrawingIdentityReviewPanel.test.tsx`

Expected: component missing.

- [ ] **Step 3: Implement review-first layout**

Layout requirements:

- top: source name, source render, short extracted source text;
- summary: Codex selection/confidence/rationale;
- horizontal candidate cards: image, `도면/삽도 + number`, caption, key support chips, contradiction chips;
- explicit action button inside each candidate card;
- separate `모두 아님` button;
- loading/error/empty states;
- do not expose raw Neo4j IDs as the primary visual label, but retain them in accessible/details text.

- [ ] **Step 4: Add restrained CSS for 3-column desktop and single-column narrow layout**

Use existing app typography/spacing conventions. Candidate crops use `object-fit: contain`; do not crop the reviewer’s evidence image in CSS.

- [ ] **Step 5: Run component tests**

Run: `cd frontend && npm test -- --run src/components/DrawingIdentityReviewPanel.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DrawingIdentityReviewPanel.tsx frontend/src/components/DrawingIdentityReviewPanel.test.tsx frontend/src/components/DrawingIdentityReviewPanel.css
git commit -m "feat: add drawing identity review panel"
```

---

### Task 6: Integrate the review panel into the Graph-first project detail flow

**Files:**
- Modify: `frontend/src/pages/GraphFirstProjectDetailPage.tsx`
- Add or Modify test: `frontend/src/pages/ProjectDetailPage.test.tsx` or `frontend/src/pages/GraphFirstProjectDetailPage.test.tsx`

**Interfaces:**
- Existing project detail route remains unchanged.
- v3 review panel appears as a clearly labeled section/tab only when a `projectId` exists.

- [ ] **Step 1: Write failing integration test**

Render the Graph-first project page with project `project-1`, mock one drawing review case, and assert the page exposes `도면 ID 검수` plus the review panel. Mock empty queue and assert a compact `검수할 도면 없음` state rather than hiding system status entirely.

- [ ] **Step 2: Run and verify RED**

Run: `cd frontend && npm test -- --run src/pages/ProjectDetailPage.test.tsx`

Expected: review section missing.

- [ ] **Step 3: Mount `DrawingIdentityReviewPanel projectId={projectId}` in the existing project detail composition**

Do not duplicate project loading or routing logic. Keep the review panel isolated so existing graph/proofreading sections do not re-render on candidate selection except where the current page architecture naturally does so.

- [ ] **Step 4: Run page and full frontend tests**

Run: `cd frontend && npm test -- --run`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/GraphFirstProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.test.tsx frontend/src/pages/GraphFirstProjectDetailPage.test.tsx
git commit -m "feat: integrate drawing identity review workflow"
```

Only add whichever test file actually exists/is created; do not stage a nonexistent path.

---

### Task 7: Verify human-review provenance end to end

**Files:**
- Modify only for regression fixes discovered by tests.

**Interfaces:**
- No new interfaces; proves backend/frontend/Neo4j behavior.

- [ ] **Step 1: Run focused backend tests**

```powershell
cd backend
pytest -q `
  tests/test_drawing_reviews_api.py `
  tests/test_drawing_evidence_repository_v3.py
cd ..
```

Expected: PASS.

- [ ] **Step 2: Run full frontend tests**

```powershell
cd frontend
npm test -- --run
cd ..
```

Expected: PASS.

- [ ] **Step 3: Run Neo4j E2E with one review case**

Create/persist a v3 `REVIEW_REQUIRED` case, GET it through the API, POST a `choose` resolution, then query Neo4j and assert: original CodexDecision still exists unchanged; HumanDrawingResolution exists; selected candidate gets one human-verified target; alternatives are rejected; the source disappears from the pending review queue.

- [ ] **Step 4: Run repository CI jobs and verify all green**

Required jobs: `backend-hermetic`, `frontend`, `neo4j-e2e`.

- [ ] **Step 5: Keep rollout and merge gates unchanged**

Do not enable v3 auto-promotion or merge PR #47/PR #1 without explicit approval. Human-review functionality may be exercised while v3 remains shadow mode.
