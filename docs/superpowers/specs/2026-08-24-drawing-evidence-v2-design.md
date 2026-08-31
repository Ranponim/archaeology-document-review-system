# Drawing Evidence Graph v2 Design

## Purpose

Improve Adobe-free AI drawing identity resolution without weakening the existing fail-closed provenance rules. The current `drawing-evidence-v1` architecture is safe and explainable, but the real `/src` revalidation resolves only 4 of 56 AI files canonically (`direct=1`, `derived_verified=3`) and the filename-blinded evaluation reaches only 8/35 Top-1 and 13/35 Top-3 agreement.

The v2 design keeps the current Candidate/Evidence/ContextEntity graph model and improves the quality of evidence used to rank and promote candidates.

## Baseline

The accepted real-data baseline is:

- AI files: 56
- Body drawing contexts: 132
- Filename-labeled AI: 35
- Direct: 1
- Derived verified: 3
- Heuristic-only: 23
- Ambiguous: 10
- Unresolved: 19
- Blinded Top-1: 8/35 (22.8571%)
- Blinded Top-3: 13/35 (37.1429%)
- Filename-only verified: 0
- Known reviewed false verified: 0
- Adobe/COM/ExtendScript: not used
- `/src`: read-only

## Non-goals

- Do not lower verification thresholds merely to increase recall.
- Do not treat filename, folder path, or sequence order as canonical authority.
- Do not introduce LLM/VLM or embedding dependencies in this iteration.
- Do not change the Adobe-free plate/JPG pipeline in this iteration.
- Do not remove the existing `direct / derived_verified / heuristic / unresolved` evidence levels.

## Requirement 1: Separate Drawing and Illustration Identity Spaces

`도면 N` and `삽도 N` must no longer compete in the same identity namespace.

Introduce an explicit publication reference kind:

- `drawing`
- `illustration`

Canonical identity is the pair `(kind, number)` rather than number alone.

Examples:

- `도면 3` => `(drawing, 3)`
- `삽도 3` => `(illustration, 3)`

A candidate whose AI source kind is explicitly `illustration` must not be promoted to a `drawing` target, and vice versa. Cross-kind matching is a hard contradiction when both sides are explicit.

Backward compatibility: existing body references that currently normalize both labels into `ref_type="drawing"` must gain a separate kind field or equivalent lossless representation without breaking consumers that still expect the broad drawing reference type.

## Requirement 2: Structured Archaeological Signature

Replace the current coarse semantic matching emphasis with deterministic structured facts.

The normalizer must recognize at least these fact kinds when they are explicit in source text:

- `site_point`: `1지점`, `2지점`, ...
- `period`: e.g. `청동기시대`, `원삼국시대`, `고려시대`, `조선시대`, `구석기시대`
- `grid`: e.g. `S1E1`
- `feature_type`: e.g. `토광묘`, `옹관묘`, `석곽묘`, `석관묘`, `주거지`, `수혈`, `구상유구`, `분구묘`
- `feature_number`: e.g. `1호`, `2호`
- `drawing_type`: e.g. `평면도`, `단면도`, `입단면도`, `평·단면도`, `토층도`, `현황도`, `위치도`
- `direction`: e.g. `북동`, `남벽`
- `section_label`: e.g. `A-A'`
- `content_type`: e.g. `출토유물`
- `map_type`: e.g. `위성지도`, `항공지도`, `분포도`, `해동지도`, `광여도`
- `year`: four-digit map/year context such as `1968`, `1989`, `2007`, `2012` when semantically tied to map evidence

A structured signature is an immutable normalized collection of these facts for one mention/source context. Exact structured matches contribute stronger evidence than generic lexical overlap.

Generic lexical Jaccard may remain only as weak supporting evidence and must not independently satisfy the multi-family verification gate.

## Requirement 3: Mention-level Context and Consensus

Do not merge every body mention for the same publication identity into a single unconditional union before scoring.

Represent body evidence at two levels:

1. `MentionContext`: one explicit reference/caption plus its local neighbor blocks.
2. `CanonicalSignature`: consensus facts derived across mention contexts for one `(kind, number)` identity.

Consensus rules:

- A fact repeated across independent mentions is high-confidence canonical evidence.
- A fact present in only one mention remains mention-local weak evidence.
- Mutually incompatible explicit facts reduce confidence and remain traceable as conflicts.
- Candidate scoring must compare AI evidence against the best compatible mention context and the canonical consensus, rather than the union of unrelated nearby vocabulary.

Neo4j persistence must retain enough provenance to explain which mention supplied each supporting or contradicting fact.

## Requirement 4: Stronger Contradiction Rules

Current hard contradictions for point/grid remain.

Add contradiction handling for explicit structured facts:

### Hard contradictions

When both sides explicitly specify different values:

- publication `kind`
- `site_point`
- `grid`
- the pair `(feature_type, feature_number)` when both components are known on both sides

A hard contradiction removes that candidate from promotion eligibility regardless of lexical similarity.

### Strong contradictions

When both sides explicitly specify different values:

