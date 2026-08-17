# Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the current ReviewRound/Neo4j/visual-asset implementation from a parallel compatibility layer into the authoritative review execution model, while enforcing the development cost budget before AI/VLM work and making the live E2E test prove the behavior it claims.

**Architecture:** `ReviewRound` becomes the authoritative source of the three active DocumentVersion inputs. A run created from a round resolves versions through Neo4j and stores the round id on AnalysisRun. Cheap graph/rule analysis runs over the full scope, but a deterministic stratified development selector chooses at most 10 expensive-review targets before LLM/VLM work. CorrectionCandidate instances are run-scoped, project-scoped on every read/write boundary, and retain severity plus raw/deduped/selected counters. Visual bundle resolution is scoped to the candidate's target/evidence and owning DocumentVersion rather than selecting an arbitrary asset attached to the same ArchaeologyObject.

**Tech Stack:** Python 3.11+, FastAPI, Neo4j 5.26 Cypher, RQ/Redis, PyMuPDF, React 19/TypeScript, pytest, Vitest.

## Global Constraints

- Neo4j remains the canonical System of Record for ReviewRound, DocumentVersion, ArchaeologyObject, Evidence, CorrectionCandidate, and ReviewDecision.
- `ReviewRound` sequence is unbounded (`1..N`). `final` is an approval state, not an upload-stage selector.
- Body/plate/drawing version ids must belong to the same project and match their expected document kind.
- Development candidate budget limits expensive AI/VLM review and materialized candidates, not full document parsing or canonical graph construction.
- Development selection is deterministic and category-balanced; plain `candidates[:10]` is forbidden.
- Record `raw_findings`, `deduped_findings`, and `selected_candidates` separately.
- Candidate ids are unique per AnalysisRun; equivalent findings may share a separate fingerprint but never the candidate node id.
- Candidate detail/decision/traceability/visual-bundle endpoints must prove `(Project)-[:HAS_CANDIDATE]->(Candidate)` ownership.
- Visual canonical asset lookup must carry the owning DocumentVersion and must never silently choose an unrelated first asset.
- All generated candidates remain `pending_review`; approval is expert action only.

---

