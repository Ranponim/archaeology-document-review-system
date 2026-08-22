# Bidirectional Visual Reference Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect and propose missing drawing/plate-photo references from graph-authoritative visual assets while preserving the existing forward body-reference-to-canonical-visual validation path.

**Architecture:** Enrich graph-derived reference/visual evidence so reverse coverage can distinguish resolved, wrong, and missing references without filesystem heuristics. Add one deterministic `VisualReferenceCoverageService`, invoke it from `ProofreadingOrchestrator` after graph bundles exist, and expose finding intent through existing evidence metadata for the current review UI.

**Tech Stack:** Python 3.12, dataclasses, Neo4j 5.26, pytest, React 18, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-22-bidirectional-visual-reference-coverage-design.md`

## Global Constraints

- ReviewRound remains the sole authority for active body/plate/drawing DocumentVersion selection.
- Publication identity comes from canonical `Plate/PlatePanel/Drawing/DrawingRegion`; filenames never establish identity.
- `OriginalAsset` is provenance only and is not an input to reverse coverage identity.
- Reverse coverage fails closed on ambiguous target identity or ambiguous body insertion location.
- Every generated candidate remains `pending_review`.
- Existing resolved-reference VLM flow continues to use canonical renders and graph-derived body claims.
- Raw source-image VLM comparison is out of scope.
- External VLM quality remains HOLD; mocked tests may verify integration behavior.

---

## File Structure

### Backend create
- `backend/app/services/visual_reference_coverage.py` — deterministic reverse-coverage logic only.
- `backend/tests/test_visual_reference_coverage.py` — hermetic unit contract for missing/blank/ambiguous/wrong-reference states.
- `backend/tests/integration/test_bidirectional_visual_reference_real_neo4j.py` — project/version-scoped reverse-coverage graph tests.

### Backend modify
- `backend/app/services/pdf_parser.py` — normalize body `사진 N` references into the canonical plate channel.
- `backend/app/graph/canonical_repository.py` — enrich reference evidence with resolution metadata and make child visual claims inherit owning visual DocumentVersion.
- `backend/app/services/proofreading_orchestrator.py` — invoke `VisualReferenceCoverageService` after graph bundles and include findings in normal dedupe/budget/persistence.
- `backend/tests/test_pdf_parser.py` — photo parsing regression tests.
- `backend/tests/test_proofreading_orchestrator.py` — coverage invocation/order/persistence regression tests.

### Frontend modify
- `frontend/src/components/SplitViewInspector.tsx` — show Korean finding-intent labels from evidence `rule_name`.
- `frontend/src/components/SplitViewInspector.test.tsx` — missing/blank/ambiguous label tests.

---

### Task 1: Normalize body photo references into the canonical plate channel

**Files:**
- Modify: `backend/app/services/pdf_parser.py`
- Modify: `backend/tests/test_pdf_parser.py`

**Interfaces:**
- Consumes: report-body text/caption strings.
- Produces: `ReferenceData(ref_type="plate", number="N", raw_text="사진 ...")` for `사진 N` / `사진: N`, preserving existing `도판` and `도면` behavior.

- [ ] **Step 1: Write failing parser tests**

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

- [ ] **Step 2: Run test and verify RED**

```bash
cd backend
pytest -q tests/test_pdf_parser.py -k 'photo_reference'
```

Expected: FAIL because current parser recognizes only `도면` and `도판`.

- [ ] **Step 3: Implement minimal parser support**

Use the same number expansion path as `도판`; normalize `사진` to `ref_type="plate"`. Do not create `ReferenceType="photo"` and do not inspect filenames.

- [ ] **Step 4: Run focused parser tests and verify GREEN**

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
- Consumes: `ArchaeologyObject`, `Reference`, `RESOLVES_TO`, `DEPICTS`, and active `document_version_ids`.
- Produces: reference evidence with resolution facts and visual claims scoped to the owning visual DocumentVersion for parent and child assets.

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

Also create `PlatePanel -> DEPICTS -> object` and `DrawingRegion -> DEPICTS -> object` where the child has no direct `document_version_id`; assert claim evidence inherits `plate_v` / `drawing_v` through the owning parent. Add a second visual version with same-number assets and assert it is excluded when not in `document_version_ids`.

- [ ] **Step 2: Run integration file and verify RED**

```bash
RUN_NEO4J_INTEGRATION=1 pytest -q tests/integration/test_bidirectional_visual_reference_real_neo4j.py -s
```

Expected: FAIL because reference evidence lacks resolution fields and child ownership traversal is incomplete.

- [ ] **Step 3: Enrich `_query_reference_evidences`**

Use exact graph traversal:

```cypher
OPTIONAL MATCH (ref)-[:RESOLVES_TO]->(resolved)
OPTIONAL MATCH (resolved)-[:DEPICTS]->(resolved_obj:ArchaeologyObject {id: $object_id})
```

Return target label/id and compute `resolved_depicts_object` from `resolved_obj`. Keep body source/version scoping unchanged.

- [ ] **Step 4: Fix `_query_visual_claims` owning-version traversal**

Support direct and parent ownership:

```cypher
OPTIONAL MATCH (plate_version:DocumentVersion)-[:HAS_PLATE]->(plate_parent:Plate)-[:HAS_PANEL]->(asset)
OPTIONAL MATCH (drawing_version:DocumentVersion)-[:HAS_DRAWING]->(drawing_parent:Drawing)-[:HAS_REGION]->(asset)
OPTIONAL MATCH (direct_version:DocumentVersion)-[:HAS_PLATE|HAS_DRAWING]->(asset)
```

Derive `visual_document_version_id` from direct or parent ownership and scope against that visual version, not an unrelated body-reference version.

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

```python
review_object(
    *,
    bundle: ObjectEvidenceBundle,
    archaeology_object: ArchaeologyObjectData,
    analysis_run_id: str,
) -> list[CorrectionCandidateData]
```

Produces only `figure_plate_table_photo_ref` candidates with `status="pending_review"`.

Canonical keys:

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

- [ ] **Step 1: Write failing unit tests**

Cover exactly:

```text
A. unique body region + Drawing30 + Plate45 + no refs -> '(도면 30, 도판 45)', added
B. body already has Drawing30 + Plate45 -> []
C. blank '(도면: , 도판: )' + unique 30/45 -> '(도면: 30, 도판: 45)'
D. unique drawing + two plates -> drawing fill plus manual plate ambiguity
E. two body regions + no placeholder -> proposed_text None, visual_reference_location_ambiguous
F. two canonical plates -> proposed_text None, visual_reference_ambiguous
G. existing Plate44 with resolved_depicts_object=False + unique Plate45 -> modified replacement '도판 45'
H. existing Plate45 with resolved_depicts_object=True -> no coverage candidate
I. no canonical Plate91 claim -> unrelated '_91.JPG' text cannot create proposal
J. duplicate parent/panel claim of same publication number -> key deduplicated
```

Use real `EvidenceData` with valid document provenance; do not mock filesystem paths.

- [ ] **Step 2: Run unit tests and verify RED**

```bash
pytest -q tests/test_visual_reference_coverage.py
```

Expected: import/service failure.

- [ ] **Step 3: Implement minimal service**

```python
class VisualReferenceCoverageService:
    def review_object(self, *, bundle, archaeology_object, analysis_run_id): ...
