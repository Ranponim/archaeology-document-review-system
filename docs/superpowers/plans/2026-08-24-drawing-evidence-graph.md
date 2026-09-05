# Drawing Evidence Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve PDF-compatible AI drawing identities from independent body/context/AI evidence, persist explainable candidate evidence in Neo4j, and promote only direct or uniquely corroborated candidates to canonical `Drawing`.

**Architecture:** Keep `DrawingIdentityResolver` as the low-level direct/filename extractor. Add a deterministic `DrawingEvidenceGraphResolver` that normalizes body and AI context, creates/scorers candidates, performs corpus-wide one-to-one assignment, and returns canonical drawings plus inspectable candidates/evidence. Extend `ReferenceCorpusRepository` to read body drawing contexts and persist corpus-scoped `DrawingCandidate`/`ResolutionEvidence`/`ContextEntity` nodes before canonical promotion.

**Tech Stack:** Python 3.12+, PyMuPDF, Neo4j 5.x, NetworkX 3.x for deterministic maximum-weight bipartite assignment, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-24-drawing-evidence-graph-design.md`

## Global Constraints

- Adobe InDesign/Illustrator, COM, and ExtendScript are not required for this path.
- Filename-only evidence must remain `heuristic`; it can never produce `derived_verified` by itself.
- A non-direct promotion requires at least two independent evidence families, including `body_context` or `semantic_content`.
- Hard contradictions, non-unique winners, insufficient score margin, or one-to-many assignment conflicts remain unresolved/ambiguous.
- Canonical `Drawing` and `DERIVED_FROM` edges may be created only for `direct` or `derived_verified` identity.
- Candidate/evidence IDs must be deterministic and corpus-scoped so reruns are idempotent.
- Existing Adobe-manifest and plate/JPG behavior must remain compatible.

---

## File Structure

- Create `backend/app/domain/drawing_evidence.py` — immutable candidate/evidence/context/result models.
- Create `backend/app/services/drawing_context_normalizer.py` — deterministic Korean archaeology context extraction and lexical normalization.
- Create `backend/app/services/drawing_evidence_graph_resolver.py` — candidate generation, scoring, promotion gate, and global one-to-one assignment.
- Modify `backend/app/services/drawing_identity_resolver.py` — expose reusable direct/filename signals without changing current public behavior.
- Modify `backend/app/graph/reference_corpus_repository.py` — query body drawing context and persist candidate/evidence/context graph.
- Modify `backend/app/services/reference_corpus_service.py` — run graph resolver for all AI assets, persist reasoning graph, pass only verified canonical drawings to existing save path, extend diagnostics.
- Modify `backend/pyproject.toml` — add `networkx>=3.2,<4.0`.
- Create `backend/tests/test_drawing_context_normalizer.py`.
- Create `backend/tests/test_drawing_evidence_graph_resolver.py`.
- Modify `backend/tests/test_reference_corpus_repository.py`.
- Modify `backend/tests/test_adobe_free_reference_corpus.py`.
- Create `backend/tests/integration/test_drawing_evidence_graph_neo4j.py`.
- Create `tools/evaluate_drawing_evidence_graph.py` — read-only `/src` evaluator for blinded 35-file and full-56 reruns.
- Create `docs/local_drawing_evidence_graph_revalidation.md` — exact local rerun command and metric contract.

---

### Task 1: Evidence domain and deterministic context normalizer

**Files:**
- Create: `backend/app/domain/drawing_evidence.py`
- Create: `backend/app/services/drawing_context_normalizer.py`
- Test: `backend/tests/test_drawing_context_normalizer.py`

**Interfaces:**
- Produces `ContextFact(kind: str, value: str, normalized_value: str, source_kind: str, source_node_id: str | None, source_sha256: str | None)`.
- Produces `NormalizedDrawingContext(raw_text: str, tokens: tuple[str, ...], facts: tuple[ContextFact, ...])`.
- Produces `DrawingCandidateEvidence`, `DrawingCandidateResult`, and `DrawingEvidenceResolution` immutable records used by later tasks.
- `DrawingContextNormalizer.normalize(text: str, *, source_kind: str, source_node_id: str | None = None, source_sha256: str | None = None) -> NormalizedDrawingContext`.

- [ ] **Step 1: Write failing normalizer tests**

Cover exact normalization for `2지점`, `S1 E1`, `북동`, `토층`, `4호 수혈`, section labels such as `A-A'`, punctuation/space normalization, and no invented facts from unrelated numeric text.

- [ ] **Step 2: Run focused test and verify RED**

Run: `pytest -q tests/test_drawing_context_normalizer.py`
Expected: import/module failure.

- [ ] **Step 3: Implement immutable domain records and deterministic normalizer**

