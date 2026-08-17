# ReviewRound, Graph Scope & Visual Assets Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the document upload and review model into an incremental `ReviewRound` sequence with asset reuse, isolate `ArchaeologyObject` and evidence bundles by project and run scope to eliminate false positive candidate explosion, and fix Neo4j Cypher nested aggregation in `AssetRepository` to ensure split-view visual assets load reliably.

**Architecture:**
1. **Input & ReviewRound Model (Review 1):** Replace fixed `1차/2차/3차/final` stage enum with first-class `ReviewRound` graph nodes (`Project -[:HAS_REVIEW_ROUND]-> ReviewRound {sequence, status}`) with `USES_BODY_VERSION`, `USES_PLATE_VERSION`, `USES_DRAWING_VERSION`. Support multi-asset batch creation, asset reuse across rounds, and decouple final approval from upload.
2. **Graph Scope & Rule Engine (Review 2 & 2A):** Scope `ArchaeologyObject` IDs with `project_id` (`hash(project_id, site, canonical_name)`), filter `get_object_evidence_bundle` by selected `DocumentVersion` nodes in the run, tighten `RuleEngine` dictionary and morphology rules to stop false positive explosion (`토광묘 -> 수혈`), and implement a deterministic Development Candidate Selector (top 10 diverse representatives for expensive AI/VLM inspection while maintaining 100% full graph construction).
3. **Visual Assets & Frontend UX (Review 3):** Fix the nested `collect(DISTINCT ...)` Cypher query in `AssetRepository.get_candidate_visual_bundle()` using unrolled `WITH` aggregations, differentiate Split-View rendering based on candidate category (text-to-text rule vs visual/VLM target), and report granular visual asset load errors.

**Tech Stack:** Python 3.12, FastAPI, Neo4j 5.26, Redis 7.4 / RQ, PyMuPDF, React 19, TypeScript, Vite.

**Spec:**
- `docs/superpowers/reviews/2026-08-17-01-input-review.md`
- `docs/superpowers/reviews/2026-08-17-02-graph-review-logic-review.md`
- `docs/superpowers/reviews/2026-08-17-02a-development-candidate-budget.md`
- `docs/superpowers/reviews/2026-08-17-03-visual-assets-frontend-review.md`

## Global Constraints

- Never reduce Neo4j canonical graph indexing scope for development budget; all pages, plates, drawings, blocks, captions, references, and objects must be fully indexed.
- `ArchaeologyObject` IDs must be scoped by project (`project_id:site:canonical_name`) so cross-project objects never merge.
- Publication identifier (e.g. `【도판 45】`) remains the authoritative canonical reference identity (Gate 2 / Case 6 protection).
- `ReviewRound.status` transitions: `draft` -> `reviewing` -> `revisions_requested` -> `approved`.
- All candidate records must be initialized with `status = "pending_review"` with full audit trail (`SUPPORTED_BY -> Evidence`).
- All existing 545+ backend tests and frontend TypeScript typechecks must pass cleanly without regressions.

---

### Task 1: ReviewRound Domain & Neo4j Repository (Review 1)

**Files:**
- Create: `backend/app/domain/review_round.py`
- Modify: `backend/app/graph/project_repository.py`
- Test: `backend/tests/test_review_round_repository.py`

**Interfaces:**
- Produces: `ReviewRound` dataclass (`id`, `project_id`, `sequence`, `status`, `body_version_id`, `plate_version_id`, `drawing_version_id`, `created_at`), `ProjectRepository.create_review_round()`, `ProjectRepository.list_review_rounds()`, `ProjectRepository.get_review_round()`, `ProjectRepository.approve_review_round()`.

- [ ] **Step 1: Write the failing test**
```python
def test_create_review_round_increments_sequence_and_links_versions():
    # test creating round 1 with body, plate, drawing versions
    # test creating round 2 reusing plate version from round 1
    # verify PRECEDES chain and sequence incrementation
```
- [ ] **Step 2: Run test to verify it fails**
Run: `uv run pytest tests/test_review_round_repository.py -v`
Expected: FAIL
- [ ] **Step 3: Implement ReviewRound domain model & repository methods**
- [ ] **Step 4: Run test to verify it passes**
Run: `uv run pytest tests/test_review_round_repository.py -v`
Expected: PASS
- [ ] **Step 5: Commit**
`git commit -m "feat(domain): implement review round domain model and neo4j repository"`

---

