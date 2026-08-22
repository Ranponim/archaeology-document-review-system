# Graph-First Review Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ReviewRound execute against body PDF + READY ReferenceCorpus, perform deterministic graph review as the authority, and invoke LLM/VLM only for explicitly escalated semantic findings with both optional features default OFF.

**Architecture:** New ReviewRounds bind exactly one body `DocumentVersion` and one immutable `ReferenceCorpus`; legacy plate/drawing-PDF rounds remain compatibility-only. The worker resolves the selected corpus, links body archaeology objects to corpus visuals only through deterministic strong identifiers, executes a four-layer graph rule engine, and emits pending candidates. Optional AI/VLM receives only semantic-review bundles and stores separate auditable `AIReviewFinding` records; it cannot mutate canonical graph identity or relationships.

**Tech Stack:** Python 3.12, FastAPI, Neo4j 5.26, RQ/Redis, existing proofreading orchestrator/repositories, React/TypeScript/Vitest.

**Spec:** `docs/superpowers/specs/2026-08-22-graph-first-reference-corpus-review-design.md`

## Global Constraints

- ReviewRound remains the sole public `/runs` input authority.
- New rounds use body PDF + READY same-project `ReferenceCorpus` only.
- Mixed new/legacy authority is rejected.
- Neo4j canonical graph and deterministic rules are authoritative; AI/VLM cannot create or mutate identity, `RESOLVES_TO`, `DEPICTS`, corpus membership, or provenance.
- Core review completes with `enable_ai_review=false` and `enable_vlm=false`.
- AI/VLM defaults are OFF in backend API, frontend client, and UI.
- Ambiguous graph identity fails closed; automatic proposed text requires unique target, unique body edit location, and complete provenance.
- All correction findings remain `pending_review` until human decision.
- Legacy ReviewRounds remain readable/executable through explicit compatibility code until later migration removal.
- Existing deterministic visual-reference behavior must not be duplicated by a second generic regex candidate path.

---

## File Structure

- Modify `backend/app/domain/review_round.py`: add `reference_corpus_id` while retaining legacy fields for compatibility.
- Create `backend/app/domain/ai_review_finding.py`: isolated AI/VLM audit model; canonical graph models remain untouched by model opinion.
- Modify `backend/app/graph/review_project_repository.py`: create/resolve corpus rounds and reject mixed authority.
- Modify `backend/app/services/review_round_execution.py`: resolve body + corpus and expose explicit mode.
- Modify `backend/app/jobs/run_inputs.py`: stop visual-PDF fallback in corpus mode.
- Modify `backend/app/jobs/worker.py`: branch corpus-mode vs legacy-mode input resolution.
- Create `backend/app/services/corpus_object_linker.py`: deterministic visual-to-object linking scoped to selected corpus/run.
- Create `backend/app/graph/graph_review_repository.py`: graph queries for integrity, corpus-scoped reference resolution, coverage, consistency, and scoped resolution evidence.
- Create `backend/app/services/graph_rules/models.py`, `corpus_integrity.py`, `reference_resolution.py`, `visual_coverage.py`, `visual_consistency.py`, `semantic_escalation.py`, and `engine.py`.
- Modify `backend/app/services/strict_rule_engine.py`: compose graph rules while preserving existing candidate intent compatibility.
- Modify `backend/app/services/proofreading_orchestrator.py`: graph-first execution followed by optional semantic review.
- Modify `backend/app/services/orchestrator_factory.py`: wire corpus/graph collaborators.
- Modify `backend/app/api/review_run_contract.py`, `backend/app/api/review_round_runs.py`, and relevant schemas: strict run input, AI/VLM defaults OFF.
- Modify `backend/app/services/ai_review_service.py` and `backend/app/services/vlm_review_service.py`: semantic-only bounded inputs and separate audit output.
- Modify `frontend/src/api.ts`, `frontend/src/api.review-round.test.ts`, and `frontend/src/pages/ProjectDetailPage.tsx`: corpus-aware rounds and OFF defaults.
- Modify candidate presentation helpers/tests to distinguish Graph confirmed, AI reviewed, and Human confirmation required.
- Verify via `.github/workflows/remediation-ci.yml`.

