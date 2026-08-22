# Bidirectional Visual Reference Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect and propose missing drawing/plate-photo references from graph-authoritative visual assets while preserving the existing forward body-reference-to-canonical-visual validation path.

**Architecture:** Enrich graph-derived reference/visual evidence so reverse coverage can distinguish resolved, wrong, and missing references without filesystem heuristics. Add one deterministic `VisualReferenceCoverageService`, invoke it from `ProofreadingOrchestrator` after graph bundles exist, and expose the resulting candidate intent through existing evidence metadata for the current review UI.

**Tech Stack:** Python 3.12, dataclasses, Neo4j 5.26, pytest, React 18, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-22-bidirectional-visual-reference-coverage-design.md`

## Global Constraints

- ReviewRound remains the sole authority for active body/plate/drawing DocumentVersion selection.
- Publication identity comes from canonical `Plate/PlatePanel/Drawing/DrawingRegion`; filenames never establish identity.
- `OriginalAsset` is provenance only and is not an input to reverse coverage identity.
- Reverse coverage must fail closed on ambiguous target identity or ambiguous body insertion location.
- Every generated candidate remains `pending_review`.
- Existing resolved-reference VLM flow continues to use canonical renders and graph-derived body claims.
- Raw source-image VLM comparison is out of scope.
- External VLM quality remains HOLD; mocked tests may verify integration behavior.

---

## File Structure

### Backend create
- `backend/app/services/visual_reference_coverage.py` — deterministic reverse-coverage logic only.
- `backend/tests/test_visual_reference_coverage.py` — hermetic unit contract for missing/blank/ambiguous/wrong-reference states.
- `backend/tests/integration/test_bidirectional_visual_reference_real_neo4j.py` — project/ReviewRound/version-scoped reverse-coverage graph tests.

### Backend modify
- `backend/app/services/pdf_parser.py` — normalize body `사진 N` references into canonical plate-channel references without changing canonical identity semantics.
- `backend/app/graph/canonical_repository.py` — enrich reference evidence with resolution metadata and make PlatePanel/DrawingRegion visual claims inherit the owning visual DocumentVersion through parent traversal.
- `backend/app/services/proofreading_orchestrator.py` — call `VisualReferenceCoverageService` after graph bundles and include candidates in normal dedupe/budget/persistence.
- `backend/tests/test_pdf_parser.py` — photo/plate reference parsing regression tests.
- `backend/tests/test_proofreading_orchestrator.py` — service invocation/order/persistence regression tests if present; otherwise use the existing orchestrator-focused test file returned by repository inspection before editing.

### Frontend modify
- `frontend/src/components/SplitViewInspector.tsx` — show Korean intent labels based on evidence `rule_name` without creating a new mutation path.
- `frontend/src/components/SplitViewInspector.test.tsx` — missing/blank/ambiguous label and evidence-side tests.

---

### Task 1: Normalize body photo references into the canonical plate channel

**Files:**
- Modify: `backend/app/services/pdf_parser.py`
- Modify: `backend/tests/test_pdf_parser.py`

**Interfaces:**
- Consumes: report-body text/caption strings.
- Produces: `ReferenceData(ref_type="plate", number="N", raw_text="사진 ...")` for `사진 N` / `사진: N` while existing `도판` and `도면` behavior remains unchanged.

- [ ] **Step 1: Write failing parser tests**

Add tests equivalent to:

```python
def test_extracts_photo_reference_as_plate_channel():
    parser = PDFParser()
    refs = parser._extract_references("6호 석관묘 (사진: 45)", source_block_id="b1")
    assert [(r.ref_type, r.number) for r in refs] == [("plate", "45")]
    assert refs[0].raw_text.startswith("사진")


def test_caption_photo_reference_is_not_blank():
    parser = PDFParser()
    cap = parser._extract_caption("사진: 45", "cap1")
    assert cap is not None
    assert cap.is_blank_reference is False
    assert [(r.ref_type, r.number) for r in cap.references] == [("plate", "45")]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd backend
