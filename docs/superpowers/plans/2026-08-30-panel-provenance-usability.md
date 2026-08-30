# Panel Provenance Usability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix revision-scoped provenance collisions, preserve deterministic candidate rankings/failure reasons, and introduce a safety-gated VLM fallback surface that can be validated on the real 2,750-panel corpus.

**Architecture:** `VisualAssetMatcher` remains the deterministic evidence engine but gains an assessment API and revision-scoped batch uniqueness. `ReferenceCorpusService` supplies explicit PDF-source scope identity. A separate panel-provenance VLM resolver consumes only panel pixels plus deterministic Top-K candidate pixels and initially produces non-final AI-supported decisions. Real-corpus gold-set evaluation gates any future auto-promotion.

**Tech Stack:** Python 3.12, pytest, Pillow, PyMuPDF, existing OpenRouter/VLM client infrastructure, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-30-panel-provenance-usability-design.md`

## Global Constraints

- Keep deterministic `minimum_score=0.97` and `minimum_margin=0.03` unchanged.
- Filename/path/caption metadata must never create verified provenance.
- Cross-revision reuse of one JPG is allowed; within-revision duplicate use is fail-closed.
- VLM receives only visual evidence and deterministic Top-K candidates.
- VLM auto-promotion to `DERIVED_VERIFIED` remains disabled until gold-set precision is explicitly accepted.
- Real-corpus acceptance is separate from CI and is required before claiming usefulness.

---

### Task 1: Revision-aware uniqueness contract

**Files:**
- Modify: `backend/tests/test_visual_asset_matcher.py`
- Modify: `backend/app/services/visual_asset_matcher.py`
- Modify: `backend/app/services/reference_corpus_service.py`
- Modify: relevant reference-corpus service tests that construct `VisualPanelRequest`

**Interfaces:**
- Produces: `VisualPanelRequest(..., uniqueness_scope_id: str)`
- Produces: `match_panels()` collision key `(uniqueness_scope_id, source_asset_id)`

- [ ] **Step 1: Write the failing cross-revision reuse test**

Add a test using two `VisualPanelRequest` objects with different `uniqueness_scope_id` values. Stub only the expensive local image scoring primitive so both return `same-photo`; assert both panel IDs survive `match_panels()`.

```python
def test_match_panels_allows_same_source_across_revision_scopes(monkeypatch):
    matcher = VisualAssetMatcher()
    requests = [
        VisualPanelRequest(
            panel_id="rev-a-panel",
            uniqueness_scope_id="pdf-a",
            pdf_path="a.pdf",
            physical_page=1,
            bbox=(0.0, 0.0, 0.5, 0.5),
        ),
        VisualPanelRequest(
            panel_id="rev-b-panel",
            uniqueness_scope_id="pdf-b",
            pdf_path="b.pdf",
            physical_page=1,
            bbox=(0.0, 0.0, 0.5, 0.5),
        ),
    ]
    monkeypatch.setattr(
        matcher,
        "match_panel",
        lambda **_: VisualAssetMatch(source_asset_id="same-photo", score=0.99),
    )

    matches = matcher.match_panels(panels=requests, candidates=[])

    assert set(matches) == {"rev-a-panel", "rev-b-panel"}
```

- [ ] **Step 2: Write/retain the within-revision fail-closed test**

Change the existing collision test so both requests use `uniqueness_scope_id="pdf-a"`; expected result remains `{}`.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
cd backend
pytest -q tests/test_visual_asset_matcher.py -k "revision_scopes or fails_closed"
```

Expected: the cross-revision test fails because `VisualPanelRequest` lacks `uniqueness_scope_id` and/or batch uniqueness is global.

- [ ] **Step 4: Implement the minimum matcher change**

Add the required immutable request field and count by scope:

```python
@dataclass(frozen=True, slots=True)
class VisualPanelRequest:
    panel_id: str
    uniqueness_scope_id: str
    pdf_path: str | Path
    physical_page: int
    bbox: tuple[float, float, float, float]
```

```python
scope_by_panel = {panel.panel_id: panel.uniqueness_scope_id for panel in panels}
source_counts = Counter(
    (scope_by_panel[panel_id], match.source_asset_id)
    for panel_id, match in local_matches.items()
)
return {
    panel_id: match
    for panel_id, match in local_matches.items()
    if source_counts[(scope_by_panel[panel_id], match.source_asset_id)] == 1
}
```

