# Task 15 Report — Render Real Graph Traceability Paths Without Fabricated Edges (commit `b5240aa`)

**Branch:** `windows-docker-foundation` (HEAD `b5240aa`, base `39dc72c`)
**Date:** 2026-08-17
**Scope:** Plan Task 15 — Gate E. `EvidenceGraphExplorer` now visualizes only the actual API-returned nodes/edges from Neo4j. No synthesized nodes/relations when fields are absent; bbox/source_sha256 render as node property chips, never as invented `HAS_BBOX`/`VERIFIED_HASH` edges (anti-pattern #10).
**Method:** Read the backend `get_candidate_traceability` response shape first, then mapped the UI to those exact fields. No `src/` access, no backend edits, no subagents, no web, no bare `any`/`ts-ignore`.

---

## 1. Files changed per deliverable

| Deliverable | File | Change |
| :--- | :--- | :--- |
| 1. Real graph data rendering | `frontend/src/components/EvidenceGraphExplorer.tsx` | **Rewritten** around a data-driven `buildGraphModel(candidate, traceability)` that consumes ONLY the API-returned traceability payload. Renders candidate → `ABOUT` → archaeology_object; `SUPPORTED_BY` → evidence → `EXTRACTED_FROM` → page; `FROM_VERSION` → document_version; `HAS_DECISION` → decision. |
| 2. No fabricated edges | `frontend/src/components/EvidenceGraphExplorer.tsx` | Removed the hardcoded `[:HAS_BBOX]` and `[:VERIFIED_HASH]` edges and the wrong `[:SUPPORTED_BY]/[:FROM_VERSION]/[:EXTRACTED_FROM]/[:ABOUT]` ordering. An edge is drawn **only** when the target node is present in the payload. bbox/source_sha256 are rendered as `property-chip` on the evidence node. |
| 3. Traceability display | `frontend/src/components/EvidenceGraphExplorer.tsx` | Linear chain candidate → evidence (kind/value/confidence as properties) → page (physical/printed) → version (stage); archaeology object and decisions rendered as branches off the candidate via `ABOUT`/`HAS_DECISION`. Property chips render from actual returned properties. |
| 4. Node/edge from API only | `frontend/src/components/EvidenceGraphExplorer.tsx` | Input is the traceability JSON the API returns; `buildGraphModel` is exported for direct unit testing of the edge set. |
| 4. (cont.) | `frontend/src/api.ts` | **Additive** type fields reflecting the real backend payload: `ArchaeologyObject.canonical_name/site/period` and `Evidence.document_version.sha256`. |
| 4. (cont.) | `frontend/src/styles.css` | Added `.pathway-segment`, `.graph-branches`, `.branch-row`, `.node-chip-row`, `.property-chip`, `.chip-key`, `.chip-value` styles. |
| 5. Tests | `frontend/src/components/EvidenceGraphExplorer.test.tsx` | **New** — 7 tests (see §5). |

`src/` untouched; backend untouched.

## 2. Traceability payload → UI mapping

Backend `get_candidate_traceability` (read from `backend/app/graph/review_repository.py` ~723-776) returns:

```json
{
  "candidate": { "id", "rule_category", "change_type", "status", "original_text", "proposed_text", "confidence", ... },
  "archaeology_object": { "id", "canonical_name", "site", "period", ... } | null,
  "evidence": [
    {
      "id", "kind", "source_sha256", "document_version_id", "page_id", "bbox",
      "method", "value", "rationale", "confidence",
      "page": { "id", "physical_page", "printed_page", "header", ... } | null,
      "document_version": { "id", "sha256", "stage", ... } | null
    }
  ],
  "decisions": [...],
  "latest_decision": {...}
}
```

The Cypher in `get_candidate_traceability` only ever traverses these relationships:

```text
(cand)-[:ABOUT]->(obj:ArchaeologyObject)
(cand)-[:SUPPORTED_BY]->(ev:Evidence)
(ev)-[:EXTRACTED_FROM]->(page:Page)
(ev)-[:FROM_VERSION]->(doc_ver:DocumentVersion)
(cand)-[:HAS_DECISION]->(dec:ReviewDecision)
```

| Backend field | UI node | UI edge | UI property chips |
| :--- | :--- | :--- | :--- |
| `candidate` | CorrectionCandidate node | — | id, rule_category, status, original_text, proposed_text, confidence |
| `archaeology_object` (when present) | ArchaeologyObject node | `ABOUT` (from candidate) | id, canonical_name, title, object_type, site, period |
| `evidence[]` | Evidence node | `SUPPORTED_BY` (from candidate) | id, kind, value, confidence, method, rationale; **chips:** bbox, source_sha256 |
| `evidence[].page` (when present) | Page node | `EXTRACTED_FROM` (from evidence) | id, physical_page, printed_page, header |
| `evidence[].document_version` (when present) | DocumentVersion node | `FROM_VERSION` (from evidence) | id, stage, sha256 |
| `decisions[]` | ReviewDecision node | `HAS_DECISION` (from candidate) | id, decision_status, reviewer, note, created_at, previous_decision_id |

## 3. Anti-pattern #10 confirmation — no fabricated edges

- The production component contains **zero** occurrences of `HAS_BBOX`, `VERIFIED_HASH`, `RESOLVES_TO`, `DEPICTS`, or `REFERENCES` as edge labels (verified by grep — the only matches are in the test file asserting they are **not** rendered).
- `REFERENCES`/`RESOLVES_TO`/`DEPICTS` are not returned by `get_candidate_traceability`, so the explorer never draws them.
- bbox and source_sha256 exist only as `Evidence` node properties in the payload → rendered as `property-chip` on the evidence node, not as edges.
- An edge is emitted only when its target node is present: a payload with evidence but no page/document_version/archaeology_object renders only `SUPPORTED_BY` (no `EXTRACTED_FROM`/`FROM_VERSION`/`ABOUT`).

## 4. Design

`buildGraphModel(candidate, traceability)` is a pure function returning `{ nodes, edges }`. It walks the payload and pushes a node + edge only for relationships whose target is actually present. The component renders the active evidence's linear chain (candidate → evidence → page → version) in the horizontal pathway, and archaeology object + decisions as branches off the candidate. The detail inspector is data-driven from the selected node's `properties`. The decision section reuses the existing `dec-node-card` markup.

## 5. Tests (vitest, follow existing patterns)

New `frontend/src/components/EvidenceGraphExplorer.test.tsx` — 7 tests:

| Group | Tests | Red proof |
| :--- | :--- | :--- |
| Real graph rendering | renders candidate/evidence/page/version/object/decision nodes from a real-shaped payload | new component (RED) |
| Real edges only | renders exactly `ABOUT`/`SUPPORTED_BY`/`EXTRACTED_FROM`/`FROM_VERSION`/`HAS_DECISION` | new component (RED) |
| No fabricated edges | no `RESOLVES_TO`/`DEPICTS`/`REFERENCES` edge or text | new component (RED) |
| Properties as chips | no `HAS_BBOX`/`VERIFIED_HASH` edge or text; `bbox`/`source_sha256` chips present | new component (RED) |
| Absent nodes → no edges | sparse payload renders only `SUPPORTED_BY`; no `ABOUT`/`EXTRACTED_FROM`/`FROM_VERSION`/arch_obj/page/doc_ver | new component (RED) |
| `buildGraphModel` edge set | edges exactly match payload relationships | new helper (RED) |
| `buildGraphModel` chips | bbox/source_sha256 are chips, never edges | new helper (RED) |

**Existing test edits:** none. `ProjectDetailPage.test.tsx` untouched (regression — still passes).

## 6. Verification

- `cd frontend && npm test -- --run` → **2 files / 12 tests passed** (7 new + 5 existing).
- `npm run typecheck` (`tsc --noEmit`) → clean.
- `npm run build` → exit 0 (dist built).
- Backend untouched: `cd ../backend && .venv/bin/python -m pytest tests -q --ignore=tests/integration` → **481 passed / 8 skipped / 8 errors** (the 8 errors are the identical `test_project_repository.py` infra gates — unchanged).

## 7. Constraints

- `src/` untouched; no backend edits; no subagents; no web; no bare `any`/`ts-ignore`; only additive type changes to `frontend/src/api.ts`.
- Commit: `b5240aa` — `feat(ui): render real graph traceability paths without fabricated edges`.