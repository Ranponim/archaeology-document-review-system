# P0-C Report — Complete Semantic Visual Validation

**Date:** 2026-08-17
**Branch:** `windows-docker-foundation`
**Review source:** `docs/superpowers/reviews/2026-08-17-neo4j-frontend-mvp-code-review.md` — Phase P0-C (§13), P0-3 (VLM body claims), P0-4 (drawing visual pipeline), Mandatory Test C, Anti-patterns #2/#3/#9/#10/#14, Definition of Done "Photo/Plate" + "Drawing".

## Goal

Close the semantic visual validation gap: the VLM must compare **body/object claims** (derived from the graph `ObjectEvidenceBundle`) against the **actual canonically-identified panel/drawing image** — not merely compare an asset caption to itself. Drawings must get the same render/crop/region pipeline as plates (Task 9). VLM evidence provenance must point to the actual visual `DocumentVersion`. Results stay `pending_review` with the structured 4-class outcome.

## Files Changed

| File | Change |
| --- | --- |
| `backend/app/services/proofreading_orchestrator.py` | Step B now derives body claims from the graph bundle (`_derive_body_claims` over `text_claims` + `references`) and passes `claims` / `expected_feature` / `expected_site` into `review_canonical_reference`; VLM evidence `document_version_id` now resolves to the **visual** plate/drawing version (anti-pattern #14), never the body version. |
| `backend/app/services/drawing_parser.py` | Added the Task-9-mirroring render/crop/region pipeline: `render_page` / `_render_page_png` (>=2x, ~1191px), `segment_page_regions` (label→embedded rect, exactly-one-candidate fail-closed), `_persist_page_render`, `is_region_badge_word`; `parse`/`parse_drawings`/`parse_page_range` accept `render_dir`/`on_progress`; `_parse_with_pymupdf` now segments regions and sets `bbox` / `bbox_status` / `render_uri` on `DrawingRegionData`. |
| `backend/app/domain/canonical_models.py` | `DrawingRegionData` gains `bbox_status` (`'segmented'` / `'insufficient'`), mirroring `PlatePanelData`. |
| `backend/app/graph/canonical_repository.py` | `_region_to_param` + `save_drawings` region cypher persist `bbox_status`; `get_drawing_index_for_version` reconstructs it. |
| `backend/tests/test_p0c_semantic_visual_validation.py` | New P0-C test module (8 tests + 1 real-Neo4j optional). |

## VLM Claims Flow (body claims → VLM)

```
Reference (source block) ──mentions──▶ ArchaeologyObject
                                          │
                              get_object_evidence_bundle(object_id)
                                          ▼
                              ObjectEvidenceBundle
                                ├─ text_claims  (value = claim text)
                                └─ references   (value.raw_text)
                                          │
                              _derive_body_claims(bundle)
                                          ▼
                    claims=[...] + expected_feature=canonical_name
                    + expected_site=point/site
                                          │
                    review_canonical_reference(claims=..., ...)
                                          ▼
                    VLM verify_plate_photo(image=cropped panel/region,
                                           claims=body claims)
                                          ▼
                    per-claim SUPPORTED / PARTIAL / CONTRADICTED /
                    INSUFFICIENT_EVIDENCE  (structured, stored in Evidence.value)
```

- The VLM prompt now includes the body claims (e.g. `규모는 길이 275cm이다`, `도판 : 45`) — not just the plate panel caption/title.
- Canonical-before-VLM: only `resolved_resolutions` (status `RESOLVED` with a canonical `PlatePanelData`/`DrawingRegionData`/`PlateData`/`DrawingData` target) reach the VLM. A wrong/missing canonical mapping (MISSING/UNRESOLVED/AMBIGUOUS) never calls the VLM — the reference produces a `pending_review` candidate with no VLM observation. VLM never establishes identity (no RESOLVES_TO/DEPICTS writes during the VLM phase — unchanged from Task 10).
- Result stays `pending_review`; the 4-class structured result is stored per-claim in `EvidenceData.value` (`status`, `supported_claims`, `contradicted_claims`, `unobservable_claims`) — never reduced to a boolean `is_match`.

## Drawing Render/Crop Design (mirror PlateParser Task 9)

```
Drawing PDF → explicit 【도면 N】 identifier → Drawing → DrawingRegion
   → page render (>=2x, ~1191px PNG) → region bbox (normalized 0..1)
   → crop PNG (ImageProcessor.crop_region) → render_uri → VLM
```

- `DrawingRegionData.bbox` is the **embedded drawing rect** (normalized page coords) derived from `segment_page_regions` — never the circled-label bbox.
- `bbox_status='segmented'` when the region is safely isolated (bbox + render_uri set); `'insufficient'` when it cannot be isolated (bbox=None, render_uri=None) — the page render is never sent as if it were the region.
- `render_uri` points to a written high-res page render under the derived dir; `source_sha256` is the original drawing PDF byte hash.
- Vector sources (AI/EPS/DWG/DXF) fail closed: `review_canonical_reference` already rejects `.ai/.dwg/.dxf/.eps/.cdr` render_uris and non-decodable bytes → `conversion_error` candidate, no VLM call (anti-pattern #9).

## Provenance Fix (anti-pattern #14)

The orchestrator previously passed `document_version_id=body_version_id` into `review_canonical_reference`, so the VLM observation Evidence pointed at the body version. Now the visual version is resolved from the canonical target:

```python
if isinstance(target, (PlateData, PlatePanelData)):
    visual_version_id = target.document_version_id or plate_version_id
elif isinstance(target, (DrawingData, DrawingRegionData)):
    visual_version_id = target.document_version_id or drawing_version_id
```

The VLM `EvidenceData.document_version_id` now equals the plate/drawing `DocumentVersion` (e.g. `ver_plate`), never the body version.

## Tests (TDD red → green)

New module `backend/tests/test_p0c_semantic_visual_validation.py`:

| Test | Verifies |
| --- | --- |
| `test_orchestrator_passes_body_claims_from_graph_bundle_to_vlm` | VLM receives body claims from the graph bundle (a `text_claim` value + a reference `raw_text`), not just the caption. |
| `test_orchestrator_skips_vlm_when_canonical_mapping_missing` | Missing canonical mapping (plate 999) → VLM NOT called; candidate stays `pending_review`. |
| `test_vlm_result_stays_pending_review_with_structured_4_class_result` | Candidate `pending_review`; evidence stores structured 4-class result (never boolean `is_match`, never auto-accepted). |
| `test_drawing_parser_renders_page_and_region_bbox_is_embedded_image_rect` | Drawing page rendered >=2x; region bbox == embedded rect (normalized); render_uri valid image; source_sha256 == PDF hash; crop round-trip valid. |
| `test_drawing_region_crop_reaches_vlm` | VLM receives the cropped drawing region bytes, never the whole page. |
| `test_drawing_insufficient_region_never_reaches_vlm` | Unisolatable region → `bbox_status='insufficient'`, no VLM call, `conversion_error` candidate. |
| `test_drawing_vector_source_fails_closed_no_vlm` | Vector render_uri (`.ai`) → no VLM call, `conversion_error` candidate (anti-pattern #9). |
| `test_real_neo4j_drawing_region_render_and_provenance` | Real Neo4j (optional): DrawingRegion bbox/bbox_status/render_uri/source_sha256 persist; `get_drawing_index_for_version` reconstructs them; scoped `p0c_test_*` ids + cleanup. |

**Before (RED):** 5 new tests failed (claims not passed, provenance wrong, no drawing render pipeline, no `bbox_status`). 3 already passed (canonical-before-VLM, 4-class result, vector fail-closed — pre-existing invariants). 1 skipped (real Neo4j).

**After (GREEN):** all 8 pass + real-Neo4j test passes against the local docker Neo4j (port 17687), 0 leftover scoped nodes.

## Verification

- Backend unit: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/integration` → **517 passed, 9 skipped, 8 errors** (the 8 errors are the pre-existing infra guards; 0 new failures; +8 tests vs the 509 baseline).
- Integration: `pytest tests/integration` against docker Neo4j → **9 passed**.
- Frontend: `cd frontend && npm test -- --run` → **14 passed**; `npm run build` → **OK** (unaffected).
- `py_compile` clean on all changed files.

## Commit

`feat(canonical): complete semantic visual validation with body-claim vlm and drawing region render`
