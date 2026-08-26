# Codex-first Drawing Evidence v3 Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Codex-first drawing identity resolver that sends every source drawing through one grounded multimodal Codex decision path while preserving deterministic fail-closed safety and measurable operational gates.

**Architecture:** Keep v1/v2 unchanged and add `drawing-evidence-v3`. Local code extracts source/body evidence, ranks a broad Top-10 candidate set, renders source/candidate crops when available, calls Codex synchronously for every source with at most one Top-20 expansion, validates the closed-world JSON response, then routes to `AUTO_VERIFIED`, `REVIEW_REQUIRED`, or `UNRESOLVED`. Neo4j persists candidates, evidence, Codex decisions, and final provenance; real API evaluation remains local and `/src` read-only.

**Tech Stack:** Python 3, PyMuPDF, Neo4j, synchronous `httpx`, OpenAI Responses API, pytest, existing FastAPI/service assembly.

**Spec:** `docs/superpowers/specs/2026-08-26-codex-first-drawing-evidence-v3-design.md`

## Global constraints

- Every source is submitted to Codex in v3; deterministic evidence never bypasses the call.
- Codex is the only AI service in initial v3. Do not add another VLM/LLM, cross-encoder, embedding service, vector DB, GNN, or learned calibrator.
- External payload is limited to the current source image, candidate images, minimal captions/context, structured facts, and evidence IDs.
- `/src` is read-only; all generated files live outside it.
- Filename/path/sequence evidence cannot independently create `AUTO_VERIFIED`.
- Explicit publication-kind, site/grid, and feature-type+feature-number contradictions can never auto-promote.
- Invented candidate/evidence IDs, malformed output, API failure, assignment conflict, `ambiguous`, or insufficient evidence fail closed.
- Candidate Recall@10 gate: >=99% on human-verified gold-known rows.
- Operational gate: auto coverage 75-85%, auto precision >=99%, review <=25%, unsafe-promotion counters all zero.
- v1/v2 remain available; production default and merge state do not change under this plan.
- Hermetic CI never calls OpenAI; live Codex evaluation is local only.

## Files

New:
- `backend/app/domain/drawing_evidence_v3.py`
- `backend/app/services/drawing_visual_extractor.py`
- `backend/app/services/drawing_candidate_generator_v3.py`
- `backend/app/services/codex_drawing_resolver_client.py`
- `backend/app/services/drawing_evidence_resolver_v3.py`
- `tools/build_drawing_gold_template.py`
- `tools/evaluate_drawing_evidence_v3.py`

Modify:
- `backend/app/graph/drawing_evidence_repository.py`
- `backend/app/services/drawing_evidence_corpus_service.py`
- `backend/app/config.py`
- `backend/app/main.py`

Tests:
- `backend/tests/test_drawing_evidence_v3_models.py`
- `backend/tests/test_drawing_visual_extractor.py`
- `backend/tests/test_drawing_candidate_generator_v3.py`
- `backend/tests/test_codex_drawing_resolver_client.py`
- `backend/tests/test_drawing_evidence_graph_resolver_v3.py`
- `backend/tests/test_drawing_evidence_repository_v3.py`
- `backend/tests/integration/test_drawing_evidence_repository_v3_neo4j.py`
- `backend/tests/test_drawing_evidence_corpus_service_v3.py`
- `backend/tests/test_drawing_evidence_resolver_config.py`
- `backend/tests/test_drawing_evidence_v3_evaluator_contract.py`

---

### Task 1: Define exact v3 domain contracts

**Files:** Create `backend/app/domain/drawing_evidence_v3.py`; test `backend/tests/test_drawing_evidence_v3_models.py`.

