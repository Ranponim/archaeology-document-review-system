# Reference Corpus Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an immutable, corpus-scoped canonical visual graph from InDesign + Links and Illustrator source files without using filenames or AI as identity authority.

**Architecture:** Existing `OriginalAsset` storage remains the provenance layer. A new `ReferenceCorpus` aggregate stages source assets, delegates Adobe DOM extraction to a separate converter-agent process, validates a versioned manifest, canonicalizes explicit internal publication identifiers, and persists corpus-scoped `Plate/PlatePanel/Drawing/DrawingRegion` nodes to Neo4j. Ordinary GitHub CI uses deterministic fixture manifests; real Adobe smoke execution is isolated behind the same agent contract for a Windows self-hosted runner.

**Tech Stack:** Python 3.12, FastAPI, Neo4j 5.26, RQ/Redis, React/TypeScript/Vitest, Adobe InDesign/Illustrator automation through a separate Windows converter agent.

**Spec:** `docs/superpowers/specs/2026-08-22-graph-first-reference-corpus-review-design.md`

## Global Constraints

- Body documents remain PDF; plate/drawing authority comes from `.indd` + linked images and `.ai` sources.
- Canonical identity precedes AI.
- Filenames never establish Plate, PlatePanel, Drawing, or DrawingRegion identity.
- Explicit identifiers inside INDD/AI document structure may establish identity only when unique and project/corpus scoped.
- `OriginalAsset` stores provenance only; derived PDF/PNG/SVG artifacts are render/evidence artifacts only.
- READY `ReferenceCorpus` revisions are immutable.
- Ambiguous identity fails closed and prevents READY.
- All source and canonical relationships must remain project/corpus scoped.
- Core behavior must be testable in ordinary CI without Adobe installed.
- Production conversion uses the exact same JSON manifest contract as CI; Adobe DOM/business rules do not leak into backend canonicalization code.

---

## File Structure

- Create `backend/app/domain/reference_corpus.py`: corpus/build/artifact domain dataclasses and status/failure enums.
- Create `backend/app/domain/adobe_manifest.py`: normalized Adobe manifest contract consumed by Python.
- Create `backend/app/graph/reference_corpus_repository.py`: all Cypher for corpus/source/artifact/canonical persistence and immutable-state enforcement.
- Create `backend/app/services/adobe_conversion_client.py`: converter protocol, subprocess production client, and deterministic fixture adapter.
- Create `tools/adobe_converter/agent.py`: standalone JSON-in/JSON-out Windows Adobe automation process.
- Create `tools/adobe_converter/scripts/indesign_extract.jsx`: InDesign structural extractor and render/export script.
- Create `tools/adobe_converter/scripts/illustrator_extract.jsx`: Illustrator structural extractor and render/export script.
- Modify `backend/app/services/source_import_service.py`: expose staged source roles without allowing names to become identity.
- Create `backend/app/services/reference_canonicalizer.py`: manifest-to-canonical deterministic rules.
- Create `backend/app/services/reference_corpus_service.py`: staging/build/idempotency/state-machine orchestration.
- Create `backend/app/api/reference_corpora.py`: corpus create/upload/build/list/detail endpoints.
- Modify `backend/app/main.py`: wire router/service/repository dependencies.
- Modify `backend/app/graph/schema.py`: constraints/indexes for `ReferenceCorpus` and `DerivedArtifact`.
- Modify `backend/app/domain/canonical_models.py`: add corpus ownership/source-asset provenance fields required by new visual nodes.
- Modify `backend/app/graph/canonical_repository.py`: persist corpus-scoped membership while retaining legacy DocumentVersion visual ownership only for old rounds.
- Create `frontend/src/referenceCorpusApi.ts`: typed corpus API client.
- Create `frontend/src/components/ReferenceCorpusPanel.tsx`: reference-data staging/build/status UI.
- Modify `frontend/src/pages/ProjectDetailPage.tsx`: replace new plate/drawing PDF workflow with the reference-data panel while leaving body PDF upload available.
- Verify with unit tests, real Neo4j integration, frontend tests/build, and `.github/workflows/remediation-ci.yml`.

