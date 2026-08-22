# Bidirectional Visual Reference Coverage Design

Date: 2026-08-22
Status: proposed-for-implementation after user review
Branch: feature/source-provenance-remediation-20260818
Baseline: current branch state derived from a6a54f282e22bdfc1d86b7e6f81a71f663d19269

## 1. Goal

The proofreading system must validate visual references in both directions.

1. If the body already contains a drawing/plate-photo reference, resolve it through the canonical graph and compare the body claim against the real canonical drawing/plate render.
2. If the body omits drawing/plate-photo information but the selected project versions contain canonical visual assets that depict the same ArchaeologyObject, create an evidence-backed correction candidate proposing the missing reference.

All proposals remain `pending_review`; a human archaeologist is the final authority.

## 2. Non-negotiable identity rule

Canonical identity comes only from the project graph built from publication-authoritative inputs:

`DocumentVersion -> HAS_PLATE/HAS_DRAWING -> Plate/PlatePanel/Drawing/DrawingRegion`

Body references resolve only through:

`TextBlock/Caption -> REFERENCES -> Reference -> RESOLVES_TO -> canonical target`

Original source files are supporting provenance only:

`canonical target -> DERIVED_FROM -> OriginalAsset`

A filename such as `4. 조사 후_45.JPG`, `_91.JPG`, or `도면30.ai` MUST NOT create, select, or repair a canonical reference. Removing filename-derived matching must not change a successful production result.

For this feature, the user-facing term “사진” means the publication photo/plate channel represented by canonical `Plate`/`PlatePanel`. Raw JPG/PNG/TIFF `OriginalAsset` nodes are not publication reference identities.

## 3. Existing behavior to preserve

The current system already supports the forward direction:

- body `Reference` extraction,
- canonical `resolve_reference()` against `PlateIndex`/`DrawingIndex`,
- `RESOLVES_TO` persistence,
- body/object claim derivation from graph evidence,
- VLM comparison against canonical Plate/Panel/Drawing/Region renders,
- all generated findings start as `pending_review`.

This behavior remains authoritative for references already present in the body.

Legacy filesystem-number matching in `AssetMatcher.match_reference()` / `AssetReviewPipeline.review_references()` must not become part of the production path for this feature.

## 4. New deterministic rule: VisualReferenceCoverageRule

The new rule operates on one graph-derived `ObjectEvidenceBundle` and the selected ReviewRound-scoped canonical visual versions.

Inputs:

- `bundle.text_claims`
- `bundle.references`
- `bundle.plate_claims`
- `bundle.drawing_claims`
- the ArchaeologyObject identity
- active `plateVersionId` / `drawingVersionId` resolved from ReviewRound

The rule computes coverage by canonical publication reference key:

- plate/photo key: `(plate, number)`
- drawing key: `(drawing, number)`

The canonical side is derived from `plate_claims` / `drawing_claims` reached through real graph relationships, not from filenames.

The body side is derived from `bundle.references`.

### 4.1 Missing reference

If a canonical asset depicts the object but the body has no matching reference, generate a `CorrectionCandidateData`:

- `rule_category = figure_plate_table_photo_ref`
- `change_type = added`
- `status = pending_review`
- `archaeology_object_id = object.id`
- evidence must include at least one body `text_claim` and the canonical plate/drawing claim

Example:

Body:

`6호 석관묘는 구릉 정상부에 위치한다.`

Graph:

`Drawing 30 -[:DEPICTS]-> 6호 석관묘`
`Plate 45 -[:DEPICTS]-> 6호 석관묘`

Candidate proposal:

`(도면 30, 도판 45)`

The rule proposes the smallest deterministic suffix; it does not rewrite the whole paragraph.

### 4.2 Blank reference placeholder

For text such as:

`(도면: , 도판: )`

if exactly one eligible canonical drawing and exactly one eligible canonical plate exist for that object in the active ReviewRound versions, propose:

`(도면: 30, 도판: 45)`