- `period`
- `map_type`
- `year` when map evidence is being compared

Strong contradictions materially reduce score and prevent promotion unless stronger independent direct evidence exists. They must never override a unique internal PDF identifier.

## Requirement 5: Path and Sequence as Tie-breakers Only

Folder/path and publication sequence may be used only after semantic/structured candidates exist.

Allowed examples:

- AI under `본문 도면/3지점/` weakly favors body contexts with `site_point=3`.
- Nearby publication numbering/order may break an otherwise near-equal tie when surrounding already-verified assignments make one ordering globally more coherent.

Restrictions:

- Path alone cannot create a candidate.
- Filename alone cannot promote a candidate.
- Sequence alone cannot promote a candidate.
- Path/filename/sequence evidence may not satisfy the required independent semantic evidence family count.

## Resolver v2 Promotion Policy

The resolver version becomes `drawing-evidence-v2`.

Promotion hierarchy:

1. Unique internal explicit identifier => `DIRECT`.
2. Otherwise candidate must have no hard contradiction.
3. Candidate must have at least two independent positive evidence families, including structured semantic/body evidence.
4. Candidate must satisfy the configured minimum score and minimum margin over the runner-up.
5. Global one-to-one assignment remains mandatory.
6. Filename/path/sequence can adjust ranking but cannot by themselves make a candidate eligible.
7. Near ties remain `ambiguous`.
8. Missing evidence remains `heuristic` or `unresolved`; do not invent a target edge.

The exact numeric weights may be tuned only by deterministic tests and blinded real-data evaluation. Threshold changes are acceptable only if safety contracts remain green and no new reviewed false verification is introduced.

## Graph Model Changes

Keep existing nodes:

- `DrawingCandidate`
- `ResolutionEvidence`
- `ContextEntity`
- canonical `Drawing`

Add or extend metadata so evidence can record:

- publication kind
- mention-context identifier
- structured fact kind/value
- consensus status (`consensus`, `mention_local`, `conflict`)
- evidence source provenance
- tie-breaker class (`semantic`, `path`, `sequence`, `filename`)

`TARGETS` must continue to exist only for `DIRECT` or `DERIVED_VERIFIED` candidates.

## Data Flow

1. Read body drawing references and local neighbors from the latest body document version.
2. Preserve each reference as a separate mention context.
3. Normalize mention text into structured archaeological facts.
4. Build consensus signatures per `(kind, number)`.
5. Read each PDF-compatible AI source and normalize internal text into the same structured fact vocabulary.
6. Parse filename/path into separate weak evidence channels; do not mix them into canonical semantic facts.
7. Score AI against compatible body identities using structured exact matches, consensus strength, weak lexical support, and contradiction penalties.
8. Apply local score/margin gates.
9. Apply global one-to-one assignment with kind separation.
10. Persist candidates, evidence, context facts, conflicts, and verified targets to Neo4j.
11. Produce blinded and full `/src` revalidation metrics.

## Real-data Evaluation

Run the same read-only evaluator concept against `/src` after v2 implementation.

### Blinded 35

For all filename-labeled AI files:

- hide filename number from scoring
- retain it only as a silver-label comparison after inference
- measure Top-1 agreement
- measure Top-3 agreement
- measure unique verified count
- record ambiguous and no-candidate cases

### Full 56

Measure:

- direct
- derived_verified
- heuristic_only
- ambiguous
- unresolved
- canonical drawing count
- hard contradiction count
- kind collision count
- filename-only verified count
- reviewed false verified count

## Acceptance Criteria

Minimum success for this iteration:

- Blinded Top-1 > 8/35
- Blinded Top-3 > 13/35
- Derived verified > 3/56
- Direct remains >= 1/56
- Filename-only verified = 0
- Kind collision = 0
- Hard contradiction promoted = 0
- Existing direct identifier remains direct
- Existing fail-closed behavior remains intact
- Backend hermetic CI passes
- Frontend CI passes
- Real Neo4j E2E passes

If recall metrics do not improve while safety remains intact, the implementation is not considered a successful resolver improvement; report the result and keep v1 as the production default until a later evidence source is added.

## Testing Strategy

Use TDD for each behavior:

- kind separation regression tests
- structured normalizer tests for each fact family
- mention-consensus tests
- hard/strong contradiction tests
- path/sequence cannot independently promote tests
- global assignment tests across duplicate numbers in different kinds
- repository persistence tests for mention provenance/consensus metadata
- production corpus-service integration tests
- evaluator contract tests
- real `/src` blinded/full evaluation

Every regression test must demonstrate the intended RED failure before production code is added.

## Compatibility and Rollout

- Preserve `drawing-evidence-v1` behavior/configuration until v2 passes acceptance criteria.
- v2 may be implemented behind an explicit resolver version or class so production assembly can switch only after successful real-data revalidation.
- Existing plate/PDF/JPG provenance behavior remains unchanged.
- Existing PR #47 remains Draft and must not be merged as part of this work.
- The main long-running PR remains open/unmerged unless separately approved.