---

### Task 1: ReferenceCorpus domain and Neo4j schema

**Files:**
- Create: `backend/app/domain/reference_corpus.py`
- Modify: `backend/app/graph/schema.py`
- Test: `backend/tests/test_reference_corpus_domain.py`

**Interfaces:**
- Produces: `ReferenceCorpusStatus`, `ReferenceCorpusFailureCode`, `ReferenceCorpusData`, `DerivedArtifactData`, `compute_build_identity(source_set_hash, converter_version, manifest_schema_version, canonicalizer_version) -> str`.
- Consumers: Tasks 2 and 5.

- [ ] **Step 1: Write the failing domain tests**

```python
from app.domain.reference_corpus import ReferenceCorpusStatus, compute_build_identity


def test_ready_is_terminal_immutable_state():
    assert ReferenceCorpusStatus.READY.is_terminal is True


def test_build_identity_changes_when_canonicalizer_changes():
    first = compute_build_identity("sources", "adobe-1", "manifest-1", "canon-1")
    second = compute_build_identity("sources", "adobe-1", "manifest-1", "canon-2")
    assert first != second
```

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_reference_corpus_domain.py`
Expected: FAIL because `app.domain.reference_corpus` does not exist.

- [ ] **Step 3: Implement the exact status/failure/domain types**

```python
class ReferenceCorpusStatus(str, Enum):
    STAGING = "staging"
    CONVERTING = "converting"
    VALIDATING = "validating"
    CANONICALIZING = "canonicalizing"
    GRAPH_VALIDATING = "graph_validating"
    READY = "ready"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.READY, self.FAILED}
```

Add all failure codes from the spec and frozen dataclasses with exact corpus/artifact audit properties. Build identity is SHA-256 over the four ordered UTF-8 fields separated by NUL.

- [ ] **Step 4: Add schema entries**

Add unique constraints for `ReferenceCorpus.id` and `DerivedArtifact.id`, plus indexes on `(projectId, status)`, `(projectId, revision)`, and `buildIdentity`.

- [ ] **Step 5: Run GREEN**

Run: `cd backend && pytest -q tests/test_reference_corpus_domain.py && python -m compileall -q app/graph/schema.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domain/reference_corpus.py backend/app/graph/schema.py backend/tests/test_reference_corpus_domain.py
git commit -m "feat(graph): add reference corpus domain"
```

---

### Task 2: Corpus repository and immutable graph membership

**Files:**
- Create: `backend/app/graph/reference_corpus_repository.py`
- Modify: `backend/app/domain/canonical_models.py`
- Modify: `backend/app/graph/canonical_repository.py`
- Test: `backend/tests/test_reference_corpus_repository.py`
- Test: `backend/tests/integration/test_reference_corpus_real_neo4j.py`

**Interfaces:**
- Produces: `ReferenceCorpusRepository.create_staging`, `attach_source`, `list_sources`, `save_artifact`, `transition_status`, `find_ready_by_build_identity`, `save_canonical_visuals`, `validate_ready_graph`, `get`, `list_for_project`.
- Consumes: Task 1 domain objects.

- [ ] **Step 1: Write repository RED tests for project scoping and immutability**

```python
def test_ready_corpus_rejects_new_source(repository, ready_corpus, source):
    with pytest.raises(ValueError, match="immutable"):
        repository.attach_source(ready_corpus.project_id, ready_corpus.id, source.id, "plate_link")


def test_cross_project_source_is_rejected(repository, corpus, foreign_source):
    with pytest.raises(ValueError, match="project"):
        repository.attach_source(corpus.project_id, corpus.id, foreign_source.id, "drawing_source")
```

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_reference_corpus_repository.py`
Expected: FAIL because repository methods are missing.

- [ ] **Step 3: Implement project-rooted Cypher only inside the repository**

