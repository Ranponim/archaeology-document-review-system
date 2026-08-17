# P0-D Report — Evidence Visual Asset Delivery API (Backend)

**Date:** 2026-08-17
**Branch:** `windows-docker-foundation`
**Review source:** `docs/superpowers/reviews/2026-08-17-neo4j-frontend-mvp-code-review.md` — Phase P0-D (§13), §10 Required Asset/Evidence API, §9 Real Split View, Mandatory Test D, Anti-pattern #15, Definition of Done "Frontend" + "Photo/Plate" + "Drawing".

## Goal

Expose complete visual asset delivery so the frontend can render the REAL body page, plate/photo panel, and drawing region that a candidate is based on — WITHOUT exposing arbitrary filesystem paths to the browser (anti-pattern #15). Serve actual image bytes via authenticated-ish routes keyed by graph node id; render body pages on demand from the stored DocumentVersion PDF and cache; return a provenance bundle (Test D) so the frontend can render both images and highlight both bboxes.

## Routes Implemented (verbatim paths)

| Route | Returns |
| --- | --- |
| `GET /api/v1/assets/pages/{page_id}/render` | body page PNG bytes (on-demand render + cache) |
| `GET /api/v1/assets/pages/{page_id}/metadata` | JSON contract |
| `GET /api/v1/assets/plates/{plate_id}/render` | full plate page PNG bytes |
| `GET /api/v1/assets/plates/{plate_id}/metadata` | JSON contract |
| `GET /api/v1/assets/plate-panels/{panel_id}/render` | cropped panel JPEG bytes |
| `GET /api/v1/assets/plate-panels/{panel_id}/metadata` | JSON contract |
| `GET /api/v1/assets/drawings/{drawing_id}/render` | full drawing page PNG bytes |
| `GET /api/v1/assets/drawings/{drawing_id}/metadata` | JSON contract |
| `GET /api/v1/assets/drawing-regions/{region_id}/render` | cropped region JPEG bytes |
| `GET /api/v1/assets/drawing-regions/{region_id}/metadata` | JSON contract |
| `GET /api/v1/projects/{project_id}/candidates/{candidate_id}/visual-bundle` | Test D provenance bundle |

## Metadata Contract

```json
{
  "assetType": "plate_panel",
  "imageUrl": "/api/v1/assets/plate-panels/{panel_id}/render",
  "documentVersionId": "ver_plate",
  "sourceSha256": "sha256_plate",
  "physicalPage": 47,
  "printedIdentifier": "【도판 45】",
  "regionId": "plate_45_panel_1",
  "bbox": [0.1, 0.1, 0.5, 0.5],
  "caption": "조사 전",
  "renderWidth": 1191,
  "renderHeight": 1684,
  "contentType": "image/jpeg"
}
```

- `imageUrl` is a **relative API path** to the render route — never a server filesystem path (anti-pattern #15).
- `bbox` is **normalized (0..1, PDF top-left origin)** for plate panels / drawing regions; the frontend overlays the highlight as `left = bbox[0]*renderWidth`, `top = bbox[1]*renderHeight`, etc.
- `renderWidth`/`renderHeight` are the **full page render dimensions** (the coordinate space the normalized bbox lives in).
- `assetType` ∈ `page | plate | plate_panel | drawing | drawing_region`.
- For a body page, `printedIdentifier` is the printed page number; for plates/drawings it is the canonical `【도판 N】` / `【도면 N】` raw identifier.

## Render-On-Demand + Cache Design

Body pages are never pre-rendered at ingest. `VisualAssetService._resolve_page_render`:

1. Resolves the stored DocumentVersion PDF: `DATA_ROOT / version.uri` (or the absolute uri if it is already a real path).
2. Checks the cache `derived/body_renders/{version_id}/p{physical_page:03d}.png`; returns it if present and non-empty.
3. Otherwise renders the physical page with PyMuPDF at `zoom = max(2.0, 1191/page_width)` (same convention as PlateParser/DrawingParser Task 9 / P0-C), writes the PNG under the derived dir, and returns the cached path.

Plates/drawings prefer an existing child (panel/region) `render_uri` page render; if none exists they render on demand from the plate/drawing version PDF. Panels/regions crop the full page render with `ImageProcessor.crop_region_full` (new method — crops WITHOUT resizing, serving the actual region at full resolution; `crop_region` keeps its VLM 768px behavior).

## Provenance Bundle (Mandatory Test D)

`GET /api/v1/projects/{project_id}/candidates/{candidate_id}/visual-bundle` returns both sides together:

```json
{
  "candidateId": "cand_1",
  "source": {
    "assetType": "page",
    "imageUrl": "/api/v1/assets/pages/ver_body_p10/render",
    "documentVersionId": "ver_body",
    "sourceSha256": "sha256_body",
    "physicalPage": 10,
    "printedIdentifier": "10",
    "regionId": "ver_body_p10",
    "bbox": [0.1, 0.1, 0.5, 0.2],
    "renderWidth": 1191,
    "renderHeight": 1686
  },
  "canonical": {
    "assetType": "plate_panel",
    "imageUrl": "/api/v1/assets/plate-panels/plate_45_panel_1/render",
    "documentVersionId": "ver_plate",
    "sourceSha256": "sha256_plate",
    "physicalPage": 47,
    "printedIdentifier": "【도판 45】",
    "regionId": "plate_45_panel_1",
    "bbox": [0.1, 0.1, 0.5, 0.5],
    "caption": "조사 전",
    "renderWidth": 1191,
    "renderHeight": 1684
  }
}
```

- **source** = the candidate's evidence chain: `(cand)-[:SUPPORTED_BY]->(ev)-[:EXTRACTED_FROM]->(page)` + `(ev)-[:FROM_VERSION]->(version)`. The source bbox (absolute PDF points from the evidence) is **normalized against the PDF page rect** so the frontend overlays it the same way as the canonical bbox.
- **canonical** = the DEPICTS visual asset: `(cand)-[:ABOUT]->(obj)<-[:DEPICTS]-(asset)` with the parent Plate/Drawing `raw_identifier`.
- Both sides carry `imageUrl` + `bbox` + `sourceSha256` + `renderWidth/Height`, so the frontend renders both images and highlights both bboxes (review §9 split view).

## Anti-pattern #15 Verification

- Render routes serve **image bytes** (`Response(content=bytes, media_type=...)`) — never a path.
- Metadata routes return `imageUrl` as a relative `/api/v1/assets/...` path. The only place `image_url` is constructed is `f"/api/v1/assets/{route}/{node_id}/render"`.
- `render_uri` / `data_root` are used **internally only** to read files from disk; they are never serialized into a response.
- Test `test_no_route_response_contains_filesystem_path` scans every metadata + render response and asserts no `/data/`, `/Users/`, `/tmp/`, `/var/`, `/private/`, or `file://` string appears.

## Fail-Closed

- Missing graph node → `404` `{"code": "input_error"}` (consistent with existing endpoints).
- Node exists but has no render/asset (e.g. `bbox_status="insufficient"`, no `render_uri`, unrenderable PDF) → `404` `{"code": "evidence_incomplete"}` — never a guessed/empty image. `ImageProcessor.crop_region_full` returns `b""` on failure and the service raises `VisualAssetIncompleteError`.

## Files Changed

| File | Change |
| --- | --- |
| `backend/app/api/assets.py` | New router: 10 render/metadata routes under `/api/v1/assets`. |
| `backend/app/api/reviews.py` | New `GET .../candidates/{candidate_id}/visual-bundle` (Test D). |
| `backend/app/api/schemas.py` | `VisualAssetMetadata` + `CandidateVisualBundle` schemas. |
| `backend/app/graph/asset_repository.py` | New `AssetRepository`: page/plate/panel/drawing/region + candidate visual bundle graph queries. |
| `backend/app/services/visual_asset_service.py` | New `VisualAssetService`: metadata + render resolution, on-demand body page render + cache, panel/region crop, bbox normalization, fail-closed errors. |
| `backend/app/services/image_processor.py` | Added `crop_region_full` (crop without resize); refactored `crop_region` onto shared `_crop`. |
| `backend/app/main.py` | Register assets router; `asset_repository`/`visual_asset_service` injection; `VisualAssetNotFoundError` (404 input_error) + `VisualAssetIncompleteError` (404 evidence_incomplete) handlers. |
| `backend/tests/test_visual_asset_api.py` | New P0-D test module (15 tests + 1 real-Neo4j optional). |

## Tests (TDD red → green)

New module `backend/tests/test_visual_asset_api.py`:

| Test | Verifies |
| --- | --- |
| `test_page_metadata_returns_contract_fields` | page metadata contract (assetType/imageUrl/documentVersionId/sourceSha256/physicalPage/printedIdentifier/renderWidth/Height). |
| `test_plate_metadata_returns_contract_fields` | plate metadata contract. |
| `test_plate_panel_metadata_returns_contract_fields` | plate panel metadata contract (bbox/caption/printedIdentifier 【도판 45】). |
| `test_drawing_metadata_returns_contract_fields` | drawing metadata contract. |
| `test_drawing_region_metadata_returns_contract_fields` | drawing region metadata contract. |
| `test_page_render_returns_decodable_bytes_and_caches` | on-demand page render from a real PDF, Pillow-open OK, cached under derived dir. |
| `test_plate_render_returns_page_bytes` / `test_drawing_render_returns_page_bytes` | full page render bytes. |
| `test_plate_panel_render_returns_cropped_bytes` / `test_drawing_region_render_returns_cropped_bytes` | cropped region bytes decodable. |
| `test_visual_bundle_contains_source_and_canonical_provenance` | **Test D**: source page + source bbox + source sha256 + canonical plate + canonical bbox + canonical sha256 together. |
| `test_visual_bundle_missing_candidate_returns_404` | missing candidate → 404 input_error. |
| `test_no_route_response_contains_filesystem_path` | **anti-pattern #15**: scan all visual responses for `/data/` / absolute paths. |
| `test_missing_render_fails_closed_404_evidence_incomplete` | **fail-closed**: no render → 404 evidence_incomplete, no empty image. |
| `test_missing_node_returns_404` | missing node → 404 input_error. |
| `test_real_neo4j_page_panel_region_render_and_provenance` | Real Neo4j (optional): create page/panel/region, render, assert bytes decodable + provenance; scoped `p0d_test_*` ids + cleanup. |

**Before (RED):** collection error — `visual_asset_service` module did not exist; after implementation 2 tests failed (visual-bundle route required a review repository it does not use). **After (GREEN):** all 15 pass + real-Neo4j test passes against the local docker Neo4j (port 17687), 0 leftover scoped nodes.

## Verification

- Backend unit: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/integration` → **532 passed, 10 skipped, 8 errors** (the 8 errors are the pre-existing infra guards; 0 new failures; +15 tests vs the 517 baseline).
- Integration: `pytest tests/integration` against docker Neo4j → **9 passed**.
- Real-Neo4j optional: `test_real_neo4j_page_panel_region_render_and_provenance` → **1 passed**, 0 leftover `p0d_test_*` nodes.
- Frontend: `cd frontend && npm test -- --run` → **14 passed**; `npm run build` → **OK** (unaffected — this phase is backend-only).
- `py_compile` clean on all changed files.

## Commit

`f2a50ab` — `feat(canonical): add evidence visual asset delivery api with provenance`

## Next Phase

Frontend (Phase P0-D UI): render the real body page / plate panel / drawing region via these routes, overlay both bboxes from the visual-bundle, and complete the §9 split view. See `progress.md`.