---

### Task 1: Corpus-aware ReviewRound contract with legacy compatibility

**Files:**
- Modify: `backend/app/domain/review_round.py`
- Modify: `backend/app/graph/review_project_repository.py`
- Modify: `backend/app/api/schemas.py`
- Test: `backend/tests/test_review_round_reference_corpus.py`
- Test: `backend/tests/integration/test_p0a_run_input_integrity.py`

**Interfaces:**
- Produces: `ReviewRound.reference_corpus_id` and explicit mode semantics (`reference_corpus` vs `legacy_pdf`).
- Consumes: Plan A READY corpus state.

- [ ] **Step 1: Write new-mode RED tests**

```python
def test_new_round_accepts_body_plus_ready_same_project_corpus(repository, body, ready_corpus):
    round_ = repository.create_review_round(
        project_id=body.project_id,
        body_version_id=body.id,
        reference_corpus_id=ready_corpus.id,
    )
    assert round_.reference_corpus_id == ready_corpus.id
    assert round_.plate_version_id is None
    assert round_.drawing_version_id is None


def test_new_round_rejects_mixed_corpus_and_legacy_visual_versions(repository, body, ready_corpus, plate):
    with pytest.raises(ValueError, match="mixed"):
        repository.create_review_round(
            project_id=body.project_id,
            body_version_id=body.id,
            reference_corpus_id=ready_corpus.id,
            plate_version_id=plate.id,
        )
```

Also cover non-READY and cross-project corpus rejection.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_review_round_reference_corpus.py`
Expected: FAIL because `reference_corpus_id` is not supported.

- [ ] **Step 3: Implement dual-mode creation/read contract**

New mode requires `body_version_id + reference_corpus_id`, validates body ownership/kind and corpus ownership/READY, persists `(round)-[:USES_REFERENCE_CORPUS]->(corpus)`, and does not create plate/drawing version edges. Legacy mode preserves historical complete body/plate/drawing relationships. Mixed mode always rejects. `PRECEDES` remains the only round-order authority.

- [ ] **Step 4: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_review_round_reference_corpus.py tests/integration/test_p0a_run_input_integrity.py tests/test_review_round_repository.py`
Expected: PASS.

```bash
git add backend/app/domain/review_round.py backend/app/graph/review_project_repository.py backend/app/api/schemas.py backend/tests/test_review_round_reference_corpus.py backend/tests/integration/test_p0a_run_input_integrity.py
git commit -m "feat(review): bind rounds to reference corpora"
```

---

### Task 2: Corpus-mode run input resolution

**Files:**
- Modify: `backend/app/services/review_round_execution.py`
- Modify: `backend/app/jobs/run_inputs.py`
- Modify: `backend/app/jobs/worker.py`
- Test: `backend/tests/test_review_round_execution.py`
- Create: `backend/tests/test_run_inputs_reference_corpus.py`
- Test: `backend/tests/test_worker_review_round_authority.py`

**Interfaces:**
- Produces: `ResolvedReviewRoundInputs(body, reference_corpus, mode, compatibility_stage)`.
- Consumers: worker/orchestrator.

- [ ] **Step 1: Write RED tests proving corpus mode never falls back to visual PDFs**

```python
@pytest.mark.asyncio
async def test_corpus_mode_resolves_selected_reference_corpus(...):
    resolved = resolve_review_round_inputs(project_repo, "p1", "r1")
    assert resolved.mode == "reference_corpus"
    assert resolved.reference_corpus.id == "c1"
```

