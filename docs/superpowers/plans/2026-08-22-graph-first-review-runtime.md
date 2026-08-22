# Graph-First Review Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ReviewRound execute against body PDF + READY ReferenceCorpus, perform deterministic graph review as the authority, and invoke LLM/VLM only for explicitly escalated semantic findings with both optional features default OFF.

**Architecture:** New ReviewRounds bind exactly one body `DocumentVersion` and one immutable `ReferenceCorpus`; legacy plate/drawing-PDF rounds remain compatibility-only. The worker resolves the selected corpus, links body archaeology objects to corpus visuals only through deterministic strong identifiers, executes a four-layer graph rule engine, and emits pending candidates. Optional AI/VLM receives only semantic-review bundles and cannot mutate canonical graph identity or relationships.

**Tech Stack:** Python 3.12, FastAPI, Neo4j 5.26, RQ/Redis, existing proofreading orchestrator/repositories, React/TypeScript/Vitest.

**Spec:** `docs/superpowers/specs/2026-08-22-graph-first-reference-corpus-review-design.md`

## Global Constraints

- ReviewRound remains the sole public `/runs` input authority.
- New rounds use body PDF + READY same-project `ReferenceCorpus` only.
- Mixed new/legacy authority is rejected.
- Neo4j canonical graph and deterministic rules are authoritative; AI/VLM cannot create or mutate identity, `RESOLVES_TO`, `DEPICTS`, corpus membership, or provenance.
- Core review completes with `enable_ai_review=false` and `enable_vlm=false`.
- AI/VLM defaults are OFF in API/client/UI.
- Ambiguous graph identity fails closed; automatic proposed text requires unique target, unique body edit location, and complete provenance.
- All findings remain `pending_review` until human decision.
- Legacy ReviewRounds remain readable/executable through explicit compatibility code until later migration removal.

---

## File Structure

- Modify `backend/app/domain/review_round.py`: add `reference_corpus_id` while retaining legacy fields for compatibility.
- Modify `backend/app/graph/review_project_repository.py`: create/resolve new corpus rounds and reject mixed authority.
- Modify `backend/app/services/review_round_execution.py`: resolve body + corpus and expose explicit mode.
- Modify `backend/app/jobs/run_inputs.py`: stop PDF fallback for corpus-mode plate/drawing authority.
- Modify `backend/app/jobs/worker.py`: branch corpus-mode vs legacy-mode input resolution.
- Create `backend/app/services/corpus_object_linker.py`: deterministic visual-to-object linking scoped to selected corpus/run.
- Create `backend/app/graph/graph_review_repository.py`: graph queries for integrity, corpus-scoped reference resolution, coverage, consistency, and scoped resolution evidence.
- Create `backend/app/services/graph_rules/corpus_integrity.py`.
- Create `backend/app/services/graph_rules/reference_resolution.py`.
- Create `backend/app/services/graph_rules/visual_coverage.py`.
- Create `backend/app/services/graph_rules/visual_consistency.py`.
- Create `backend/app/services/graph_rules/semantic_escalation.py`.
- Create `backend/app/services/graph_rules/engine.py`.
- Modify `backend/app/services/strict_rule_engine.py`: compose the graph rule engine while preserving existing candidate intent compatibility.
- Modify `backend/app/services/proofreading_orchestrator.py`: run graph-first review and optional semantic escalation.
- Modify `backend/app/services/orchestrator_factory.py`: wire corpus/graph repositories and optional AI/VLM collaborators.
- Modify `backend/app/api/review_run_contract.py`, `backend/app/api/review_round_runs.py`, and schemas: default AI/VLM OFF and keep run input strict.
- Modify `frontend/src/api.ts` and `frontend/src/api.review-round.test.ts`: corpus-aware ReviewRound contract and OFF defaults.
- Modify `frontend/src/pages/ProjectDetailPage.tsx`: choose READY corpus, create new corpus-mode round, and show graph review always enabled with optional AI/VLM switches OFF.
- Modify candidate UI helpers to distinguish Graph confirmed / AI reviewed / Human confirmation required.
- Test with new backend unit/integration tests and frontend ReviewRound/component tests.

---

### Task 1: Corpus-aware ReviewRound contract with legacy compatibility

**Files:**
- Modify: `backend/app/domain/review_round.py`
- Modify: `backend/app/graph/review_project_repository.py`
- Modify: `backend/app/api/schemas.py`
- Test: `backend/tests/test_review_round_reference_corpus.py`
- Test: `backend/tests/integration/test_p0a_run_input_integrity.py`

**Interfaces:**
- Produces: `ReviewRound.reference_corpus_id`, mode inference (`reference_corpus` vs `legacy_pdf`), and repository validation.
- Consumes: Plan A READY corpus repository state.

