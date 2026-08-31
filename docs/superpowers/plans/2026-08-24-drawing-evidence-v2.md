# Drawing Evidence Graph v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve AI drawing identity recall by adding publication-kind separation, structured archaeology signatures, mention-level consensus, stronger contradictions, and weak path/sequence tie-breakers while preserving fail-closed provenance.

**Architecture:** Keep the existing Candidate/Evidence/ContextEntity graph and v1 resolver intact. Add v2-compatible fields to the evidence domain, extend the deterministic normalizer, introduce mention/consensus aggregation in a new v2 resolver, persist the new metadata, and switch production assembly only after focused tests and CI pass. Real `/src` acceptance is executed locally with the evaluator and remains read-only.

**Tech Stack:** Python 3.12, dataclasses, regex, NetworkX, Neo4j, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-24-drawing-evidence-v2-design.md`

## Global Constraints

- Adobe/COM/ExtendScript remain unused in the Adobe-free path.
- Filename/path/sequence evidence cannot independently produce `DERIVED_VERIFIED`.
- `TARGETS` remains restricted to `DIRECT` and `DERIVED_VERIFIED`.
- Hard contradictions cannot be promoted.
- Existing v1 behavior remains available until local `/src` v2 acceptance succeeds.
- PR #47 remains Draft and unmerged.
- `/src` is read-only; local evaluator outputs must be outside `/src`.

---

### Task 1: Publication kind and structured signature domain

**Files:**
- Modify: `backend/app/domain/drawing_evidence.py`
- Modify: `backend/app/services/drawing_context_normalizer.py`
- Modify: `backend/tests/test_drawing_context_normalizer.py`

**Interfaces:**
- Produces `publication_kind`, richer `ContextFact.kind` values, and deterministic normalization used by v2.

- [ ] **Step 1: Write failing tests** for `drawing|illustration`, site point, period, feature type/number, drawing type, content type, map type, and map-bound year.
- [ ] **Step 2: Run focused tests and verify RED.**
- [ ] **Step 3: Implement minimal domain/normalizer changes.** Preserve legacy `point`/`feature` aliases where needed by v1 tests.
- [ ] **Step 4: Run focused tests and verify GREEN.**
- [ ] **Step 5: Commit.**

### Task 2: Mention-level consensus and resolver v2

**Files:**
- Create: `backend/app/services/drawing_evidence_graph_resolver_v2.py`
- Create: `backend/tests/test_drawing_evidence_graph_resolver_v2.py`
- Modify: `backend/app/domain/drawing_evidence.py`

**Interfaces:**
- Consumes `DrawingSourceObservation`, `BodyDrawingContext`, structured facts.
- Produces `DrawingEvidenceResolution` with resolver version `drawing-evidence-v2`.

- [ ] **Step 1: Write RED tests** for kind collision, consensus over union, feature-number hard contradiction, period strong contradiction, filename/path non-promotion, and kind-separated global 1:1 assignment.
- [ ] **Step 2: Run focused tests and verify RED.**
- [ ] **Step 3: Implement v2 resolver** as an isolated class; keep v1 untouched.
- [ ] **Step 4: Run v1 + v2 resolver suites and verify GREEN.**
- [ ] **Step 5: Commit.**

### Task 3: Neo4j provenance metadata

**Files:**
- Modify: `backend/app/graph/drawing_evidence_repository.py`
- Modify: `backend/tests/test_drawing_evidence_repository.py`

**Interfaces:**
- Persists publication kind, mention id, consensus status, structured fact metadata and tie-breaker class.

- [ ] **Step 1: Write RED persistence tests.**
- [ ] **Step 2: Run focused tests and verify RED.**
- [ ] **Step 3: Extend deterministic MERGE payloads/queries.**
- [ ] **Step 4: Run repository tests and real Neo4j E2E.**
- [ ] **Step 5: Commit.**

### Task 4: Production integration behind v2 switch

**Files:**
- Modify: `backend/app/services/drawing_evidence_corpus_service.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_drawing_evidence_corpus_service.py`

**Interfaces:**
- Production can select v2 explicitly while v1 remains available for rollback.

- [ ] **Step 1: Write RED integration test** proving the selected resolver is v2 without altering plate/JPG behavior.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Wire v2 and retain v1 fallback.**
- [ ] **Step 4: Verify focused integration tests.**
- [ ] **Step 5: Commit.**

### Task 5: Local `/src` evaluator v2 contract

**Files:**
- Modify: `tools/evaluate_drawing_evidence_graph.py`
- Modify: `backend/tests/test_drawing_evidence_graph_evaluator_contract.py`
- Create: `docs/local_drawing_evidence_v2_revalidation.md`

**Interfaces:**
- Emits blinded Top-1/Top-3 and full-56 distribution plus kind collisions, hard-contradiction promotions, filename-only promotions, resolver version.

- [ ] **Step 1: Write RED evaluator contract tests.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Add `--resolver-version v1|v2` and v2 metrics while preserving read-only guard.**
- [ ] **Step 4: Verify evaluator contract tests.**
- [ ] **Step 5: Document local command and acceptance criteria.**
- [ ] **Step 6: Commit.**

### Task 6: Final CI and push verification

- [ ] **Step 1:** `python -m compileall -q app` and all focused v2 tests.
- [ ] **Step 2:** GitHub Actions backend-hermetic GREEN.
- [ ] **Step 3:** GitHub Actions frontend GREEN.
- [ ] **Step 4:** GitHub Actions Neo4j E2E GREEN.
- [ ] **Step 5:** Verify PR #47 remains Draft/open/unmerged and record final HEAD.
- [ ] **Step 6:** Do not claim real `/src` acceptance until the local v2 evaluator output is committed or supplied.

## Local acceptance after pull

Run locally after CI:

```powershell
python tools/evaluate_drawing_evidence_graph.py `
  --source-root src `
  --resolver-version v2 `
  --output-json docs/local_drawing_evidence_v2_metrics.json `
  --output-report docs/local_drawing_evidence_v2_report.md `
  --blinded
```

Minimum acceptance: blinded Top-1 > 8/35, Top-3 > 13/35, derived verified > 3/56, direct >= 1/56, filename-only verified = 0, kind collision = 0, hard-contradiction promoted = 0. If these are not met, keep v1 as the production default and report v2 as experimental.