Every mutation starts from `MATCH (p:Project {id:$project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id:$corpus_id})`. READY rejects source/artifact/canonical/status mutations. Source attachment must also match `OriginalAsset {projectId:$project_id}`. Save `role` on `USES_SOURCE`.

- [ ] **Step 4: Add corpus ownership to visual canonical objects**

Add `reference_corpus_id: str | None = None` to `PlateData` and `DrawingData`, and `source_asset_id: str | None = None` to `PlatePanelData`/`DrawingRegionData` where provenance needs it. New persistence creates `(corpus)-[:HAS_PLATE/HAS_DRAWING]->(...)`; legacy `DocumentVersion` relationships remain only when `document_version_id` is supplied.

- [ ] **Step 5: Run unit + real Neo4j GREEN**

Run: `cd backend && pytest -q tests/test_reference_corpus_repository.py tests/integration/test_reference_corpus_real_neo4j.py`
Expected: PASS including READY immutability and cross-project rejection.

- [ ] **Step 6: Commit**

```bash
git add backend/app/graph/reference_corpus_repository.py backend/app/domain/canonical_models.py backend/app/graph/canonical_repository.py backend/tests/test_reference_corpus_repository.py backend/tests/integration/test_reference_corpus_real_neo4j.py
git commit -m "feat(graph): persist immutable reference corpora"
```

---

### Task 3: Versioned Adobe manifest and real converter-agent boundary

**Files:**
- Create: `backend/app/domain/adobe_manifest.py`
- Create: `backend/app/services/adobe_conversion_client.py`
- Create: `tools/adobe_converter/agent.py`
- Create: `tools/adobe_converter/scripts/indesign_extract.jsx`
- Create: `tools/adobe_converter/scripts/illustrator_extract.jsx`
- Test: `backend/tests/test_adobe_manifest.py`
- Test: `backend/tests/test_adobe_conversion_client.py`
- Test: `backend/tests/test_adobe_converter_agent_contract.py`
- Create fixtures: `backend/tests/fixtures/reference_corpus/indesign_manifest_v1.json`, `backend/tests/fixtures/reference_corpus/illustrator_manifest_v1.json`

**Interfaces:**
- Produces: `AdobeManifestV1.from_dict`, `ConversionRequest`, `ConversionResult`, `AdobeConversionClient.convert`, `SubprocessAdobeConversionClient`, and the agent command `python tools/adobe_converter/agent.py --request <request.json> --result <result.json>`.
- Consumers: Tasks 4 and 5.

- [ ] **Step 1: Write strict manifest RED tests**

```python
def test_manifest_rejects_unknown_schema_version():
    with pytest.raises(ValueError, match="schema"):
        AdobeManifestV1.from_dict({"schemaVersion": 99, "application": "indesign"})


def test_manifest_preserves_internal_text_and_link_ids():
    manifest = AdobeManifestV1.from_dict(load_fixture("indesign_manifest_v1.json"))
    assert manifest.pages[0].text_frames[0].text == "【도판 45】"
    assert manifest.pages[0].graphics[0].link_id == "link-301"
```

- [ ] **Step 2: Write converter-agent boundary RED tests**

Mock subprocess execution and assert the production client writes a request JSON containing only asset IDs/paths, corpus/project IDs, output directory, and schema version; assert it rejects nonzero exit/timeout/missing result as normalized converter failures.

- [ ] **Step 3: Run RED**

Run: `cd backend && pytest -q tests/test_adobe_manifest.py tests/test_adobe_conversion_client.py tests/test_adobe_converter_agent_contract.py`
Expected: FAIL because the types/client/agent do not exist.

- [ ] **Step 4: Implement normalized manifest dataclasses**

Model only structure: pages/artboards, text frames/text/bounds, graphic/placed items, link IDs/paths, object IDs, application/version, and artifact descriptors. Do not parse publication numbers in this layer.

- [ ] **Step 5: Implement production subprocess client and deterministic fixture client**

```python
class AdobeConversionClient(Protocol):
    def convert(self, request: ConversionRequest) -> ConversionResult: ...
```

