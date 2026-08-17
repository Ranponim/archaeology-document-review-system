# ReviewRound Predecessor + Evidence-Aware Visual Comparison Design

**Date:** 2026-08-17  
**Branch:** `review-remediation-20260817`  
**Status:** Approved design, implementation pending  

## 1. Purpose

This change fixes two remaining MVP correctness problems without introducing a general-purpose evidence viewer.

1. **Revision comparison authority:** previous-body comparison must come from the immediate predecessor `ReviewRound`, not from `DocumentVersion.stage` strings such as `3차`.
2. **Frontend comparison meaning:** the Split View must show the evidence that actually produced the candidate. A numeric/text revision candidate must not render an empty plate/photo pane merely because the right-hand pane is currently hard-coded as a canonical visual pane.

The goal is a small, explicit set of comparison modes built on the existing Graph/Evidence/VisualAsset infrastructure.

---

## 2. Non-negotiable invariants

### 2.1 ReviewRound lineage is the only revision-order authority

For a current round:

```text
(previous:ReviewRound)-[:PRECEDES]->(current:ReviewRound)
```

The previous body is:

```text
previous -[:USES_BODY_VERSION]-> previousBody
```

The current body is:

```text
current -[:USES_BODY_VERSION]-> currentBody
```

`DocumentVersion.stage` is compatibility/display metadata only. It must not determine revision identity.

This scenario must work even when every uploaded document has `stage=source`:

```text
Round #1 -> body v1
Round #2 -> body v2
Round #3 -> body v2  # reuse
Round #4 -> body v3
Round #5 -> body v4
```

For Round #4 the comparison pair must be `body v2 -> body v3` because Round #3 is the immediate predecessor.

### 2.2 The UI must never imply a visual comparison that did not happen

A candidate such as:

```text
길이 220cm -> 길이 210cm
```

must not automatically display:

```text
표준 도판 / 사진
해당 에셋 렌더 없음
```

unless a plate/photo reference is actually part of the candidate's evidence path.

### 2.3 Wrong asset is worse than no asset

Canonical visual selection remains fail-closed. If the exact reference target cannot be determined, return an explicit unresolved state rather than the first asset depicting the same object.

### 2.4 Comparison provenance must be visible

The user must be able to answer, from the candidate screen:

> “이 220cm -> 210cm 제안은 정확히 무엇과 무엇을 비교해서 나온 것인가?”

The response must name the comparison type and expose relevant `DocumentVersion`, page, reference, and target identifiers when available.

---

# 3. Workstream A — ReviewRound predecessor resolution

## 3.1 Current problem

`backend/app/jobs/run_inputs.py` still derives comparison stages from strings:

```text
4차 -> 3차, 4차
```

and resolves the previous body through `resolve_version_input(..., stage="3차")`.

This fails for the actual frontend workflow because uploads are intentionally stored with `stage=source`, and it also fails conceptually when a body version is reused across rounds.

## 3.2 Target repository API

Add an explicit repository operation that returns the immediate predecessor round for a project-scoped current round.

Recommended shape:

```python
def get_previous_review_round(
    self,
    project_id: str,
    round_id: str,
) -> ReviewRound | None:
    ...
```

Cypher authority:

```cypher
MATCH (project:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->
      (current:ReviewRound {id: $round_id})
OPTIONAL MATCH (previous:ReviewRound)-[:PRECEDES]->(current)
WHERE (project)-[:HAS_REVIEW_ROUND]->(previous)
OPTIONAL MATCH (previous)-[:USES_BODY_VERSION]->(body:DocumentVersion)
OPTIONAL MATCH (previous)-[:USES_PLATE_VERSION]->(plate:DocumentVersion)
OPTIONAL MATCH (previous)-[:USES_DRAWING_VERSION]->(drawing:DocumentVersion)
RETURN ...
```

No stage arithmetic is allowed in this path.

## 3.3 Target worker input resolution

For a ReviewRound-backed AnalysisRun:

```text
AnalysisRun
  -> FOR_ROUND -> current Round

current Round
  -> current body

PRECEDES inverse
  -> previous Round
  -> previous body
```

`resolve_body_versions_for_alignment()` should receive explicit current and previous `VersionInput` values for ReviewRound execution, or a new small helper should be introduced for round-aware comparison.

Recommended minimal contract:

```python
async def resolve_round_body_versions_for_alignment(
    *,
    current_round: ReviewRound,
    previous_round: ReviewRound | None,
    current_body: VersionInput,
    previous_body: VersionInput | None,
    ...,
) -> tuple[dict[str, list[ParsedPage]], dict[str, str]]:
    ...
```

The keys may remain compatibility labels for existing `PageAligner` code, but identity is passed as explicit version IDs, never looked up by those labels.

Example internal labels:

