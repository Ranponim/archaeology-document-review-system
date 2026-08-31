# Drawing Evidence Graph Design

Date: 2026-08-24
Branch: `feature/adobe-free-provenance-20260823`
Status: approved in chat; written spec pending final user review before implementation

## 1. Purpose

The Adobe-free audit has moved the main bottleneck from file readability to cross-source identity resolution.

Current real `/src` results:

- body reference page coverage: 384/384 (100.0%)
- plate panel segmentation: 2,750/2,804 (98.1%)
- AI readable/renderable/PDF-compatible: 56/56 (100.0%)
- AI direct semantic identity: 1/56 (1.8%)
- AI resolved_any using filename fallback: 35/56 (62.5%)
- AI heuristic-only: 34/56 (60.7%)
- AI unresolved: 21/56 (37.5%)
- exact verified body→source sample chains: 2/7 (28.6%)

The next subsystem must convert currently isolated clues into explicit graph evidence while preserving the fail-closed rule: no filename-only or low-confidence candidate may become canonical verified identity.

The target is to resolve archaeological drawing identity from independent evidence families:

1. body drawing caption/reference
2. nearby body text/title/context
3. AI internal PDF-compatible text
4. AI filename number/title tokens
5. normalized drawing content entities such as site, point/grid, direction, layer, feature/object and section labels

## 2. Design principles

### 2.1 Canonical identity and candidate identity are different nodes

A `DrawingCandidate` is allowed to be wrong. A canonical `Drawing` is not.

Candidate/evidence nodes may contain heuristic associations, competing identities and conflicting sources. Canonical `Drawing` nodes are created or promoted only after a verification gate passes.

### 2.2 Independent evidence families matter more than raw score

The resolver must not promote a candidate merely because several correlated filename tokens add up to a large numeric score.

Evidence is grouped into independent families:

- `identity`: explicit internal identifier or filename drawing number
- `body_context`: drawing reference, caption, same-page/nearby body text
- `semantic_content`: normalized archaeological entities extracted independently from body and AI content
- `visual_structure`: optional deterministic/visual evidence added later; not required for the first implementation

A promotion requires evidence from more than one independent family unless direct identity exists.

### 2.3 Fail closed

If evidence conflicts, the top candidate is not sufficiently unique, a global one-to-one assignment is unstable, or only filename evidence exists, the result remains `HEURISTIC` or `UNRESOLVED`.

No threshold lowering may be used merely to increase the success rate.

### 2.4 Provenance must remain explainable

Every promoted identity must be reproducible from stored graph evidence. The graph must expose which source text/token/entity supported or contradicted a candidate, the scoring method/version, and the winning/second-best margin.

## 3. Graph model

### 3.1 Existing nodes reused

- `Project`
- `DocumentVersion`
- `Page`
- `TextBlock`
- `Caption`
- `Reference`
- `OriginalAsset` for AI files
- canonical `Drawing`
- `ArchaeologyObject` where existing object extraction already provides a trustworthy entity

### 3.2 New nodes

#### `DrawingCandidate`

Properties:

- `id`
- `referenceCorpusId`
- `sourceAssetId`
- `candidateNumber`
- `status`: `candidate | verified | ambiguous | unresolved`
- `evidenceLevel`: `direct | derived_verified | heuristic | unresolved`
- `resolverVersion`
- `score`
- `runnerUpScore`
- `margin`
- `createdAt`

Candidate IDs must be deterministic within one corpus, for example:

`drawing-candidate:{corpus_id}:{source_asset_id}:{candidate_number}`

#### `ResolutionEvidence`

Properties:

- `id`
- `family`: `identity | body_context | semantic_content | visual_structure`
- `method`
- `value`
- `normalizedValue`
- `weight`
- `score`
- `sourceSha256`
- `sourcePage`
- `sourceNodeId`
- `resolverVersion`
- `createdAt`

Evidence IDs should be deterministic from corpus, candidate, family, method and source fact so reruns are idempotent.

#### `ContextEntity`

A lightweight normalized fact used for deterministic matching, not a new ontology authority.

Properties:

- `id`
- `kind`: examples `site`, `point`, `grid`, `direction`, `feature`, `layer`, `section_label`, `drawing_type`
- `value`
- `normalizedValue`
- `sourceKind`: `body | drawing_ai`
- `sourceSha256`
- `sourceNodeId`

Examples:

- `2지점` → `kind=point`, `normalizedValue=2`
- `S1 E1` → `kind=grid`, `normalizedValue=S1E1`
- `북동` → `kind=direction`, `normalizedValue=북동`
- `토층` → `kind=drawing_type`, `normalizedValue=토층`