### Task 2: ReviewRound API & Batch Input Endpoints (Review 1)

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/projects.py`
- Modify: `backend/app/api/reviews.py`
- Test: `backend/tests/test_review_round_api.py`

**Interfaces:**
- Produces: `POST /api/v1/projects/{project_id}/rounds` (create round with optional multipart uploads or reused version IDs), `GET /api/v1/projects/{project_id}/rounds`, `POST /api/v1/projects/{project_id}/rounds/{round_id}/approve`.

- [ ] **Step 1: Write failing API test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement schemas and API endpoints**
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**
`git commit -m "feat(api): add review round creation, reuse, and approval endpoints"`

---

### Task 3: Project-Scoped ArchaeologyObject ID & Evidence Isolation (Review 2)

**Files:**
- Modify: `backend/app/services/object_resolver.py`
- Modify: `backend/app/graph/canonical_repository.py`
- Test: `backend/tests/test_object_resolver_scope.py`

**Interfaces:**
- Consumes: `project_id` in `generate_object_id(project_id, site, canonical_name)`.
- Produces: Strict project isolation for `ArchaeologyObject` nodes and `get_object_evidence_bundle(object_id, version_ids)` filtering.

- [ ] **Step 1: Write failing test for cross-project object ID isolation and evidence bundle version filtering**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Update `object_resolver.py` and `canonical_repository.py`**
- [ ] **Step 4: Run test to verify pass**
- [ ] **Step 5: Commit**
`git commit -m "fix(graph): scope archaeology object ids and evidence bundles by project and version"`

---

### Task 4: Rule Engine False Positive Suppression & Development Candidate Budget (Review 2 & 2A)

**Files:**
- Modify: `backend/app/services/rule_engine.py`
- Modify: `backend/app/services/candidate_budget.py` (New)
- Modify: `backend/app/services/proofreading_orchestrator.py`
- Test: `backend/tests/test_candidate_budget.py`
- Test: `backend/tests/test_rule_engine_suppression.py`

**Interfaces:**
- Produces: `CandidateBudgetSelector.select_development_candidates(raw_candidates, max_count=10)` covering category diversity, and strict morphology guards preventing `토광묘 -> 수혈` synonym swaps.

- [ ] **Step 1: Write failing tests for candidate budget diversity selector and morphology guards**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement `CandidateBudgetSelector` and tighten rule engine**
- [ ] **Step 4: Run tests to verify pass**
- [ ] **Step 5: Commit**
`git commit -m "feat(rules): suppress false positive synonyms and add development candidate budget"`

---

### Task 5: Fix Visual Assets Cypher Nested Aggregation & Service (Review 3)

**Files:**
- Modify: `backend/app/graph/asset_repository.py`
- Modify: `backend/app/services/visual_asset_service.py`
- Test: `backend/tests/test_candidate_visual_bundle.py`

**Interfaces:**
- Produces: Robust `AssetRepository.get_candidate_visual_bundle()` using sequential `WITH` aggregation and error-tolerant `VisualAssetService`.

- [ ] **Step 1: Write failing test querying `get_candidate_visual_bundle()` across real Neo4j candidate nodes**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Rewrite Cypher query with separated WITH aggregations and add fallback rendering**
- [ ] **Step 4: Run test to verify pass**
- [ ] **Step 5: Commit**
`git commit -m "fix(assets): resolve nested cypher aggregation in candidate visual bundle query"`

---

### Task 6: Frontend ReviewRound Management, Batch Upload, & Split-View UX (Reviews 1, 2, 3)

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/components/SplitViewInspector.tsx`
- Modify: `frontend/src/components/VisualAssetPane.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/pages/ProjectDetailPage.test.tsx`

**Interfaces:**
- Produces: ReviewRound sequence UI with previous asset reuse checkboxes, category-aware SplitView (text vs visual), and granular visual error indicators.

- [ ] **Step 1: Update `frontend/src/api.ts` with ReviewRound types and fetchers**
- [ ] **Step 2: Update `ProjectDetailPage.tsx` for round creation, reuse, and round progression**
- [ ] **Step 3: Update `SplitViewInspector.tsx` and `VisualAssetPane.tsx` to handle rule candidates vs VLM vision comparisons**
- [ ] **Step 4: Run `npm run typecheck`, `npm run build`, and `npm test`**
- [ ] **Step 5: Commit**
`git commit -m "feat(frontend): implement review round batch upload, asset reuse, and split-view ux"`

---

### Task 7: E2E Verification & Gate Acceptance Across All 3 Reviews

**Files:**
- Create: `backend/tests/test_e2e_remediation_suite.py`
- Test: `backend/tests/test_e2e_remediation_suite.py`

**Interfaces:**
- Validates all 3 reviews:
  1. ReviewRound sequence with asset reuse across rounds.
  2. Project-scoped object IDs, evidence bundle isolation, and candidate budget <= 10.
  3. Real visual bundle loading in candidate split-view.

- [ ] **Step 1: Write complete integration test suite**
- [ ] **Step 2: Run suite against test Neo4j and Redis**
- [ ] **Step 3: Run full backend and frontend test suites**
- [ ] **Step 4: Commit**
`git commit -m "test: add comprehensive e2e verification for review round, graph scope, and visual assets"`