```text
previous
current
```

are preferred over `3차` / `4차` if the downstream aligner can accept them with a small change.

## 3.4 Legacy compatibility

Legacy pre-ReviewRound queued jobs may retain the old stage-based resolution path temporarily.

The public ReviewRound path must not call it.

---

# 4. Workstream B — Evidence-aware comparison modes

## 4.1 Scope

Do **not** build a generic N-way Evidence viewer.

Add four explicit modes:

```text
version_change
plate_reference
drawing_reference
text_evidence
```

These modes only control which evidence is displayed and how the right side is labelled.

## 4.2 Comparison mode semantics

### A. `version_change`

Use when the candidate is grounded in a previous/current body revision comparison.

Example:

```text
previous body: 길이 220cm
current body:  길이 210cm
```

UI:

```text
LEFT  : 이전 본문 PDF / source claim
RIGHT : 현재 본문 PDF / revised claim
```

If both page render provenances exist, render both.

If one side lacks render provenance, show an explicit metadata state:

```text
비교 유형: 본문 수정본 간 변경
이전값: 길이 220cm
현재값: 길이 210cm
이전 페이지 렌더 provenance 없음
```

Do not show a plate placeholder.

### B. `plate_reference`

Use only when candidate/evidence contains an explicit plate/photo Reference and the canonical Graph path resolves to `Plate` or `PlatePanel`.

UI:

```text
LEFT  : source body page
RIGHT : resolved plate/panel image
```

### C. `drawing_reference`

Use only when the explicit Reference resolves to `Drawing` or `DrawingRegion`.

UI:

```text
LEFT  : source body page
RIGHT : resolved drawing/region render
```

### D. `text_evidence`

Use for deterministic rule findings that have no visual or version-pair comparison.

UI:

```text
LEFT  : source body page when available
RIGHT : evidence summary / rule finding / metadata
```

No fake visual placeholder.

---

# 5. Backend visual-bundle contract

Extend `CandidateVisualBundle` with comparison semantics rather than making the frontend infer from category strings alone.

Recommended response:

```json
{
  "candidateId": "...",
  "comparisonType": "version_change",
  "source": { ... },
  "comparison": { ... },
  "canonical": null,
  "reference": null,
  "unresolvedReason": null
}
```

Suggested fields:

```text
comparison_type
source
comparison
canonical
reference
unresolved_reason
render_status
```

### `source`

Primary source evidence page.

### `comparison`

Second comparison side for `version_change` or other non-canonical evidence.

### `canonical`

Only for plate/drawing reference modes.

### `reference`

Canonical reference metadata when a visual reference exists:

```json
{
  "type": "plate",
  "number": "45",
  "referenceId": "ref_...",
  "targetId": "plate_45"
}
```

### `render_status`

Renderability must be distinguishable from identity resolution.

Recommended values:

```text
ready
missing_render
not_applicable
```

This lets the UI distinguish:

```text
A. This candidate has no visual comparison at all.
B. This candidate has a resolved Plate45 but its image render failed.
```

Those are different states and must never share the same generic fallback message.

---

# 6. How comparison mode is determined

Priority order:

```text
1. Explicit candidate Reference -> RESOLVES_TO Drawing/Region
      => drawing_reference

2. Explicit candidate Reference -> RESOLVES_TO Plate/Panel
      => plate_reference

3. Candidate contains version_change evidence with previous/current provenance
      => version_change

4. Otherwise
      => text_evidence
```

A numeric candidate is **not automatically** `version_change`; the evidence must actually show previous/current version provenance.

A `figure_plate_table_photo_ref` category is **not automatically** `plate_reference`; the Graph must contain the exact Reference -> RESOLVES_TO target.

---

# 7. Visual identity and render fallback

## 7.1 Canonical identity

Canonical visual selection remains:

```text
Candidate
  -> ABOUT object
  -> source MENTIONS object
  -> source REFERENCES Reference
  -> Reference RESOLVES_TO exact target
```

Candidate text may be used to disambiguate among already Graph-resolved references, but it must not manufacture a target.

## 7.2 Render generation

For resolved `Plate` / `Drawing` nodes:

1. prefer existing panel/region render when appropriate;
2. otherwise render the owning `DocumentVersion` PDF page on demand;
3. cache the page render;
4. return an API render URL, never a filesystem path.

If identity exists but render generation fails:

```text
comparisonType = plate_reference | drawing_reference
canonical = metadata with target ID
renderStatus = missing_render
unresolvedReason = render_unavailable
```

The UI should show:

```text
도판 45는 Graph에서 정상 연결됨
하지만 이미지 렌더를 생성하지 못했습니다.
DocumentVersion: ...
Physical page: ...
Target: plate_45
```

It must not claim that there is no comparison target.

---

# 8. Frontend design