If only one type is uniquely resolvable, fill only that type and leave the other unresolved for manual review.

### 4.3 Multiple canonical candidates

If more than one eligible canonical asset of the same type depicts the object and the body does not disambiguate which belongs at that text location, the system MUST NOT invent a number.

Generate a `pending_review` candidate with:

- `proposed_text = None`
- evidence listing the competing canonical claims
- rationale indicating `AMBIGUOUS_VISUAL_REFERENCE`

The UI may show candidate numbers as evidence, but no automatic insertion is proposed.

### 4.4 Already covered

If the body already contains a matching canonical reference, no `added` coverage candidate is created. The existing forward consistency/VLM path handles validation instead.

### 4.5 Wrong existing reference

If the body contains `도판 44` but the object is depicted by canonical `도판 45`, coverage logic must not simply add 45 alongside 44. Existing reference consistency first resolves/evaluates 44. A correction candidate may propose replacing the incorrect reference only when the graph evidence uniquely supports 45 and the existing reference is proven inconsistent with the same object.

## 5. Graph requirements

Coverage may succeed only when the canonical visual claim is reachable from the selected project scope through authoritative relationships.

Minimum accepted paths include:

`Project -> HAS_DOCUMENT -> Document -> HAS_VERSION -> DocumentVersion -> HAS_PLATE -> Plate -> DEPICTS -> ArchaeologyObject`

or

`Project -> HAS_DOCUMENT -> Document -> HAS_VERSION -> DocumentVersion -> HAS_DRAWING -> Drawing -> DEPICTS -> ArchaeologyObject`

Panel/region variants are allowed through `HAS_PANEL` / `HAS_REGION`.

A graph node from another project or another non-selected ReviewRound visual version must not be used for a proposal.

## 6. OriginalAsset behavior

`OriginalAsset` can strengthen visual evidence but never establishes identity.

If a canonical target has a declared provenance path:

`canonical target -> DERIVED_FROM -> OriginalAsset`

and the OriginalAsset is directly renderable (JPG/PNG/TIFF or another supported rendered representation), it may be included as additional evidence for VLM/manual comparison.

Absence of an OriginalAsset must not invalidate a valid canonical publication reference.

A raw source photo whose only apparent relationship is a filename suffix remains `unlinked` and is excluded from coverage proposals.

## 7. Service boundary

Add a focused deterministic component rather than embedding this logic in the orchestrator:

`VisualReferenceCoverageService`

Responsibilities:

- read graph-derived bundle families,
- normalize canonical publication reference keys,
- detect missing/blank/ambiguous/already-covered states,
- create evidence-backed `CorrectionCandidateData` objects,
- never access the filesystem.

It must be callable from the existing `ProofreadingOrchestrator` after graph bundles are loaded and before candidate prioritization/deduplication.

`RuleEngine` may retain generic reference mismatch checks, but bidirectional coverage logic belongs in this dedicated service to keep responsibilities explicit and testable.

## 8. Orchestrator flow

Target flow:

1. ReviewRound resolves exact body/plate/drawing DocumentVersions.
2. Parse/persist body and canonical visual versions.
3. Build ArchaeologyObjects, References, `RESOLVES_TO`, and `DEPICTS`.
4. Query graph-derived `ObjectEvidenceBundle` for each object.
5. Run existing consistency rules.
6. Run `VisualReferenceCoverageService`.
7. For references already present and resolved, run existing canonical VLM comparison.
8. Run grounded LLM review only on graph evidence.
9. Deduplicate/prioritize candidates and persist them as `pending_review`.

Coverage candidates must be available to the same candidate review UI and evidence graph as other findings.

## 9. Candidate deduplication

Coverage candidate identity should be deterministic for a run/object/reference set, for example from:

`analysisRunId + objectId + normalized missing reference keys + source region`

Equivalent findings from blank-placeholder detection and general missing-reference detection must collapse to one candidate. Prefer the blank-placeholder candidate when both describe the same source region because it provides a more precise replacement location.