- [ ] Write RED imports/tests for `DrawingV3Evidence`, `DrawingVisualRegion`, `BodyDrawingEvidencePacket`, `DrawingSourceEvidencePacket`, `DrawingCandidatePacket`, `CodexDrawingDecision`, `DrawingV3SourceResult`, `DrawingV3Resolution`.
- [ ] Run `cd backend && pytest -q tests/test_drawing_evidence_v3_models.py`; verify import failure.
- [ ] Implement frozen/slotted dataclasses with these exact semantics:
  - `DrawingV3Evidence(id, family, method, value, supports=True, weak=False)` so evidence ID→family/weakness is explicit.
  - `DrawingVisualRegion(region_id, image_path, page, bbox, confidence, source_sha256=None)`.
  - `BodyDrawingEvidencePacket(publication_kind, number, raw_texts, source_node_ids, source_sha256, document_version_id, physical_page, source_bbox, visual_regions)`.
  - `DrawingSourceEvidencePacket(source_asset_id, source_sha256, original_name, source_path, raw_text, publication_kind, internal_numbers, facts, visual_regions, evidence)`.
  - `DrawingCandidatePacket(candidate_id, publication_kind, number, raw_texts, facts, visual_regions, local_score, evidence, hard_contradiction, strong_contradiction_ids)`.
  - `CodexDrawingDecision(run_id, model, verdict, candidate_id, confidence, cited_support_ids, cited_contradiction_ids, reason_codes, summary)`.
  - statuses exactly `AUTO_VERIFIED | REVIEW_REQUIRED | UNRESOLVED`; verdicts exactly `match | ambiguous | none`.
- [ ] Run the focused test and commit `feat: add drawing evidence v3 contracts`.

---

### Task 2: Expose body page/bbox metadata and render visual regions

**Files:** Create `backend/app/services/drawing_visual_extractor.py`; modify `backend/app/graph/drawing_evidence_repository.py`; test `backend/tests/test_drawing_visual_extractor.py`, `backend/tests/test_drawing_evidence_repository_v3.py`.

**Contract:** add a separate `list_body_drawing_v3_contexts(project_id) -> list[BodyDrawingEvidencePacket]`; do not overload v1/v2 `list_body_drawing_contexts()`.

- [ ] Write RED repository test using a fake Neo4j row with `document_version_id`, `physical_page`, and `source_bbox`; assert one-reference=one-mention grouping remains intact.
- [ ] Write RED PyMuPDF test generating a tiny PDF-compatible `.ai`, calling `render_source()` and `crop_body_region()`, and asserting PNG outputs exist outside the input root.
- [ ] Run `cd backend && pytest -q tests/test_drawing_visual_extractor.py tests/test_drawing_evidence_repository_v3.py`; verify RED.
- [ ] Implement v3 body query returning latest body `DocumentVersion` ID, page, bbox, source/reference text, neighbor text, and SHA. Group by `(publication_kind, number, source_id)` and return `BodyDrawingEvidencePacket(visual_regions=())`.
- [ ] Implement `DrawingVisualExtractor` with PyMuPDF only. `render_source()` renders page 1. `crop_body_region()` uses `page_number - 1`, clamps `Rect(*bbox)` to `page.rect`, rejects empty clips with `ValueError`, and never writes into `/src`.
- [ ] Missing/invalid bbox means visual unavailable, not identity evidence and not an inferred crop.
- [ ] Run `pytest -q tests/test_drawing_visual_extractor.py tests/test_drawing_evidence_repository_v3.py tests/test_drawing_evidence_repository_v2_context.py` and commit `feat: add v3 drawing visual packets`.

---

### Task 3: Build transparent high-recall Top-10/Top-20 candidates

**Files:** Create `backend/app/services/drawing_candidate_generator_v3.py`; test `backend/tests/test_drawing_candidate_generator_v3.py`.

- [ ] Write RED tests proving explicit feature-pair/site/grid/kind contradictions are filtered, missing fields are retained, correct synthetic target survives Top-10, and Top-20 expansion is duplicate-free and never reintroduces hard contradictions.
- [ ] Run `cd backend && pytest -q tests/test_drawing_candidate_generator_v3.py`; verify RED.
- [ ] Implement using existing `DrawingContextNormalizer`. Transparent ordering weights only: site 8, grid 10, feature pair 10, period 4, drawing type 3, map type 4, year 4, token overlap 2, sequence neighbor 1, filename .25, path .25.
- [ ] Emit one `DrawingV3Evidence` for each signal. Set `weak=True` for filename/path/sequence; all structured/text signals are nonweak. Local score is ranking only, never probability.
- [ ] Run v3 tests plus `tests/test_drawing_evidence_graph_resolver_v2.py`; commit `feat: add v3 drawing candidate retrieval`.

