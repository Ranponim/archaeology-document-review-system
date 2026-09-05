# Hybrid Panel Visual Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace exact-only panel matching as the primary path with a hermetic pixel-shortlist + SIFT/RANSAC fallback while preserving provenance safety.

**Architecture:** `VisualAssetMatcher` keeps the existing 0.97/0.03 Tier-0 verifier, then sends unresolved panels and a bounded pixel shortlist to a focused `GeometricVisualRetriever`. Batch uniqueness counts distinct physical panel geometries so parser aliases cannot create fake collisions. A new local hybrid runner measures the same production retrieval components on the read-only corpus.

**Tech Stack:** Python 3.12+, Pillow, PyMuPDF, OpenCV headless (SIFT/RANSAC), pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-30-hybrid-panel-visual-retrieval-design.md`

## Global Constraints

- Keep Tier-0 `minimum_score=0.97` and `minimum_margin=0.03` unchanged.
- Filename/path/caption/sequence text is never verification evidence.
- Same source across PDF revisions is allowed.
- Same source across genuinely distinct panel geometries in one revision remains fail-closed.
- Identical `(scope, page, bbox)` aliases are one physical geometry for collision counting.
- VLM auto-promotion stays disabled.
- Local `/src` is read-only and is used only for real-corpus E2E acceptance.

---

### Task 1: Geometric retrieval RED tests

**Files:**
- Create: `backend/tests/test_geometric_visual_retriever.py`
- Modify: `backend/tests/test_visual_asset_matcher.py`

**Interfaces:**
- Consumes: existing `VisualAssetMatcher`, `VisualPanelRequest`.
- Produces expected API: `GeometricVisualRetriever.rank(panel_image, candidates, top_k)` and duplicate-geometry-aware `match_panels`.

- [ ] **Step 1:** Add a generated synthetic image test where the source is cropped, resized and rotated before insertion into a PDF; assert Tier-0 pixel-only matching does not verify it while geometric retrieval returns the original source with strong RANSAC evidence.
- [ ] **Step 2:** Add a batch test with two panel IDs sharing the exact same scope/page/bbox and source; assert aliases do not fail collision.
- [ ] **Step 3:** Keep the existing test proving different bboxes in the same revision selecting the same source fail closed.
- [ ] **Step 4:** Push the tests only and verify `backend-hermetic` fails for the missing geometric retriever/behavior.

### Task 2: Minimal geometric retriever

**Files:**
- Create: `backend/app/services/geometric_visual_retriever.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces `GeometricVisualEvidence(source_asset_id, score, good_matches, inliers, inlier_ratio)`.
- Produces `GeometricVisualRetriever.rank(panel_image, candidates, top_k=5)`.

- [ ] **Step 1:** Add `opencv-python-headless>=4.10,<5.0` dependency.
- [ ] **Step 2:** Implement grayscale conversion, SIFT descriptor extraction, candidate descriptor cache, Lowe-ratio KNN matches, RANSAC homography, and bounded geometric score.
- [ ] **Step 3:** Require minimum 12 inliers and 0.55 inlier ratio before a candidate is eligible.
- [ ] **Step 4:** Run CI and confirm the focused geometric tests pass.

### Task 3: Hybrid production matcher

**Files:**
- Modify: `backend/app/services/visual_asset_matcher.py`
- Test: `backend/tests/test_visual_asset_matcher.py`

**Interfaces:**
- `VisualAssetMatch.method` is `pixel_thumbnail_similarity` or `sift_ransac`.
- `VisualAssetMatch` carries optional geometric evidence fields.
- `VisualAssetMatcher.assess_panel` keeps pixel ranking diagnostics and invokes geometric fallback only after Tier-0 fails.

- [ ] **Step 1:** Extract the embedded panel as an image once, derive the Tier-0 fingerprint from it, and keep the existing pixel ranking behavior.
- [ ] **Step 2:** Send at most the top 50 pixel candidates to the geometric retriever after Tier-0 failure.
- [ ] **Step 3:** Accept the geometric winner only if it clears the retriever gates and has at least 0.08 score separation from runner-up.
- [ ] **Step 4:** Change batch collision counting to distinct `(scope, physical_page, bbox)` geometry keys.
- [ ] **Step 5:** Run matcher tests and the full backend hermetic CI.

### Task 4: Read-only hybrid local runner

**Files:**
- Create: `tools/evaluate_panel_provenance_hybrid.py`

**Interfaces:**
- Reuses vectorized Tier-0 scoring from `tools/evaluate_panel_provenance.py` for shortlist generation.
- Reuses production `GeometricVisualRetriever` for Tier-1 verification.
- Writes JSON/Markdown outside `/src`.

- [ ] **Step 1:** Run the existing vectorized evaluator with an internal candidate pool of 50.
- [ ] **Step 2:** For unresolved segmented rows, extract the same embedded image and geometrically evaluate only the shortlisted candidates.
- [ ] **Step 3:** Recompute uniqueness using distinct physical geometry keys and report pixel/geometric/total counts separately.
- [ ] **Step 4:** Preserve source-root before/after mutation detection and optional gold Recall@1/3/5.
- [ ] **Step 5:** Add a CLI smoke test if a hermetic runner test already exists; otherwise compile/import is covered by backend compile and the runner remains a local acceptance tool.

### Task 5: Full verification and handoff

**Files:**
- Update PR #48 description if needed.

- [ ] **Step 1:** Verify `backend-hermetic` success including Drawing Gold/safety regressions.
- [ ] **Step 2:** Verify `frontend` success.
- [ ] **Step 3:** Verify `neo4j-e2e` success.
- [ ] **Step 4:** Commit all implementation changes to `feat/revision-aware-panel-provenance`.
- [ ] **Step 5:** Hand off the exact local command for `tools/evaluate_panel_provenance_hybrid.py` and state the 56/2750 baseline without claiming improvement before local execution.