Add tests that invalid corpus fails before proofreading and legacy rounds still resolve their old visual DocumentVersions.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_review_round_execution.py tests/test_run_inputs_reference_corpus.py`
Expected: FAIL until mode-aware input resolution exists.

- [ ] **Step 3: Implement explicit worker mode branching**

Corpus mode resolves body pages normally, gets visual indexes only from the selected corpus graph, and never invokes `_resolve_asset_pdf_path` for plate/drawing authority. Legacy mode retains the existing visual PDF compatibility path.

- [ ] **Step 4: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_review_round_execution.py tests/test_run_inputs_reference_corpus.py tests/test_worker_review_round_authority.py tests/test_analysis_worker.py`
Expected: PASS.

```bash
git add backend/app/services/review_round_execution.py backend/app/jobs/run_inputs.py backend/app/jobs/worker.py backend/tests/test_review_round_execution.py backend/tests/test_run_inputs_reference_corpus.py backend/tests/test_worker_review_round_authority.py
git commit -m "feat(review): resolve corpus-mode run inputs"
```

---

### Task 3: Deterministic CorpusObjectLinker

**Files:**
- Create: `backend/app/services/corpus_object_linker.py`
- Modify: `backend/app/graph/reference_corpus_repository.py`
- Test: `backend/tests/test_corpus_object_linker.py`
- Test: `backend/tests/integration/test_reference_corpus_real_neo4j.py`

**Interfaces:**
- Produces: `CorpusObjectLinker.link(project_id, corpus_id, objects) -> LinkResult`.
- Consumes: corpus visual descriptors and body `ArchaeologyObjectData`.

- [ ] **Step 1: Write RED uniqueness tests**

```python
def test_unique_strong_identifier_creates_depicts_link(linker):
    result = linker.link("p1", "c1", [object_6_tomb()])
    assert result.created


def test_multiple_strong_matches_remain_ambiguous(linker):
    result = linker.link("p1", "c1", duplicate_named_objects())
    assert result.created == []
    assert result.ambiguous
```

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_corpus_object_linker.py`
Expected: FAIL.

- [ ] **Step 3: Implement deterministic linking**

Reuse existing strong-identifier normalization semantics but scope all visual queries to `project_id + corpus_id`. Weak numeric matches alone never create `DEPICTS`. Persist only unique strong matches; ambiguous assets remain explicit review metadata.

- [ ] **Step 4: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_corpus_object_linker.py tests/test_depicts_links.py tests/integration/test_reference_corpus_real_neo4j.py`
Expected: PASS.

```bash
git add backend/app/services/corpus_object_linker.py backend/app/graph/reference_corpus_repository.py backend/tests/test_corpus_object_linker.py backend/tests/integration/test_reference_corpus_real_neo4j.py
git commit -m "feat(graph): link corpus visuals to body objects"
```

---

### Task 4: GraphReviewRepository and scoped resolution evidence

**Files:**
- Create: `backend/app/graph/graph_review_repository.py`
- Test: `backend/tests/test_graph_review_repository.py`
- Create: `backend/tests/integration/test_graph_first_review_real_neo4j.py`

**Interfaces:**
- Produces: `validate_corpus_integrity`, `resolve_reference`, `visuals_for_object`, `references_for_object`, `save_resolution_evidence`.
- Consumers: Task 5 graph rules.

- [ ] **Step 1: Write repository RED tests**

Cover selected-corpus resolution, V1/V2 separation, missing/ambiguous status, and cross-project exclusion.

```python
def test_resolution_is_corpus_scoped(repository):
    v1 = repository.resolve_reference("p1", "c1", "plate", "45")
    v2 = repository.resolve_reference("p1", "c2", "plate", "45")
    assert v1.target_id != v2.target_id
```

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_graph_review_repository.py`
Expected: FAIL.

- [ ] **Step 3: Implement focused Cypher methods**

Rule modules contain no Cypher. Persist resolution evidence scoped by both `analysisRunId` and `referenceCorpusId` so reruns and corpus revisions cannot overwrite each other's meaning.

- [ ] **Step 4: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_graph_review_repository.py tests/integration/test_graph_first_review_real_neo4j.py`
Expected: PASS.