---

### Task 4: Add the synchronous Codex multimodal client

**Files:** Create `backend/app/services/codex_drawing_resolver_client.py`; modify `backend/app/config.py`; test `backend/tests/test_codex_drawing_resolver_client.py` and config tests.

**Contract:** `CodexDrawingResolverClient.resolve(...)` is synchronous because current `EvidenceGraphReferenceCorpusService._adobe_free_visuals()` is synchronous.

- [ ] Write RED tests with injected `httpx.MockTransport`: closed-world prompt, source/candidate `input_image`, `match/ambiguous/none`, invented candidate/evidence IDs, invalid confidence, malformed JSON, one retry, typed failure after retry.
- [ ] Run focused tests; verify RED.
- [ ] Add Codex-specific config: `OPENAI_API_KEY`, `DRAWING_CODEX_MODEL`, `DRAWING_CODEX_TIMEOUT_SECONDS`, `DRAWING_CODEX_AUTO_CONFIDENCE`, `DRAWING_CODEX_MAX_CANDIDATES`, `DRAWING_CODEX_MAX_EXPANSIONS`. Do not change OpenRouter behavior.
- [ ] Implement synchronous Responses API request with PNG data URLs and a closed-world text packet containing only submitted candidate/evidence IDs.
- [ ] Validate `match` candidate is submitted; cited support/contradiction IDs are subsets of submitted IDs; confidence is `[0,1]`; malformed/invented output raises `CodexDrawingDecisionError`.
- [ ] Run tests with zero network traffic and commit `feat: add Codex drawing resolver client`.

---

### Task 5: Orchestrate mandatory Codex decisions and final states

**Files:** Create `backend/app/services/drawing_evidence_resolver_v3.py`; test `backend/tests/test_drawing_evidence_graph_resolver_v3.py`.

- [ ] Write RED state matrix: high-confidence valid match→AUTO, low confidence→REVIEW, hard contradiction→REVIEW, ambiguous→REVIEW, none after bounded expansion→UNRESOLVED.
- [ ] Assert every source invokes Codex, including explicit internal-ID sources.
- [ ] Assert one Top-20 expansion maximum and repeated Codex client error routes to review.
- [ ] Implement final safety gate by merging source+candidate evidence maps, resolving every cited ID to `DrawingV3Evidence`, requiring >=2 independent cited families and >=1 nonweak cited evidence, and rejecting any hard contradiction.
- [ ] Implement conflict policy for multiple sources selecting one target: explicit internal-ID agreement first, then higher Codex confidence, then greater nonweak cited evidence count; losing sources become `REVIEW_REQUIRED`.
- [ ] Run v3/v2 resolver tests and commit `feat: add Codex-first drawing resolver v3`.

---

### Task 6: Persist v3 candidates, Codex decisions, and safe targets

**Files:** Modify `backend/app/graph/drawing_evidence_repository.py`; test unit and `backend/tests/integration/test_drawing_evidence_repository_v3_neo4j.py`.

- [ ] Write RED payload tests for model/run/verdict/confidence/reason codes/citations/final status; assert shadow AUTO, REVIEW, and UNRESOLVED create no v3 TARGETS.
- [ ] Implement `save_v3_resolution(project_id, corpus_id, resolution, auto_promote)` with graph:
  - `(OriginalAsset)-[:HAS_CODEX_DECISION]->(CodexDecision)`
  - `(CodexDecision)-[:CONSIDERED]->(DrawingCandidate)`
  - `(CodexDecision)-[:SELECTED]->(DrawingCandidate)` for match only
  - citation edges to `ResolutionEvidence`.
- [ ] Preserve v1/v2. Only `AUTO_VERIFIED` with `auto_promote=True`, or later human-verified results, may create derived TARGETS.
- [ ] Add Neo4j integration test for one AUTO and one REVIEW result; run unit/integration tests; commit `feat: persist Codex drawing provenance`.

---

### Task 7: Wire explicit v3 shadow mode and reuse the existing body-PDF path resolver

**Files:** Modify `backend/app/services/drawing_evidence_corpus_service.py`, `backend/app/config.py`, `backend/app/main.py`; test service/config.