`SplitViewInspector` remains the main component. `VisualAssetPane` remains the reusable image renderer.

Add a small comparison renderer switch:

```tsx
switch (visualBundle.comparisonType) {
  case 'version_change':
    return <VersionChangeComparison ... />
  case 'plate_reference':
    return <CanonicalVisualComparison kind="plate" ... />
  case 'drawing_reference':
    return <CanonicalVisualComparison kind="drawing" ... />
  default:
    return <TextEvidenceComparison ... />
}
```

These may be helper functions/components inside the same file initially to avoid broad refactoring.

### Important UI change

Remove unconditional copy such as:

```text
CANONICAL TARGET (표준 대조군)
표준 도판 / 사진 — 실제 패널 이미지
```

for non-visual candidates.

Instead always display an explicit comparison header:

```text
비교 근거: 본문 수정본 간 비교
비교 근거: 본문 ↔ 도판 45
비교 근거: 본문 ↔ 도면 30
비교 근거: 규칙 기반 본문 Evidence
```

---

# 9. VLM display rule

The UI must not show a generic `VLM 비전 분석 관찰 소견` box for candidates that have no `vlm_observation` Evidence.

Show the VLM block only when traceability/evidence contains:

```text
kind = vlm_observation
```

Otherwise show deterministic evidence / rule explanation only.

This avoids presenting a rule rationale as if a vision model actually observed it.

---

# 10. Tests required before implementation is considered complete

## 10.1 ReviewRound predecessor RED/GREEN

Real Neo4j test:

```text
all DocumentVersion.stage = source

Round #1 -> body v1
Round #2 -> body v2
Round #3 -> body v2
Round #4 -> body v3
Round #5 -> body v4
```

Assertions:

```text
Round4 previous == v2
Round4 current  == v3
Round5 previous == v3
Round5 current  == v4
```

Also assert that changing/omitting `DocumentVersion.stage` does not change the result.

## 10.2 Comparison mode unit tests

Fixtures:

```text
numeric version-change candidate -> version_change
Plate45 reference -> plate_reference
Drawing30 reference -> drawing_reference
plain typo/rule candidate -> text_evidence
```

## 10.3 Render state tests

Test both:

```text
resolved target + ready image       -> ready
resolved target + render unavailable -> missing_render
```

and ensure the latter does not become `no_canonical_reference_target`.

## 10.4 Wrong-asset prevention

Reverse asset insertion order:

```text
Plate46 first
Plate45 second
Candidate explicitly references 도판 45
```

Expected `Plate45`.

## 10.5 Frontend tests

For `길이 220cm -> 길이 210cm` version-change candidate:

- no `표준 도판 / 사진` placeholder;
- explicit `본문 수정본 간 비교` label;
- previous/current values shown;
- render panes shown only when metadata exists.

For a plate candidate:

- explicit plate number/target ID displayed;
- actual image element when render ready;
- precise `render missing` metadata when target exists but render fails.

## 10.6 VLM label test

No `vlm_observation` Evidence -> no VLM observation UI.

---

# 11. Verification-agent handoff additions

After implementation, update the evaluation handoff with a new section requiring an independent verifier to provide evidence for:

1. ReviewRound predecessor with all stages set to `source`.
2. Round #3 body reuse and Round #4 previous-body resolution.
3. `version_change`, `plate_reference`, `drawing_reference`, `text_evidence` API examples.
4. Browser screenshots for all four comparison modes.
5. For visual modes, `visual-bundle` JSON plus successful render HTTP response bytes.
6. For `missing_render`, Graph target exists but the UI displays render failure metadata rather than “no asset”.
7. The numeric example `길이 220cm -> 길이 210cm` must show exactly what two evidence sources were compared.
8. VLM UI must only appear when a real `vlm_observation` Evidence node is present.
9. `raw_findings >= 50` budget stress with `selected_candidates <= 10` and `expensive_operations <= 10`.
10. Official backend hermetic, real Neo4j, frontend test/build gates remain green.

The verifier must record candidate IDs, project ID, round ID, AnalysisRun ID, relevant version IDs, and screenshots/HTTP statuses. A narrative `PASS` without those artifacts is not sufficient.

---

# 12. Non-goals

Not part of this change:

- generic arbitrary N-evidence graph viewer;
- automatic archaeological truth adjudication;
- using VLM/LLM to decide Reference identity;
- raw JPG filename suffix matching;
- adding new external AI providers;
- broad frontend redesign;
- production-scale 500MB performance tuning.

---

# 13. Acceptance summary

The implementation is accepted only if both statements are true:

> Round revision comparison follows `ReviewRound PRECEDES`, not stage strings.

and

> The candidate screen shows the evidence actually compared; it never displays an empty plate/photo pane for a candidate that was not a plate/photo comparison.
