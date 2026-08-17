# Canonical Identity Path Report — Evidence Graph Frontend (review §11)

**Date:** 2026-08-17
**Branch:** `windows-docker-foundation`
**Review source:** `docs/superpowers/reviews/2026-08-17-neo4j-frontend-mvp-code-review.md` — §11 "Evidence Graph Frontend — Expand to Canonical Identity Path", anti-patterns #7/#10, Mandatory Test D, Definition of Done "Frontend" (canonical graph identity path is visible).
**Commit:** `fad62ab` — `feat(canonical): expose canonical reference identity path in candidate traceability`

## Goal

Close review §11: the graph UI must expose the canonical identity path so a reviewer understands **why this particular image or drawing was chosen**:

```text
TextBlock / Caption
     ↓ REFERENCES
Reference
     ↓ RESOLVES_TO
Plate / Drawing
     ↓ DEPICTS
ArchaeologyObject
```

The critical anti-pattern #7/#10 constraint is that the frontend renders **only** edges the backend actually returns from Neo4j — no invented relationships. This therefore required a **backend change first** (extend `get_candidate_traceability`), then the frontend consumes the new field.

## Files Changed

| File | Change |
| --- | --- |
| `backend/app/graph/review_repository.py` | `get_candidate_traceability` now traverses the canonical identity path (TextBlock/Caption → REFERENCES → Reference → RESOLVES_TO → Plate/PlatePanel/Drawing/DrawingRegion → DEPICTS → ArchaeologyObject) and returns a structured `canonical_path` list. Existing traceability fields unchanged (additive). |
| `backend/app/api/schemas.py` | `TraceabilityResponse` gains `canonical_path: list[dict[str, Any]]` (alias `canonicalPath`, default `[]`) — additive. |
| `backend/tests/test_evidence_traceability.py` | +3 unit tests: canonical_path returned when the graph has the edges; empty when the graph lacks them; defaults empty when rows absent (backward compatible). |
| `backend/tests/integration/test_review_traceability_graph.py` | +1 real-Neo4j integration test (`cip_test_*` scoped, finally-cleanup) asserting the full REFERENCES/RESOLVES_TO/DEPICTS path is returned from the real DB. |
| `frontend/src/api.ts` | New `CanonicalPathEdge` type + `canonicalPath`/`canonical_path` fields on `TraceabilityResponse`. |
| `frontend/src/components/EvidenceGraphExplorer.tsx` | Consumes `canonical_path`; new `text_source`/`reference` node kinds; renders the canonical identity path chains (TextBlock → REFERENCES → Reference → RESOLVES_TO → Plate/Drawing → DEPICTS → ArchaeologyObject) only when the backend returned them; canonical asset label (【도판 45】/【도면 30】) as a node. |
| `frontend/src/components/EvidenceGraphExplorer.test.tsx` | +3 tests: renders canonical path edges from a `canonical_path` payload; does NOT render them when omitted; `buildGraphModel` adds edges only when present. |
| `frontend/src/styles.css` | Styles for `canonical-path-section`/`canonical-path-row` and `node-text_source`/`node-reference`. |

## canonical_path response shape (verbatim)

`get_candidate_traceability` returns the existing fields unchanged and adds one new field:

```json
{
  "candidate": { "...": "unchanged" },
  "archaeology_object": { "...": "unchanged" },
  "evidence": [ "...": "unchanged" ],
  "decisions": [ "...": "unchanged" ],
  "latest_decision": { "...": "unchanged" },
  "canonical_path": [
    {
      "from": "<source node id>",
      "from_label": "TextBlock | Caption",
      "edge": "REFERENCES",
      "to": "<reference id>",
      "to_label": "Reference",
      "source": { "...source node properties (id, text, physical_page, ...)" },
      "target": { "...reference node properties (id, ref_type, number, raw_text, ...)" }
    },
    {
      "from": "<reference id>",
      "from_label": "Reference",
      "edge": "RESOLVES_TO",
      "to": "<plate/drawing id>",
      "to_label": "Plate | PlatePanel | Drawing | DrawingRegion",
      "source": { "...reference node properties" },
      "target": { "...target node properties (id, number, raw_identifier, title, ...)" }
    },
    {
      "from": "<plate/drawing id>",
      "from_label": "Plate | PlatePanel | Drawing | DrawingRegion",
      "edge": "DEPICTS",
      "to": "<archaeology object id>",
      "to_label": "ArchaeologyObject",
      "source": { "...target node properties" },
      "target": { "...object node properties (id, canonical_name, site, period, ...)" }
    }
  ]
}
```

Semantics:

- `canonical_path` is a flat list of **edge objects** — one entry per real relationship the traversal found. Each entry carries `from`/`to` node ids, their labels, and the full node properties (`source`/`target`) so the frontend can render the nodes without synthesizing data.
- The traversal anchors on the candidate's `ABOUT` ArchaeologyObject and the candidate evidence's `EXTRACTED_FROM` page:
  - source nodes = `(source)-[:MENTIONS]->(obj)` **or** `(page)-[:HAS_BLOCK|HAS_CAPTION]->(source)`
  - `(source)-[:REFERENCES]->(ref)`
  - `(ref)-[:RESOLVES_TO]->(target)` where target ∈ {Plate, PlatePanel, Drawing, DrawingRegion}
  - `(target)-[:DEPICTS]->(depicted)` restricted to the candidate's ABOUT object when present (`obj IS NULL OR depicted.id = obj.id`)