pytest -q tests/test_pdf_parser.py -k 'photo_reference'
```

Expected: FAIL because current parser recognizes only `도면` and `도판`.

- [ ] **Step 3: Implement minimal parser support**

Use the same number expansion path as `도판`; normalize `사진` to `ref_type="plate"`. Do not create `ReferenceType="photo"` and do not touch asset filenames.

- [ ] **Step 4: Run parser tests and verify GREEN**

```bash
pytest -q tests/test_pdf_parser.py -k 'photo_reference or reference'
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pdf_parser.py backend/tests/test_pdf_parser.py
git commit -m "feat: normalize body photo references"
```

---

### Task 2: Make graph evidence sufficient for reverse coverage

**Files:**
- Modify: `backend/app/graph/canonical_repository.py`
- Create: `backend/tests/integration/test_bidirectional_visual_reference_real_neo4j.py`

**Interfaces:**
- Consumes: `ArchaeologyObject`, `Reference`, `RESOLVES_TO`, `DEPICTS`, active `document_version_ids`.
- Produces: `ObjectEvidenceBundle.references[].value` with resolution facts and `plate_claims` / `drawing_claims` whose `document_version_id` is the owning visual version for both parent and child assets.

Reference evidence value must contain:

```python
{
    "ref_type": "plate" | "drawing",
    "number": "45",
    "raw_text": "도판 45",
    "resolved_target_id": "plate_45" | None,
    "resolved_target_label": "Plate" | "PlatePanel" | "Drawing" | "DrawingRegion" | None,
    "resolved_depicts_object": True | False,
}
```

- [ ] **Step 1: Write failing Real Neo4j tests**

Create a disposable project with body/plate/drawing versions and assert:

```python
bundle = repo.get_object_evidence_bundle(
    object_id,
    document_version_ids=[body_v, plate_v, drawing_v],
)
ref = next(ev for ev in bundle.references if ev.value["number"] == "44")
assert ref.value["resolved_target_id"] == plate_44
assert ref.value["resolved_depicts_object"] is False
```

Also create `PlatePanel -> DEPICTS -> object` and `DrawingRegion -> DEPICTS -> object` where the child has no direct `document_version_id`; assert their claim evidence is scoped to `plate_v` / `drawing_v` through the owning parent.

Add a second visual version with same-number assets and assert it is excluded when not present in `document_version_ids`.

- [ ] **Step 2: Run integration file and verify RED**

```bash
RUN_NEO4J_INTEGRATION=1 pytest -q tests/integration/test_bidirectional_visual_reference_real_neo4j.py -s
```

Expected: FAIL because reference evidence lacks resolution fields and child visual ownership traversal is incomplete.

- [ ] **Step 3: Enrich `_query_reference_evidences`**

Use graph traversal from the exact `Reference`:

```cypher
OPTIONAL MATCH (ref)-[:RESOLVES_TO]->(resolved)
OPTIONAL MATCH (resolved)-[:DEPICTS]->(resolved_obj:ArchaeologyObject {id: $object_id})
```

Return target label/id and compute `resolved_depicts_object` from whether `resolved_obj` exists. Keep project/version scoping on the body source path.

- [ ] **Step 4: Fix `_query_visual_claims` owning-version traversal**

For child assets support both direct and parent ownership:

```cypher
OPTIONAL MATCH (plate_version:DocumentVersion)-[:HAS_PLATE]->(plate_parent:Plate)-[:HAS_PANEL]->(asset)
OPTIONAL MATCH (drawing_version:DocumentVersion)-[:HAS_DRAWING]->(drawing_parent:Drawing)-[:HAS_REGION]->(asset)
OPTIONAL MATCH (direct_version:DocumentVersion)-[:HAS_PLATE|HAS_DRAWING]->(asset)
```

Derive `visual_document_version_id` from direct or parent ownership and apply `document_version_ids` to that visual version, not to unrelated body-reference versions.

- [ ] **Step 5: Run Real Neo4j test and verify GREEN**

```bash
RUN_NEO4J_INTEGRATION=1 pytest -q tests/integration/test_bidirectional_visual_reference_real_neo4j.py -s
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/graph/canonical_repository.py backend/tests/integration/test_bidirectional_visual_reference_real_neo4j.py
git commit -m "feat: expose graph facts for reverse visual coverage"
```

---

### Task 3: Add deterministic `VisualReferenceCoverageService`

**Files:**
- Create: `backend/app/services/visual_reference_coverage.py`
- Create: `backend/tests/test_visual_reference_coverage.py`

**Interfaces:**
- Consumes:

```python
review_object(
    *,
    bundle: ObjectEvidenceBundle,
    archaeology_object: ArchaeologyObjectData,
    analysis_run_id: str,
) -> list[CorrectionCandidateData]
```

- Produces: only `figure_plate_table_photo_ref` candidates with `status="pending_review"`.

Canonical key normalization:

```python
("plate", "45")
("drawing", "30")
```

Evidence rule names:

```text
visual_reference_missing
visual_reference_blank_fill
visual_reference_ambiguous
visual_reference_location_ambiguous
visual_reference_wrong_target
```

- [ ] **Step 1: Write failing unit tests for all deterministic states**

Cover these exact cases:

```text
A. unique body region + Drawing 30 + Plate 45 + no refs -> proposed_text '(도면 30, 도판 45)', change_type added
B. body already references 30/45 -> []
C. blank '(도면: , 도판: )' + unique 30/45 -> '(도면: 30, 도판: 45)'
D. unique drawing + two plates -> precise drawing fill plus manual plate ambiguity
E. two body regions + no placeholder -> proposed_text None, rule visual_reference_location_ambiguous
F. two canonical plates -> proposed_text None, rule visual_reference_ambiguous
G. existing plate 44 resolved_depicts_object=False + unique Plate45 -> modified candidate replacing token with '도판 45'
H. existing Plate45 resolved_depicts_object=True -> no added/replacement candidate
I. no canonical Plate91 claim -> filename-like text '_91.JPG' in unrelated evidence cannot create a proposal
J. same graph claim duplicated by panel/parent -> canonical key is deduplicated
```

Use real `EvidenceData` objects with valid document provenance; do not mock filesystem paths.

- [ ] **Step 2: Run unit tests and verify RED**

```bash
pytest -q tests/test_visual_reference_coverage.py
```

Expected: import/service failure.

- [ ] **Step 3: Implement minimal service**

Implementation rules:

```python
class VisualReferenceCoverageService:
    def review_object(self, *, bundle, archaeology_object, analysis_run_id): ...
