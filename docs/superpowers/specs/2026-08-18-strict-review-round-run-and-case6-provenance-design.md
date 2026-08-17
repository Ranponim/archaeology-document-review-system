# Strict ReviewRound Run Contract and Case 6 Canonical Provenance Design

## Status
Approved design for remediation of regressions introduced after commit `ee82aa50ecb2838fdc84c2606c375e87445762a9`, with current working base `32879b1a8f7b451cc432b9d820b8b0a297e8d037` on branch `review-remediation-20260818-strict-run-contract`.

## Goals
1. Restore ReviewRound as the only production authority for starting analysis runs.
2. Make legacy run inputs impossible to use, even when `reviewRoundId` is present.
3. Put strict `/runs` negative tests into the mandatory CI path rather than deselecting them.
4. Restore Case 6 identity semantics so filenames never establish publication plate identity.
5. Retain useful post-remediation fixes from `0aaee3d` only when they preserve graph authority.
6. Hold external VLM acceptance until API, graph identity, and provenance are revalidated.

## Non-goals
- No backward-compatible production direct-version run path.
- No feature flag that re-enables legacy run execution.
- No external VLM pass/fail claim in this remediation batch.
- No fabrication of Golden Dataset expert provenance.

## 1. Production `/runs` contract
There must be exactly one production route:

`POST /api/v1/projects/{project_id}/runs`

Accepted request fields:
- `reviewRoundId` — required, non-empty
- `enableVlm` — optional
- `enableAiReview` — optional

Forbidden request fields include, but are not limited to:
- `bodyVersionId`
- `plateVersionId`
- `drawingVersionId`
- `bodyPdfPath`
- `platePdfPath`
- `drawingPdfPath`
- `versionStage`

The request model must use strict extra-field rejection (`extra="forbid"`). Therefore:
- missing `reviewRoundId` => HTTP 422
- legacy-only payload => HTTP 422
- valid `reviewRoundId` plus any legacy field => HTTP 422

A valid request resolves the referenced ReviewRound from the project graph. The exact body/plate/drawing `DocumentVersion` IDs stored on that ReviewRound are the only inputs allowed to create the `AnalysisRun` and enqueue the worker.

## 2. Route ownership
`backend/app/api/review_round_runs.py` owns the sole public `/runs` route.

The compatibility `/runs` handler in `backend/app/api/reviews.py` must be deleted, not hidden by router order. The application must register `review_round_runs_router` explicitly. OpenAPI and runtime routing must expose the same strict contract.

Any helper whose only purpose is direct-version/stage/path run execution should be removed or made private to non-production code if still required by tests; production request handling must not call it.

## 3. CI contract gate
Strict API contract tests are P0 mandatory tests and must run in the normal hermetic backend job.

Required negative tests:
1. `{}` => 422
2. `{"bodyVersionId":"..."}` => 422
3. `{"reviewRoundId":"round-x","bodyVersionId":"..."}` => 422
4. `{"reviewRoundId":"round-x","versionStage":"3차"}` => 422
5. `{"reviewRoundId":"round-x","bodyPdfPath":"/tmp/body.pdf"}` => 422

Required authority tests:
- nonexistent ReviewRound fails closed
- ReviewRound from another project fails closed
- valid ReviewRound creates an AnalysisRun using exactly its body/plate/drawing version IDs
- conflicting client version IDs can never override graph membership because such requests are rejected before execution

The current 12 run/version tests that are deselected must be either:
- rewritten to test the strict ReviewRound contract, or
- removed if they only specify obsolete direct-version behavior.

The CI command must not need those 12 `--deselect` entries after this remediation.

## 4. ReviewRound predecessor invariants
The already-remediated predecessor behavior remains mandatory:

`current ReviewRound <-[:PRECEDES]- previous ReviewRound -> bodyVersionId`

DocumentVersion stage labels such as `1차`, `2차`, `3차`, `source`, or `final` must not determine predecessor identity.

Regression scenario:
- Round 1 -> body v1
- Round 2 -> body v2
- Round 3 -> body v2 (reuse)
- Round 4 -> body v3
- Round 5 -> body v4
- all `DocumentVersion.stage = "source"`

Round 4 comparison must use previous body v2 and current body v3.

## 5. Case 6 canonical identity and provenance
Case 6 represents the filename-suffix trap.

Identity path:

`body text "도판 45" -> Reference(type=plate, number=45) -> RESOLVES_TO -> canonical Plate/PlatePanel with publication identifier 【도판 45】`