- **Only relationships that exist are returned.** When the graph lacks any of them, `canonical_path` is `[]` — nothing is synthesized (anti-pattern #7/#10).
- The API schema exposes it as `canonicalPath` (camelCase alias) with `canonical_path` accepted on input; default `[]` keeps older payloads valid.

## Frontend graph mapping

`EvidenceGraphExplorer.buildGraphModel` consumes `traceability.canonical_path` (or `canonicalPath`) and maps each edge to nodes + an edge:

| Backend `canonical_path` entry | Frontend node(s) | Frontend edge |
| --- | --- | --- |
| `from_label` TextBlock/Caption | `text_source` node (title = text snippet, subtitle "본문/캡션 소스") | `REFERENCES` |
| `to_label` Reference | `reference` node (title = `참조 {ref_type} {number}`) | — |
| `from_label` Reference | `reference` node | `RESOLVES_TO` |
| `to_label` Plate/PlatePanel/Drawing/DrawingRegion | `canonical_asset` node (title = `raw_identifier` e.g. 【도판 45】, else 【도판 N】/【도면 N】) | — |
| `from_label` Plate/PlatePanel/Drawing/DrawingRegion | `canonical_asset` node | `DEPICTS` |
| `to_label` ArchaeologyObject | `arch_obj` node (deduped with the ABOUT object node) | — |

- Nodes are deduped by id (`pushNode`), so the DEPICTS target reuses the existing `arch_obj` node from the `ABOUT` edge — the graph shows `Candidate ─ABOUT→ Object ←DEPICTS─ Plate ←RESOLVES_TO─ Reference ←REFERENCES─ TextBlock`.
- `buildCanonicalChains` reconstructs linear chains from the flat edge list and renders each chain in a "CANONICAL IDENTITY PATH" section as `node → edge → node → ...`.
- The pre-existing visual-bundle DEPICTS section is now gated on `visualBundle?.canonical` being present (it previously triggered whenever any `canonical_asset` node existed, which would double-render DEPICTS once the canonical path also produced one).

## Anti-pattern #7/#10 verification

- **#7 (frontend invents relationships):** the frontend renders `REFERENCES`/`RESOLVES_TO`/`DEPICTS` **only** when the backend `canonical_path` payload contains those edges. The unit test "does not render canonical path edges when the payload omits canonical_path" and the existing "does not fabricate RESOLVES_TO / DEPICTS / REFERENCES edges" both assert no invented labels.
- **#10 (VLM converts PARTIAL into identity):** not applicable to this change — no VLM path is touched; the canonical path is purely graph-derived and read-only.
- Backend never synthesizes: `canonical_path` is built strictly from `canonical_path_rows` returned by the Cypher traversal; a graph without the relationships yields `[]` (unit test + backward-compat test).

## Tests (before → after)

| Test | Verifies |
| --- | --- |
| `test_get_candidate_traceability_returns_canonical_path_when_graph_has_edges` | canonical_path contains REFERENCES/RESOLVES_TO/DEPICTS with correct from/to/labels/properties when the graph has them. |
| `test_get_candidate_traceability_returns_empty_canonical_path_when_graph_lacks_edges` | canonical_path is `[]` (no invented edges) when the graph lacks them. |
| `test_get_candidate_traceability_canonical_path_defaults_empty_when_rows_absent` | Older payloads without `canonical_path_rows` still return `[]` and keep all existing fields. |
| `test_real_neo4j_canonical_identity_path_in_traceability` (integration, `cip_test_*`) | Real Neo4j: full TextBlock→REFERENCES→Reference→RESOLVES_TO→Plate→DEPICTS→Object path returned; scoped ids cleaned in finally. |
| `EvidenceGraphExplorer` renders canonical identity path edges from a `canonical_path` payload | `graph-edge-REFERENCES`/`RESOLVES_TO`/`DEPICTS` + `graph-node-text_source`/`reference`/`canonical_asset` + 【도판 45】 label. |
| `EvidenceGraphExplorer` does not render canonical path edges when omitted | No invented REFERENCES/RESOLVES_TO/DEPICTS/text_source/reference. |
| `buildGraphModel` adds canonical path edges only when present | Model-level assertion. |
| Regression | Existing traceability + graph tests unchanged and passing. |

**Backend before:** 532 passed, 10 skipped, 8 errors (infra guards). **After:** 535 passed (+3), 10 skipped, 8 errors (same infra guards) — 0 new failures.
**Integration before:** 9 skipped. **After:** 10 skipped (no local Neo4j; new test collects cleanly and runs when `NEO4J_PASSWORD` is set).
**Frontend before:** 22 passed. **After:** 25 passed (+3), `npx tsc --noEmit` clean, `npm run build` exit 0.

## Verification

- `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/integration` → **535 passed, 10 skipped, 8 errors** (same 8 infra guards; 0 new failures).
- `cd backend && .venv/bin/python -m pytest tests/integration -q` → **10 skipped** (real-Neo4j suite; new `cip_test_*` test included, runs when Neo4j is available).
- `cd frontend && npm test -- --run` → **25 passed**.
- `cd frontend && npm run build` → **exit 0**; `npx tsc --noEmit` → clean.

## Existing-test edits (strictly required)

- None of the existing tests were modified. The existing `test_get_candidate_traceability_traversal` (asserts `len(driver.queries) == 1`) still passes because the canonical path traversal was added to the **same** Cypher query (single `execute_query`), and its fake record simply lacks `canonical_path_rows` → `canonical_path == []`.

## Review §11 status

**Review §11 is now CLOSED.** The Evidence Graph frontend exposes the canonical identity path (TextBlock/Caption → REFERENCES → Reference → RESOLVES_TO → Plate/Drawing → DEPICTS → ArchaeologyObject) driven entirely by the backend `canonical_path` field, with the canonical asset label (【도판 45】/【도면 30】) rendered as a node, and only edges the backend actually returns from Neo4j are rendered (anti-patterns #7/#10 satisfied).