## 10. Failure and unresolved states

Fail closed where identity or scope is not proven.

- canonical asset missing: no invented reference
- ambiguous canonical assets: manual review candidate, no proposed number
- graph unavailable in production: preserve existing `GRAPH_EVIDENCE_UNAVAILABLE` behavior
- canonical render missing: coverage reference candidate may still be generated from graph identity, but VLM consistency status is `missing_render`
- source OriginalAsset missing: no effect on canonical identity
- unlinked filename-decoy OriginalAsset: ignored
- cross-project target: rejected

## 11. UI behavior

No new autonomous-edit UI is required.

Candidate display should clearly distinguish:

- `참조 누락` — proposed `added` reference
- `참조 빈칸` — proposed blank-field completion
- `참조 후보 복수` — manual selection required
- `기존 참조 불일치` — existing forward consistency finding

The inspector should show the two evidence sides:

`본문 근거 -> 고고학 객체 <- 실제 도면/도판 근거`

Raw node IDs remain hidden under technical details.

## 12. TDD acceptance matrix

The implementation is incomplete until these tests exist and pass.

### Deterministic unit tests

1. object has Drawing 30 + Plate 45, body has neither -> one/additive coverage proposal containing both
2. body already has Drawing 30 + Plate 45 -> no coverage candidate
3. blank `(도면: , 도판: )` + unique 30/45 -> exact fill proposal
4. blank placeholder + unique drawing but two plates -> fill drawing only; plate remains ambiguous/manual
5. two canonical plates depict object -> no invented plate number
6. wrong existing reference + uniquely proven correct target -> replacement path, not duplicate addition
7. `_45.JPG` OriginalAsset without `DERIVED_FROM` -> cannot create Plate 45 proposal
8. `_91.JPG` exists but canonical Plate 91 absent -> no Plate 91 proposal
9. canonical Plate 45 with `DERIVED_FROM` source photo -> reference identity remains Plate 45; source file only adds provenance evidence
10. filename-number matching API cannot be invoked by production coverage service

### Graph integration tests with real Neo4j

11. selected ReviewRound plate/drawing versions only are eligible
12. same-number asset in another project cannot satisfy coverage
13. removing `DEPICTS` prevents reverse coverage success
14. removing `HAS_PLATE` / `HAS_DRAWING` scope prevents reverse coverage success
15. existing `Reference -> RESOLVES_TO` produces no duplicate added candidate
16. candidate persists `ABOUT -> ArchaeologyObject` and `SUPPORTED_BY -> Evidence`

### Orchestrator tests

17. coverage runs after graph bundle construction
18. graph failure in production fails closed as today
19. coverage findings participate in normal dedupe/budget/persistence
20. existing resolved-reference VLM path still receives body claims and canonical visual version IDs

### Frontend tests

21. missing-reference candidate is labeled `참조 누락`
22. ambiguous candidate shows manual-review wording and no fake replacement
23. evidence inspector exposes body side and canonical visual side

## 13. Explicit non-goals

This feature does not:

- auto-edit the PDF/HWP/INDD source,
- use filenames to infer publication numbers,
- let VLM invent canonical identity,
- require VLM to create deterministic missing-reference candidates,
- replace ReviewRound as run-input authority,
- promote `OriginalAsset` to publication identity,
- auto-accept corrections.

## 14. Definition of done

PASS requires:

- deterministic reverse coverage implemented from real graph evidence,
- existing forward canonical comparison preserved,
- blank references can be completed only when uniquely grounded,
- ambiguity never invents a number,
- filename decoys cannot influence publication identity,
- project/ReviewRound scoping proven in real Neo4j tests,
- all candidates remain `pending_review`,
- backend hermetic, Real Neo4j, frontend typecheck/tests/build all green.

External VLM quality evaluation remains a separate HOLD/verification activity; mocked VLM tests may verify integration behavior.