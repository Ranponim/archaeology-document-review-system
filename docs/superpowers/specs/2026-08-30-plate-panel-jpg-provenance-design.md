# Plate Panel → JPG Provenance Design

## Goal

Complete the Adobe-free plate provenance chain by linking safely segmented `PlatePanelData` objects to their original `plate_link` JPG assets without weakening provenance safety.

Target chain:

```text
Plate PDF -> canonical Plate -> segmented PlatePanel -> original JPG SourceAsset
```

The existing drawing/AI resolver is out of scope and must remain a regression-only surface.

## Problem

The current `VisualAssetMatcher` compares one extracted PDF image against every original JPG using one padded 32×32 grayscale thumbnail. A panel is promoted immediately when its local best score exceeds `0.97` and the local runner-up margin exceeds `0.03`.

This is safe but brittle when the PDF image is cropped, has different borders, has been resized/recompressed, or when multiple panels independently select the same JPG. The current per-panel API also cannot enforce corpus-wide source uniqueness before `DERIVED_VERIFIED` is assigned.

## Approved Architecture

### 1. Deterministic robust visual verification first

Use only deterministic image evidence for the first pass. Do not add an LLM/VLM dependency in this phase.

Normalize image content with Pillow and compare multiple deterministic views:

- EXIF orientation normalization
- grayscale normalization
- light-border trimming when a removable border is present
- full-frame fingerprint
- bounded center-crop variants for common PDF cropping

Keep the existing conservative score threshold and margin gate unless tests prove a threshold change is necessary. The first implementation must improve tolerance by improving the evidence representation, not by simply lowering the acceptance threshold.

### 2. Global collision fail-closed

A single original JPG must not be independently promoted as `DERIVED_VERIFIED` for multiple distinct panels in the same reference corpus.

The matcher therefore needs a batch resolution surface. It may compute per-panel local matches internally, but it must remove any candidate asset selected by more than one panel before returning verified matches.

For this phase, collisions are deliberately unresolved rather than assigning the JPG to the highest scorer. This preserves provenance safety and leaves ambiguous cases available for a later review/VLM layer.

### 3. Evidence semantics

Only a deterministic visual match that passes both:

1. robust local visual verification, and
2. corpus-wide uniqueness

may set:

```text
evidence_level = DERIVED_VERIFIED
source_asset_id = <original JPG>
source_sha256 = <original JPG sha256>
```

A filename, path, caption, sequence number, or other textual hint may be used later for candidate retrieval, but must never by itself create `DERIVED_VERIFIED` provenance.

Ambiguous, colliding, insufficient-bbox, missing-file, or low-score cases remain:

```text
evidence_level = UNRESOLVED
source_asset_id = None
```

The repository must therefore continue to create no fake source provenance edge for unresolved panels.

## API Shape

Add a small immutable panel request type to the visual matcher and a batch API conceptually equivalent to:

```python
match_panels(*, panels, candidates) -> dict[panel_id, VisualAssetMatch]
```

`match_panel()` remains the local deterministic scoring primitive. `match_panels()` applies the corpus-level collision/uniqueness gate.

`ReferenceCorpusService` should collect all safely segmented panel requests first, call the batch matcher once for the corpus, and only then promote returned matches to `DERIVED_VERIFIED`.

## TDD Acceptance

The implementation is accepted only when tests prove all of the following:

1. A bounded crop of the same source image can match without lowering the safety threshold.
2. A visually different candidate is not promoted merely because of filename/path metadata.
3. If two panels select the same original JPG, the collision is fail-closed and neither is returned as verified.
4. `ReferenceCorpusService` uses corpus-level batch resolution and only binds returned unique matches.
5. Unresolved panels retain `source_asset_id=None` and do not create fake provenance edges.
6. Existing drawing-evidence tests and the full backend/frontend/Neo4j CI remain green.

## Real-Corpus Verification Boundary

GitHub CI does not contain the local Windows `/src` corpus. Code-level TDD can prove the behavior contract, but no claim about real 2,750-panel coverage improvement is valid until the full local corpus is rerun and its audit artifact is committed.

A later phase may add a closed-world Luna/VLM fallback for the remaining unresolved panels, but only after deterministic coverage and error/collision rates are measured on the real corpus.