```

The service must:

1. derive body regions from `bundle.text_claims` using `region_id`,
2. derive body reference keys only from `bundle.references`,
3. derive canonical keys only from `bundle.plate_claims` / `bundle.drawing_claims`,
4. never import `Path`, `AssetMatcher`, `OriginalAssetData`, or source-import modules,
5. prefer blank-placeholder candidates over generic missing candidates for the same region/key,
6. use `finding_fingerprint` deterministically from run/object/source-region/reference keys,
7. set `evidence` to the body evidence and include canonical claim(s) in `evidence_list`,
8. return ambiguity candidates with `proposed_text=None`.

- [ ] **Step 4: Run unit tests and verify GREEN**

```bash
pytest -q tests/test_visual_reference_coverage.py
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/visual_reference_coverage.py backend/tests/test_visual_reference_coverage.py
git commit -m "feat: detect missing visual references from graph evidence"
```

---

### Task 4: Integrate coverage into `ProofreadingOrchestrator`

**Files:**
- Modify: `backend/app/services/proofreading_orchestrator.py`
- Modify/create the current orchestrator-focused test file found in `backend/tests`.

**Interfaces:**
- Consumes: graph bundles after `get_object_evidence_bundle` succeeds.
- Produces: coverage candidates appended to the same `all_candidates` list before dedupe/budget/persistence.

- [ ] **Step 1: Write failing orchestrator tests**

Test with a stub coverage service injected into the orchestrator:

```python
coverage = StubCoverageService([coverage_candidate])
orchestrator = ProofreadingOrchestrator(..., visual_reference_coverage_service=coverage)
result = await orchestrator.run_proofreading(...)
assert coverage.calls[0].bundle is graph_bundle
assert coverage_candidate in result.candidates
```

Also assert coverage is not invoked for an object whose graph bundle is unavailable in production, and existing canonical VLM receives unchanged body claims / visual version IDs.

- [ ] **Step 2: Run focused orchestrator tests and verify RED**

Expected: constructor has no coverage dependency and run flow does not append its candidates.

- [ ] **Step 3: Add constructor dependency and invocation**

Constructor:

```python
visual_reference_coverage_service: VisualReferenceCoverageService | None = None
```

Default to `VisualReferenceCoverageService()` and invoke only for objects with graph-authoritative bundles. Copy returned candidates into run-scoped `CorrectionCandidateData` exactly as existing rule/VLM candidates are normalized.

- [ ] **Step 4: Keep normal dedupe/budget/persistence unchanged**

Coverage candidates must flow through existing `prioritize_and_cap_candidates` and `ReviewRepository.save_candidates`; do not create a parallel persistence API.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the focused orchestrator test file plus:

```bash
pytest -q tests/test_visual_reference_coverage.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/proofreading_orchestrator.py backend/tests/<orchestrator-test-file>
git commit -m "feat: run reverse visual coverage in proofreading"
```

---

### Task 5: Add Real Neo4j end-to-end coverage acceptance

**Files:**
- Modify: `backend/tests/integration/test_bidirectional_visual_reference_real_neo4j.py`

**Interfaces:**
- Exercises the repository + service contract using real Neo4j graph state.

- [ ] **Step 1: Add failing graph acceptance cases**

Build project-scoped graphs for:

```text
1. body object, no reference, selected Plate45/Draw30 DEPICTS object -> proposal contains 45/30
2. existing Reference45 RESOLVES_TO Plate45 DEPICTS object -> no added proposal
3. remove DEPICTS -> reverse proposal disappears
4. same Plate45 under another project -> cannot satisfy proposal
5. Plate45 in old/non-selected plate version -> cannot satisfy current ReviewRound bundle
6. `_45.JPG` OriginalAsset with no DERIVED_FROM and no canonical Plate45 -> cannot create proposal
7. canonical Plate45 with DERIVED_FROM `_45.JPG` -> identity remains canonical Plate45
8. wrong Reference44 resolved to Plate44 not depicting object + unique Plate45 depicting object -> replacement candidate
```

- [ ] **Step 2: Run test and verify RED/GREEN around missing integration gaps**

```bash
RUN_NEO4J_INTEGRATION=1 pytest -q tests/integration/test_bidirectional_visual_reference_real_neo4j.py -s
```

- [ ] **Step 3: Fix only integration defects exposed by these cases**

Allowed fixes are limited to graph query scoping/metadata or service logic required by the approved spec. Do not add filename matching.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_bidirectional_visual_reference_real_neo4j.py backend/app/graph/canonical_repository.py backend/app/services/visual_reference_coverage.py
git commit -m "test: prove reverse visual coverage with real neo4j"
```