- [ ] **Step 1: Write RED tests for the new authority contract**

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

Also cover non-READY corpus and cross-project corpus rejection.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_review_round_reference_corpus.py`
Expected: FAIL because ReviewRound/repository lack `reference_corpus_id`.

- [ ] **Step 3: Implement the dual-mode repository contract**

New mode requires `body_version_id + reference_corpus_id`; legacy mode permits the historical body/plate/drawing set only for existing compatibility paths. Mixed mode is always rejected. Corpus lookup must prove same project and `status='ready'` before the round node is created.

Persist `(round)-[:USES_REFERENCE_CORPUS]->(corpus)` and keep existing `PRECEDES` semantics untouched.

- [ ] **Step 4: Run GREEN**

Run: `cd backend && pytest -q tests/test_review_round_reference_corpus.py tests/integration/test_p0a_run_input_integrity.py`
Expected: PASS.

- [ ] **Step 5: Commit**

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
- Test: `backend/tests/test_run_inputs_reference_corpus.py`

**Interfaces:**
- Produces: `ResolvedReviewRoundInputs(body, reference_corpus, mode, compatibility_stage)`.
- Consumers: worker/orchestrator.

- [ ] **Step 1: Write RED tests proving corpus mode never falls back to visual PDFs**

```python
@pytest.mark.asyncio
async def test_corpus_mode_uses_graph_indexes_not_plate_pdf_fallback(...):
    resolved = await resolve_review_round_inputs(...)
    assert resolved.mode == "reference_corpus"
    assert resolved.reference_corpus.id == corpus.id
```

Add a test that missing/invalid selected corpus fails before proofreading and that legacy round still resolves old plate/drawing versions.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_review_round_execution.py tests/test_run_inputs_reference_corpus.py`
Expected: FAIL.

- [ ] **Step 3: Implement explicit mode branching**

In `worker.py`, corpus mode resolves body pages normally, loads Plate/Drawing indexes only from the selected corpus graph, and never calls `_resolve_asset_pdf_path` for visual authority. Keep the existing PDF path only inside the legacy branch.

- [ ] **Step 4: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_review_round_execution.py tests/test_run_inputs_reference_corpus.py tests/test_worker_review_round.py`
Expected: PASS.

```bash
git add backend/app/services/review_round_execution.py backend/app/jobs/run_inputs.py backend/app/jobs/worker.py backend/tests/test_review_round_execution.py backend/tests/test_run_inputs_reference_corpus.py
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
- Consumes: canonical visual descriptors from Plan A and body `ArchaeologyObjectData`.

- [ ] **Step 1: Write RED uniqueness tests**

```python
def test_unique_strong_identifier_creates_depicts_link(linker):
    result = linker.link("p1", "c1", [object_6_tomb()])
    assert result.created == [("PlatePanel", "plate-panel:c1:45:1", object_6_tomb().object_id)]


def test_multiple_strong_matches_remain_ambiguous(linker):
    result = linker.link("p1", "c1", duplicate_named_objects())
    assert result.created == []
    assert result.ambiguous
```

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_corpus_object_linker.py`
Expected: FAIL.

- [ ] **Step 3: Implement deterministic linking**

Reuse the existing strong-identifier normalization semantics from canonical matching, but make all queries corpus scoped. A weak numeric match alone must never create `DEPICTS`. Persist only unique deterministic links and return ambiguity metadata for later human/semantic review.

- [ ] **Step 4: Run unit + Neo4j GREEN and commit**

Run: `cd backend && pytest -q tests/test_corpus_object_linker.py tests/integration/test_reference_corpus_real_neo4j.py`
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
- Test: `backend/tests/integration/test_graph_first_review_real_neo4j.py`

**Interfaces:**
- Produces query methods: `validate_corpus_integrity`, `resolve_reference`, `visuals_for_object`, `references_for_object`, `save_resolution_evidence`.
- Consumers: graph rules.

- [ ] **Step 1: Write RED repository tests**

Cover:
- resolving `Reference(type='plate', number='45')` only inside selected corpus;
- V1/V2 results never overwrite each other;
- missing and ambiguous statuses;
- cross-project target exclusion.

```python
def test_resolution_is_corpus_scoped(repository):
    v1 = repository.resolve_reference("p1", "c1", "plate", "45")
    v2 = repository.resolve_reference("p1", "c2", "plate", "45")
    assert v1.target_id != v2.target_id
```

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_graph_review_repository.py`
Expected: FAIL.

- [ ] **Step 3: Implement Cypher behind focused methods**

