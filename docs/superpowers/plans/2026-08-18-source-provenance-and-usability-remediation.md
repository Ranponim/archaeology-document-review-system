# Source Provenance and Archaeologist Usability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the four approved follow-up slices—project timestamps, frontend visibility, archaeologist-friendly graph presentation, and strict OriginalAsset provenance—without weakening canonical publication identity.

**Architecture:** Neo4j remains the canonical authority for publication identity and review state. Raw HWP/HWPX/AI/INDD/image files are persisted as project-owned `OriginalAsset` nodes and can only connect to already-existing canonical nodes through an explicitly scoped manifest and `DERIVED_FROM`; filenames and VLM never establish identity. Frontend presentation is semantic/read-only, while IDs and hashes remain technical details.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, Neo4j 5.26, PyMuPDF, pytest, React 18, TypeScript, Vitest, GitHub Actions

## Global Constraints

- Baseline is `a6a54f282e22bdfc1d86b7e6f81a71f663d19269`; implementation branch is `feature/source-provenance-remediation-20260818`.
- The authoritative design is `docs/superpowers/specs/2026-08-18-source-provenance-and-usability-final-design.md`; the earlier draft is superseded.
- Filename, relative path, folder name, AI filename, Links sequence number, physical page number, LLM output, and VLM output contribute zero authority to canonical `Plate/PlatePanel/Drawing/DrawingRegion` identity.
- AI/INDD/HWP/HWPX/raw images never create canonical publication nodes in this batch.
- `Reference(type=plate,45)-[:RESOLVES_TO]->canonical target` remains the Case 6 authority path; `_45.JPG` and `_91.JPG` cannot create or repair targets.
- `OriginalAsset` is supplementary provenance only; it does not replace canonical PDF render/VLM input. VLM acceptance remains HOLD.
- Persistent `SourceBundle` and `PROVENANCED_BY` are forbidden in this batch. Use project-owned `OriginalAsset` plus scoped `DERIVED_FROM` only.
- Public `POST /api/projects/{project_id}/documents` remains publication-PDF-only after this remediation; source-only formats use `SourceImportService`/CLI.
- Source root symlink is allowed after one `resolve()`; child paths must remain inside the resolved boundary.
- No failing test may be hidden with `--deselect` or removed merely to obtain green CI.

## File Map

### Project timestamps
- Modify `backend/app/domain/models.py` — add `Project.created_at/updated_at`.
- Modify `backend/app/api/schemas.py` — expose `createdAt/updatedAt`.
- Modify `backend/app/api/projects.py` — serialize timestamp fields and restrict publication upload to PDF.
- Modify `backend/app/graph/project_repository.py` — persist/read timestamps, deterministic list ordering, update `updatedAt` during structural mutations.
- Modify `frontend/src/api.ts` — add project timestamps.
- Modify `frontend/src/pages/ProjectsPage.tsx` — display creation time without client-side re-sort.
- Tests: `backend/tests/test_project_repository.py`, `backend/tests/test_projects_api.py` or existing project API test file, `frontend/src/pages/ProjectsPage.test.tsx`.

### Visibility and semantic presentation
- Modify `frontend/src/styles.css` — real secondary button and project-card base/focus styles.
- Modify `frontend/src/pages/ProjectsPage.tsx` — semantic classes, no visibility-critical inline colors/backgrounds.
- Create `frontend/src/graphPresentation.ts` — semantic node and edge labels.
- Modify `frontend/src/components/EvidenceGraphExplorer.tsx` — consume semantic labels; no ID-prefix title fallback.
- Modify `frontend/src/components/ProjectStructureInspector.tsx` — localized relationship labels and collapsed technical details.
- Tests: create `frontend/src/graphPresentation.test.ts`; modify/add explorer and structure tests.