---

### Task 6: Make candidate intent visible to archaeologists

**Files:**
- Modify: `frontend/src/components/SplitViewInspector.tsx`
- Modify: `frontend/src/components/SplitViewInspector.test.tsx`

**Interfaces:**
- Consumes: `Evidence.rule_name` from the primary/connected evidence.
- Produces: Korean read-only finding label; no new mutation endpoint.

Mapping:

```ts
visual_reference_missing -> '참조 누락'
visual_reference_blank_fill -> '참조 빈칸'
visual_reference_ambiguous -> '참조 후보 복수'
visual_reference_location_ambiguous -> '참조 위치 확인 필요'
visual_reference_wrong_target -> '기존 참조 불일치'
```

- [ ] **Step 1: Write failing Vitest cases**

Render candidates with each rule name and assert the Korean label. For ambiguity assert no fake replacement text is shown as a proposed correction.

- [ ] **Step 2: Run focused frontend test and verify RED**

```bash
cd frontend
npm test -- --run src/components/SplitViewInspector.test.tsx
```

- [ ] **Step 3: Implement a small pure label helper inside the component file**

Prefer `rule_name` / `ruleName` from linked evidence. Keep the existing category badge and add one intent label; no API contract change is required.

- [ ] **Step 4: Run focused test and verify GREEN**

```bash
npm test -- --run src/components/SplitViewInspector.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SplitViewInspector.tsx frontend/src/components/SplitViewInspector.test.tsx
git commit -m "feat: label visual reference coverage findings"
```

---

### Task 7: Full verification and regression gate

**Files:**
- Modify only if a test exposes a defect; no speculative refactors.

- [ ] **Step 1: Backend hermetic suite**

Use the workflow-equivalent command from `.github/workflows/remediation-ci.yml`; `test_visual_reference_coverage.py` must be included and must not be deselected.

- [ ] **Step 2: Real Neo4j suite**

```bash
RUN_NEO4J_INTEGRATION=1 pytest -q tests/integration tests/test_real_neo4j_remediation.py tests/test_project_repository.py -s
```

- [ ] **Step 3: Frontend verification**

```bash
cd frontend
npm run typecheck
npm test -- --run
npm run build
```

- [ ] **Step 4: Regression assertions**

Confirm via tests/code inspection:

```text
- ReviewRound remains sole `/runs` input authority.
- production coverage service imports no filesystem matcher.
- `_45.JPG` / `_91.JPG` cannot create reference identity.
- removing DEPICTS removes reverse-coverage success.
- already-covered references do not produce duplicate added candidates.
- existing resolved-reference VLM path still uses canonical visual versions.
```

- [ ] **Step 5: Push final branch HEAD and record CI result**

The mandatory GitHub Actions workflow must show all three jobs green: backend-hermetic, neo4j-e2e, frontend. External VLM quality remains HOLD.