```bash
git add backend/app/graph/graph_review_repository.py backend/tests/test_graph_review_repository.py backend/tests/integration/test_graph_first_review_real_neo4j.py
git commit -m "feat(graph): add corpus-scoped review queries"
```

---

### Task 5: Four-layer deterministic graph rule engine

**Files:**
- Create: `backend/app/services/graph_rules/__init__.py`
- Create: `backend/app/services/graph_rules/models.py`
- Create: `backend/app/services/graph_rules/corpus_integrity.py`
- Create: `backend/app/services/graph_rules/reference_resolution.py`
- Create: `backend/app/services/graph_rules/visual_coverage.py`
- Create: `backend/app/services/graph_rules/visual_consistency.py`
- Create: `backend/app/services/graph_rules/semantic_escalation.py`
- Create: `backend/app/services/graph_rules/engine.py`
- Test: `backend/tests/test_graph_rule_engine.py`

**Interfaces:**
- Produces: `GraphRuleFinding` and `GraphRuleEngine.run(...) -> list[GraphRuleFinding]`.
- Consumes: Task 4 repository.

- [ ] **Step 1: Define/test the finding model**

```python
@dataclass(frozen=True, slots=True)
class GraphRuleFinding:
    rule_code: str
    severity: str
    source_block_id: str | None
    archaeology_object_id: str | None
    reference_corpus_id: str
    canonical_target_ids: tuple[str, ...]
    original_text: str | None
    proposed_text: str | None
    rationale: str
    evidence_ids: tuple[str, ...]
    requires_ai: bool = False
```

- [ ] **Step 2: L1 corpus-integrity RED/GREEN**

Hard failures: non-READY corpus, duplicate visual number, missing mandatory provenance/artifact, cross-project relationship, empty canonical graph. These stop review rather than becoming ordinary correction candidates.

- [ ] **Step 3: L2 reference-resolution RED/GREEN**

Resolve only selected corpus. Emit deterministic missing/invalid findings; graph ambiguity cannot be delegated to AI to choose identity.

- [ ] **Step 4: L3 coverage/consistency RED/GREEN**

Preserve approved semantics:
- missing visual reference;
- blank placeholder fill;
- wrong-target replacement only when current target is proven wrong/unresolved and exactly one correct same-type target exists;
- multiple targets => `proposed_text=None`;
- multiple insertion locations => `proposed_text=None`;
- all candidates remain pending human review.

- [ ] **Step 5: L4 semantic escalation RED/GREEN**

Emit `SEMANTIC_REVIEW_REQUIRED` with `requires_ai=True` only for geometry/orientation/nuanced semantic claims the graph cannot prove. With AI/VLM disabled this remains a human-review finding and does not fail the run.

- [ ] **Step 6: Run full graph-rule GREEN and commit**

Run: `cd backend && pytest -q tests/test_graph_rule_engine.py tests/test_visual_reference_coverage.py tests/test_bidirectional_coverage_rule_engine.py`
Expected: PASS.

```bash
git add backend/app/services/graph_rules backend/tests/test_graph_rule_engine.py
git commit -m "feat(review): add graph-first rule engine"
```

---

### Task 6: Integrate graph rules into existing strict review without duplicate candidates

**Files:**
- Modify: `backend/app/services/strict_rule_engine.py`
- Modify: `backend/app/services/proofreading_orchestrator.py`
- Modify: `backend/app/services/orchestrator_factory.py`
- Modify: `backend/app/services/visual_reference_coverage.py` only where corpus mode delegates to the new graph engine.
- Test: `backend/tests/test_graph_first_orchestrator.py`
- Test: `backend/tests/test_bidirectional_coverage_rule_engine.py`

**Interfaces:**
- Produces: graph-first candidate generation for corpus rounds and unchanged legacy compatibility behavior.
- Consumes: Tasks 3-5.

- [ ] **Step 1: Write orchestration RED tests**