- [ ] **Step 5: Supply the scope from `ReferenceCorpusService`**

When creating each request from one `plate_pdf` source, pass `uniqueness_scope_id=source.id`. Do not derive this from path or filename.

- [ ] **Step 6: Run focused and reference-corpus tests GREEN**

```bash
cd backend
pytest -q tests/test_visual_asset_matcher.py tests/test_reference_corpus_service.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/tests backend/app/services/visual_asset_matcher.py backend/app/services/reference_corpus_service.py
git commit -m "fix: scope panel provenance collisions by revision"
```

---

### Task 2: Preserve deterministic failure reason and Top-K candidates

**Files:**
- Modify: `backend/tests/test_visual_asset_matcher.py`
- Modify: `backend/app/services/visual_asset_matcher.py`

**Interfaces:**
- Produces: `RankedVisualCandidate`
- Produces: `VisualPanelAssessment`
- Produces: `VisualAssetMatcher.assess_panel(..., top_k: int = 5) -> VisualPanelAssessment`
- Keeps: `match_panel(...) -> VisualAssetMatch | None`

- [ ] **Step 1: Write RED test for below-score ranking**

Patch only fingerprint extraction/similarity inputs as needed to create deterministic scores `0.95`, `0.91`, `0.80`; assert:

```python
assessment.status == "BELOW_SCORE"
assessment.best_score == pytest.approx(0.95)
assessment.candidates[0].source_asset_id == "candidate-a"
assessment.match is None
```

- [ ] **Step 2: Write RED test for ambiguous margin**

Create scores `0.98` and `0.97`; assert `status == "AMBIGUOUS_MARGIN"`, both candidates are retained in rank order, and `match is None`.

- [ ] **Step 3: Write RED test for verified assessment**

Create scores `0.99` and `0.90`; assert `status == "VERIFIED"`, `match.source_asset_id` equals the winner, and ranking remains available.

- [ ] **Step 4: Run focused tests RED**

```bash
cd backend
pytest -q tests/test_visual_asset_matcher.py -k "assessment"
```

Expected: failure because assessment types/API do not exist.

- [ ] **Step 5: Implement immutable assessment types and extraction**

Use exact status strings from the spec. `assess_panel()` must perform the existing scoring once, sort candidates by `(-score, asset.id)`, cap returned ranking to `top_k`, and create a `VisualAssetMatch` only for verified cases.

- [ ] **Step 6: Refactor `match_panel()` into a verified-only wrapper**

```python
assessment = self.assess_panel(...)
return assessment.match
```

Do not change threshold or margin semantics.

- [ ] **Step 7: Run matcher tests GREEN**

```bash
cd backend
pytest -q tests/test_visual_asset_matcher.py
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/visual_asset_matcher.py backend/tests/test_visual_asset_matcher.py
git commit -m "feat: retain panel match assessments and top candidates"
```

---

### Task 3: Separate panel-provenance VLM adjudicator

**Files:**
- Create: `backend/app/services/panel_provenance_vlm.py`
- Create: `backend/tests/test_panel_provenance_vlm.py`

**Interfaces:**
- Produces: `PanelProvenanceVLMResult`
- Produces: `PanelProvenanceVLMResolver.compare(panel_bytes: bytes, candidate_bytes: bytes) -> PanelProvenanceVLMResult`

- [ ] **Step 1: Write RED normalization tests**

Test exact verdict normalization for `SAME_SOURCE`, `DIFFERENT_SOURCE`, and `INSUFFICIENT_EVIDENCE`; unknown verdicts normalize to insufficient evidence.

- [ ] **Step 2: Write RED prompt-safety test**

Use a fake client that captures the multimodal payload. Assert the user/system prompt does not contain supplied filename/path/caption strings and contains exactly two image inputs.

- [ ] **Step 3: Run RED**

```bash
cd backend
pytest -q tests/test_panel_provenance_vlm.py
```

- [ ] **Step 4: Implement the minimal resolver**

Reuse only the existing OpenRouter configuration/call style. The system instruction asks whether two images are crops/re-encodes/edits of the same underlying photograph and requests the spec JSON contract. It must not accept textual provenance metadata in the public API.

