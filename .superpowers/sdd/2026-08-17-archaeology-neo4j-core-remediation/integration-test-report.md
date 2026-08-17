# Integration Test Report — Real Neo4j Gate Tests (plan §6)

**Branch:** `windows-docker-foundation`
**Date:** 2026-08-17
**Scope:** Plan §6 "Real Neo4j Integration Tests — Mandatory" — a real-Neo4j
integration suite that executes the real repositories/orchestrator and queries
the running database to verify persisted nodes **and relationships** (FakeDriver
tests are unit tests only, not MVP evidence). Covers Gates A, C, D, E and
§6 Test 5 (version graph).
**Method:** Real driver only (no FakeDriver in `tests/integration`); every test
queries the DB post-execution; scoped ids (`it_<uuid8>_`) + cleanup in `finally`;
skip-when-unreachable module fixture for portability; follows the repo's existing
real-Neo4j pattern (`test_graph_evidence_bundle.py`).

---

## 1. Files created

| Deliverable | File | Gate |
| :--- | :--- | :--- |
| 1. Test compose | `compose.test.yml` | — |
| 2. Shared fixtures | `backend/tests/integration/conftest.py` | — |
| 3. Canonical body/plate graph | `backend/tests/integration/test_neo4j_canonical_graph.py` | Gate A |
| 4. Case 6 canonical identity | `backend/tests/integration/test_case6_real_graph.py` | Gate C |
| 5. Graph-driven consistency | `backend/tests/integration/test_graph_driven_consistency.py` | Gate D |
| 6. Review traceability | `backend/tests/integration/test_review_traceability_graph.py` | Gate E |
| 7. Version graph | `backend/tests/integration/test_version_alignment_graph.py` | §6 Test 5 |

`src/` untouched. No other tasks' reports/progress rows changed except the
Integration row in `progress.md`.

## 2. Fixture design (`conftest.py`)

- **`neo4j_driver`** (module-scoped): reads `NEO4J_URI` (default
  `bolt://127.0.0.1:7687`), `NEO4J_USER` (default `neo4j`), `NEO4J_PASSWORD`
  from env; **skips the whole module** when the password is unset or
  `verify_connectivity()` fails — portable (CI without a Neo4j instance skips
  cleanly).
- **`_asset_cache_dir`** (autouse): points `ASSET_CACHE_DIR` at a writable temp
  dir so factory-built orchestrators (`VLMReviewService` → `AssetHashCache`)
  never touch the read-only `/data` path.
- **`scoped_prefix`** (function-scoped): `it_<uuid8>_` per test.
- **`create_project`**: creates a `Project` node with a **scoped id**
  (`{scope}project`) so cleanup can delete its whole subtree. This is required
  because `ProjectRepository.create_document_with_version` emits
  random-uuid `DocumentVersion`/`AnalysisRun` nodes that a scope-only id match
  would miss.
- **`cleanup`**: deletes the scoped project's whole subtree
  (`MATCH (p:Project) WHERE p.id CONTAINS $scope OPTIONAL MATCH (p)-[*1..10]-(n)
  DETACH DELETE p FOREACH ...`) **and** any remaining node whose id `CONTAINS`
  the scope. `CONTAINS` (not `STARTS WITH`) is used because `Reference` ids are
  `ref_{scope}_...` (prefixed with `ref_`). The scope `it_<uuid8>_` is unique
  enough that `CONTAINS` never touches unrelated data.

## 3. Per-gate assertions + real-run results

All tests ran against the local Neo4j (`bolt://127.0.0.1:7687`, Community
single-db) with the container password. **6 passed / 0 failed.**

### Gate A — `test_neo4j_canonical_graph.py`
Registers real `DocumentVersion(body/plate/drawing)` via `ProjectRepository`,
runs the factory-assembled `ProofreadingOrchestrator` over real body pages,
plates and drawings, then queries the DB:
- `DocumentVersion -[:HAS_PAGE]-> Page -[:HAS_BLOCK|HAS_CAPTION]-> source
  -[:REFERENCES]-> Reference -[:RESOLVES_TO]-> Plate` traversal returns ≥1 row
  (asserted `plate == plate.plate_id` and `scope in reference_id`).
- ≥1 `source -[:MENTIONS]-> ArchaeologyObject`.
- ≥1 `Plate -[:DEPICTS]-> ArchaeologyObject`.
- ≥1 `Reference -[:RESOLVES_TO]-> Plate`.

Sample traversal output (scoped diagnostic):
```
diag_<uuid>_v -> diag_<uuid>_p -> diag_<uuid>_b -> ref_diag_<uuid>_b_plate_45 -> diag_<uuid>_plate45
diag_<uuid>_b MENTIONS 1지점 청동기시대 6호 석관묘 ; ['Plate'] diag_<uuid>_plate45 DEPICTS 1지점 청동기시대 6호 석관묘
```