`SubprocessAdobeConversionClient` runs the separate agent with timeout and parses result JSON. A fixture client returns the checked-in manifests for hermetic CI.

- [ ] **Step 6: Implement the standalone Windows Adobe agent and JSX extractors**

`agent.py` dynamically imports Windows COM support only when actually executed on Windows, opens the requested InDesign/Illustrator source through the installed Adobe application, executes the appropriate JSX, writes manifest/render outputs, and emits structured error JSON. JSX records DOM facts only; it must not decide Plate/Drawing publication identity. On non-Windows or missing Adobe, emit `ADOBE_UNAVAILABLE` rather than silently falling back to filename/PDF heuristics.

- [ ] **Step 7: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_adobe_manifest.py tests/test_adobe_conversion_client.py tests/test_adobe_converter_agent_contract.py`
Expected: PASS without Adobe installed.

```bash
git add backend/app/domain/adobe_manifest.py backend/app/services/adobe_conversion_client.py tools/adobe_converter backend/tests/test_adobe_manifest.py backend/tests/test_adobe_conversion_client.py backend/tests/test_adobe_converter_agent_contract.py backend/tests/fixtures/reference_corpus
git commit -m "feat(source): add adobe converter agent contract"
```

---

### Task 4: Deterministic INDD/AI canonicalizer

**Files:**
- Create: `backend/app/services/reference_canonicalizer.py`
- Test: `backend/tests/test_reference_canonicalizer.py`

**Interfaces:**
- Produces: `ReferenceCanonicalizer.canonicalize(corpus_id, manifests, assets) -> CanonicalizationResult`.
- Consumes: Task 3 manifest types and `OriginalAssetData`.

- [ ] **Step 1: Write RED authority tests**

```python
def test_filename_number_never_creates_plate(canonicalizer):
    result = canonicalizer.canonicalize("c1", manifests=[], assets=[asset("조사후_45.JPG")])
    assert result.plates == []


def test_unique_indesign_internal_identifier_creates_plate_and_linked_panel(canonicalizer):
    result = canonicalizer.canonicalize("c1", [indesign_fixture()], assets_fixture())
    assert result.plates[0].number == "45"
    assert result.plates[0].panels[0].source_asset_id == "photo-1"


def test_duplicate_drawing_identifier_fails_closed(canonicalizer):
    with pytest.raises(CanonicalizationError, match="DUPLICATE_CANONICAL_IDENTIFIER"):
        canonicalizer.canonicalize("c1", duplicate_drawing_manifests(), assets_fixture())
```

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_reference_canonicalizer.py`
Expected: FAIL because canonicalizer does not exist.

- [ ] **Step 3: Implement explicit-identifier parsing over manifest DOM text only**

Recognize explicit patterns such as `【도판 45】` and `【도면 30】` from structural manifest text frames. Generate corpus-scoped IDs exactly as in the spec. Use actual InDesign graphic-frame/link-ID placement to bind a panel to its OriginalAsset. Never use filenames to choose number or canonical target.

- [ ] **Step 4: Implement fail-closed errors**

Normalize `LINK_MISSING`, `IDENTIFIER_UNRESOLVED`, `AMBIGUOUS_IDENTIFIER`, `DUPLICATE_CANONICAL_IDENTIFIER`, and `PROVENANCE_INCOMPLETE`. DrawingRegion exists only when ownership/identifier is deterministic; otherwise keep only the parent Drawing.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_reference_canonicalizer.py tests/test_case6_filename_trap.py`
Expected: PASS.

```bash
git add backend/app/services/reference_canonicalizer.py backend/tests/test_reference_canonicalizer.py
git commit -m "feat(graph): canonicalize indesign and illustrator sources"
```

---

### Task 5: ReferenceCorpus state machine, idempotency, build/retry service

**Files:**
- Create: `backend/app/services/reference_corpus_service.py`
- Modify: `backend/app/services/source_import_service.py`
- Test: `backend/tests/test_reference_corpus_service.py`
- Test: `backend/tests/test_source_import_service.py`

**Interfaces:**
- Produces: `ReferenceCorpusService.create`, `stage_sources`, `build`, `retry_failed_build`, `list`, `get`.
- Consumes: Tasks 2-4.

- [ ] **Step 1: Write RED state/idempotency tests**

```python
def test_identical_build_reuses_existing_ready_corpus(service):
    first = service.build(project_id, corpus_id)
    second = service.build(project_id, another_staging_id_with_same_sources)
    assert second.id == first.id


