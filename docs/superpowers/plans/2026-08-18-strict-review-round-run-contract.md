# Strict ReviewRound Run Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task with TDD.

**Goal:** Make `ReviewRound` the only production authority for `/api/v1/projects/{project_id}/runs`, reject all legacy run fields with 422, remove the duplicate compatibility route, and make those checks mandatory CI gates.

**Architecture:** Keep `backend/app/api/review_round_runs.py` as the sole `/runs` owner. Make its Pydantic request model `extra="forbid"`, resolve body/plate/drawing only through `resolve_review_round_inputs`, delete the duplicate route in `reviews.py`, register the strict router in `main.py`, and remove obsolete direct-version test deselections from CI.

**Tech Stack:** FastAPI, Pydantic v2, pytest, Neo4j, GitHub Actions.

## Global Constraints
- `reviewRoundId` is required and non-empty.
- `bodyVersionId`, `plateVersionId`, `drawingVersionId`, `bodyPdfPath`, `platePdfPath`, `drawingPdfPath`, and `versionStage` are forbidden public run inputs.
- Missing `reviewRoundId` => 422.
- `reviewRoundId` plus any forbidden field => 422.
- Exactly one runtime POST route exists for `/api/v1/projects/{project_id}/runs`.
- The route resolves versions from the project-scoped ReviewRound graph only.
- Existing ReviewRound predecessor traversal and Case 6 graph-authority work must not regress.
- VLM acceptance remains HOLD.

### Task 1: RED strict request-contract tests
**Files:** Create `backend/tests/test_strict_review_round_run_api.py`.

- [ ] Add tests for empty payload, legacy-only payload, `reviewRoundId+bodyVersionId`, `reviewRoundId+versionStage`, and `reviewRoundId+bodyPdfPath`, all expecting 422.
- [ ] Add a route-table test requiring exactly one POST `/api/v1/projects/{project_id}/runs` route.
- [ ] Add valid-round test proving `create_analysis_run` receives only the versions resolved from ReviewRound.
- [ ] Push RED commit and confirm failures on Actions.

### Task 2: GREEN strict route
**Files:** Modify `backend/app/api/review_run_contract.py`, `backend/app/api/review_round_runs.py`, `backend/app/api/reviews.py`, `backend/app/main.py`.

- [ ] Set `ReviewRoundRunTriggerRequest.model_config = ConfigDict(populate_by_name=True, extra="forbid")`.
- [ ] Remove all legacy branches/path fields from `trigger_review_round_run`; always resolve the ReviewRound.
- [ ] Delete the duplicate `/runs` handler from `reviews.py` and obsolete imports used only by that handler.
- [ ] Register `review_round_runs_router` in `create_app()` and remove route-hiding compatibility logic.
- [ ] Run/push GREEN and confirm strict tests pass.

### Task 3: Mandatory CI gate
**Files:** Modify `.github/workflows/remediation-ci.yml`; rewrite/remove obsolete direct-version tests only where needed.

- [ ] Add `review-remediation-20260818-strict-run-contract` to workflow push branches.
- [ ] Remove the 12 `--deselect` entries for old run/version contracts.
- [ ] Replace obsolete direct-version expectations with strict 422 expectations rather than hiding failures.
- [ ] Confirm hermetic backend, real Neo4j, frontend all green.

### Task 4: Handoff
**Files:** Create/update `docs/superpowers/reviews/2026-08-18-strict-run-contract-verification.md`.

- [ ] Record tested SHA/run ID.
- [ ] Require exact 422 examples, route-table proof, ReviewRound version-membership proof, predecessor reuse proof, and VLM `NOT VERIFIED / HOLD`.
