# Adobe-free provenance design

## Context

The `/src` real-asset audit showed that the production source set is physically readable without Adobe: all 56 AI files are PDF-compatible and render successfully, all 1,032 JPGs decode, and the plate PDFs recover 546/546 plate headers. The failures are identity/provenance failures rather than file-open failures: body reference recall is 47.4%, plate-panel segmentation is 68.9%, semantic drawing identity is 1/56, and the strict body→visual→original chain is 0/7 because the current ReferenceCorpus READY contract assumes Adobe DOM manifests.

## Goal

Make the default reference-corpus path work without Adobe while preserving conservative provenance. Adobe/IDML may remain optional corroborating evidence, but they are no longer required for the primary build path.

## Design principles

1. **Evidence is graded, not binary.** Canonical/reference objects carry one of `direct`, `derived_verified`, `heuristic`, or `unresolved` plus an evidence method.
2. **Do not invent identity.** Filename identity is allowed only as lower-grade evidence; it must never be represented as direct evidence.
3. **Plate PDF is publication authority for plate number.** The real audit recovered 546/546 plate headers. The plate PDF may therefore create direct `Plate` identity.
4. **AI is a valid render/source format.** PDF-compatible AI is parsed with PyMuPDF. Explicit internal `도면 N` text is direct. A unique drawing number in a filename is heuristic unless corroborated later.
5. **Original JPG provenance is independent evidence.** A panel may link to a staged JPG only when a deterministic pixel-level matcher produces a unique high-confidence match. Otherwise the panel stays unresolved.
6. **READY means structurally usable, not fully resolved.** A corpus may be READY with unresolved panels/drawing identities when those gaps are explicit. READY still rejects cross-project provenance and falsely declared source edges.
7. **Adobe path remains backward-compatible.** Existing `plate_layout`/AdobeManifest conversion remains available as a legacy/optional path, but a corpus containing `plate_pdf` uses the Adobe-free path and must not call Adobe conversion.

## Source roles

- `plate_pdf`: publication plate PDF; `.pdf`; preferred/default plate authority.
- `plate_link`: original linked photo/image; `.jpg/.jpeg/.png/.tif/.tiff/.webp`.
- `drawing_source`: `.ai` (PDF-compatible preferred) and existing accepted drawing formats where parsers already support them.
- `plate_layout`: `.indd`; optional provenance/archive input for the Adobe path, not required for Adobe-free builds.

An Adobe-free build requires at least one `plate_pdf` and one `drawing_source`. `plate_layout` is optional. A legacy Adobe build (no `plate_pdf`) retains the previous `plate_layout + drawing_source` requirement.

## Evidence model

`EvidenceLevel`:

- `direct`: explicit identifier or direct source relation from the document itself.
- `derived_verified`: deterministic transformation/match with a uniqueness check (for example unique pixel match from PDF panel image to original JPG).
- `heuristic`: useful candidate evidence such as a filename number, never enough to masquerade as direct.
- `unresolved`: evidence insufficient for a safe identity or source relation.

The graph persists `evidenceLevel` and `evidenceMethod` on Plate/Drawing/Panel/Region nodes and provenance edges. A missing `sourceAssetId` is allowed only when `evidenceLevel == unresolved`.

## Body reference extraction

The body parser must support the actual corpus forms observed in `/src`, including:

- `도면 1`
- `도면: 1` / `도면 : 1`
- `도판 1`
- `도판: 1` / `도판 : 1`
- `【도판 1】`
- `【원색도판 2】`
- lists/ranges already handled by `expand_reference_numbers`

Blank proofreading captions such as `(도면 : , 도판 : )` keep the existing caption behavior.

## Plate-to-original image matching

A `VisualAssetMatcher` works only on staged local sources. It extracts the embedded PDF image occurrence corresponding to the already-safe segmented panel bbox, generates a normalized grayscale thumbnail fingerprint, and compares it with staged image fingerprints. It returns a match only when:

- best similarity is at least `0.97`, and
- the margin over the second-best candidate is at least `0.03` (or there is only one candidate).

A successful match is `derived_verified` with method `pixel_thumbnail_similarity`. Ambiguous/low-score results stay unresolved; no nearest-neighbor guess is persisted.

## Drawing identity resolution

`DrawingIdentityResolver` applies this order per AI source:

1. Parse internal PDF text with existing `DrawingParser`; explicit identifier => `direct`, `pdf_internal_identifier`.
2. If no explicit record, inspect the basename for a single `도면 N` or `삽도 N` number. Create one candidate `DrawingData` with `heuristic`, `filename_identifier`.
3. If filename has no unique number, keep the source in the build diagnostics as unresolved and do not invent a Drawing number.

The resolver does not use body references during corpus build because a ReferenceCorpus is independent of a ReviewRound. ReviewRound resolution may later corroborate a heuristic drawing with body evidence.

## Adobe-free ReferenceCorpus build

When `plate_pdf` is staged:

1. Calculate source-set/build identity as today.
2. Transition through the existing immutable state machine.
3. Parse each plate PDF with `PlateParser` and rewrite IDs into corpus scope.
4. Try deterministic panel→`plate_link` matching only for safely segmented panels.
5. Parse/resolve each `drawing_source` directly with PyMuPDF/`DrawingParser` and filename fallback.
6. Persist a JSON build-diagnostics artifact containing counts of direct/derived/heuristic/unresolved objects and unresolved source paths.
7. Persist canonical visuals with evidence metadata.
8. READY validation requires corpus ownership and consistent provenance edges but permits explicit unresolved objects.

## Graph READY invariants

READY rejects:

- canonical visual belonging to another corpus/project;
- a non-unresolved panel/region that names a source asset without a matching `DERIVED_FROM` edge;
- a `DERIVED_FROM` source outside the corpus/project;
- a `sourceAssetId` on an unresolved node;
- zero canonical visuals.

READY permits:

- unresolved panels/regions with `sourceAssetId = null`;
- heuristic Drawing identity when clearly labeled heuristic;
- diagnostics describing unresolved AI sources.

## UI

The ReferenceCorpus UI adds a `도판 PDF` input and classifies `.pdf` inside an uploaded plate package as `plate_pdf`. INDD remains uploadable but optional. Copy explicitly says Adobe-free builds use plate PDF + AI + Links; INDD may be retained as original provenance.

## Verification

Automated tests must cover:

- reference syntax variants and evidence level;
- drawing identity direct/filename/unresolved behavior;
- deterministic image matcher success and ambiguity refusal;
- source-role validation for `plate_pdf`;
- Adobe-free build not calling the Adobe converter;
- repository persistence/READY validation with unresolved panels;
- frontend API/package role classification for plate PDF.

Existing Adobe/legacy tests must remain green. The real `/src` audit must be rerun locally after merge to measure actual reference recall, panel matching coverage, drawing identity coverage, and body→visual→original chain coverage; CI cannot claim those real-data numbers because `/src` is not part of the repository test fixtures.