**Existing path authority to reuse:** `backend/app/jobs/run_inputs.py::resolve_stored_pdf_path(version)` already resolves a `VersionInput.uri` via `DATA_ROOT / uri` and then a direct local path. `ProjectRepository.resolve_version_input(project_id, kind, stage, version_id)` is the existing authority for resolving a project-owned body version. Do **not** implement another URI/path resolver.

- [ ] Write RED config tests: default resolver remains v1; `v3`/`drawing-evidence-v3` aliases select v3; `DRAWING_EVIDENCE_V3_AUTO_PROMOTE` defaults false.
- [ ] Write RED service test using fake sync v3 resolver: every source processed, v3 decisions persisted, shadow mode creates no new v3 canonical targets.
- [ ] Extend service dependencies so v3 has access to the existing project repository. Do not construct Codex/OpenAI dependencies when v1/v2 is selected.
- [ ] For each `BodyDrawingEvidencePacket.document_version_id`, resolve the project-owned body using exactly:
  `project_repository.resolve_version_input(project_id, "report_body", None, document_version_id)`.
- [ ] Convert that returned `VersionInput` to a local PDF path using exactly `app.jobs.run_inputs.resolve_stored_pdf_path(version)`. If it returns a file, use `DrawingVisualExtractor.crop_body_region()` with the packet page/bbox. If it returns `None`, leave `visual_regions=()` and continue fail-closed with text/structured evidence.
- [ ] The local evaluator supplies its known real body PDF path directly and does not mutate `/src`.
- [ ] Add `DRAWING_EVIDENCE_V3_AUTO_PROMOTE=false` shadow getter and v3 lazy dependency wiring; preserve synchronous `_adobe_free_visuals()`.
- [ ] Run `pytest -q tests/test_drawing_evidence_corpus_service_v3.py tests/test_drawing_evidence_corpus_service_v2.py tests/test_drawing_evidence_resolver_config.py`; commit `feat: wire drawing evidence v3 shadow mode`.

---

### Task 8: Add human-gold template and local v3 evaluator

**Files:** Create `tools/build_drawing_gold_template.py`, `tools/evaluate_drawing_evidence_v3.py`, fixture and evaluator contract tests.

- [ ] Write RED tests: unknown gold rows excluded from accuracy, coverage and precision computed separately, output paths inside source root rejected.
- [ ] Gold template CLI enumerates source AI files but initializes every truth row as `{publication_kind: null, number: null, verification: "unknown"}`. Never infer truth from filename number.
- [ ] Evaluator CLI supports deterministic fake mode for tests and `--live-codex` for local real calls. Metrics: Recall@5/10/20, Codex Top-1, ambiguous/none, auto coverage, auto precision, review rate, invalid response count, hard contradiction promoted, filename-only promoted, kind collision, API unsafe promotion.
- [ ] Follow existing evaluator Python-path bootstrap/read-only guard.
- [ ] Run evaluator tests and commit `test: add drawing evidence v3 gold evaluator`.

---

### Task 9: Verify hermetic CI and local live acceptance

- [ ] Run `python -m compileall -q app` and all focused v3 backend tests.
- [ ] Run full repository CI-equivalent suites; required green jobs: `backend-hermetic`, `frontend`, `neo4j-e2e`; no real OpenAI traffic in CI.
- [ ] Locally run `tools/build_drawing_gold_template.py`, then human-review every defensible current source/body identity; uncertain rows remain `unknown`.
- [ ] Run `tools/evaluate_drawing_evidence_v3.py --live-codex` with `DRAWING_EVIDENCE_RESOLVER_VERSION=v3` and `DRAWING_EVIDENCE_V3_AUTO_PROMOTE=false`.
- [ ] Pass only if gold-known rows achieve Recall@10 >=99%, auto coverage 75-85%, auto precision >=99%, review <=25%, unsafe counters all zero.
- [ ] If Recall@10 fails, improve Task 3 retrieval. If precision fails, tighten threshold/routing from measured gold confidence buckets. If coverage fails while precision passes, remain shadow/review-only. Do not add another AI model or lower safety gates under this plan.
- [ ] Commit measured gold/metrics/report only after human gold review/live run.
- [ ] Do not enable auto-promote, change production default, or merge PR #47/PR #1 without explicit user approval.