### OriginalAsset provenance
- Modify `backend/app/services/file_store.py` — add `.indd` MIME support.
- Create `backend/app/domain/source_assets.py` — `OriginalAssetData`, import/mapping result contracts.
- Create `backend/app/services/source_import_service.py` — safe source enumeration, immutable storage, classification, optional AI metadata inspection, manifest validation.
- Create `backend/app/graph/source_asset_repository.py` — project-scoped OriginalAsset persistence, canonical-target resolution within one DocumentVersion, `DERIVED_FROM` write.
- Create `backend/scripts/ingest_src_folder.py` — CLI adapter only; no business logic.
- Modify `backend/app/graph/schema.py` — retain OriginalAsset unique constraint and add project/path/hash lookup indexes needed by import.
- Modify `backend/app/api/project_structure_contract.py` — add `source_asset_group`, `source_kind_group`, `original_asset`.
- Modify `backend/app/graph/project_structure_repository.py` — lazy project-scoped source groups/assets and source relationships.
- Modify `backend/app/services/project_structure_service.py` — sixth `원천 자료` root group and semantic source labels/status.
- Modify `frontend/src/projectStructureApi.ts` — source node types.
- Tests: create `backend/tests/test_source_import_service.py`, `backend/tests/test_source_asset_repository.py`; extend `backend/tests/integration/test_project_structure_real_neo4j.py` or the existing real-Neo4j structure test; extend frontend structure tests.

### CI
- Modify `.github/workflows/remediation-ci.yml` — include `feature/source-provenance-remediation-20260818` in push branches while implementation is active.

---

### Task 1: Complete Project Timestamp Contract and Publication Upload Boundary

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/projects.py`
- Modify: `backend/app/graph/project_repository.py`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `.github/workflows/remediation-ci.yml`
- Test: `backend/tests/test_project_repository.py`
- Test: existing project API test file under `backend/tests/`
- Test: `frontend/src/pages/ProjectsPage.test.tsx`

**Interfaces:**
- Produces: `Project(id, name, internal_code, created_at, updated_at)` where timestamps are `str | None`.
- API produces `createdAt` and `updatedAt` ISO strings or null.
- `list_projects()` authoritative order: non-null `createdAt` first, then `createdAt DESC`, `name ASC`, `id ASC`; null legacy rows last.
- `POST /api/projects/{project_id}/documents` accepts only PDF publication files; source-only formats fail with HTTP 422/400 through existing input-error handling rather than becoming `DocumentVersion`.

- [ ] **Step 1: Add branch CI trigger and timestamp RED tests**

Add the feature branch under workflow `push.branches`. In repository tests, assert project creation Cypher writes both timestamps and list query returns both timestamp fields with null-last ordering. In API tests, construct `Project(..., created_at="2026-08-18T00:00:00Z", updated_at="2026-08-18T01:00:00Z")` and assert camelCase response fields.

- [ ] **Step 2: Add publication upload boundary RED test**

Use the upload endpoint with a valid `.hwp`, `.ai`, or `.jpg` payload and assert it is rejected before `repository.add_document_version` is called. Keep ordinary PDF upload test passing.

- [ ] **Step 3: Push the RED-only commit and verify Actions fail for the expected missing timestamp/upload-boundary assertions**

Expected: backend/API/frontend tests fail because timestamp fields and PDF-only publication guard do not exist yet. Do not proceed if failure is unrelated infrastructure breakage.

- [ ] **Step 4: Implement timestamps minimally**

`Project`:

```python
@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    internal_code: str | None
    created_at: str | None = None
    updated_at: str | None = None
