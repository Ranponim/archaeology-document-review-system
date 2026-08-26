# Codex-first Drawing Evidence v3 Review UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give reviewers a fast, auditable workflow for v3 `REVIEW_REQUIRED` identities, persist human decisions as gold provenance, and allow only an explicit human-selected candidate to become human-verified canonical evidence.

**Architecture:** The backend exposes two v3 drawing-review endpoints backed by `DrawingEvidenceRepository`. It follows the existing API pattern: `/api/v1/projects` prefix, `Request.app.state` lazy repository construction, async route functions, and `run_in_threadpool` for synchronous Neo4j methods. The frontend follows existing `graphFirstReviewApi.ts` fetch/error conventions and mounts one comparison panel in `GraphFirstProjectDetailPage`.

**Spec:** `docs/superpowers/specs/2026-08-26-codex-first-drawing-evidence-v3-design.md`
**Dependency:** Core plan through Task 6: `docs/superpowers/plans/2026-08-26-codex-first-drawing-evidence-v3-core.md`.

## Constraints

- Do not change existing proofreading review semantics.
- No UI selection/highlight mutates graph state; only an explicit action POST does.
- `approve` and `choose` require a candidate already connected to that source's persisted v3 Codex decision.
- `none` creates no TARGETS.
- Original `CodexDecision` is immutable; human review is a separate `HumanDrawingResolution` event.
- Human resolution records resolver/model/run snapshot, selected/rejected candidates, reviewer, and timestamp.
- Human `approve/choose` final status is exactly `HUMAN_VERIFIED`; human `none` is exactly `HUMAN_UNRESOLVED`.
- Review UI shows source/candidate images, captions and concise evidence; raw graph IDs are secondary detail only.
- Human review does not enable v3 automatic production promotion.

## Files

Backend:
- Create `backend/app/api/drawing_review_contract.py`
- Create `backend/app/api/drawing_reviews.py`
- Modify `backend/app/graph/drawing_evidence_repository.py`
- Modify `backend/app/main.py`
- Test `backend/tests/test_drawing_reviews_api.py`
- Extend `backend/tests/test_drawing_evidence_repository_v3.py`

Frontend:
- Create `frontend/src/drawingReviewApi.ts`
- Create `frontend/src/drawingReviewApi.test.ts`
- Create `frontend/src/components/DrawingIdentityReviewPanel.tsx`
- Create `frontend/src/components/DrawingIdentityReviewPanel.test.tsx`
- Create `frontend/src/components/DrawingIdentityReviewPanel.css`
- Modify `frontend/src/pages/GraphFirstProjectDetailPage.tsx`
- Create `frontend/src/pages/GraphFirstProjectDetailPage.test.tsx`

---

### Task 1: Define exact drawing-review API contracts

- [ ] Write RED Pydantic tests in `backend/tests/test_drawing_reviews_api.py` for these exact schemas:

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

class DrawingReviewResolveResponse(BaseModel):
    source_asset_id: str
    action: Literal["approve", "choose", "none"]
    candidate_id: str | None
    final_status: Literal["HUMAN_VERIFIED", "HUMAN_UNRESOLVED"]
```

- [ ] Add `model_validator` tests: approve/choose without candidate → 422 contract failure; none with candidate → failure; none with null → valid.
- [ ] Run `cd backend && pytest -q tests/test_drawing_reviews_api.py -k contract`; verify RED, implement `backend/app/api/drawing_review_contract.py`, rerun GREEN.
- [ ] Commit `feat: add drawing review API contracts`.

---

### Task 2: Query pending v3 reviews and persist immutable human resolutions

**Repository methods:**
- `list_v3_review_cases(project_id: str) -> list[dict]`
- `resolve_v3_review(project_id: str, source_asset_id: str, action: str, candidate_id: str | None, reviewer: str) -> dict`

- [ ] Write RED repository tests with one latest `CodexDecision(finalStatus="REVIEW_REQUIRED")` and three persisted candidates. Assert queue returns source image/text, Codex selection/confidence/summary, candidates/crops, evidence and contradiction summaries.
- [ ] Assert stable order: Codex-selected candidate first when present, remaining candidates by local score descending.
- [ ] Mutation RED tests:
  - `choose(candidate:drawing:53)` → `HUMAN_VERIFIED` and exactly one human-verified TARGETS.
  - `approve` only accepts the Codex-selected persisted candidate.
  - unknown/not-submitted candidate raises a dedicated `DrawingReviewConflictError`.
  - `none` → `HUMAN_UNRESOLVED`, records rejection, creates zero TARGETS.
- [ ] Implement graph shape:

```text
(OriginalAsset)-[:HAS_HUMAN_RESOLUTION]->(HumanDrawingResolution)
(HumanDrawingResolution)-[:REVIEWS]->(CodexDecision)
(HumanDrawingResolution)-[:SELECTED]->(DrawingCandidate)   # approve/choose
(HumanDrawingResolution)-[:REJECTED]->(DrawingCandidate)   # rejected alternatives
```

- [ ] Store `action`, `reviewer`, `resolverVersion="drawing-evidence-v3"`, Codex run/model snapshot, `createdAt`, selected/rejected candidate IDs. Preserve the original Codex node unchanged.
- [ ] Latest human resolution removes the source from pending queue; never delete historical Codex/human nodes.
- [ ] Run `cd backend && pytest -q tests/test_drawing_evidence_repository_v3.py`; commit `feat: persist human drawing resolutions`.

---

### Task 3: Expose API using the repository pattern already used by `reviews.py`

**Exact endpoints:**
- GET `/api/v1/projects/{project_id}/drawing-reviews`
- POST `/api/v1/projects/{project_id}/drawing-reviews/{source_asset_id}/resolve`

- [ ] Write RED TestClient tests using `app.dependency_overrides[get_drawing_evidence_repository] = lambda: fake_repo`.
- [ ] In `backend/app/api/drawing_reviews.py`, define:

```python
router = APIRouter(prefix="/api/v1/projects", tags=["drawing-reviews"])

