# Task 14 Report — Restore True Expert Decision Semantics (commit `acd57de`)

**Branch:** `windows-docker-foundation` (HEAD `acd57de`, base `f0c8bd7`)
**Date:** 2026-08-17
**Scope:** Plan Task 14 — Gate F. Candidate generation status (`pending_review`) kept separate from append-only expert `ReviewDecision` records with exactly `accepted | rejected | modified | deferred`. `layout_noise` remains a rule classification only (anti-pattern #11). Metrics use the latest decision while the full audit history stays queryable.
**Method:** TDD (red → green). No `src/` access, no subagents, no web, no bare `except`, no destructive Neo4j writes outside scoped `dec_test_*` ids.

---

## 1. Files changed per deliverable

| Deliverable | File | Change |
| :--- | :--- | :--- |
| 1. Generation status audit | *(no production change needed)* | **Verified by grep + tests:** every candidate generation path already writes `status="pending_review"` — `rule_engine.py` (default param line 225 + 9 explicit sites), `ai_review_service.py` (default param lines 105/216, model-echoed `confirmed` overridden), `asset_review_pipeline.py` (VLM: lines 82/98/139/180/195/247 + invariant comment), `proofreading_orchestrator.py` (re-wraps rule/AI/pipeline candidates lines 679/841). New regression tests lock this in (rule + LLM + VLM paths, incl. model claiming `confirmed`). |
| 2. Append-only ReviewDecision | `backend/app/domain/review_models.py` | **New** `ReviewDecisionValue = Literal["accepted","rejected","modified","deferred"]` + frozen `ReviewDecisionData` dataclass validating the 4-value set (reviewer, rationale/note, decision, created_at, previous_decision_id, candidate link). |
| 2. (cont.) | `backend/app/graph/review_repository.py` | **`save_review_decision` rewritten:** raises `ValueError` for any non-4-value decision (incl. `confirmed`/`layout_noise`); **removed `SET cand.status = $candidate_status`** — the candidate generation status is never mutated by an expert action; decision node now persists `previous_decision_id` property (chain) in addition to the existing `MERGE (dec)-[:SUPERSEDES]->(prev)` relationship; `modified_text` still propagates to `cand.proposed_text` (modify-with-proposed-text), status untouched. |
| 2. (cont.) | `backend/app/graph/review_repository.py` | **`compute_latest_decision(decisions)`** module-level helper — most recent ReviewDecision by `created_at` (fallback id); **`latest_decision` added** to `get_candidate`, `get_candidates`, `get_candidate_traceability` payloads; `decisions` (full history) unchanged. |
| 3. Metrics latest-decision | `backend/app/graph/review_repository.py` | **`compute_review_metrics(project_id, candidates)`** pure helper: accepted/rejected/modified/deferred counted from the **latest** ReviewDecision per candidate; candidate.status never counts as an expert outcome (no more `confirmed`/`layout_noise` buckets); `deferred_candidates` added; `get_metrics` delegates to it (no-driver default extended with `deferred_candidates: 0`). |
| 4. API | `backend/app/api/schemas.py` | `ReviewDecisionRequest.decision_valid` restricted to exactly `accepted|rejected|modified|deferred` (422 for `confirmed`/`layout_noise`/aliases); `CandidateResponse` + `TraceabilityResponse` gain `latest_decision` (alias `latestDecision`); `ReviewMetricsResponse` gains `deferred_candidates` (alias `deferredCandidates`) — all additive. |
| 4. (cont.) | `backend/app/api/reviews.py` | `record_candidate_decision` returns the persisted decision record (now with `candidate_id` + `decision` normalized in) → `ReviewDecisionResponse`. |
| 4. Browser client | `frontend/src/api.ts` | `ReviewDecisionValue` type + `ReviewDecisionPayload.decision` typed to the 4 values; `ReviewDecision`/`CorrectionCandidate`/`TraceabilityResponse`/`ReviewMetrics` gain `latest_decision`/`deferred_candidates` fields. |
| 4. (cont.) | `frontend/src/components/SplitViewInspector.tsx` | Decision buttons send canonical `accepted|rejected|modified|deferred` (+ new ⏸ 보류/Defer button); payload builds `modified_text` only for `modified`; status badge derives from `latest_decision` (no `confirmed`/`layout_noise` mapping); timeline badges match the 4-value vocabulary. |
| 4. (cont.) | `frontend/src/pages/ProjectDetailPage.tsx` | `handleDecisionSubmitted` appends the decision + sets `latest_decision` — **candidate.status is no longer overwritten locally** (`layout_noise`/`confirmed` mapping removed); status filter uses decision values and filters client-side by latest outcome (server filter only for `pending_review`); metrics fallback counts from latest decision. |
| 4. (cont.) | `frontend/src/styles.css` | `status-dot`/`status-badge`/`badge-def`/`btn-defer` styles for modified/deferred outcomes. |
| 5. Tests (TDD) | `backend/tests/test_review_decision_semantics.py` | **New** — 22 tests (see §5). |
| 5. (cont.) | `backend/tests/test_reviews_api.py` | Existing decision tests migrated to Gate F semantics (each edit listed in §6). |

`src/` untouched.

## 2. Generation vs decision separation — proof

```text
Generation paths (all write candidate.status = "pending_review"):
  grep -n 'status="pending_review"' app/services/rule_engine.py            → 629,668,692,714,738,760,786,877,903 (+ default param 225)
  grep -n 'status: ReviewStatus = "pending_review"' app/services/*.py      → rule_engine.py:225, ai_review_service.py:105,216
  grep -n 'status="pending_review"' app/services/asset_review_pipeline.py  → 82,98,139,180,195,247
  grep -n 'status="pending_review"' app/services/proofreading_orchestrator.py → 679,841 (re-wrap of rule + AI candidates)

Decision writes (only place expert actions persist):
  grep -rn "layout_noise" backend/app → review_models.py:25 (ReviewStatus literal — rule classification),
                                         rule_engine.py:263 (summary counter — rule classification)
  grep -rn "confirmed" backend/app    → review_models.py:15 (literal), rule_engine.py:262 (summary counter)
  → NO production code writes confirmed/layout_noise onto candidate.status anymore
    (previously review_repository.py:608 `SET cand.status = $candidate_status`; now removed).
```

- Every machine-generated candidate (rule / VLM / LLM / orchestrator re-wrap) starts `pending_review`.
- Expert actions create `ReviewDecision` nodes only; `candidate.status` stays `pending_review` forever.
- `layout_noise` survives only as rule classification vocabulary; the API/repo reject it as a decision value (422 / `ValueError`).

## 3. Append-only chain design

```text
MATCH (cand:CorrectionCandidate {id:$candidate_id})
OPTIONAL MATCH (cand)-[:HAS_DECISION]->(prev:ReviewDecision)
WHERE ($previous_decision_id IS NOT NULL AND prev.id = $previous_decision_id)
   OR ($previous_decision_id IS NULL AND NOT (() -[:SUPERSEDES]-> (prev)) AND prev.id <> $decision_id)
WITH cand, prev ORDER BY prev.created_at DESC LIMIT 1
MERGE (dec:ReviewDecision {id:$decision_id})
SET dec.decision_status/note/reviewer/modified_text/
    dec.previous_decision_id = CASE WHEN prev IS NOT NULL THEN prev.id ELSE null END,
    dec.created_at = toString(datetime())
MERGE (cand)-[:HAS_DECISION]->(dec)
FOREACH (modified_text → SET cand.proposed_text)
FOREACH (prev → MERGE (dec)-[:SUPERSEDES]->(prev))
```

- Append-only: previous `ReviewDecision` nodes are never deleted/overwritten; a new decision links via `HAS_DECISION` and chains to the head of the chain through both a `SUPERSEDES` relationship **and** a persisted `previous_decision_id` property.
- `latest_decision` = the decision with the greatest `created_at` (chronological last append); `decisions` = full history.
- Re-saving an existing `decision_id` cannot create a `SUPERSEDES` self-loop (`prev.id <> $decision_id`).

## 4. Metrics-latest logic

`compute_review_metrics` counts each candidate's **latest** ReviewDecision:

```text
accepted  ← latest.decision_status == "accepted"
rejected  ← latest.decision_status == "rejected"
modified  ← latest.decision_status == "modified"
deferred  ← latest.decision_status == "deferred"   (new, distinct bucket)
pending   ← no decision yet
completion_rate = resolved / total;  accuracy_rate = accepted / (accepted+rejected+modified)
```

The audit trail is untouched: `decisions` history per candidate is still returned by every read path, and the real-Neo4j test asserts both decisions + the `SUPERSEDES` chain after a second append.

## 5. Tests (TDD red → green)

New `backend/tests/test_review_decision_semantics.py` — 22 tests:

| Group | Tests | Red proof |
| :--- | :--- | :--- |
| Generation status | rule / LLM (model echoes `confirmed`) / VLM unresolved-path candidates always `pending_review` | passed pre-change (existing guards; locked in) |
| Decision vocabulary | literal is exactly 4 values; repo rejects 8 non-4-value inputs (`accept`/`reject`/`modify`/`confirm`/`confirmed`/`layout_noise`/`pending_review`/`?()`); accepts the 4 | `ReviewDecisionValue` import failed (RED) |
| Append-only | `save_review_decision` cypher contains no `SET cand.status` / `cand.status = $candidate_status`, keeps `HAS_DECISION` + `SUPERSEDES`; `previous_decision_id` persisted | query-shape assertions failed (RED) |
| latest_decision | helper returns newest-by-created_at / None; `get_candidate` + `get_candidates` expose `latest_decision` alongside full `decisions` history | `latest_decision` key absent (RED) |
| Metrics | latest decision across history (accept→reject ⇒ rejected=1, accepted=0); deferred distinct bucket; layout_noise never counts as rejection | `compute_review_metrics` NameError (RED) |
| Real Neo4j (optional) | two decisions ⇒ both exist, latest = 2nd, `(dec2,dec1)` + `(dec1,None)` chain rows, candidate.status still `pending_review`; scoped `dec_test_*` ids, DETACH DELETE cleanup in `finally`, skips when `NEO4J_PASSWORD` unset | skipped in this env |

**Before:** 458 passed / 7 skipped / 8 errors (8 = `NEO4J_TEST_URI` infra gates).
**After:** `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/integration` → **481 passed / 8 skipped / 8 errors** (+23 passed, +1 skip; the 8 errors are the identical `test_project_repository.py` infra gates — untouched). `pytest ../tests/compose -q` → 6 passed / 1 skipped (unchanged). Frontend: vitest **5/5**, `npm run build` OK, `tsc --noEmit` clean.

## 6. Existing test edits (each reported)

`backend/tests/test_reviews_api.py`:
1. `FakeReviewRepository.save_review_decision` — removed candidate-status mutation (`confirmed`/`layout_noise` mapping); now validates the 4-value set, appends, sets `latest_decision`, `created_at` (mirrors Gate F repo contract).
2. `FakeReviewRepository.get_metrics` — status-based counting replaced with latest-decision counting + `deferred_candidates` (mirrors `compute_review_metrics`).
3. `seed_candidate` — added `"latest_decision": None` default.
4. Fixture `cand_2` seeded with `status="confirmed"` → `"pending_review"` (generation status only; old value contradicted Gate F).
5. `test_record_accept_decision` — `decision:"accept"` → `"accepted"`; asserts `decisionStatus == "accepted"`, candidate stays `pending_review`, `latest_decision` accepted.
6. `test_record_reject_decision` — `"reject"` → `"rejected"`; asserts candidate stays `pending_review`, latest rejected (no `layout_noise`).
7. `test_record_modify_decision_and_audit_trail_supersedes` — `"modify"` → `"modified"`; `previousDecisionId` chain intact; candidate status stays `pending_review`; `proposed_text` propagation kept.
8. `test_record_decision_missing_candidate_returns_404` — payload `"accept"` → `"accepted"` (keeps testing 404, not 422).
9. **New** `test_record_decision_rejects_layout_noise_as_decision_value` (422 for `layout_noise` and `confirmed`) + **new** `test_record_defer_decision`.
10. `test_list_candidates_filter_by_status` — both fixtures now `pending_review` ⇒ total 2.
11. `test_get_review_metrics` → `test_get_review_metrics_uses_latest_decision` — baseline (2 pending / 0 accepted) then accept one ⇒ accepted=1 / pending=1.

Untouched existing decision-related tests (already Gate F-compatible): `test_evidence_traceability.py` (uses `decision_status: "accepted"` fixtures), `test_canonical_repository.py::test_review_repository_extensions` (`decision_status="accepted"`), `test_ai_review_service.py` (already enforces pending_review), `test_rule_engine.py` (already asserts non-confirmed statuses).

## 7. Anti-pattern #11 verification

```bash
grep -rn "layout_noise" backend/app   # only review_models.py:25 (Literal) + rule_engine.py:263 (summary counter)
grep -rn "layout_noise" frontend/src  # only CSS class names (styles.css)
```
`layout_noise` is accepted nowhere as an expert decision value: API validator 422s it, repo raises `ValueError`, frontend never sends it.

## 8. Constraints

- `src/` untouched; no subagents; no web; no bare `except`; real-Neo4j writes only under scoped `dec_test_*` ids with cleanup in `finally`.
- Commit: `acd57de` — `feat(canonical): restore append-only expert decision semantics separate from candidate generation`.
