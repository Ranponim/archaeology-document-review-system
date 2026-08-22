# Bidirectional Visual Reference Coverage Design

Date: 2026-08-22
Status: proposed-for-implementation after user review
Branch: feature/source-provenance-remediation-20260818
Baseline: current branch state derived from a6a54f282e22bdfc1d86b7e6f81a71f663d19269

## 1. Goal

The proofreading system must validate visual references in both directions.

1. If the body already contains a drawing/plate-photo reference, resolve it through the canonical graph and compare the body claim against the real canonical drawing/plate render.
2. If the body omits drawing/plate-photo information but the selected project versions contain canonical visual assets that depict the same ArchaeologyObject, create an evidence-backed correction candidate proposing the missing reference only when both the target identity and insertion location are deterministic.

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

## 4. New deterministic rule: VisualReferenceCoverageService

The new service operates on one graph-derived `ObjectEvidenceBundle` and the selected ReviewRound-scoped canonical visual versions.

Inputs:

- `bundle.text_claims`
- `bundle.references`
- `bundle.plate_claims`
- `bundle.drawing_claims`
- the ArchaeologyObject identity
- active `plateVersionId` / `drawingVersionId` resolved from ReviewRound

The service computes coverage by canonical publication reference key:

- plate/photo key: `(plate, number)`
- drawing key: `(drawing, number)`

The canonical side is derived from `plate_claims` / `drawing_claims` reached through real graph relationships, not from filenames.

The body side is derived from `bundle.references`.

### 4.1 Missing reference with one deterministic insertion region

If a canonical asset depicts the object, the body has no matching reference, and exactly one eligible body text/caption region for that object exists in the active body version, generate a `CorrectionCandidateData`:

- `rule_category = figure_plate_table_photo_ref`
- `change_type = added`
- `status = pending_review`
- `archaeology_object_id = object.id`
- `proposed_text` is the smallest deterministic reference suffix, not a rewritten paragraph
- evidence includes the chosen body `text_claim` plus the canonical plate/drawing claim

Example:

Body region:

`6호 석관묘는 구릉 정상부에 위치한다.`

Graph:

`Drawing 30 -[:DEPICTS]-> 6호 석관묘`
`Plate 45 -[:DEPICTS]-> 6호 석관묘`

Candidate proposal:

`(도면 30, 도판 45)`

### 4.2 Missing reference with multiple possible insertion regions

If the same ArchaeologyObject appears in multiple eligible body regions and no blank placeholder/reference location disambiguates the intended insertion point, the system MUST NOT choose the first occurrence.

Generate a `pending_review` candidate with:

- `proposed_text = None`
- rationale code `AMBIGUOUS_REFERENCE_LOCATION`
- evidence listing the competing body regions and canonical visual claims

This is a manual placement decision.

### 4.3 Blank reference placeholder

A blank placeholder is an explicit insertion location and takes precedence over general missing-reference coverage.

For text such as:

`(도면: , 도판: )`

if exactly one eligible canonical drawing and exactly one eligible canonical plate exist for that object in the active ReviewRound versions, propose:

`(도면: 30, 도판: 45)`

If one type is unique and the other type is ambiguous, emit:

1. one precise blank-fill candidate for the unique part, e.g. `(도면: 30, 도판: )`, and
2. one manual ambiguity candidate for the unresolved type with `proposed_text = None` and rationale `AMBIGUOUS_VISUAL_REFERENCE`.

The blank-fill candidate and generic missing-reference candidate for the same region/reference keys must deduplicate to the blank-fill candidate.

### 4.4 Multiple canonical candidates

If more than one eligible canonical asset of the same type depicts the object and the body does not disambiguate which belongs at that text location, the system MUST NOT invent a number.

Generate a `pending_review` candidate with:

- `proposed_text = None`
- evidence listing the competing canonical claims
- rationale code `AMBIGUOUS_VISUAL_REFERENCE`

The UI may show candidate numbers as evidence, but no automatic insertion is proposed.