### 3.3 Relationships

The first implementation should use a small, explicit relationship vocabulary:

- `(OriginalAsset)-[:PROPOSES]->(DrawingCandidate)`
- `(DrawingCandidate)-[:TARGETS]->(Drawing)` only after canonical identity exists and verification gate permits this relation
- `(DrawingCandidate)-[:SUPPORTED_BY]->(ResolutionEvidence)`
- `(DrawingCandidate)-[:CONTRADICTED_BY]->(ResolutionEvidence)`
- `(ResolutionEvidence)-[:FROM_SOURCE]->(OriginalAsset|TextBlock|Caption|Reference|Page)` when the source node is persisted
- `(ResolutionEvidence)-[:USES_CONTEXT]->(ContextEntity)`
- `(TextBlock|Caption|OriginalAsset)-[:HAS_CONTEXT]->(ContextEntity)`

The candidate graph is corpus-scoped. Queries must start from `Project`/`ReferenceCorpus` ownership and must never treat a global candidate ID supplied by a client as authority.

## 4. Context extraction

### 4.1 Body context

For every body `Reference` of type drawing:

1. use the explicit drawing number as the target identity candidate
2. collect the source Caption/TextBlock
3. collect same-page neighboring TextBlocks by order
4. collect the page Caption for the same drawing number where available
5. normalize archaeological terms into `ContextEntity` facts

The first implementation should use a deterministic window rather than an LLM. Suggested default: the source block/caption plus the previous and next two TextBlocks on the same page, stopping at page boundaries.

### 4.2 AI context

For each PDF-compatible AI:

1. extract all available PDF text blocks
2. retain direct `도면 N`/`삽도 N` identity when present
3. normalize filename tokens, but keep them in the `identity` family with heuristic strength
4. normalize text/content entities using the same deterministic normalizer used for body context
5. retain source SHA and text/page coordinates where available

AI files with outlined text may have no semantic text. They remain candidates only if other evidence exists; lack of text must not be interpreted as negative evidence.

## 5. Candidate generation

### 5.1 Direct candidate

If AI internal content explicitly contains one unambiguous drawing identifier, create a direct candidate for that number.

This remains `EvidenceLevel.DIRECT` and is not dependent on graph scoring.

### 5.2 Filename candidate

If filename contains exactly one drawing/illustration number, create a heuristic candidate.

Filename alone can never produce `DERIVED_VERIFIED`.

### 5.3 Content-derived candidates

For AI without a filename number, or to provide competing candidates for validation, compare normalized AI context entities with body drawing contexts and generate the top small candidate set.

Initial limit: at most top 5 candidates per AI source after deterministic pruning.

Pruning rules should prefer exact normalized entity matches before fuzzy text similarity.

## 6. Scoring and promotion gate

### 6.1 Family scoring

A candidate receives per-family evidence scores. The first implementation should remain deterministic and versioned.

Suggested evidence behavior:

- internal explicit drawing ID: direct, bypass normal promotion scoring
- filename drawing number: strong heuristic identity clue, but insufficient alone
- exact body caption number match: direct body-side identity fact, but it does not identify the AI by itself
- exact shared normalized grid/point/direction/drawing-type entities: semantic support
- title/token overlap after normalization: additional body-context support
- contradictions such as incompatible point/grid identifiers: negative evidence

No exact numeric weights are part of the public contract. They must be test-backed and stored under a resolver version.

### 6.2 Required gate for `DERIVED_VERIFIED`

A non-direct candidate may be promoted only when all conditions hold:

1. candidate has evidence from at least two independent families, one of which must be `body_context` or `semantic_content`
2. filename-only is insufficient
3. no hard contradiction exists
4. the candidate is the unique winner for that AI source above a configured minimum score
5. winning score exceeds runner-up by a configured minimum margin
6. global assignment does not produce a one-to-many conflict for canonical drawing identity
7. promotion can be explained by persisted evidence nodes

If any condition fails, retain `HEURISTIC` or `UNRESOLVED`.

## 7. Global assignment

Local best-match decisions are insufficient because current real data already contains conflicting drawing numbers.

The resolver therefore performs a project/corpus-scoped assignment after candidate scoring.

Rules:

- one AI source may verify to at most one canonical drawing identity
- one canonical drawing identity may be verified to at most one AI source unless an explicit configuration later allows multi-source revisions
- direct internal identifiers outrank derived candidates
- an existing direct assignment blocks a heuristic/derived contender for the same identity
- ties or near-ties remain ambiguous rather than being broken arbitrarily