No rule module may embed Cypher. Save `RESOLVES_TO` evidence with `analysisRunId` and `referenceCorpusId` properties or an equivalent scoped evidence node/relationship that preserves both run and corpus identity.

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

- [ ] **Step 1: Define and test the shared finding model**

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

Run: `cd backend && pytest -q tests/test_graph_rule_engine.py::test_finding_model`
Expected: RED before implementation, GREEN after model creation.

- [ ] **Step 2: Add L1 corpus-integrity rule tests and implementation**

Hard failures include duplicate visual numbers, missing required provenance/artifacts, cross-project edges, empty graph, or non-READY corpus. These stop graph review rather than becoming ordinary correction candidates.

- [ ] **Step 3: Add L2 reference-resolution tests and implementation**

Emit deterministic findings for `MISSING`/`INVALID`; resolved references persist scoped evidence. Canonical ambiguity must not be delegated to AI for identity selection.

- [ ] **Step 4: Add L3 coverage/consistency tests and implementation**

Cover the accepted semantics already implemented previously:
- missing visual reference;
- blank placeholder fill;
- wrong-target replacement only when the existing reference is proven wrong/unresolved and exactly one correct same-type target exists;
- multiple targets -> `proposed_text=None`;
- multiple insertion locations -> `proposed_text=None`.

- [ ] **Step 5: Add L4 semantic escalation tests and implementation**

Emit `SEMANTIC_REVIEW_REQUIRED` with `requires_ai=True` for visual geometry/orientation/nuanced claims the graph cannot prove. With AI disabled this remains a pending human-review finding.

- [ ] **Step 6: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_graph_rule_engine.py`
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
- Modify: `backend/app/services/visual_reference_coverage.py` as needed to delegate corpus-mode behavior rather than duplicate it.
- Test: `backend/tests/test_graph_first_orchestrator.py`
- Test: `backend/tests/test_bidirectional_coverage_rule_engine.py`

**Interfaces:**
- Produces graph-first candidate generation while preserving legacy behavior.
- Consumes Tasks 3-5.

- [ ] **Step 1: Write RED orchestration tests**

```python
@pytest.mark.asyncio
async def test_graph_only_run_completes_with_ai_and_vlm_disabled(orchestrator):
    result = await orchestrator.run_proofreading(..., enable_ai_review=False, enable_vlm=False)
    assert result.status == "completed"
    assert any(c.rule_category == "visual_reference_missing" for c in result.candidates)
```

Also assert blank-reference findings are not duplicated by generic regex and graph coverage paths.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_graph_first_orchestrator.py tests/test_bidirectional_coverage_rule_engine.py`
Expected: FAIL until graph engine is wired.

- [ ] **Step 3: Integrate in strict order**

Run body parse/object resolution -> corpus object linking -> graph rules -> candidate conversion -> optional semantic review. Corpus-mode uses the new engine; legacy mode keeps the existing compatibility path. Deduplicate by stable finding fingerprint.

- [ ] **Step 4: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_graph_first_orchestrator.py tests/test_bidirectional_coverage_rule_engine.py tests/test_visual_reference_coverage.py`
Expected: PASS.

```bash
git add backend/app/services/strict_rule_engine.py backend/app/services/proofreading_orchestrator.py backend/app/services/orchestrator_factory.py backend/app/services/visual_reference_coverage.py backend/tests/test_graph_first_orchestrator.py backend/tests/test_bidirectional_coverage_rule_engine.py
git commit -m "feat(review): run graph authority before optional ai"
```

---

### Task 7: Optional AI/VLM escalation with OFF defaults and non-fatal failures

**Files:**
- Modify: `backend/app/api/review_run_contract.py`
- Modify: `backend/app/api/review_round_runs.py`
- Modify: `backend/app/services/ai_review_service.py`
- Modify: `backend/app/services/vlm_review_service.py`
- Modify: `backend/app/domain/review_models.py` or create focused AI finding model if existing model cannot represent audit fields cleanly.
- Test: `backend/tests/test_optional_ai_review.py`
- Test: `backend/tests/test_review_round_runs.py`

**Interfaces:**
- Produces default OFF API flags, semantic-only AI/VLM dispatch, auditable AI findings, and warning-only optional failures.

- [ ] **Step 1: Write RED default/off tests**

```python
def test_run_flags_default_off():
    payload = ReviewRunRequest(review_round_id="r1")
    assert payload.enable_ai_review is False
    assert payload.enable_vlm is False
```

Add tests that deterministic findings are never sent to AI, semantic findings are sent only when enabled, and an AI timeout does not erase/abort graph findings.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_optional_ai_review.py tests/test_review_round_runs.py`
Expected: FAIL because current defaults are ON/dispatch is broader.

