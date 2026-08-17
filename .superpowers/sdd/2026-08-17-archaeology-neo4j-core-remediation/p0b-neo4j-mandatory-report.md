# P0-B Report — Make Neo4j a Mandatory Production Dependency

**Date:** 2026-08-17
**Branch:** `windows-docker-foundation`
**Review source:** `docs/superpowers/reviews/2026-08-17-neo4j-frontend-mvp-code-review.md` — Phase P0-B (§13), P0-2, Mandatory Test B, Anti-patterns #4/#6, Definition of Done "Graph" section.

## Goal

Make Neo4j a mandatory operational dependency of the proofreading flow — NOT an optional side channel that can silently fall back to in-memory evidence (P0-2 / anti-pattern #6). Production default `allow_degraded_mode=False`; fail closed; persist structured failure/unresolved reasons; kill-switch test proves the analysis OUTCOME changes when a load-bearing graph relationship is removed.

## Files Changed

| File | Change |
| --- | --- |
| `backend/app/config.py` | Added `ALLOW_DEGRADED_MODE` env + `get_allow_degraded_mode()` (production default **False**). |
| `backend/app/graph/review_repository.py` | Added `save_object_unresolved_reason()` — persists structured `{object_id, reason_code, message}` entries on the `AnalysisRun.unresolvedObjects` list. |
| `backend/app/services/proofreading_orchestrator.py` | Mode gating in step 7b (graph bundles), step 8A (RuleEngine), step B (VLM refresh), step C (LLM); `allow_degraded_mode` on constructor + `run_proofreading`; `OrchestratorResult.unresolved`; summary `unresolved_objects`. |
| `backend/tests/test_graph_evidence_bundle.py` | +5 kill-switch/fail-closed unit tests; updated `test_rewired_orchestrator_degrades_explicitly_when_graph_has_no_evidence` → `allow_degraded_mode=True`. |
| `backend/tests/integration/test_graph_driven_consistency.py` | +2 real-Neo4j kill-switch tests (MENTIONS + DEPICTS). |
| `backend/tests/test_env_unification.py` | +3 `get_allow_degraded_mode` config tests. |
| `backend/tests/test_production_orchestrator_assembly.py` | +1 worker-level fail-closed test (`GRAPH_EVIDENCE_UNAVAILABLE`). |
| `backend/tests/test_graph_grounded_ai.py` | Updated `test_llm_degrades_explicitly_to_in_memory_without_graph_evidence` → `allow_degraded_mode=True`. |
| `backend/tests/test_golden_verification_gates.py` | Orchestrator → `allow_degraded_mode=True`. |
| `backend/tests/test_canonical_identity_enforcement.py` | Orchestrator → `allow_degraded_mode=True`. |
| `backend/tests/test_proofreading_orchestrator.py` | 8 tests → `allow_degraded_mode=True` (in-memory pipeline tests). |

## Mode-Gating Design (production vs degraded)

`allow_degraded_mode` resolves at orchestrator construction (`ProofreadingOrchestrator(allow_degraded_mode=...)`) and can be overridden per `run_proofreading(...)` call. Default comes from `config.get_allow_degraded_mode()` → `ALLOW_DEGRADED_MODE` env, **False** in production.

### Production mode (`allow_degraded_mode=False`) — fail closed

| Condition | Behavior |
| --- | --- |
| `canonical_repo is None` (no graph DB) | `save_analysis_run(status="failed", error_code="GRAPH_EVIDENCE_UNAVAILABLE", retryable=False)` then raise `RuntimeError`. |
| `get_object_evidence_bundle` raises (graph DB error) | Same fail-closed: run failed with `GRAPH_EVIDENCE_UNAVAILABLE`. |
| Bundle empty for a required object | Object marked **unresolved/manual_review** with persisted reason (`save_object_unresolved_reason` → `run.unresolvedObjects`); semantic consistency check **skipped**; no candidate from in-memory lists. |
| RuleEngine step | Objects without a graph bundle are skipped (already marked unresolved) — never `check_object_consistency` on in-memory lists. |
| LLM step | Objects without a graph bundle are skipped — never `review_object_evidence` on in-memory lists. |
| VLM bundle refresh raises | Fail closed with `GRAPH_EVIDENCE_UNAVAILABLE`. |
| VLM bundle refresh returns empty | Keep pre-VLM graph bundle with explicit warning (still graph-derived, not in-memory). |

### Degraded mode (`allow_degraded_mode=True`) — explicit, dev/test only

Preserves the previous behavior: in-memory RuleEngine/LLM fallback with an explicit `DEGRADED` warning — never silent. Only reachable via `ALLOW_DEGRADED_MODE=true` or an explicit constructor/run flag.

## Fail-Closed / Unresolved Reason Mechanism

1. **Run-level fail-closed:** `save_analysis_run(status="failed", error_code="GRAPH_EVIDENCE_UNAVAILABLE", retryable=False)`. The worker's `_record_analysis_failure` detects the run is already `failed` and preserves the specific error_code (never overwrites with generic `analysis_error`).
2. **Object-level unresolved:** `ReviewRepository.save_object_unresolved_reason(project_id, run_id, object_id, reason_code, message)` appends `{object_id, reason_code, message}` to `AnalysisRun.unresolvedObjects`. The orchestrator also surfaces the same entries in `OrchestratorResult.unresolved` and `summary["unresolved_objects"]`.

Nothing is silently skipped: every production refusal to run a semantic check is either a failed run or a persisted unresolved reason.

## Kill-Switch Test Results

### Unit (FakeNeo4jDriver) — `tests/test_graph_evidence_bundle.py`

- `test_production_mode_fails_closed_when_graph_db_unavailable` — `canonical_repo=None` → `RuntimeError(GRAPH_EVIDENCE_UNAVAILABLE)` + failed run persisted. **PASS**
- `test_production_mode_fails_closed_when_bundle_query_raises` — bundle query raises → fail closed. **PASS**
- `test_production_mode_marks_object_unresolved_when_bundle_missing` — empty bundle → run completes, **no candidates**, object unresolved with persisted reason. **PASS**
- `test_production_mode_produces_candidate_from_graph_evidence` — valid bundle → candidate produced, no unresolved. **PASS**
- `test_kill_switch_relationship_deletion_changes_analysis_outcome` — run 1 (graph evidence) produces the numeric candidate; run 2 (empty bundle simulating deleted MENTIONS) produces **no candidate** + unresolved with persisted reason. **PASS**

### Real Neo4j — `tests/integration/test_graph_driven_consistency.py`

- `test_real_neo4j_kill_switch_mentions_deletion_changes_outcome` — orchestrator ingests a valid body/object graph and produces the numeric candidate; `DETACH DELETE` the scoped `MENTIONS` edges; re-running the production-mode graph-driven analysis yields an **empty bundle → no candidate**. **PASS**
- `test_real_neo4j_kill_switch_depicts_deletion_changes_visual_evidence` — DEPICTS variant: deleting the scoped `DEPICTS` edge removes the `plate_claim` visual evidence from the bundle. **PASS**

Both real-Neo4j tests use scoped ids (`it_<uuid8>_`) with `finally` cleanup; verified **0 leftover scoped nodes** after the suite.

> **Design note:** the orchestrator re-creates MENTIONS/REFERENCES/RESOLVES_TO/DEPICTS from in-memory parsed data on every run (self-healing). Therefore the real-Neo4j kill-switch is demonstrated at the graph-driven analysis level (`get_object_evidence_bundle` → `RuleEngine.check_object_bundle_consistency`) — the exact production-mode code path — after the relationship is deleted. The orchestrator-level fail-closed/unresolved behavior is covered by the unit tests (which control the driver).

### Worker-level — `tests/test_production_orchestrator_assembly.py`

- `test_analysis_worker_fails_closed_when_graph_evidence_unavailable` — a production worker run whose bundle query fails ends `failed` with `GRAPH_EVIDENCE_UNAVAILABLE` persisted. **PASS**

## Existing Tests Updated (each reported)

| Test | Change |
| --- | --- |
| `test_graph_evidence_bundle.py::test_rewired_orchestrator_degrades_explicitly_when_graph_has_no_evidence` | Added `allow_degraded_mode=True` — the old test asserted the in-memory fallback produces candidates, which now contradicts the mandatory contract. |
| `test_graph_grounded_ai.py::test_llm_degrades_explicitly_to_in_memory_without_graph_evidence` | Added `allow_degraded_mode=True` — same reason (in-memory LLM fallback). |
| `test_golden_verification_gates.py` (orchestrator) | Added `allow_degraded_mode=True` — asserts in-memory candidate generation. |
| `test_canonical_identity_enforcement.py` (orchestrator) | Added `allow_degraded_mode=True` — no canonical repo, asserts in-memory resolution. |
| `test_proofreading_orchestrator.py` (8 tests) | Added `allow_degraded_mode=True` — in-memory pipeline tests (full pipeline, golden fixture, integrity, VLM integration, module helper, discrepancy, AI grounding, Neo4j persistence). |

Tests that fail closed **before** step 7b (empty body version, missing file, zero pages, empty plate/drawing index) were **not** changed — they never reach the mode gate.

## Test Results

| Suite | Before | After |
| --- | --- | --- |
| Backend unit (`pytest tests --ignore=tests/integration`) | 500 passed / 8 skipped / 8 infra errors | **509 passed** / 8 skipped / 8 infra errors (same 8 infra guards) |
| Integration (real Neo4j, `NEO4J_PASSWORD` set) | 7 passed | **9 passed** (2 new kill-switch) |
| Frontend `npm test -- --run` | 14 passed | **14 passed** (unaffected) |
| Frontend `npm run build` | OK | **OK** (unaffected) |

## Anti-Pattern Compliance

- **#4** (required relation missing → fail closed, never substitute): production mode never substitutes a guessed relationship; missing bundle → unresolved/manual_review with persisted reason.
- **#6** (no graph-backed claim from in-memory lists): production mode never runs RuleEngine/LLM on in-memory lists; candidates come only from graph bundles.

## Definition of Done — Graph section

- [x] Production analysis depends on graph traversal (fail-closed when graph unavailable).
- [x] Graph failure does not silently degrade to normal success (kill-switch tests prove outcome change).
- [x] Candidate provenance traversable to exact version/page/evidence (unchanged; verified by existing traceability tests).