```

Neo4j creation:

```cypher
CREATE (project:Project {
  id: $id,
  name: $name,
  internalCode: $internal_code,
  createdAt: datetime(),
  updatedAt: datetime()
})
RETURN project.createdAt AS created_at, project.updatedAt AS updated_at
```

List query returns `toString(project.createdAt)` / `toString(project.updatedAt)` (or driver-safe string conversion in Python) and orders with an explicit null key before descending timestamp.

Every document/version creation transaction adds:

```cypher
SET project.updatedAt = datetime()
```

`create_review_round` and `approve_review_round` update the matched Project in the same write query/transaction.

- [ ] **Step 5: Implement publication PDF-only boundary**

In `upload_document`, reject `file.filename`/content type unless suffix is `.pdf` and FileStore resolves it as `application/pdf`. This endpoint must not become the raw-source import path.

- [ ] **Step 6: Implement API/frontend serialization**

Add nullable aliases in `ProjectResponse`; pass fields in list/create/detail routes; add `createdAt/updatedAt` to frontend `Project`. Render `createdAt` in cards using a small formatter and show `생성일 기록 없음` when null. Do not sort in React.

- [ ] **Step 7: Run/observe Task 1 GREEN**

Required: targeted backend tests + frontend ProjectsPage test pass; then all three workflow jobs pass at the task commit.

- [ ] **Step 8: Commit**

Commit message: `feat(projects): complete timestamp contract and publication boundary`.

---

### Task 2: Make Project UI Visible Without Hover

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Test: `frontend/src/pages/ProjectsPage.test.tsx`

**Interfaces:**
- Produces CSS classes: `.projects-header-row`, `.project-list`, `.project-card-item`, `.project-card-title`, `.project-card-meta`, `.project-card-open`, `.secondary-button`.
- Base state—not hover—contains readable foreground/background/border.

- [ ] **Step 1: Write RED component/style contract tests**

Render ProjectsPage with two projects and assert refresh/open controls are present before pointer interaction. Assert elements carry semantic classes. Add a lightweight CSS contract test reading `styles.css` (or equivalent source assertion) that `.secondary-button` has explicit `color`, `background`, and `border`, and `.project-card-item:focus-within`/button focus has visible outline.

- [ ] **Step 2: Push RED and confirm frontend job fails only on new visibility assertions**

- [ ] **Step 3: Replace visibility-critical inline card styles**

Keep layout-related inline style only where it is non-visual if unavoidable; move colors/background/border/title/meta/action visibility to classes. Make the card keyboard-safe by keeping the explicit Open button as the actionable control; do not create nested interactive elements inside a clickable button.

- [ ] **Step 4: Add base/focus CSS**

`.secondary-button` uses a light neutral background, dark readable text, visible border; hover changes emphasis only. Project cards have visible title/meta/action in default state and an accessible focus outline.

- [ ] **Step 5: Verify targeted + full frontend GREEN and commit**

Commit message: `fix(frontend): make project controls visible by default`.

---

### Task 3: Add Shared Archaeologist-Friendly Graph Presentation

**Files:**
- Create: `frontend/src/graphPresentation.ts`
- Create: `frontend/src/graphPresentation.test.ts`
- Modify: `frontend/src/components/EvidenceGraphExplorer.tsx`
- Modify: `frontend/src/components/ProjectStructureInspector.tsx`
- Modify: relevant existing explorer/structure tests

**Interfaces:**
- Produces:

```ts
export function semanticNodeTitle(label: string | undefined, props: Record<string, unknown>): string
export function relationshipLabel(type: string): string
export function technicalDetails(details: Record<string, unknown>): Array<[string, unknown]>
```

- Known edge names map to Korean semantic text.
- Unknown/missing node metadata yields a domain fallback such as `[도판] 식별 정보 없음`, never any `id.slice(...)`, UUID prefix, or SHA prefix.

- [ ] **Step 1: Write RED presentation tests**

Cover ArchaeologyObject, Plate, PlatePanel, Drawing, Reference, OriginalAsset, missing metadata, and relationships `RESOLVES_TO`, `MENTIONS`, `DEPICTS`, `ABOUT`, `SUPPORTED_BY`, `EXTRACTED_FROM`, `FROM_VERSION`, `HAS_PANEL`, `HAS_REGION`, `PRECEDES`, `DERIVED_FROM`.

Add explicit assertion:

```ts
expect(semanticNodeTitle('Plate', { id: '550e8400-e29b-41d4-a716-446655440000' }))
  .toBe('[도판] 식별 정보 없음');
```

- [ ] **Step 2: Push RED and verify frontend failure is the missing helper/old ID fallback**

- [ ] **Step 3: Implement `graphPresentation.ts`**

Use publication number/title/caption/canonical_name/text/originalName in priority order by node type. OriginalAsset label may display filename because filename is a display/provenance fact, but append provenance state (`canonical 미연결`, `연결 선언`, etc.) and never imply a publication number.

- [ ] **Step 4: Replace EvidenceGraphExplorer title fallbacks**

Route canonical-path nodes and candidate/object display through semantic helper. Candidate fallback is `[교열 제안] 검수 후보`; internal candidate ID stays in properties/technical detail only.

- [ ] **Step 5: Refactor ProjectStructureInspector**

Main relation row renders `relationshipLabel(relationship.type)`. Move `ID`, raw node type, SHA/storage URI/raw label into a `<details>` block titled `기술 정보`; ordinary storage/parse/provenance facts remain in the normal facts section.

- [ ] **Step 6: Verify targeted + full frontend GREEN and commit**

Commit message: `feat(frontend): present graph in archaeological language`.

---

### Task 4: Implement Strict Project-Owned OriginalAsset Import and Manifest Provenance

**Files:**
- Modify: `backend/app/services/file_store.py`
- Create: `backend/app/domain/source_assets.py`
- Create: `backend/app/services/source_import_service.py`
- Create: `backend/app/graph/source_asset_repository.py`
- Create: `backend/scripts/ingest_src_folder.py`
- Modify: `backend/app/graph/schema.py`
- Test: `backend/tests/test_source_import_service.py`
- Test: `backend/tests/test_source_asset_repository.py`
- Test: real-Neo4j integration test file

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class OriginalAssetData:
    id: str
    project_id: str
    uri: str
    sha256: str
    size_bytes: int
    mime_type: str
    original_name: str
    relative_path: str
    asset_kind: str
    source_root_name: str
    import_batch_id: str
    parse_status: str
    provenance_status: str
    created_at: str | None = None

@dataclass(frozen=True, slots=True)
class SourceImportResult:
    import_batch_id: str
    imported: tuple[OriginalAssetData, ...]
    errors: tuple[str, ...]
```