- [ ] **Step 3: Implement semantic-only dispatch and audit record**

Build a bounded AI review bundle containing source text, object identity, selected canonical target IDs/render metadata, graph path/evidence, deterministic finding, and requested checks. Store model/provider/promptVersion/inputHash/confidence/verdict/rationale/proposedText separately from canonical nodes.

- [ ] **Step 4: Make optional failures non-fatal**

Graph-successful runs finish with warnings when AI/VLM times out, rate-limits, or is unavailable. Core corpus/body/graph failures remain fatal.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_optional_ai_review.py tests/test_review_round_runs.py`
Expected: PASS.

```bash
git add backend/app/api/review_run_contract.py backend/app/api/review_round_runs.py backend/app/services/ai_review_service.py backend/app/services/vlm_review_service.py backend/app/domain/review_models.py backend/tests/test_optional_ai_review.py backend/tests/test_review_round_runs.py
git commit -m "feat(ai): make semantic review optional and isolated"
```

---

### Task 8: Corpus-mode ReviewRound and Graph-first UI

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.review-round.test.ts`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Create or modify: `frontend/src/pages/ProjectDetailPage.test.tsx`
- Modify: `frontend/src/candidateIntent.ts`
- Modify: `frontend/src/candidateIntent.test.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces READY-corpus selection, corpus-mode round creation, and OFF-by-default semantic-review switches.
- Consumes Plan A corpus API and Task 1/7 backend contracts.

- [ ] **Step 1: Write frontend RED tests for the new creation payload/defaults**

```ts
it('creates a round with body + reference corpus and no visual document versions', async () => {
  // assert request body includes body_version_id/reference_corpus_id only
})

it('defaults AI and VLM deep review to off', () => {
  // render page and assert both checkboxes are unchecked
})
```

- [ ] **Step 2: Run RED**

Run: `cd frontend && npm test -- --run src/api.review-round.test.ts src/pages/ProjectDetailPage.test.tsx`
Expected: FAIL on old plate/drawing round contract and ON defaults.

- [ ] **Step 3: Implement corpus selection and simplified round modal**

New round UI selects body PDF and READY ReferenceCorpus. Remove new `reusePlate/reuseDrawing/customPlate/customDrawing` authority controls from corpus-mode creation. Legacy rounds may display their historic assets read-only.

- [ ] **Step 4: Make execution copy graph-first**

Display `Graph 기반 구조/참조 검수` as always enabled and show `AI 문맥 심화검수`, `VLM 도판·도면 시각 심화검수` as optional unchecked controls.

- [ ] **Step 5: Distinguish finding provenance**

Candidate UI must render Graph confirmed / AI reviewed / Human confirmation required from explicit finding metadata, not infer authority from free-form text.

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
- Test: `backend/tests/integration/test_graph_first_review_real_neo4j.py`
- Test: `backend/tests/integration/test_bidirectional_visual_reference_real_neo4j.py`
- Test: `backend/tests/test_graph_first_review_e2e.py`
- Modify `.github/workflows/review-remediation-ci.yml` only if current commands omit the new tests.

**Interfaces:**
- Produces final verification evidence for the feature branch.

- [ ] **Step 1: Add E2E scenario**

Exercise:
1. project exists;
2. READY ReferenceCorpus from fixture INDD/Links/AI build;
3. upload body PDF;
4. create ReviewRound(body + corpus);
5. run with AI/VLM OFF;
6. resolve references against selected corpus;
7. detect one missing reference and one wrong reference;
8. assert all generated candidates are pending human review;
9. assert no AI collaborator was called.

- [ ] **Step 2: Run focused graph-first backend tests**

Run the Task 1-7 test files together.
Expected: PASS.

- [ ] **Step 3: Run complete backend hermetic suite**

Run the repository's existing backend CI test command.
Expected: all existing and new hermetic tests PASS; pre-existing warnings only.

- [ ] **Step 4: Run real Neo4j suite**

Run the repository's existing Neo4j E2E command including both reference-corpus and graph-first integration tests.
Expected: PASS.

- [ ] **Step 5: Run complete frontend verification**

Run: `cd frontend && npm ci && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

- [ ] **Step 6: Push feature branch and inspect fresh GitHub Actions**

```bash
git push origin feature/source-provenance-remediation-20260818
```

Wait for the fresh workflow run associated with the pushed head SHA. Inspect backend hermetic, frontend, and real Neo4j jobs. Do not claim completion until every required job is green.

- [ ] **Step 7: Final verification record**

Record current branch head SHA, workflow run ID, per-job pass counts, and any non-failing warnings. Keep PR #1 draft unless the user separately asks to merge or mark ready.