```

Rules:

1. derive body regions only from `bundle.text_claims`,
2. derive body reference keys only from `bundle.references`,
3. derive canonical keys only from `bundle.plate_claims` / `bundle.drawing_claims`,
4. never import `Path`, `AssetMatcher`, `OriginalAssetData`, or source-import modules,
5. prefer blank-placeholder candidates over generic missing candidates for the same region/key,
6. use deterministic `finding_fingerprint` from run/object/source-region/reference keys,
7. set primary evidence to body evidence and include canonical claim(s) in `evidence_list`,
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
- Modify: `backend/tests/test_proofreading_orchestrator.py`

**Interfaces:**
- Consumes: graph bundles after `get_object_evidence_bundle` succeeds.
- Produces: coverage candidates appended to existing `all_candidates` before dedupe/budget/persistence.

- [ ] **Step 1: Write failing orchestrator tests**

Use an injected stub:

```python
coverage = StubCoverageService([coverage_candidate])
orchestrator = ProofreadingOrchestrator(..., visual_reference_coverage_service=coverage)
result = await orchestrator.run_proofreading(...)
assert coverage.calls[0].bundle is graph_bundle
assert coverage_candidate in result.candidates
```

Also assert coverage is not invoked for an object without a graph-authoritative bundle in production, and existing canonical VLM receives unchanged body claims / visual version IDs.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
pytest -q tests/test_proofreading_orchestrator.py -k 'coverage or graph or vlm'
```

Expected: constructor has no coverage dependency and run flow does not append its candidate.

- [ ] **Step 3: Add constructor dependency and invocation**

```python
visual_reference_coverage_service: VisualReferenceCoverageService | None = None
```