Repository operations:

```python
save_original_asset(asset: OriginalAssetData) -> OriginalAssetData
resolve_scoped_target(project_id: str, document_version_id: str, node_type: str, node_id: str | None, publication_identifier: str | None) -> dict | None
link_derived_from(project_id: str, target_label: str, target_id: str, asset_id: str, *, method: str, manifest_sha256: str) -> None
```

`link_derived_from` only allows `method == "manifest_mapping"` in automated source import; `filename_match` is rejected.

- [ ] **Step 1: Write RED filesystem/import tests**

Temporary source tree tests must cover: root itself is a symlink and is accepted; nested symlink escaping the resolved root is rejected; `..`/absolute manifest asset path rejected; HWP/HWPX/AI/INDD/JPG/PNG/TIF/TIFF classified and stored; unsupported file produces a per-asset error without mutating source tree.

- [ ] **Step 2: Write RED identity tests**

A file named `도면30. 1지점.ai` produces only `OriginalAsset(asset_kind="drawing_source")`; AI metadata inspection may return `internal_identifiers=["30"]`, but repository receives no `save_drawings`. A file `4. 조사 후_45.JPG` remains provenance `unlinked` without manifest.

- [ ] **Step 3: Write RED manifest tests**

Manifest target requires `documentVersionId`; target must be reachable from the same Project and version. Missing, ambiguous, cross-project, or conflicting mappings write no `DERIVED_FROM`. `_91.JPG` never creates Plate 91. Mapping by `nodeId` or version-scoped explicit publication identifier may succeed only when exactly one existing target is found.

- [ ] **Step 4: Push RED and confirm expected backend/Neo4j failures**

- [ ] **Step 5: Add `.indd` to FileStore source MIME support**

Allow `application/x-indesign`, `application/vnd.adobe.indesign-idml-package` only if actually applicable to `.indd`; otherwise use a single explicit project MIME constant such as `application/x-indesign` consistently in tests and importer. Do not loosen arbitrary extension handling.

- [ ] **Step 6: Implement safe enumeration and immutable OriginalAsset storage**

Resolve source root once. For every child, call `resolved = path.resolve(strict=True)` and require `resolved == boundary or boundary in resolved.parents`. Read bytes; store through FileStore with the basename; persist original relative path separately. Deterministic asset ID is SHA-256 of `project_id + "\0" + normalized_relative_path + "\0" + file_sha256` with a stable prefix such as `asset_`.

- [ ] **Step 7: Implement source classification and AI source inspection**

Folder/path classification affects `asset_kind` only. AI inspector attempts PyMuPDF open; records source metadata/optional internal identifier but never invokes canonical Drawing persistence. INDD parse status is `unsupported`.

- [ ] **Step 8: Implement source repository and manifest mapping**

Persist:

```cypher
MATCH (p:Project {id:$project_id})
MERGE (a:OriginalAsset {id:$id})
ON CREATE SET ...
MERGE (p)-[:HAS_ORIGINAL_ASSET]->(a)
SET p.updatedAt = datetime()
```

The node also stores `projectId`; on an existing ID with a different projectId, fail closed.

Scoped target queries start at:

```cypher
MATCH (p:Project {id:$project_id})-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(v:DocumentVersion {id:$document_version_id})
```