### Task 1: ReviewRound-authoritative run creation and unbounded revision flow

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/reviews.py`
- Modify: `backend/app/graph/project_repository.py`
- Modify: `backend/app/graph/review_repository.py`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Test: `backend/tests/test_review_round_api.py`
- Test: `backend/tests/test_e2e_remediation_suite.py`
- Test: `frontend/src/pages/ProjectDetailPage.test.tsx`

**Interfaces:**
- `RunTriggerRequest.review_round_id: str | None`
- `ProjectRepository.get_review_round(project_id, round_id) -> ReviewRound | None`
- `ProjectRepository.resolve_version_input(project_id, expected_kind, version_id=...)`
- `AnalysisRun.roundId` persisted when run originates from a ReviewRound.

- [ ] Add failing backend tests proving a run with `reviewRoundId` resolves all three version ids from the graph and ignores conflicting direct ids.
- [ ] Add failing tests proving ReviewRound creation rejects cross-project or wrong-kind versions.
- [ ] Add failing test proving approving a round twice preserves the first `approvedAt`.
- [ ] Implement round-authoritative run creation and graph validation.
- [ ] Replace frontend run execution with selected `ReviewRound` rather than independent version selectors.
- [ ] Remove the fixed `1차/2차/3차/final` user choice from the review workflow; use `ReviewRound.sequence` for display and automatic upload metadata compatibility.

### Task 2: Development candidate budget before expensive AI/VLM

**Files:**
- Modify: `backend/app/services/rule_engine.py`
- Modify: `backend/app/services/proofreading_orchestrator.py`
- Modify: `compose.yml`
- Test: `backend/tests/test_rule_engine_guards.py`
- Test: `backend/tests/test_e2e_remediation_suite.py`

**Interfaces:**
- `select_development_candidates(candidates, max_candidates=10) -> list[CorrectionCandidateData]`
- summary keys: `raw_findings`, `deduped_findings`, `selected_candidates`, `selection_mode`.

- [ ] Add failing tests for deterministic category-balanced selection including at least one reference/visual category when present.
- [ ] Add failing orchestrator test proving expensive review input is bounded before VLM/LLM execution.
- [ ] Implement pre-AI/VLM budget selection while still building the entire canonical graph and counting all cheap findings.
- [ ] Persist raw/deduped/selected counts separately.
- [ ] Set Docker worker development defaults explicitly to a 10-candidate budget.

### Task 3: Run-scoped candidates, severity persistence, and project ownership

**Files:**
- Modify: `backend/app/graph/review_repository.py`
- Modify: `backend/app/api/reviews.py`
- Modify: `backend/app/services/proofreading_orchestrator.py`
- Test: `backend/tests/test_e2e_remediation_suite.py`
- Test: `backend/tests/test_review_round_api.py`

**Interfaces:**
- Candidate node id includes `analysis_run_id` or a generated run-specific UUID.
- Candidate keeps a stable `findingFingerprint` for semantic dedupe across runs.
- `ReviewRepository.get_candidate(project_id, candidate_id)` and related trace/visual ownership checks are project-scoped.

- [ ] Add failing test proving identical finding in two runs creates two Candidate nodes.
- [ ] Add failing API tests proving Project A cannot decide/trace/view Project B candidate.
- [ ] Add failing persistence test for candidate severity and real severity metrics.
- [ ] Implement run-scoped candidate ids/fingerprints, severity persistence, and project-scoped API lookups.

### Task 4: Evidence/type false-positive hardening

**Files:**
- Modify: `backend/app/services/rule_engine.py`
- Test: `backend/tests/test_rule_engine_guards.py`

**Interfaces:**
- Structured evidence value is authoritative when present.
- Generated rationale text is never re-parsed as an independent factual source when a structured value exists.

- [ ] Add failing regression tests for `토광묘`, `수혈`, `수혈유구`, generic `유구`, and multi-object text.
- [ ] Stop rationale re-parsing when structured evidence already provides type/value.
- [ ] Preserve longest-match/compatible-type guards and verify candidate volume is not inflated by nested morphology tokens.

### Task 5: Candidate-specific visual bundle and owning DocumentVersion

**Files:**
- Modify: `backend/app/graph/asset_repository.py`
- Modify: `backend/app/services/visual_asset_service.py`
- Modify: `backend/app/api/reviews.py`
- Test: `backend/tests/test_candidate_visual_bundle.py`
- Test: `backend/tests/test_e2e_remediation_suite.py`

**Interfaces:**
- Canonical asset rows include `version` properties.
- Candidate visual lookup is project-scoped.
- When an exact candidate target/reference cannot be established, canonical visual remains unresolved instead of choosing an arbitrary first asset.

- [ ] Add failing test proving canonical asset includes owning DocumentVersion URI/SHA.
- [ ] Add failing test with two assets depicting the same object proving the bundle does not silently choose an unrelated asset.
- [ ] Implement version-carrying query and deterministic target selection/fail-closed behavior.
- [ ] Keep graceful UI metadata fallback, but distinguish `unresolved target` from `render unavailable`.

### Task 6: Honest live E2E validation

**Files:**
- Modify: `scripts/run_live_10_api_validation.py`
- Modify: `docs/4th_phase_e2e_verification_report.md`

**Interfaces:**
- Round 1 uses body v1 + plate v1 + drawing v1.
- Round 2 uploads a new body v2 and reuses plate v1 + drawing v1.
- Run endpoint is called with `reviewRoundId`.

- [ ] Fail if AnalysisRun does not reach `completed`.
- [ ] Fail unless candidate count is `1..10` in development mode.
- [ ] Assert summary raw/deduped/selected counters are internally consistent.
- [ ] Exercise candidate traceability and visual-bundle endpoint; when a render URL is returned, assert the render endpoint returns image bytes.
- [ ] Create a true second body version for Round 2 and assert reuse of plate/drawing versions.
- [ ] Update the report so it only claims capabilities directly asserted by the script/test suite.

### Task 7: Verification and merge back

**Files:** all modified files above.

- [ ] Run targeted backend tests for every changed behavior.
- [ ] Run the full backend test suite if the environment supports the repository dependencies.
- [ ] Run frontend Vitest/typecheck/build if dependencies are available; otherwise perform TypeScript syntax/static contract checks and clearly record the limitation.
- [ ] Run Python compile/static checks for all changed Python files.
- [ ] Re-review the final diff against the 2026-08-17 code-review findings.
- [ ] Fast-forward `windows-docker-foundation` only after verification evidence is collected.