### 4.5 Already covered

If the body already contains a matching canonical reference, no `added` coverage candidate is created. The existing forward consistency/VLM path handles validation instead.

### 4.6 Wrong existing reference

Coverage logic must never solve a wrong reference by simply appending another number.

A deterministic replacement candidate is allowed only when all of the following are true:

1. the body contains an existing reference in the same body region,
2. that reference resolves to a canonical target that does not depict the ArchaeologyObject, or the reference is canonically unresolved/missing,
3. exactly one same-type canonical target in the selected ReviewRound visual version depicts the ArchaeologyObject,
4. the target and source body region are both project-scoped and unambiguous.

Then generate a `modified` candidate replacing the existing reference token with the uniquely supported canonical token. Otherwise return a manual ambiguity/unresolved finding with no invented replacement.

## 5. Graph requirements

Coverage may succeed only when the canonical visual claim is reachable from the selected project scope through authoritative relationships.

Minimum accepted paths include:

`Project -> HAS_DOCUMENT -> Document -> HAS_VERSION -> DocumentVersion -> HAS_PLATE -> Plate -> DEPICTS -> ArchaeologyObject`

or

`Project -> HAS_DOCUMENT -> Document -> HAS_VERSION -> DocumentVersion -> HAS_DRAWING -> Drawing -> DEPICTS -> ArchaeologyObject`

Panel/region variants are allowed through `HAS_PANEL` / `HAS_REGION`.

A graph node from another project or another non-selected ReviewRound visual version must not be used for a proposal.

## 6. OriginalAsset boundary

`OriginalAsset` never establishes publication identity and is not an input to `VisualReferenceCoverageService`.

The existing source-provenance implementation remains visible through:

`canonical target -> DERIVED_FROM -> OriginalAsset`

but this feature does not add a new raw-source VLM pipeline. “Actual drawing/photo comparison” in this phase means comparison against the canonical published `Plate/PlatePanel/Drawing/DrawingRegion` render already selected by graph identity.

A future feature may compare a canonical render with a provenance-linked raw source image as additional evidence, but that comparison must not alter canonical identity.

A raw source photo whose only apparent relationship is a filename suffix remains `unlinked` and is excluded from coverage proposals.

## 7. Service boundary

Add a focused deterministic component rather than embedding this logic in the orchestrator:

`VisualReferenceCoverageService`

Responsibilities:

- read graph-derived bundle families,
- normalize canonical publication reference keys,
- detect missing/blank/ambiguous/already-covered/wrong-reference states,
- choose a source region only when deterministic,
- create evidence-backed `CorrectionCandidateData` objects,
- never access the filesystem,
- never query `OriginalAsset` for identity.

It is called from the existing `ProofreadingOrchestrator` after graph bundles are loaded and before candidate prioritization/deduplication.

`RuleEngine` retains generic consistency checks; bidirectional coverage stays in this dedicated service.

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

Coverage candidates use the same candidate review UI and evidence graph as other findings.

## 9. Candidate deduplication

Coverage candidate identity must be deterministic from:

`analysisRunId + objectId + normalized reference keys + source region + finding kind`

Equivalent findings from blank-placeholder detection and general missing-reference detection collapse to one candidate. Prefer the blank-placeholder candidate for the same region because it has an explicit edit location.

Wrong-reference replacement and missing-reference addition are distinct finding kinds and must not collapse into each other.

## 10. Failure and unresolved states

Fail closed where identity or scope is not proven.

- canonical asset missing: no invented reference
- ambiguous canonical assets: manual review candidate, no proposed number
- ambiguous body insertion location: manual review candidate, no proposed text
- graph unavailable in production: preserve existing `GRAPH_EVIDENCE_UNAVAILABLE` behavior
- canonical render missing: deterministic reference coverage may still be identified from graph identity, but VLM comparison remains `missing_render`
- source OriginalAsset missing: no effect on canonical identity
- unlinked filename-decoy OriginalAsset: ignored
- cross-project or non-selected-version target: rejected

