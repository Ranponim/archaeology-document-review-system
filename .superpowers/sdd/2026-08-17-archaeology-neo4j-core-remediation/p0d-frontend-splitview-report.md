# P0-D Report — Real Expert Visual Review UI (Frontend)

**Date:** 2026-08-17
**Branch:** `windows-docker-foundation`
**Review source:** `docs/superpowers/reviews/2026-08-17-neo4j-frontend-mvp-code-review.md` — Phase P0-D (§13), §9 Real Split View, §11 Evidence Graph canonical identity path, Mandatory Test D, §6.3 severity filter, §6.4 retry, §8.2 analysis readiness, anti-patterns #7/#10/#13/#15, Definition of Done "Frontend".
**Backend contract:** `p0d-backend-visual-api-report.md` (11 routes + metadata JSON + provenance bundle shape).

## Goal

A reviewer must see the ACTUAL body page, ACTUAL plate/photo, and ACTUAL drawing region used by the system, with highlighted provenance, before making the final decision — without opening external files. This report covers the frontend half of Phase P0-D.

## Files Changed (per deliverable)

| File | Change |
| --- | --- |
| `frontend/src/api.ts` | Added `VisualAssetMetadata`, `CandidateVisualBundle`, `RetryAnalysisRunResponse` types + `fetchVisualBundle()` + `retryAnalysisRun()` fetch functions. |
| `frontend/src/components/VisualAssetPane.tsx` | **New** — renders one visual asset (image + bbox highlight overlay + metadata) with `bboxOverlayStyle()` helper. |
| `frontend/src/components/SplitViewInspector.tsx` | Upgraded to a real visual split view: fetches/consumes the `visual-bundle`, renders the body page image + source bbox (left), the canonical plate/photo panel image + panel bbox (right), and a full-width Canonical Drawing section when the canonical asset is a drawing. |
| `frontend/src/components/EvidenceGraphExplorer.tsx` | Added the canonical identity path: the visual-bundle `canonical` asset →DEPICTS→ ArchaeologyObject, rendered only when the backend returns it. |
| `frontend/src/pages/ProjectDetailPage.tsx` | Fetches the visual bundle per candidate and passes it to both the split view and the graph; added retry button for retryable failed runs; removed the silent severity filter; added an analysis-readiness gate that disables 검수 시작 when a selected version's ingest failed. |
| `frontend/src/styles.css` | Added styles for the visual asset pane, bbox overlay, drawing pane, canonical identity section, retry button, and readiness warning. |
| `frontend/src/components/SplitViewInspector.test.tsx` | **New** — split view + bbox tests. |
| `frontend/src/components/EvidenceGraphExplorer.test.tsx` | Added canonical identity path tests. |
| `frontend/src/pages/ProjectDetailPage.test.tsx` | Added retry + severity-honesty tests. |

## visual-bundle → UI mapping (which backend fields become which elements)

| Backend field | UI element |
| --- | --- |
| `source.imageUrl` | Left pane `<img>` (본문 PDF — 실제 렌더 페이지) |
| `source.bbox` + `source.renderWidth/Height` | Left pane bbox highlight overlay |
| `source.sourceSha256` | Left pane "원본 SHA-256" |
| `source.physicalPage` / `source.printedIdentifier` | Left pane "물리 페이지" / "인쇄 식별자" |
| `candidate.original_text` | Left pane selected text claim (existing) |
| `canonical.imageUrl` | Right pane `<img>` (표준 도판/사진 — 실제 패널 이미지) |
| `canonical.bbox` + `canonical.renderWidth/Height` | Right pane panel bbox highlight overlay |
| `canonical.printedIdentifier` | Right pane "인쇄 식별자" (【도판 45】) |
| `canonical.caption` | Right pane "캡션" (panel caption) |
| `canonical.assetType` ∈ drawing/drawing_region | Full-width Canonical Drawing section below the two panes |
| `canonical` (DEPICTS asset) | Evidence graph canonical identity path node + DEPICTS edge |

## Bbox overlay math

`bbox` is normalized (0..1, PDF top-left origin). `bboxOverlayStyle()` positions the overlay with **percentages** so it stays aligned with the image at any display size, and exposes the **pixel values derived from `renderWidth`/`renderHeight`** as CSS custom properties for auditability:

```text
left   = bbox[0] * 100%            (--bbox-left-px   = bbox[0] * renderWidth)
top    = bbox[1] * 100%            (--bbox-top-px    = bbox[1] * renderHeight)
width  = (bbox[2]-bbox[0]) * 100%  (--bbox-width-px  = (bbox[2]-bbox[0]) * renderWidth)
height = (bbox[3]-bbox[1]) * 100%  (--bbox-height-px = (bbox[3]-bbox[1]) * renderHeight)
```

The image frame uses `aspect-ratio: renderWidth / renderHeight` with `object-fit: fill`, so the percentage overlay aligns with the rendered image. The test asserts both the normalized percentage position and the renderWidth/Height-derived pixel custom properties.

## Graph canonical-path addition

The backend `get_candidate_traceability` returns candidate / archaeology_object / evidence / page / document_version / decisions — it does **not** return the intermediate `TextBlock/Caption → REFERENCES → Reference → RESOLVES_TO` nodes. Per anti-pattern #7/#10, the frontend must not invent those. The backend **does** return the canonical visual asset via the `visual-bundle` endpoint, which the backend report identifies as the DEPICTS asset (`(cand)-[:ABOUT]->(obj)<-[:DEPICTS]-(asset)`).

Therefore `EvidenceGraphExplorer` now renders the canonical identity path **to the extent the backend returns it**:

```text
CanonicalAsset (PlatePanel/DrawingRegion/Plate/Drawing)
        │ DEPICTS
        ▼
   ArchaeologyObject
```

- New `canonical_asset` node kind, rendered in a dedicated "CANONICAL IDENTITY PATH" section connected to the ArchaeologyObject via a `DEPICTS` edge.
- The node carries `printedIdentifier` (【도판 45】), `caption`, `assetType`, `regionId`, `sourceSha256`, and a `bbox` chip.
- The edge/node are rendered **only** when `visualBundle.canonical` is present; otherwise nothing is fabricated (existing test "does not fabricate RESOLVES_TO / DEPICTS / REFERENCES edges" still passes).

## Retry (6.4)

- `retryAnalysisRun(projectId, analysisRunId)` → `POST /api/projects/{project_id}/analysis-runs/{analysis_run_id}/retry`.
- In the run list, a run with `status === 'failed' && retryable === true` shows a `[재시도]` button that calls the endpoint and then refreshes the project detail.

## Severity filter honesty (6.3 / anti-pattern #13)

The backend `get_candidates` accepts a `severity` parameter but its Cypher query does **not** filter on `cand.severity` — the filter was a silent no-op. Per anti-pattern #13, the severity filter was **removed** from the UI (state, request param, and the `<select>`). A test asserts no silent severity filter is presented.

## Analysis readiness (§8.2)

A readiness gate disables the `[새 검수 실행]` button and shows a warning when any selected version's ingest run has `status === 'failed'` (canonical graph ingestion failed). The full §8.1 kind×stage document matrix was not added because the backend `ProjectDetailResponse` does not expose per-version page count / sha / graph ingest counts; the readiness gate is the feasible subset with available data.

## Tests (before → after)

| Test | Verifies |
| --- | --- |
| `SplitViewInspector` renders body page + panel images from the visual-bundle | Both `<img src>` point to the render routes (`/api/v1/assets/pages/.../render`, `/api/v1/assets/plate-panels/.../render`), NOT filesystem paths (anti-pattern #15). |
| bbox highlight renders at correct normalized position | Overlay style uses renderWidth/Height (percentage position + `--bbox-*-px` custom properties). |
| canonical drawing renders in the drawing section | When `canonical.assetType` is a drawing, the drawing `<img>` points to the drawing-region render route. |
| graph shows canonical identity path when present | `graph-node-canonical_asset` + `graph-edge-DEPICTS` rendered when `visualBundle.canonical` exists. |
| graph does NOT invent canonical path when absent | No `canonical_asset` node / `DEPICTS` edge when the visual-bundle is absent. |
| retry button appears for retryable failed run | `[재시도]` shown and `retryAnalysisRun('proj_1', 'run_fail')` called. |
| severity filter removed | No silent no-op severity filter presented. |
| regression | Existing 14 tests still pass. |

**Before:** 14 passed. **After:** 22 passed (14 baseline + 8 new).

## Verification

- Frontend: `cd frontend && npm test -- --run` → **22 passed**; `npm run build` → **OK** (exit 0); `npx tsc --noEmit` → clean.
- Backend untouched: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/integration` → **532 passed, 10 skipped, 8 errors** (the 8 errors are the pre-existing infra guards requiring `NEO4J_TEST_URI`; 0 new failures).

## Commit

`feat(ui): render real visual split view with highlighted provenance and canonical identity path`
