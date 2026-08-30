# Plate Panel JPG Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Adobe-free `PlatePanel -> original JPG` provenance with deterministic crop-tolerant matching and a fail-closed corpus-wide uniqueness gate, without regressing the completed drawing-evidence path.

**Architecture:** Keep `VisualAssetMatcher.match_panel()` as the conservative local visual primitive, strengthen its deterministic fingerprint representation, add `match_panels()` for corpus-wide collision removal, then refactor `ReferenceCorpusService` to resolve all segmented panels in one batch before assigning `DERIVED_VERIFIED` provenance.

**Tech Stack:** Python 3.12, Pillow, PyMuPDF, pytest, Neo4j integration CI, React frontend regression CI.

**Spec:** `docs/superpowers/specs/2026-08-30-plate-panel-jpg-provenance-design.md`

## Global Constraints

- [ ] Do not modify drawing-evidence ranking, Luna resolver, or AUTO gate behavior.
- [ ] Do not lower the current visual acceptance threshold merely to improve coverage.
- [ ] Filename/path/caption evidence alone must never create `DERIVED_VERIFIED` panel provenance.
- [ ] Ambiguous/colliding cases must fail closed to `UNRESOLVED`.
- [ ] Do not claim real-corpus coverage improvement until a new local `/src` audit artifact is committed.
- [ ] Every production change follows RED -> verified RED -> minimal GREEN -> full CI verification.

## Task 1: Crop-tolerant deterministic local matching

**Files:**
- Create: `backend/tests/test_visual_asset_matcher.py`
- Modify: `backend/app/services/visual_asset_matcher.py`

- [ ] Add a synthetic PDF/JPG test where the PDF embeds a bounded center crop of the original JPG and a visually different distractor is present.
- [ ] Assert the current matcher returns the correct original without changing `minimum_score=0.97`.
- [ ] Commit the RED test and verify the PR CI fails for that new behavior for the expected reason.
- [ ] Add deterministic normalized fingerprint variants: EXIF/grayscale normalization, conservative light-border trim, full frame, bounded center crops.
- [ ] Score the best compatible deterministic variant pair while preserving the existing threshold and local runner-up margin.
- [ ] Run/verify the targeted test and then the full CI GREEN.

## Task 2: Corpus-wide JPG collision gate

**Files:**
- Modify: `backend/tests/test_visual_asset_matcher.py`
- Modify: `backend/app/services/visual_asset_matcher.py`

- [ ] Add a RED test proving that two distinct panel requests whose local best is the same JPG cannot both be returned as verified.
- [ ] Verify the RED failure is caused by the missing batch/uniqueness behavior.
- [ ] Introduce an immutable panel request type and `match_panels()` batch API.
- [ ] Reuse `match_panel()` for local scoring, then remove every source asset selected by more than one panel.
- [ ] Keep collisions unresolved rather than selecting a winner.
- [ ] Verify targeted and full CI GREEN.

## Task 3: Wire batch uniqueness into reference-corpus construction

**Files:**
- Modify: `backend/tests/test_adobe_free_reference_corpus.py`
- Modify: `backend/app/services/reference_corpus_service.py`
- Verify: `backend/tests/test_reference_corpus_repository.py`

- [ ] Add a RED service test with multiple segmented panels proving the service sends all panel requests through one corpus-level batch resolution surface.
- [ ] Add a RED service test proving only IDs returned by the unique batch result receive `source_asset_id`, `source_sha256`, and `DERIVED_VERIFIED`.
- [ ] Refactor `_adobe_free_visuals()` to first create canonical unresolved panels and collect all safely segmented requests.
- [ ] Invoke `match_panels()` once after all plate PDFs are parsed.
- [ ] Promote only returned matches; keep every other panel explicitly `UNRESOLVED`.
- [ ] Preserve existing repository fail-closed graph semantics for panels without a source.
- [ ] Verify targeted tests and full backend/frontend/Neo4j CI GREEN.

## Task 4: Verification and local acceptance handoff

- [ ] Fresh-fetch branch HEAD and confirm all expected implementation commits are present.
- [ ] Confirm latest PR workflow: backend-hermetic, frontend, and neo4j-e2e all success.
- [ ] Record exact backend pass/skip/warning counts from the latest workflow log.
- [ ] Confirm no drawing-evidence regression tests failed.
- [ ] Prepare the local real-corpus rerun command/instructions for the Windows `/src` corpus.
- [ ] Require a committed audit artifact before reporting new real panel/JPG coverage, precision, or chain-completion metrics.
