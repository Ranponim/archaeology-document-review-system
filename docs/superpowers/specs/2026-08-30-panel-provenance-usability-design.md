# Panel Provenance Usability Design

## Context

The real local Adobe-free corpus acceptance at code HEAD `d6b1661506361ce11cdcdccce9330759cd979c6e` found 2,804 panels, 2,750 safely segmented panels, 75 deterministic local high-confidence matches, 52 collision removals, and only 23 final `DERIVED_VERIFIED` panels (0.84% of segmented panels). Failure taxonomy was 2,565 below-minimum-score, 110 ambiguous-margin, 75 local matches, and 54 insufficient-bbox.

The current matcher enforces uniqueness by `source_asset_id` across the entire reference corpus. That is too broad when the corpus contains multiple revisions of the same plate PDF because the same original JPG may legitimately be reused in 1st/2nd/3rd revision PDFs.

## Goal

Make panel -> original JPG provenance usable on the real corpus without weakening provenance safety.

The delivery order is:

1. fix the invalid cross-revision collision assumption;
2. preserve deterministic failure details and ranked candidates;
3. measure retrieval Recall@K on a real gold set;
4. add a closed-world Luna/VLM adjudication fallback for unresolved deterministic cases;
5. only permit VLM auto-promotion after measured precision satisfies an explicit acceptance gate.

## Non-goals

- Do not lower the deterministic `minimum_score=0.97` or `minimum_margin=0.03` in this phase.
- Do not use filename/path/caption text as verification evidence.
- Do not allow a VLM to search all 1,032 assets directly.
- Do not treat CI green as proof of real-corpus usefulness.

## 1. Revision-aware deterministic uniqueness

`VisualPanelRequest` gains `uniqueness_scope_id`.

The production service must set it from the plate-PDF source asset identity (or another explicit revision identity), never from display filename heuristics.

Batch collision scope changes from:

```text
source_asset_id
```

to:

```text
(uniqueness_scope_id, source_asset_id)
```

Required behavior:

- revision A / panel 1 -> JPG X and revision B / panel 1 -> JPG X: both may survive uniqueness.
- revision A / panel 1 -> JPG X and revision A / panel 2 -> JPG X: both fail closed as a within-revision collision.

## 2. Deterministic assessment instead of lossy `None`

Add immutable types conceptually equivalent to:

```python
@dataclass(frozen=True, slots=True)
class RankedVisualCandidate:
    source_asset_id: str
    score: float

@dataclass(frozen=True, slots=True)
class VisualPanelAssessment:
    status: str  # VERIFIED | BELOW_SCORE | AMBIGUOUS_MARGIN | INSUFFICIENT_PANEL | NO_CANDIDATE
    best_score: float | None
    margin: float | None
    candidates: tuple[RankedVisualCandidate, ...]
    match: VisualAssetMatch | None = None
```

`assess_panel(..., top_k=5)` is the scoring primitive. `match_panel()` remains a backwards-compatible verified-only wrapper.

No failure may be converted to verified merely because ranked candidates exist.

## 3. Closed-world VLM fallback

Create a dedicated panel provenance resolver rather than reusing the archaeology claim-review prompt.

The VLM compares exactly two images at a time:

- segmented PDF panel render;
- one deterministic Top-K original JPG candidate.

The prompt must not include filename, path, caption, sequence number, or other textual provenance hints.

Result contract:

```json
{
  "verdict": "SAME_SOURCE | DIFFERENT_SOURCE | INSUFFICIENT_EVIDENCE",
  "confidence": 0.0,
  "matching_features": [],
  "contradictions": []
}
```

Initial policy:

- deterministic verified -> `DERIVED_VERIFIED` and no VLM call;
- deterministic below-score or ambiguous-margin -> eligible for VLM adjudication over Top-K;
- insufficient panel -> remain unresolved and no VLM call;
- VLM-supported results are recorded as non-final AI-supported evidence until gold-set precision is proven.

## 4. Gold-set and real-corpus acceptance

Before enabling VLM auto-promotion, build a gold set containing:

- all ambiguous-margin cases;
- all prior collision cases;
- stratified below-score samples across score bands;
- a sample of deterministic high-confidence positives.

Measure deterministic retrieval `Recall@1`, `Recall@3`, and `Recall@5` against the gold set.

If the correct JPG is not present in Top-K, the defect is retrieval and must not be attributed to the VLM.

## 5. Definition of Done

Code-level:

- RED/GREEN TDD proves cross-revision reuse and within-revision fail-closed behavior.
- RED/GREEN TDD proves unresolved assessments preserve Top-K and failure reason.
- VLM routing tests prove no call for deterministic verified or insufficient-panel cases.
- VLM safety tests prove ambiguous/multiple-supported/low-confidence outcomes remain unresolved.
- backend/full CI and Neo4j/frontend regressions remain green.

Real-corpus:

- cross-revision reuse is no longer counted as collision;
- within-revision collisions remain fail-closed;
- unsafe filename/path/caption/threshold/collision promotion remains zero;
- post-fix deterministic verified count equals local high-confidence matches minus real within-revision collisions;
- Recall@1/3/5 is reported from a human-labelled gold set before claiming VLM usefulness;
- VLM auto-promotion stays disabled until measured precision meets an explicitly documented production threshold.

## Safety invariant

A source relationship is never fabricated. If evidence is insufficient or ambiguous, the panel remains unresolved with no fake `source_asset_id` provenance edge.