Rules:
- a filename such as `4. 조사 후_45.JPG` has zero authority to establish plate 45 identity
- a decoy `_45.JPG` must never satisfy an unresolved `Reference(number=45)`
- a decoy `_91.JPG` must never satisfy missing publication plate 91
- Links/source-photo files may be shown only after provenance is established from the canonical Plate/PlatePanel target
- if canonical target exists but no provenanced render/source asset exists, return `missing_render` or another explicit unresolved state
- if canonical target does not exist, fail closed with unresolved reason; never substitute by filename

Required graph evidence for a shown Links asset must be derivable from the canonical target. The exact relationship implementation may use existing provenance relationships, but the test must prove the asset is reached from the canonical Plate/Panel rather than discovered by filename suffix.

## 6. Post-`0aaee3d` changes to retain or reject
### Retain, subject to regression tests
- candidate deduplication improvements
- canonical-entry reference filtering that deduplicates repeated graph rows by target ID
- `parse_dimensions()` defense that ignores reference dictionaries instead of interpreting `plate_number`/`drawing_number` as dimensions
- live validation timeout increase
- stress fixture batching and 50+ finding generation

### Re-evaluate before retaining
- synthetic plate/drawing fixture object mismatches added only to force comparison categories; keep only if they do not weaken canonical identity assertions

### Remove
- optional `reviewRoundId` production execution
- direct body/plate/drawing version IDs in public run execution
- server PDF path inputs in public run execution
- stage-based run selection
- router changes that removed the strict ReviewRound route and made the compatibility route authoritative

## 7. VLM status
External VLM evaluation is HOLD for this batch.

The existing 10-case archaeological evaluation report must not be treated as externally shareable acceptance evidence because it contains unverified VLM/cost claims and a Case 6 filename-based mapping contradiction.

During this remediation:
- do not rerun or optimize external VLM for PASS
- do not mark VLM semantic accuracy PASS
- keep VLM-related code paths buildable and testable with mocks where appropriate
- mark external VLM as `NOT VERIFIED / HOLD`

After strict API and canonical provenance pass, a later acceptance run may re-run the 10 cases using only canonical graph-selected assets.

## 8. Evaluation report status
`docs/superpowers/reviews/2026-08-17-archaeologist-10-cases-evaluation-report.md` must be clearly marked as invalidated/superseded for acceptance use until rerun.

It must not claim:
- 100% filename-trap defense based on filename-selected images
- verified token/cost statistics without preserved raw run evidence
- verified canonical photo mapping where graph provenance was not recorded

The historical content may remain for audit, but it must carry an explicit warning at the top that VLM results are HOLD and Case 6 canonical provenance requires rerun.

## 9. Mandatory verification gates
Software remediation can be called PASS only when all of these are true:
- strict `/runs` route is the only runtime route
- no `reviewRoundId` => 422
- any forbidden legacy input => 422, including when combined with `reviewRoundId`
- no direct-version production compatibility path remains
- normal backend CI runs strict API tests without the 12 legacy deselections
- Real Neo4j integration passes
- frontend typecheck/tests/build pass
- ReviewRound predecessor reuse scenario passes with all stages `source`
- Case 6 decoy filename test passes
- canonical target/provenance controls visual asset selection
- 50+ raw-finding stress harness remains available
- external VLM is reported `NOT VERIFIED / HOLD`

## 10. Verification-agent evidence requirements
The verification agent must record:
- tested SHA
- exact CI run URL and job results
- exact `/runs` request/response examples for 422 cases
- OpenAPI/runtime proof that one strict route exists
- Neo4j rows proving ReviewRound input membership
- Neo4j rows proving Round 4 predecessor body v2
- Case 6 graph path `Reference(45) -> RESOLVES_TO -> 【도판 45】`
- decoy `_45.JPG` and `_91.JPG` outcomes
- visual-bundle JSON showing canonical/provenance selection or explicit unresolved state
- confirmation that external VLM was not used as a PASS criterion

## 11. P0 failure conditions
Any of the following is a P0 failure:
- production run can start without ReviewRound
- any legacy version/path/stage field is silently accepted
- router ordering rather than route deletion is relied upon for strictness
- strict API tests remain deselected from official CI
- current/previous body selection falls back to stage identity
- filename suffix establishes or repairs plate identity
- a Links asset is displayed as canonical without graph provenance from the canonical Plate/Panel
- VLM or AI repairs identity or supplies missing graph truth