def test_changed_source_creates_new_revision(service):
    v1 = service.build(project_id, corpus_v1)
    v2 = service.build(project_id, corpus_with_changed_ai)
    assert v2.revision == v1.revision + 1
```

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_reference_corpus_service.py`
Expected: FAIL because service does not exist.

- [ ] **Step 3: Implement exact state transitions**

`staging -> converting -> validating -> canonicalizing -> graph_validating -> ready`. On failure persist `failed` plus normalized failure code while retaining sources/artifacts/manifest diagnostics. Compute `sourceSetHash` from sorted `(role, asset.sha256)` pairs, then compute build identity with converter/manifest/canonicalizer versions.

- [ ] **Step 4: Keep upload role separate from canonical identity**

Extend source staging so `.indd`, linked images, and `.ai` are accepted only with explicit roles. Role routes the converter input; it never provides publication number identity.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_reference_corpus_service.py tests/test_source_import_service.py`
Expected: PASS.

```bash
git add backend/app/services/reference_corpus_service.py backend/app/services/source_import_service.py backend/tests/test_reference_corpus_service.py backend/tests/test_source_import_service.py
git commit -m "feat(source): orchestrate reference corpus builds"
```

---

### Task 6: Corpus API and app wiring

**Files:**
- Create: `backend/app/api/reference_corpora.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/projects.py`
- Test: `backend/tests/test_reference_corpora_api.py`
- Test: `backend/tests/test_projects_api.py`

**Interfaces:**
- Produces: create/upload/build/list/detail endpoints from the spec.
- Consumes: Task 5 service.

- [ ] **Step 1: Write API contract RED tests**

```python
def test_upload_plate_layout_accepts_indd(client, project_id, corpus_id):
    response = client.post(
        f"/api/projects/{project_id}/reference-corpora/{corpus_id}/sources?role=plate_layout",
        files={"file": ("plates.indd", b"indd-bytes", "application/octet-stream")},
    )
    assert response.status_code == 202


def test_new_plate_pdf_upload_is_rejected(client, project_id):
    response = client.post(
        f"/api/projects/{project_id}/documents?kind=plate_book&stage=source",
        files={"file": ("plates.pdf", b"%PDF-fake", "application/pdf")},
    )
    assert response.status_code in {400, 422}
```

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_reference_corpora_api.py`
Expected: FAIL because router does not exist.

- [ ] **Step 3: Implement create/upload/build/list/detail**

Enforce role-extension contract: `plate_layout=.indd`, `plate_link={.jpg,.jpeg,.png,.tif,.tiff}`, `drawing_source=.ai`. Build endpoint returns current build state and diagnostics rather than pretending upload completion equals READY.

- [ ] **Step 4: Restrict new visual publication-PDF uploads**

The normal document endpoint continues accepting `report_body` PDF. New `plate_book`/`drawing_book` uploads are rejected; legacy graph records remain readable and legacy round execution remains compatibility-only.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && pytest -q tests/test_reference_corpora_api.py tests/test_projects_api.py`
Expected: PASS.

```bash
git add backend/app/api/reference_corpora.py backend/app/main.py backend/app/api/schemas.py backend/app/api/projects.py backend/tests/test_reference_corpora_api.py backend/tests/test_projects_api.py
git commit -m "feat(api): add reference corpus build endpoints"
```

---

### Task 7: Reference-data UI

**Files:**
- Create: `frontend/src/referenceCorpusApi.ts`
- Create: `frontend/src/referenceCorpusApi.test.ts`
- Create: `frontend/src/components/ReferenceCorpusPanel.tsx`
- Create: `frontend/src/components/ReferenceCorpusPanel.test.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces: separate reference-data staging/build/status UI and typed API client.
- Consumes: Task 6 endpoints.

