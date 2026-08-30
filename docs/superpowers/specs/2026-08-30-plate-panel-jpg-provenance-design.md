# Plate Panel → JPG Provenance Design

## Goal

Complete the Adobe-free plate provenance chain by linking safely segmented `PlatePanelData` objects to their original `plate_link` JPG assets without weakening provenance safety, while remaining practical for the measured real-corpus batch size.

Target chain:

```text
Plate PDF -> canonical Plate -> segmented PlatePanel -> original JPG SourceAsset
```

The existing drawing/AI resolver is out of scope and must remain a regression-only surface.

## Problem

The original `VisualAssetMatcher` compared one extracted PDF image against every original JPG using one padded 32×32 grayscale thumbnail. A panel was promoted when its local best score exceeded `0.97` and the local runner-up margin exceeded `0.03`.

The real-corpus acceptance run established a larger and more realistic operating boundary than the original unit tests:

- 3 correction/version plate PDFs
- 2,804 parsed panels
- 2,750 safely segmented panels
- 1,032 decodable JPG candidates
- 75 local high-confidence matches before collision handling
- 52 panels removed by the original global collision rule
- 23 final `DERIVED_VERIFIED` panels
- 2,565 panels below the minimum score and 110 below the minimum margin

The run also demonstrated two important production facts that were not represented in the initial design:

1. the same original photograph can legitimately occur once in more than one correction/version PDF, so corpus-global JPG uniqueness incorrectly rejects valid reuse; and
2. a production batch cannot repeatedly decode 1,032 candidate JPGs, reopen the same PDFs per panel, or execute one Python byte-difference loop for every panel/candidate pair.

The matcher is also brittle when a correction PDF changes crop, border, exposure/tonal range, resize, or JPEG recompression.

## Approved Architecture

### 1. Deterministic robust visual verification first

Use deterministic image evidence for the first pass. Do not add an LLM/VLM dependency merely to compensate for deterministic implementation defects.

Normalize and compare multiple deterministic views with Pillow:

- EXIF orientation normalization
- grayscale representation
- raw tonal representation retained as the primary signal
- autocontrast representation as an additional exposure/tonal-drift fallback
- light-border trimming when a removable border is present
- full-frame fingerprint
- bounded center-crop variants for common PDF cropping

Keep the conservative score threshold and margin gate at `0.97` and `0.03` unless a separate evidence-backed TDD change proves that a threshold change is safe. Robustness improvements must come from stronger evidence representation, not from silently lowering the gate.

### 2. Collision safety is scoped to one PDF version

A single original JPG must not be independently promoted as `DERIVED_VERIFIED` for multiple distinct panels **inside the same plate PDF**. That remains a fail-closed collision because the visual evidence alone cannot identify which panel owns the source.

The same original JPG **may** be linked once in each distinct correction/version PDF. Reusing a photograph across document revisions is a normal publication workflow and is not a provenance collision.

The matcher therefore uses a batch resolution surface and counts collisions by `(pdf_identity, source_asset_id)`, not by `source_asset_id` across the entire reference corpus. It may compute per-panel local matches internally, but any source selected by more than one panel in the same PDF is removed before verified matches are returned.

For same-PDF collisions, the system deliberately remains unresolved rather than assigning the JPG to the highest scorer. This preserves provenance safety and leaves ambiguous cases available for later review/VLM escalation.

### 3. Production batch execution must share expensive work

The real operating size is approximately `2,750 panels × 1,032 candidate JPGs`, so batch execution is part of the correctness contract rather than an optional optimization.

Within one `match_panels()` call:

- each candidate JPG is decoded/fingerprinted at most once;
- each distinct plate PDF is opened at most once and closed at the end of the batch;
- candidate fingerprints are assembled into a bulk score index once;
- panel-to-candidate absolute pixel differences are computed with Pillow native image operations rather than invoking the Python `_similarity()` byte loop for every pair;
- the resulting score remains mathematically equivalent to the existing normalized mean-absolute-error score before the unchanged `0.97` / `0.03` gates are applied.

Batch caches are scoped to the call/context and must not become persistent global state that can leak stale files across corpus builds.

### 4. Evidence semantics

Only a deterministic visual match that passes both:

1. robust local visual verification, and
2. same-PDF uniqueness

may set:

```text
evidence_level = DERIVED_VERIFIED
source_asset_id = <original JPG>
source_sha256 = <original JPG sha256>
```

A filename, path, caption, sequence number, or other textual hint may be used later for candidate retrieval, but must never by itself create `DERIVED_VERIFIED` provenance.

Ambiguous, same-PDF-colliding, insufficient-bbox, missing-file, or low-score cases remain:

```text
evidence_level = UNRESOLVED
source_asset_id = None
```

The repository must therefore continue to create no fake source provenance edge for unresolved panels.

## API Shape

Use the immutable panel request and batch API:

```python
match_panels(*, panels, candidates) -> dict[panel_id, VisualAssetMatch]
```

`match_panel()` remains the deterministic local scoring surface. When called inside `match_panels()`, it consumes the batch score index while preserving the same score/margin semantics. `match_panels()` applies per-PDF collision/uniqueness handling.

`ReferenceCorpusService` collects all safely segmented panel requests first, calls the batch matcher once for the corpus, and only then promotes returned matches to `DERIVED_VERIFIED`.

## TDD Acceptance

The implementation is accepted only when tests prove all of the following:

1. A bounded crop of the same source image can match without lowering the safety threshold.
2. A removable light source border does not break a valid match.
3. A deterministic brightness/recompression shift can match through the additional tonal representation without lowering the safety threshold.
4. A visually different candidate is not promoted merely because of filename/path metadata.
5. If two panels in the same PDF select the same original JPG, the collision is fail-closed and neither is returned as verified.
6. If the same JPG is selected once in each of two distinct PDF revisions, both uses are allowed.
7. Each candidate is fingerprinted once per production batch and each PDF is opened once per production batch.
8. Production batch matching does not invoke the scalar Python `_similarity()` loop for every panel/candidate pair.
9. `ReferenceCorpusService` uses batch resolution and only binds returned verified matches.
10. Unresolved panels retain `source_asset_id=None` and do not create fake provenance edges.
11. Existing drawing-evidence tests and the full backend/frontend/Neo4j CI remain green.

## Real-Corpus Verification Boundary

GitHub CI does not contain the local Windows `/src` corpus. Code-level TDD now covers the failures observed in the committed 2,750-panel acceptance artifact, but **no new claim about real-corpus coverage, collision count, or wall-clock runtime is valid until the full local corpus is rerun on the current production code and its audit artifact is committed**.

The next acceptance run must report at minimum:

- total/segmented/insufficient-bbox panel counts
- local high-confidence count
- final `DERIVED_VERIFIED` count and coverage
- below-score and below-margin counts
- same-PDF collision panel/source counts
- cross-PDF reused-source count
- filename/path/caption-only promotions (must remain zero)
- threshold bypasses (must remain zero)
- source mutation status (must remain false)
- total wall-clock time plus deterministic matcher time

Only after that rerun should remaining unresolved cases be sampled and classified for a closed-world Luna/VLM fallback. A VLM fallback must never be used to hide deterministic scoring, collision, or performance defects.