- [ ] **Step 5: Run GREEN**

```bash
cd backend
pytest -q tests/test_panel_provenance_vlm.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/panel_provenance_vlm.py backend/tests/test_panel_provenance_vlm.py
git commit -m "feat: add visual-only panel provenance adjudicator"
```

---

### Task 4: Safety-gated fallback routing

**Files:**
- Create or modify: a focused provenance orchestration service adjacent to `visual_asset_matcher.py`
- Create: focused routing tests
- Modify: `backend/app/services/reference_corpus_service.py` only if the orchestration can be introduced without coupling network calls into deterministic builds

**Interfaces:**
- Consumes: `VisualPanelAssessment`
- Consumes: `PanelProvenanceVLMResolver`
- Produces: non-final AI-supported decision records; does not produce `DERIVED_VERIFIED`

- [ ] **Step 1: Write RED routing tests**

Assert:

```text
VERIFIED -> no VLM call
BELOW_SCORE -> eligible VLM call
AMBIGUOUS_MARGIN -> eligible VLM call
INSUFFICIENT_PANEL -> no VLM call
```

- [ ] **Step 2: Write RED fail-closed tests**

If more than one candidate returns `SAME_SOURCE`, confidence is below configured review threshold, or every candidate is insufficient/different, final provenance remains unresolved.

- [ ] **Step 3: Implement minimum routing**

The routing layer may return an AI-supported candidate for review but must not assign `EvidenceLevel.DERIVED_VERIFIED` or source provenance edges.

- [ ] **Step 4: Run GREEN**

Run the new routing tests plus reference corpus tests.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat: route unresolved panels through safe VLM fallback"
```

---

### Task 5: Real-corpus evaluation contract

**Files:**
- Create: `tools/evaluate_panel_provenance.py`
- Create: `tools/build_panel_gold_template.py`
- Create: unit tests for evaluator pure functions
- Update: acceptance report documentation after local Windows run

**Interfaces:**
- Gold rows identify panel identity, revision scope, and human-labelled correct `source_asset_id` or unresolved.
- Evaluator outputs `Recall@1`, `Recall@3`, `Recall@5`, deterministic verified coverage, cross-revision reuse count, within-revision collision count, and all existing safety counters.

- [ ] **Step 1: Write RED evaluator metric tests**

Provide a tiny fixture where the correct asset appears at ranks 1, 3, >5, and absent. Assert exact Recall@1/3/5 values.

- [ ] **Step 2: Implement pure metric functions**

Keep them independent of `/src` so CI can test them hermetically.

- [ ] **Step 3: Implement local runner**

The runner reads `/src` without mutation, records all panel assessments including Top-K rankings, separates cross-revision reuse from within-revision collision, and can join a human gold CSV/JSON.

- [ ] **Step 4: Run hermetic evaluator tests GREEN**

- [ ] **Step 5: Commit**

```bash
git commit -am "test: add panel provenance real-corpus evaluator"
```

- [ ] **Step 6: Run local Windows acceptance**

Against `D:/Coding/archaeology-document-review-system/src`, record exact corpus results. Required safety outcomes:

```text
filename-only promotion = 0
path-only promotion = 0
caption-only promotion = 0
threshold bypass = 0
within-revision collision promotion = 0
source root mutation = false
```

Do not claim a VLM coverage gain unless a human-labelled gold set exists and Recall@K plus VLM precision are reported.

---

### Task 6: Full verification and review

**Files:**
- No new production behavior.
- Update docs only with measured results.

- [ ] **Step 1: Run backend hermetic suite**

Use the same exclusions as `.github/workflows/remediation-ci.yml`.

- [ ] **Step 2: Run Neo4j E2E and frontend checks**

Require the existing workflow jobs to pass.

- [ ] **Step 3: Inspect PR diff for safety regression**

Confirm no threshold change, no metadata-based verification, no VLM auto-promotion, and no fake unresolved provenance edge.

- [ ] **Step 4: Commit measured acceptance documentation**

Only after the real local corpus rerun.

- [ ] **Step 5: Mark implementation complete only if both gates pass**

```text
Gate A: code-level TDD + CI GREEN
Gate B: real-corpus acceptance report with revision-aware collision metrics and Recall@K
```