- [ ] **Step 1: Write frontend RED tests**

```tsx
it('shows INDD, linked-photo, and AI source selectors instead of visual PDF upload', async () => {
  render(<ReferenceCorpusPanel projectId="p1" />)
  expect(screen.getByText('도판 INDD')).toBeInTheDocument()
  expect(screen.getByText('도면 AI')).toBeInTheDocument()
  expect(screen.queryByText('도판 PDF')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run RED**

Run: `cd frontend && npm test -- --run src/components/ReferenceCorpusPanel.test.tsx`
Expected: FAIL because component does not exist.

- [ ] **Step 3: Implement typed API and panel**

Show current revision/status, INDD source, linked-photo count/status, AI count/status, canonical counts, failure diagnostics, and build/rebuild action. File inputs use `.indd`, accepted linked-image types, and `.ai`; body PDF remains outside this panel.

- [ ] **Step 4: Remove new visual-PDF authority from ProjectDetailPage**

Users are offered `본문 PDF 선택` for review-body upload and the ReferenceCorpus panel for plate/drawing sources. Existing legacy round visual IDs may still render read-only.

- [ ] **Step 5: Run frontend GREEN**

Run: `cd frontend && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/referenceCorpusApi.ts frontend/src/referenceCorpusApi.test.ts frontend/src/components/ReferenceCorpusPanel.tsx frontend/src/components/ReferenceCorpusPanel.test.tsx frontend/src/pages/ProjectDetailPage.tsx frontend/src/styles.css
git commit -m "feat(ui): add reference corpus source workflow"
```

---

### Task 8: ReferenceCorpus E2E, CI and Adobe smoke gate

**Files:**
- Add: `backend/tests/test_reference_corpus_build_e2e.py`
- Test: `backend/tests/integration/test_reference_corpus_real_neo4j.py`
- Modify: `.github/workflows/remediation-ci.yml` only if its current test commands do not automatically include the new hermetic/integration tests.
- Add: `.github/workflows/adobe-converter-smoke.yml` only when a labeled Windows self-hosted Adobe runner is available; this workflow must never be a prerequisite for ordinary Linux hermetic CI unless the runner exists.

**Interfaces:**
- Produces: fresh authoritative Plan A test evidence and an isolated real-Adobe smoke contract.

- [ ] **Step 1: Add fixture-converter E2E test**

Exercise project -> corpus create -> stage INDD/Links/AI -> fixture converter -> canonicalize -> persist real Neo4j graph -> READY. Assert corpus-scoped IDs, provenance edges, canonical counts, and filename non-authority.

- [ ] **Step 2: Run focused backend suite**

Run: `cd backend && pytest -q tests/test_reference_corpus_domain.py tests/test_adobe_manifest.py tests/test_adobe_conversion_client.py tests/test_adobe_converter_agent_contract.py tests/test_reference_canonicalizer.py tests/test_reference_corpus_service.py tests/test_reference_corpora_api.py tests/test_reference_corpus_build_e2e.py`
Expected: PASS.

- [ ] **Step 3: Run real Neo4j integration**

Run the repository's existing Neo4j CI command including `tests/integration/test_reference_corpus_real_neo4j.py`.
Expected: PASS.

- [ ] **Step 4: Run complete frontend verification**

Run: `cd frontend && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

- [ ] **Step 5: Verify real Adobe adapter separately when runner is available**

On a Windows self-hosted machine with InDesign/Illustrator installed, run the converter agent against one tiny INDD+linked-photo fixture and one AI fixture. Assert both produce schema-v1 manifests and renders accepted by `AdobeManifestV1`. If no such runner is connected, report this gate as environment-dependent rather than claiming Adobe runtime execution.

- [ ] **Step 6: Commit CI-only changes**

```bash
git add .github/workflows backend/tests
git commit -m "test: cover reference corpus build end to end"
```