```python
@pytest.mark.asyncio
async def test_graph_only_run_completes_with_ai_and_vlm_disabled(orchestrator):
    result = await orchestrator.run_proofreading(..., enable_ai_review=False, enable_vlm=False)
    assert result.status == "completed"
    assert any(c.rule_category == "visual_reference_missing" for c in result.candidates)
```

Also assert a blank reference is not emitted once by generic regex and again by graph coverage.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_graph_first_orchestrator.py tests/test_bidirectional_coverage_rule_engine.py`
Expected: FAIL until graph engine is wired.

- [ ] **Step 3: Integrate in strict order**

Body parse/object resolution -> corpus object linker -> graph rules -> stable-fingerprint candidate conversion -> optional semantic review. Corpus mode uses the new graph engine; legacy mode retains the old compatibility path. Deterministic graph findings never need AI to become candidates.

- [ ] **Step 4: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_graph_first_orchestrator.py tests/test_bidirectional_coverage_rule_engine.py tests/test_visual_reference_coverage.py tests/test_proofreading_orchestrator.py tests/test_production_orchestrator_assembly.py`
Expected: PASS.

```bash
git add backend/app/services/strict_rule_engine.py backend/app/services/proofreading_orchestrator.py backend/app/services/orchestrator_factory.py backend/app/services/visual_reference_coverage.py backend/tests/test_graph_first_orchestrator.py
git commit -m "feat(review): run graph authority before optional ai"
```

---

### Task 7: Optional AI/VLM escalation with OFF defaults and non-fatal failures

**Files:**
- Create: `backend/app/domain/ai_review_finding.py`
- Modify: `backend/app/api/review_run_contract.py`
- Modify: `backend/app/api/review_round_runs.py`
- Modify: `backend/app/services/ai_review_service.py`
- Modify: `backend/app/services/vlm_review_service.py`
- Test: `backend/tests/test_optional_ai_review.py`
- Test: `backend/tests/test_review_round_run_contract.py`
- Test: `backend/tests/test_strict_review_round_run_api.py`
- Test: `backend/tests/test_ai_review_service.py`
- Test: `backend/tests/test_vlm_review_service.py`

**Interfaces:**
- Produces: `AIReviewFindingData`, default OFF flags, semantic-only AI/VLM dispatch, warning-only optional failures.

- [ ] **Step 1: Write default-OFF RED tests**

```python
def test_run_flags_default_off():
    payload = ReviewRunRequest(review_round_id="r1")
    assert payload.enable_ai_review is False
    assert payload.enable_vlm is False
```

Add tests that deterministic findings are not sent to model services; semantic findings are dispatched only when enabled; an AI/VLM timeout preserves all graph findings and returns warnings rather than a core failure.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_optional_ai_review.py tests/test_review_round_run_contract.py tests/test_strict_review_round_run_api.py`
Expected: FAIL because current defaults/dispatch differ.

- [ ] **Step 3: Implement isolated AI audit model and bounded review bundle**

`AIReviewFindingData` stores provider/model/prompt_version/input_hash/confidence/verdict/rationale/proposed_text and links to candidate/evidence/object IDs. The review bundle contains source text, already-resolved canonical target/render metadata, graph evidence/path, deterministic finding, and requested checks only.

- [ ] **Step 4: Make optional failures non-fatal**

Graph-successful runs complete with optional-review warnings on timeout/rate limit/unavailability. Body/corpus/graph failures remain fatal.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_optional_ai_review.py tests/test_review_round_run_contract.py tests/test_strict_review_round_run_api.py tests/test_ai_review_service.py tests/test_vlm_review_service.py tests/test_graph_grounded_ai.py`
Expected: PASS.

```bash
git add backend/app/domain/ai_review_finding.py backend/app/api/review_run_contract.py backend/app/api/review_round_runs.py backend/app/services/ai_review_service.py backend/app/services/vlm_review_service.py backend/tests/test_optional_ai_review.py
git commit -m "feat(ai): make semantic review optional and isolated"
```