The first implementation may use a deterministic maximum-weight bipartite assignment over eligible candidates, with direct assignments pre-locked and ambiguous near-ties excluded before optimization.

## 8. Persistence and canonical graph behavior

### 8.1 Candidate graph persistence

Candidate/evidence nodes are saved before canonical promotion so failed and ambiguous reasoning is inspectable.

Rerunning the same corpus with the same resolver version must be idempotent.

### 8.2 Canonical `Drawing`

- direct AI identity may produce/update the corpus-scoped canonical `Drawing` as today
- `DERIVED_VERIFIED` may produce/update the canonical `Drawing`
- `HEURISTIC` and `UNRESOLVED` must not become canonical verified Drawing identities
- `DERIVED_FROM` edges from canonical Drawing to AI OriginalAsset are allowed only for direct or derived_verified identities
- heuristic candidate relations remain only in the candidate/evidence graph

### 8.3 READY gate

A corpus may remain READY with unresolved drawings if the product contract permits incomplete evidence, but READY must not imply 100% identity resolution.

The corpus must expose counts for:

- direct
- derived_verified
- heuristic
- unresolved
- ambiguous/conflicted

## 9. Validation experiment on real `/src`

### 9.1 Blinded 35-file evaluation

The 35 AI files whose filenames contain a drawing number serve as a silver-label evaluation set.

For the blinded experiment:

1. hide the filename drawing number from candidate generation/scoring
2. use AI internal text/content plus body context graph only
3. rank canonical drawing identities
4. only after prediction, compare with the hidden filename label

Report:

- Top-1 agreement
- Top-3 agreement
- unique verified count under the normal promotion gate
- ambiguous count
- unresolved count
- cases where hidden filename and content disagree

The hidden filename label is not ground truth; disagreement cases require manual/error analysis and must not be counted automatically as resolver errors.

### 9.2 Positive control

The one AI with explicit internal drawing identity is a positive control. The graph resolver must preserve its direct identity and must not downgrade or conflict with it.

### 9.3 Full 56-file evaluation

After the blinded test, rerun with all evidence enabled across all 56 AI files.

Report before/after counts:

- direct
- derived_verified
- heuristic-only
- unresolved
- ambiguous/conflicted

The success criterion is not a predetermined resolution percentage. The required outcome is:

- at least one new `DERIVED_VERIFIED` identity from graph evidence, or a documented evidence-based conclusion that the corpus lacks sufficient independent content
- zero known false verified identities in reviewed samples
- no filename-only promotion
- all conflicts explainable from stored evidence

## 10. Tests

### 10.1 Unit tests

Add RED tests before implementation for:

- deterministic context normalization
- filename-only remains heuristic
- filename + independent matching body/AI context can become derived_verified
- hard contradiction prevents promotion
- insufficient margin prevents promotion
- direct internal ID outranks candidate scoring
- outlined/no-text AI remains unresolved rather than negative
- global one-to-one assignment resolves a clear conflict
- near-tie global conflict remains ambiguous
- rerun persistence is idempotent

### 10.2 Neo4j integration tests

Verify:

- candidate/evidence nodes are corpus scoped
- heuristic candidate does not create canonical DERIVED_FROM edge
- direct/derived_verified candidate does create the allowed source edge
- ambiguity is queryable
- READY validation still passes with explicitly unresolved candidates
- project isolation prevents cross-project candidate/source reuse

### 10.3 Real `/src` audit

Create/update machine-readable and human-readable outputs, for example:

- `docs/local_drawing_evidence_graph_report.md`
- `docs/local_drawing_evidence_graph_metrics.json`

The real-data report must include selected evidence paths for each promoted identity and representative unresolved/conflict cases.

## 11. Implementation boundaries

In scope:

- deterministic context extractor/normalizer
- candidate/evidence domain models
- candidate graph repository
- graph-aware drawing identity resolver
- global assignment
- ReferenceCorpus integration
- tests and local audit script/instructions
- metrics/reporting

Out of scope for the first implementation:

- LLM-generated evidence
- VLM-based drawing interpretation
- generic knowledge-graph ontology redesign
- automatic promotion from filename alone
- panel→JPG matcher redesign
- Adobe/COM/ExtendScript dependency

## 12. Expected result

The system should move from:

`AI file → filename heuristic → maybe Drawing N`

to:

`AI file → multiple explicit evidence paths → DrawingCandidate → uniqueness/conflict gate → direct/derived_verified canonical Drawing or fail-closed unresolved`

This is intended to improve verified drawing identity while making every promotion explainable, reversible and independently auditable.