Default to `VisualReferenceCoverageService()` and invoke only for objects with graph-authoritative bundles. Normalize returned candidates to the current `analysis_run_id` exactly like rule/VLM candidates.

- [ ] **Step 4: Keep normal persistence path**

Coverage candidates must flow through existing `prioritize_and_cap_candidates` and `ReviewRepository.save_candidates`; no parallel persistence API.

- [ ] **Step 5: Run focused tests and verify GREEN**

```bash
pytest -q tests/test_proofreading_orchestrator.py tests/test_visual_reference_coverage.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/proofreading_orchestrator.py backend/tests/test_proofreading_orchestrator.py
git commit -m "feat: run reverse visual coverage in proofreading"
```

---

### Task 5: Complete Real Neo4j end-to-end acceptance

**Files:**
- Modify: `backend/tests/integration/test_bidirectional_visual_reference_real_neo4j.py`
- Modify only if exposed by tests: `backend/app/graph/canonical_repository.py`, `backend/app/services/visual_reference_coverage.py`

- [ ] **Step 1: Add graph acceptance cases**

```text
1. body object, no reference, selected Plate45/Draw30 DEPICTS object -> proposal contains 45/30
2. Reference45 RESOLVES_TO Plate45 DEPICTS object -> no added proposal
3. remove DEPICTS -> reverse proposal disappears
4. same Plate45 under another project -> cannot satisfy proposal
5. Plate45 in non-selected visual version -> cannot satisfy current bundle
6. '_45.JPG' OriginalAsset with no canonical Plate45 -> cannot create proposal
7. canonical Plate45 with DERIVED_FROM '_45.JPG' -> identity remains Plate45
8. wrong Reference44 resolved to Plate44 not depicting object + unique Plate45 -> replacement candidate
```

- [ ] **Step 2: Run integration test**

```bash
RUN_NEO4J_INTEGRATION=1 pytest -q tests/integration/test_bidirectional_visual_reference_real_neo4j.py -s
```

- [ ] **Step 3: Fix only defects exposed by those cases**

Allowed fixes are graph query scoping/metadata or deterministic coverage logic. Do not add filename matching.

- [ ] **Step 4: Re-run and commit**

```bash
RUN_NEO4J_INTEGRATION=1 pytest -q tests/integration/test_bidirectional_visual_reference_real_neo4j.py -s
git add backend/tests/integration/test_bidirectional_visual_reference_real_neo4j.py backend/app/graph/canonical_repository.py backend/app/services/visual_reference_coverage.py
git commit -m "test: prove reverse visual coverage with real neo4j"
```

---

### Task 6: Make candidate intent visible to archaeologists

**Files:**
- Modify: `frontend/src/components/SplitViewInspector.tsx`
- Modify: `frontend/src/components/SplitViewInspector.test.tsx`

**Interfaces:**
- Consumes: `Evidence.rule_name` / `ruleName`.
- Produces: one Korean read-only intent label; no new mutation endpoint.

Mapping:

```ts
visual_reference_missing -> '참조 누락'
visual_reference_blank_fill -> '참조 빈칸'
visual_reference_ambiguous -> '참조 후보 복수'
visual_reference_location_ambiguous -> '참조 위치 확인 필요'
visual_reference_wrong_target -> '기존 참조 불일치'
```

- [ ] **Step 1: Write failing Vitest cases**

Render candidates with each rule name and assert the Korean label. For ambiguity assert no fake replacement text is presented as an automatic proposal.

- [ ] **Step 2: Run focused frontend test and verify RED**

```bash
cd frontend
npm test -- --run src/components/SplitViewInspector.test.tsx
```

- [ ] **Step 3: Implement pure label mapping**

Prefer `rule_name` / `ruleName` from connected evidence. Keep the existing category badge and add one intent label.

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

- [ ] **Step 1: Backend hermetic suite**

Run the workflow-equivalent command from `.github/workflows/remediation-ci.yml`; `tests/test_visual_reference_coverage.py` must be included and not deselected.

- [ ] **Step 2: Real Neo4j suite**

```bash
cd backend
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

Confirm through tests/code inspection:

```text
- ReviewRound remains sole /runs input authority.
- production coverage service imports no filesystem matcher.
- _45.JPG / _91.JPG cannot create reference identity.
- removing DEPICTS removes reverse-coverage success.
- already-covered references do not produce duplicate added candidates.
- resolved-reference VLM still uses canonical visual versions.
```

- [ ] **Step 5: Push final branch HEAD and record CI**

Mandatory GitHub Actions jobs must all be green: backend-hermetic, neo4j-e2e, frontend. External VLM quality remains HOLD.