# Adobe-free Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the primary ReferenceCorpus build work without Adobe using real plate PDF, PDF-compatible AI, and original Links while preserving graded, conservative provenance.

**Architecture:** Add evidence levels to canonical data, broaden deterministic body reference parsing, add two isolated services (`VisualAssetMatcher`, `DrawingIdentityResolver`), and add a `plate_pdf` branch in `ReferenceCorpusService`. Keep the existing AdobeManifest path intact when no `plate_pdf` is staged. Neo4j persists evidence metadata and allows explicitly unresolved nodes without inventing source edges.

**Tech Stack:** Python 3.12, PyMuPDF, Pillow, FastAPI, Neo4j, pytest, React/TypeScript/Vitest.

**Spec:** `docs/superpowers/specs/2026-08-23-adobe-free-provenance-design.md`

## Global Constraints

- `/src` real files are not CI fixtures and must not be added to Git.
- Adobe COM/ExtendScript is not used by the new default path.
- Filename identity is never `direct` evidence.
- Ambiguous visual matches remain unresolved; no nearest-neighbor guess is persisted.
- Existing legacy Adobe/manifest behavior remains backward-compatible.
- PR #1 stays draft/unmerged; verified work fast-forwards its feature branch only after green CI.

---

### Task 1: Evidence model and body references

**Files:**
- Modify: `backend/app/domain/canonical_models.py`
- Modify: `backend/app/services/pdf_parser.py`
- Test: `backend/tests/test_adobe_free_provenance.py`

**Interfaces:**
- Produces: `EvidenceLevel` enum and optional `evidence_level` / `evidence_method` fields on reference/visual models.
- Produces: `_extract_references()` support for bare/colon/bracket/원색도판 forms.

- [ ] **Step 1: Write failing tests** for `도면 1`, `도면:1`, `도판 1`, `【도판 2】`, `【원색도판 3】`, and `ReferenceData.evidence_level == direct`.
- [ ] **Step 2: Run CI and verify RED** because the enum/fields/patterns do not yet exist.
- [ ] **Step 3: Implement the minimal enum/fields and shared reference regex** while preserving blank caption parsing.
- [ ] **Step 4: Run tests and verify GREEN** for the focused tests and existing parser tests.

### Task 2: Drawing identity resolver

**Files:**
- Create: `backend/app/services/drawing_identity_resolver.py`
- Test: `backend/tests/test_adobe_free_provenance.py`

**Interfaces:**
- Consumes: `DrawingParser`, staged `OriginalAssetData`, local source path.
- Produces: `DrawingIdentityResolution(drawings, unresolved)` and corpus-scoped `DrawingData` with source/evidence metadata.

- [ ] **Step 1: Add RED tests** for direct internal ID, filename-only `도면14`/`삽도 7`, and filename with no unique number.
- [ ] **Step 2: Verify RED in CI.**
- [ ] **Step 3: Implement resolver**: direct parser result first, then one unique basename number as heuristic, else unresolved.
- [ ] **Step 4: Verify GREEN.**

### Task 3: Deterministic panel-to-original matcher

**Files:**
- Create: `backend/app/services/visual_asset_matcher.py`
- Test: `backend/tests/test_adobe_free_provenance.py`

**Interfaces:**
- Consumes: plate PDF path, physical page, normalized panel bbox, candidate `OriginalAssetData` + local paths.
- Produces: `VisualAssetMatch(source_asset_id, score, method)` or `None`.

- [ ] **Step 1: Add RED synthetic tests** that create a PDF with an embedded image and staged candidate images; assert correct unique match and ambiguity refusal.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement fingerprint/index/match** using EXIF-normalized grayscale thumbnails, conservative score/margin thresholds, and image occurrence lookup by panel bbox.
- [ ] **Step 4: Verify GREEN.**

### Task 4: Adobe-free ReferenceCorpus service

**Files:**
- Modify: `backend/app/services/reference_corpus_service.py`
- Modify: `backend/app/graph/reference_corpus_repository.py`
- Modify: `backend/app/domain/canonical_models.py`
- Test: `backend/tests/test_adobe_free_reference_corpus.py`

**Interfaces:**
- New source role: `plate_pdf` (`.pdf`).
- Adobe-free build selected when at least one `plate_pdf` is staged.
- Legacy path remains selected otherwise.

- [ ] **Step 1: Add RED tests** for role validation, Adobe converter not called, direct plates from PDF fixtures, heuristic/direct drawings, unresolved panels allowed, and diagnostics artifact creation.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement source-role/mode routing and Adobe-free build** using `PlateParser`, `DrawingIdentityResolver`, `VisualAssetMatcher`.
- [ ] **Step 4: Update Neo4j payloads/edges** to persist evidence metadata and visual-level `DERIVED_FROM`; unresolved panel/region with no source is legal.
- [ ] **Step 5: Update READY validation** to reject false/cross-project provenance but accept explicit unresolved gaps.
- [ ] **Step 6: Verify focused + full backend + Neo4j CI GREEN.**

### Task 5: Frontend plate-PDF upload path

**Files:**
- Modify: `frontend/src/referenceCorpusApi.ts` only if role typing requires it.
- Modify: `frontend/src/components/ReferenceCorpusPanel.tsx`
- Modify: existing ReferenceCorpus panel/package tests.

**Interfaces:**
- Package classifier maps `.pdf` to `plate_pdf`.
- UI exposes `도판 PDF` and states the Adobe-free minimum set: plate PDF + AI + Links.

- [ ] **Step 1: Add/adjust RED frontend tests** for `.pdf` classification/upload.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement UI/API changes.**
- [ ] **Step 4: Verify frontend typecheck/tests/build GREEN.**

### Task 6: Final verification and handoff

**Files:**
- Update: `docs/local_real_asset_audit_report.md` only with a short implementation note; do not alter measured audit numbers.

- [ ] **Step 1: Run fresh PR CI**: backend-hermetic, frontend, real Neo4j E2E.
- [ ] **Step 2: Inspect workflow logs for zero failures.**
- [ ] **Step 3: Fast-forward `feature/source-provenance-remediation-20260818` to the verified commit and keep PR #1 draft/unmerged.**
- [ ] **Step 4: Record the exact local Codex rerun command for `/src`** so real-data coverage is measured after pull.