### Gate C — `test_case6_real_graph.py`
Photo files `4. 조사 후_45.JPG` / `photo_45.JPG` / `조사후_45.JPG` present as
`OriginalAsset` nodes; canonical `Plate(number=45, raw_identifier="【도판 45】")`
persisted via `save_plates`; `Reference(plate,45)` persisted and linked via
`link_reference_to_target`:
- `Reference(plate,45) -[:RESOLVES_TO]-> Plate(45)` exists (asserted
  `ref_type == "plate"`, `number == "45"`, `plate_number == "45"`,
  `raw_identifier == "【도판 45】"`).
- Plate 45 identity properties (`raw_identifier`/`title`/`source_kind`) never
  contain `4. 조사 후_45.JPG`.
- No `OriginalAsset` with the trap filename is connected to Plate 45
  (`count(r) == 0`).
- No `Evidence` whose `value`/`rationale` contains the trap filename is
  connected to Plate 45 (`count(r) == 0`).

### Gate D — `test_graph_driven_consistency.py`
One `ArchaeologyObject` with two graph-backed text claims (`길이 275cm` on Page A,
`길이 2.45m` on Page B). `get_object_evidence_bundle` → `RuleEngine`:
- Exactly **one** `numeric_value` candidate, `status == "pending_review"`,
  supported by evidence from **both** pages (`page_ids == {page1, page2}`).
- Equivalent values (`275cm` vs `2.75m`) produce **no** numeric conflict.

### Gate E — `test_review_traceability_graph.py`
Persists a candidate + evidence + two decisions via real repos, then asserts the
full traversal in the real DB:
- `Candidate -[:ABOUT]-> Object`
- `Candidate -[:SUPPORTED_BY]-> Evidence -[:EXTRACTED_FROM]-> Page`
- `Evidence -[:FROM_VERSION]-> DocumentVersion`
- `Candidate -[:HAS_DECISION]-> ReviewDecision` (append-only: two decisions)
- `candidate.status == "pending_review"`; decision values in the 4-value set
  (`accepted|rejected|modified|deferred`); `latest_decision` = the second
  (`deferred`), full history preserved.

### §6 Test 5 — `test_version_alignment_graph.py`
Persists 1차/2차/3차 `DocumentVersion`s + pages, runs `PageAligner` via the real
orchestrator (`persist_version_alignment`):
- `PRECEDES`: 1차→2차 and 2차→3차 (each `count == 1`).
- `ALIGNED_TO` between the three pages with the exact property set
  (`status` in `{exact, probable, manual_review}`, `method == "dtw_weighted"`,
  `run_id == {scope}_run`).

## 4. Cleanup verification

After the full suite run:
- `MATCH (n) WHERE n.id CONTAINS 'it_' RETURN count(n)` → **0**.
- `MATCH (p:Project) WHERE p.name CONTAINS 'it_' RETURN count(p)` → **0**.
- Post-run node counts returned to the pre-existing shared-DB baseline
  (Concept 232 / CrossReference 18054 / Procedure 25 / Requirement 405 /
  Section 4371 / Specification 19) — nothing outside the scoped ids was touched.

## 5. compose.test.yml validation

- `docker compose -f compose.yml -f compose.test.yml config -q` → **OK**
  (only benign `DATA_ROOT` unset warnings from the shell env).
- Python `yaml.safe_load` → **OK**.
- `compose.test.yml` extends `compose.yml` with a disposable `neo4j-test`
  service (separate `neo4j_test_data` volume, `NEO4J_AUTH:
  neo4j/${NEO4J_PASSWORD:-testpass-2026}`, port `7688`) and reuses the existing
  `redis` service. Test-only service names; non-destructive.

## 6. Verification commands

```bash
cd backend
NEO4J_PASSWORD=... .venv/bin/python -m pytest tests/integration -q   # 6 passed
.venv/bin/python -m pytest tests -q --ignore=tests/integration        # 481 passed / 8 skipped / 8 errors
.venv/bin/python -m pytest ../tests/compose -q                        # 6 passed / 1 skipped
```

The 8 unit-suite errors are the pre-existing `NEO4J_TEST_URI` infra gates in
`test_project_repository.py` (untouched, as instructed).

## 7. Constraints honored

- `src/` untouched; no other tasks' reports/progress rows changed except the
  Integration row.
- Real repos/driver only in `tests/integration`; every test queries the DB
  post-execution; scoped ids + `finally` cleanup; skip-when-unreachable fixture.
- No destructive writes outside scoped ids (the shared DB's Concept/
  CrossReference/etc. data was never touched).
- No subagents, no web search, no bare `except`, no credentials printed.