Use regex/token rules only. Preserve raw text; normalize case/spacing; keep a small explicit archaeology vocabulary for direction/drawing type/feature classes; do not call an LLM.

- [ ] **Step 4: Run focused test and verify GREEN**

Run: `pytest -q tests/test_drawing_context_normalizer.py`
Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add drawing evidence context model`

---

### Task 2: Candidate scoring, promotion gate, and one-to-one assignment

**Files:**
- Create: `backend/app/services/drawing_evidence_graph_resolver.py`
- Modify: `backend/app/services/drawing_identity_resolver.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_drawing_evidence_graph_resolver.py`

**Interfaces:**
- `BodyDrawingContext(number: str, raw_texts: tuple[str, ...], source_node_ids: tuple[str, ...])` in `drawing_evidence.py`.
- `DrawingSourceContext(asset: OriginalAssetData, path: Path)` input wrapper.
- `DrawingEvidenceGraphResolver.resolve(*, corpus_id: str, sources: list[DrawingSourceContext], body_contexts: list[BodyDrawingContext], include_filename_evidence: bool = True) -> DrawingEvidenceResolution`.
- Resolution returns `canonical_drawings`, `candidates`, `evidence`, `context_facts`, `unresolved_source_ids`, `ambiguous_source_ids`, and diagnostics.

- [ ] **Step 1: Write RED tests for promotion policy**

Required cases:
1. internal explicit ID remains `direct`.
2. filename-only stays `heuristic`.
3. filename + matching point/grid/direction/type + lexical body context promotes to `derived_verified`.
4. point/grid contradiction blocks promotion.
5. near-tie below minimum margin remains ambiguous.
6. two AI sources competing for one drawing are globally assigned at most one source.
7. blinded mode `include_filename_evidence=False` does not leak filename number into candidate scoring.

- [ ] **Step 2: Run focused test and verify RED**

Run: `pytest -q tests/test_drawing_evidence_graph_resolver.py`
Expected: module/function missing.

- [ ] **Step 3: Add NetworkX dependency and implement resolver**

Use `networkx.algorithms.matching.max_weight_matching` on a bipartite graph of eligible non-direct candidates after direct identities are locked. Limit content-derived candidates to top 5 per AI. Use versioned deterministic thresholds (`resolverVersion = drawing-evidence-v1`).

Initial policy:
- direct internal identifier: bypass scoring, locked assignment.
- filename exact number: identity-family heuristic support only.
- exact structured entity matches contribute semantic-content support.
- normalized lexical overlap contributes body-context support.
- incompatible point/grid facts are hard contradictions.
- promotion requires score >= configured minimum, margin >= configured minimum, >=2 families, and global unique assignment.

Store score components/evidence; do not expose numeric weights as a public API contract.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest -q tests/test_drawing_context_normalizer.py tests/test_drawing_evidence_graph_resolver.py`
Expected: all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: resolve drawings from multi-source evidence`

---

### Task 3: Neo4j body-context query and evidence graph persistence

**Files:**
- Modify: `backend/app/graph/reference_corpus_repository.py`
- Modify: `backend/tests/test_reference_corpus_repository.py`
- Create: `backend/tests/integration/test_drawing_evidence_graph_neo4j.py`

**Interfaces:**
- `ReferenceCorpusRepository.list_body_drawing_contexts(project_id: str) -> list[BodyDrawingContext]`.
- `ReferenceCorpusRepository.save_drawing_resolution_graph(project_id: str, corpus_id: str, resolution: DrawingEvidenceResolution) -> None`.
- Persistence creates/updates corpus-scoped `DrawingCandidate`, `ResolutionEvidence`, `ContextEntity` and relationships `PROPOSES`, `SUPPORTED_BY`, `CONTRADICTED_BY`, `FROM_SOURCE`, `USES_CONTEXT`, `HAS_CONTEXT`, and verified `TARGETS` only where permitted.

- [ ] **Step 1: Write repository RED tests**

Verify:
- body context query starts from project ownership and returns reference/caption/source text grouped by drawing number.
- deterministic rerun does not duplicate candidate/evidence/context nodes.
- filename-only candidate has no verified `TARGETS` relation.
- derived-verified candidate has `TARGETS` and evidence metadata.
- direct candidate wins over heuristic contender for same drawing number.

- [ ] **Step 2: Run hermetic repository tests and verify RED**

Run: `pytest -q tests/test_reference_corpus_repository.py`
Expected: missing methods/queries.

- [ ] **Step 3: Implement query and persistence methods**

All Cypher must scope through `Project` and `ReferenceCorpus`. `FROM_SOURCE` may target `OriginalAsset`, `TextBlock`, `Caption`, `Reference`, or `Page` only if that source node exists under the same project.

- [ ] **Step 4: Run hermetic tests GREEN**

Run: `pytest -q tests/test_reference_corpus_repository.py`
Expected: all pass.

- [ ] **Step 5: Run real Neo4j integration GREEN**

Run the repository's integration test command for `test_drawing_evidence_graph_neo4j.py` and existing real-Neo4j remediation tests.

- [ ] **Step 6: Commit**

Commit message: `feat: persist drawing resolution evidence graph`

---

### Task 4: ReferenceCorpus build integration and diagnostics

**Files:**
- Modify: `backend/app/services/reference_corpus_service.py`
- Modify: `backend/tests/test_adobe_free_reference_corpus.py`
- Modify: `backend/tests/test_adobe_free_provenance.py`

**Interfaces:**
- The Adobe-free build obtains body contexts from repository, resolves all drawing sources in one batch, persists the resolution graph, and saves only direct/derived-verified drawings to the canonical graph.
- Build diagnostics add `drawingResolution` containing direct/derivedVerified/heuristic/unresolved/ambiguous counts, conflict numbers, resolver version, and blinded-capable score metadata.

- [ ] **Step 1: Write RED integration-service tests**

Verify:
- multi-source resolver called once for all AI sources.
- direct and derived-verified drawings enter canonical save.
- heuristic/unresolved candidates are persisted but excluded from canonical drawings and `DERIVED_FROM` edges.
- corpus may still become READY with unresolved candidates while diagnostics expose incompleteness.
- legacy Adobe path remains untouched.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `pytest -q tests/test_adobe_free_reference_corpus.py tests/test_adobe_free_provenance.py`
Expected: failures on missing batch graph resolver integration.

- [ ] **Step 3: Implement minimal service integration**

Inject `DrawingEvidenceGraphResolver` optionally for tests; reuse existing low-level resolver through it; call repository persistence before canonical save; keep panel/JPG logic unchanged.

- [ ] **Step 4: Run focused tests GREEN**

Run same command; expected all pass.

- [ ] **Step 5: Commit**

Commit message: `feat: integrate drawing evidence graph into corpus build`

---

### Task 5: Read-only real `/src` evaluation tool

**Files:**
- Create: `tools/evaluate_drawing_evidence_graph.py`
- Create: `docs/local_drawing_evidence_graph_revalidation.md`
- Test: `backend/tests/test_drawing_evidence_graph_evaluator_contract.py`

**Interfaces:**
- CLI accepts `--source-root`, `--repo-root`, `--output-json`, `--output-report`, and `--blinded`.
- It never modifies `/src`.
- It reports the 35-file blinded silver-label evaluation and full 56-file evidence distribution separately.

- [ ] **Step 1: Write evaluator contract RED test**

Verify read-only inputs, output schema, filename-hiding behavior, and no Adobe invocation/import.

- [ ] **Step 2: Implement evaluator**

Reuse production normalizer/resolver. Produce machine-readable metrics including Top-1/Top-3 agreement, unique verified, direct, derived_verified, heuristic, unresolved, ambiguous, and reviewed false-verified count field.

- [ ] **Step 3: Add local execution document**

Document exact Windows/local commands and before baseline: direct 1/56, heuristic-only 34/56, unresolved 21/56. State that hidden filename is silver-label only, not ground truth.

- [ ] **Step 4: Run evaluator contract tests GREEN**

Run: `pytest -q tests/test_drawing_evidence_graph_evaluator_contract.py`

- [ ] **Step 5: Commit**

Commit message: `test: add real drawing evidence graph evaluator`

---

### Task 6: Full verification and push

**Files:**
- No functional changes unless verification reveals a root-cause defect.

- [ ] **Step 1: Run compile and focused suite**

Run `python -m compileall -q app` and all new drawing-evidence tests.

- [ ] **Step 2: Run backend hermetic CI**

Use PR-triggered GitHub Actions and require backend-hermetic GREEN.

- [ ] **Step 3: Run real Neo4j E2E CI**

Require the existing real Neo4j job and the new evidence-graph integration coverage GREEN.

- [ ] **Step 4: Run frontend CI**

No frontend behavior is intentionally changed by this feature; require existing frontend typecheck/tests/build not to regress. If an already-known unrelated failure remains, report it explicitly rather than claiming full green.

- [ ] **Step 5: Inspect final diff and evidence policy**

Confirm no code path promotes filename-only evidence, all canonical drawing provenance is direct/derived_verified, and candidate graph remains corpus-scoped/idempotent.

- [ ] **Step 6: Push final branch state**

Push/retain changes on `feature/adobe-free-provenance-20260823`; keep PR #47 draft and unmerged unless explicit merge approval is later given.