and only traverse `HAS_PLATE/HAS_PANEL` or `HAS_DRAWING/HAS_REGION` for the requested label. `DERIVED_FROM` MATCHes the canonical target and `OriginalAsset` through the same Project ownership path before MERGE.

- [ ] **Step 9: Implement CLI adapter**

`backend/scripts/ingest_src_folder.py` parses `--project-id`, `--source-root`, optional `--manifest`, initializes existing app config/Neo4j/FileStore adapters, invokes `SourceImportService`, prints JSON summary, and exits nonzero only for whole-import fatal errors. No canonical filename matching code is allowed in the script.

- [ ] **Step 10: Run unit + real Neo4j GREEN and commit**

Commit message: `feat(provenance): import strict project-owned original assets`.

---

### Task 5: Extend Project Structure Explorer With Lazy Source Tree

**Files:**
- Modify: `backend/app/api/project_structure_contract.py`
- Modify: `backend/app/graph/project_structure_repository.py`
- Modify: `backend/app/services/project_structure_service.py`
- Modify: `frontend/src/projectStructureApi.ts`
- Modify: relevant project-structure frontend components/tests
- Test: backend project-structure unit and real-Neo4j integration tests

**Interfaces:**
- Adds node types: `source_asset_group`, `source_kind_group`, `original_asset`.
- Root group ID: `source-assets`, label `원천 자료`.
- Derived kind groups are not Neo4j nodes; OriginalAsset children are persisted nodes.
- Lazy list queries are project-scoped and paginated.

- [ ] **Step 1: Write RED root/children tests**

Root contains six groups in order: 본문, 도판 / 사진, 도면, 원천 자료, 검수 세트, 고고학 객체. `source-assets` expands to derived groups for `body_source`, `drawing_source`, `layout_source`, `linked_photo`, `other_source`; each kind group lazy-loads only project-owned assets.

- [ ] **Step 2: Write RED detail/relationship tests**

Unlinked `_45.JPG` label is `[원천 사진] 4. 조사 후_45.JPG · canonical 미연결`. A declared manifest mapping exposes `DERIVED_FROM` relationship to the canonical target, but display text does not call it canonical identity. Cross-project asset ID detail returns not-found/fail-closed.

- [ ] **Step 3: Push RED and verify expected failures**

- [ ] **Step 4: Implement backend contracts/repository/service**

Project summary adds `original_asset_count`. `get_root()` child count becomes 6. Repository list/detail queries anchor at `(Project)-[:HAS_ORIGINAL_ASSET]->(OriginalAsset)` and paginate with deterministic `relativePath, id` ordering.

- [ ] **Step 5: Implement frontend node types and render path**

Reuse existing lazy tree mechanics; no separate source-tree component unless current switch requires it. Badges show `stored/unsupported` and provenance status. Technical IDs remain inspector-only.

- [ ] **Step 6: Verify Project Structure unit + real Neo4j + frontend GREEN and commit**

Commit message: `feat(structure): expose original source provenance tree`.

---

### Task 6: Final Regression and Acceptance Gate

**Files:**
- Modify/add only tests or verification docs if a real gap is discovered; no speculative refactor.

**Interfaces:**
- Final HEAD must preserve strict ReviewRound `/runs`, Case 6 canonical identity, and all new provenance/UI contracts.

- [ ] **Step 1: Re-run mandatory strict run API negative tests**

Verify `{}` and any legacy `bodyVersionId/versionStage/bodyPdfPath` payload still return 422 and no compatibility route reappears.

- [ ] **Step 2: Re-run Case 6 + `_91.JPG` regression against real Neo4j**

Required evidence: `Reference(plate,45)-[:RESOLVES_TO]->canonical target`; `_45.JPG` without manifest has no `DERIVED_FROM`; `_91.JPG` cannot create/resolve Plate 91; scoped manifest may add provenance only after the canonical target exists.

- [ ] **Step 3: Run complete workflow gates**

Required GitHub Actions jobs:

```text
backend-hermetic: GREEN
neo4j-e2e: GREEN
frontend typecheck/test/build: GREEN
```

- [ ] **Step 4: Inspect workflow logs rather than status badge only**

Record actual pytest passed/skipped/deselected counts. New relevant tests must not be absent or deselected.

- [ ] **Step 5: Commit final verification note if needed and leave branch at verified HEAD**

VLM remains `HOLD / NOT VERIFIED`; do not claim VLM acceptance.