---

### Task 8: Corpus-mode ReviewRound and Graph-first UI

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.review-round.test.ts`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Create: `frontend/src/pages/ProjectDetailPage.test.tsx` if no focused page test exists.
- Modify: `frontend/src/candidateIntent.ts`
- Modify: `frontend/src/candidateIntent.test.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces: READY-corpus selection, corpus-mode round creation, and OFF-by-default optional deep-review switches.
- Consumes: Plan A corpus API and Tasks 1/7 backend contracts.

- [ ] **Step 1: Write frontend RED tests for new payload/defaults**

Assert round creation sends `body_version_id + reference_corpus_id + notes` only, and AI/VLM controls are unchecked by default.

- [ ] **Step 2: Run RED**

Run: `cd frontend && npm test -- --run src/api.review-round.test.ts src/pages/ProjectDetailPage.test.tsx`
Expected: FAIL on old plate/drawing contract and ON defaults.

- [ ] **Step 3: Implement corpus selection and simplified round creation**

New rounds select body PDF and a READY ReferenceCorpus. Remove new `reusePlate/reuseDrawing/customPlate/customDrawing` controls for corpus-mode creation. Legacy rounds display historical visual DocumentVersion IDs read-only.

- [ ] **Step 4: Make execution copy graph-first**

Show `Graph 기반 구조/참조 검수` as always enabled and `AI 문맥 심화검수`, `VLM 도판·도면 시각 심화검수` as optional unchecked controls.

- [ ] **Step 5: Distinguish finding provenance explicitly**

Render Graph confirmed / AI reviewed / Human confirmation required from explicit metadata rather than free-form text inference.

- [ ] **Step 6: Run frontend GREEN and commit**

Run: `cd frontend && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

```bash
git add frontend/src/api.ts frontend/src/api.review-round.test.ts frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.test.tsx frontend/src/candidateIntent.ts frontend/src/candidateIntent.test.ts frontend/src/styles.css
git commit -m "feat(ui): make review rounds graph first"
```

---

### Task 9: Full graph-first E2E, regression suite, CI and push gate

**Files:**
- Create: `backend/tests/test_graph_first_review_e2e.py`
- Test: `backend/tests/integration/test_graph_first_review_real_neo4j.py`
- Test: `backend/tests/integration/test_bidirectional_visual_reference_real_neo4j.py`
- Modify: `.github/workflows/remediation-ci.yml` only if current commands omit new tests.

**Interfaces:**
- Produces: final verification evidence for the feature branch.

- [ ] **Step 1: Add end-to-end graph-only scenario**

Exercise READY ReferenceCorpus -> body PDF -> ReviewRound(body+corpus) -> run AI/VLM OFF -> reference resolution -> one missing ref + one wrong ref -> pending candidates. Assert no AI/VLM collaborator call and corpus-scoped resolution evidence.

- [ ] **Step 2: Run focused graph-first backend tests**

Run all Task 1-7 new test files together.
Expected: PASS.

- [ ] **Step 3: Run complete backend hermetic suite**

Run the exact backend command from `.github/workflows/remediation-ci.yml`.
Expected: all existing and new hermetic tests PASS; only known non-failing warnings remain.

- [ ] **Step 4: Run real Neo4j suite**

Run the exact Neo4j E2E command from `.github/workflows/remediation-ci.yml`, including reference-corpus and graph-first integration tests.
Expected: PASS.

- [ ] **Step 5: Run complete frontend verification**

Run: `cd frontend && npm ci && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

- [ ] **Step 6: Push and inspect fresh GitHub Actions**

Push `feature/source-provenance-remediation-20260818`, then inspect the workflow run attached to the fresh head SHA. Do not claim completion until required backend hermetic, frontend, and real Neo4j jobs are green.

- [ ] **Step 7: Record final evidence**

Record feature head SHA, workflow run ID, per-job test counts, and warnings. Keep PR #1 draft and unmerged unless the user separately asks otherwise.