def get_drawing_evidence_repository(request: Request):
    repo = getattr(request.app.state, "drawing_evidence_repository", None)
    if repo is None:
        driver = getattr(request.app.state, "neo4j_driver", None)
        if driver is not None:
            repo = DrawingEvidenceRepository(driver)
            request.app.state.drawing_evidence_repository = repo
    return repo
```

- [ ] Implement async routes. First call existing `get_project_repository` / `_run_repository(project_repository.get_project, project_id)` to enforce project ownership, matching `backend/app/api/reviews.py`. Call synchronous drawing repository methods with `run_in_threadpool`.
- [ ] If drawing repository is not configured, raise existing `ServerOperationError`.
- [ ] Add dedicated exceptions `DrawingReviewNotFoundError` and `DrawingReviewConflictError`; in `main.py` map them to 404 and 409 using existing `_error_response` convention.
- [ ] POST maps repository result to `DrawingReviewResolveResponse`; malformed request remains FastAPI 422.
- [ ] Import/register `drawing_reviews_router` in `main.py` beside existing review routers. No second API prefix.
- [ ] Run `cd backend && pytest -q tests/test_drawing_reviews_api.py tests/test_drawing_evidence_repository_v3.py`; commit `feat: expose drawing identity review API`.

---

### Task 4: Add typed frontend API using existing fetch conventions

- [ ] Write RED `frontend/src/drawingReviewApi.test.ts` for GET and POST URLs under `/api/v1/projects/...`, URL encoding, JSON body and error propagation.
- [ ] Implement `frontend/src/drawingReviewApi.ts` with a private `readJson<T>()` matching `graphFirstReviewApi.ts` behavior.
- [ ] Wire types in snake_case to match backend response exactly; do not create a one-off rename layer.
- [ ] Export:
  - `fetchDrawingReviews(projectId): Promise<DrawingReviewCase[]>`
  - `resolveDrawingReview(projectId, sourceAssetId, input): Promise<DrawingReviewResolution>`
- [ ] POST body: `{action, candidate_id, reviewer}`.
- [ ] Run `cd frontend && npm test -- --run src/drawingReviewApi.test.ts`; commit `feat: add drawing review frontend API`.

---

### Task 5: Build the candidate comparison panel

**Component:** `DrawingIdentityReviewPanel({projectId})`.

- [ ] Write RED component tests with mocked API:
  - source image/text appears;
  - `Codex 98%` and short rationale appear;
  - candidate image, `도면/삽도 + number`, caption, support/contradiction chips appear;
  - Codex candidate button sends `approve`;
  - different candidate sends `choose`;
  - `모두 아님` sends `none` with null candidate;
  - merely highlighting/focusing a card sends no mutation;
  - successful mutation removes current source and advances queue;
  - loading/error/empty states are explicit.
- [ ] Implement `DrawingIdentityReviewPanel.tsx` and CSS. Desktop candidate comparison is 3-column when space permits; narrow screens stack. Images use `object-fit: contain` so evidence is not visually cropped.
- [ ] Keep raw candidate/source IDs in details/accessibility text, not as the primary display label.
- [ ] Run `cd frontend && npm test -- --run src/components/DrawingIdentityReviewPanel.test.tsx`; commit `feat: add drawing identity review panel`.

---

### Task 6: Integrate exactly into `GraphFirstProjectDetailPage`

- [ ] Create `frontend/src/pages/GraphFirstProjectDetailPage.test.tsx` (do not reuse/modify the legacy `ProjectDetailPage.test.tsx` for this new flow).
- [ ] RED test renders `GraphFirstProjectDetailPage` with project `project-1`; mock one review and assert a labeled `도면 ID 검수` section contains the comparison panel.
- [ ] Empty queue test asserts `검수할 도면 없음` so review state is visible rather than silently absent.
- [ ] Modify `GraphFirstProjectDetailPage.tsx` to import/mount `<DrawingIdentityReviewPanel projectId={project.id} />` within the existing Graph-first project detail composition. Do not duplicate routing/project loading.
- [ ] Run the new page test, then `cd frontend && npm test -- --run`; commit `feat: integrate drawing identity review workflow`.

---

### Task 7: Verify human-review provenance end to end

- [ ] Backend focused: `cd backend && pytest -q tests/test_drawing_reviews_api.py tests/test_drawing_evidence_repository_v3.py`.
- [ ] Frontend full: `cd frontend && npm test -- --run`.
- [ ] Neo4j E2E fixture: persist one v3 `REVIEW_REQUIRED`; GET through API; POST `choose`; query graph and assert original CodexDecision unchanged, one HumanDrawingResolution exists, selected candidate has one human-verified target, alternatives recorded rejected, source absent from pending queue.
- [ ] Required repository CI jobs all green: `backend-hermetic`, `frontend`, `neo4j-e2e`.
- [ ] Do not set v3 auto-promote, change production default, or merge PR #47/PR #1 without explicit approval.