## 11. UI behavior

No autonomous-edit UI is added.

Candidate display distinguishes:

- `참조 누락` — deterministic `added` reference
- `참조 빈칸` — deterministic blank-field completion
- `참조 후보 복수` — target selection required
- `삽입 위치 불명확` — body placement required
- `기존 참조 불일치` — deterministic replacement or manual review

The inspector shows both evidence sides:

`본문 근거 -> 고고학 객체 <- 실제 도면/도판 근거`

Raw node IDs remain hidden under technical details.

## 12. TDD acceptance matrix

The implementation is incomplete until these tests exist and pass.

### Deterministic unit tests

1. one body region + Drawing 30 + Plate 45 + no references -> one `added` proposal containing both
2. body already has Drawing 30 + Plate 45 -> no coverage candidate
3. blank `(도면: , 도판: )` + unique 30/45 -> exact fill proposal
4. blank placeholder + unique drawing but two plates -> precise drawing fill plus separate plate ambiguity finding
5. two canonical plates depict object -> no invented plate number
6. multiple body regions + unique visual target + no placeholder -> `AMBIGUOUS_REFERENCE_LOCATION`, no proposed text
7. wrong existing reference + uniquely proven correct target -> `modified` replacement, not duplicate addition
8. unresolved existing reference + uniquely proven target -> deterministic replacement allowed
9. `_45.JPG` OriginalAsset without `DERIVED_FROM` -> cannot create Plate 45 proposal
10. `_91.JPG` exists but canonical Plate 91 absent -> no Plate 91 proposal
11. canonical Plate 45 with `DERIVED_FROM` source photo -> reference identity remains Plate 45 and coverage output is unchanged
12. filename-number matching API cannot be invoked by production coverage service

### Graph integration tests with real Neo4j

13. selected ReviewRound plate/drawing versions only are eligible
14. same-number asset in another project cannot satisfy coverage
15. removing `DEPICTS` prevents reverse coverage success
16. removing `HAS_PLATE` / `HAS_DRAWING` scope prevents reverse coverage success
17. existing `Reference -> RESOLVES_TO` produces no duplicate added candidate
18. candidate persists `ABOUT -> ArchaeologyObject` and `SUPPORTED_BY -> Evidence`

### Orchestrator tests

19. coverage runs after graph bundle construction
20. graph failure in production fails closed as today
21. coverage findings participate in normal dedupe/budget/persistence
22. existing resolved-reference VLM path still receives body claims and canonical visual version IDs
23. no production path calls legacy filesystem filename matching for coverage

### Frontend tests

24. missing-reference candidate is labeled `참조 누락`
25. ambiguous target candidate shows manual-review wording and no fake replacement
26. ambiguous location candidate shows `삽입 위치 불명확`
27. evidence inspector exposes body side and canonical visual side

## 13. Explicit non-goals

This feature does not:

- auto-edit the PDF/HWP/INDD source,
- use filenames to infer publication numbers,
- let VLM invent canonical identity,
- require VLM to create deterministic missing-reference candidates,
- compare raw `OriginalAsset` files with canonical renders in a new VLM pipeline,
- replace ReviewRound as run-input authority,
- promote `OriginalAsset` to publication identity,
- auto-accept corrections.

## 14. Definition of done

PASS requires:

- deterministic reverse coverage implemented from real graph evidence,
- existing forward canonical comparison preserved,
- blank references completed only when uniquely grounded,
- insertion location selected only when uniquely grounded,
- wrong references replaced only when uniquely grounded,
- ambiguity never invents a number or body location,
- filename decoys cannot influence publication identity,
- project/ReviewRound scoping proven in real Neo4j tests,
- all candidates remain `pending_review`,
- backend hermetic, Real Neo4j, frontend typecheck/tests/build all green.

External VLM quality evaluation remains a separate HOLD/verification activity; mocked VLM tests may verify integration behavior.