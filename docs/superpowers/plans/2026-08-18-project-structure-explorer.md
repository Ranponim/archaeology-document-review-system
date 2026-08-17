# Project Structure Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only, lazy-loading Project Structure Explorer that lets archaeologists understand uploaded body/plate/drawing material, FileStore presence, Neo4j persistence, ingest state, ReviewRound membership, and canonical graph relationships without loading the whole graph.

**Architecture:** Add a focused read-only `ProjectStructureRepository` for project-scoped Neo4j queries, a `ProjectStructureService` that merges graph facts with FileStore presence, and a dedicated project-structure API. The React UI renders a shallow tree on first load and fetches child branches/details only when clicked. Cross-graph relationships are shown in a right-side inspector as jump links instead of recursively duplicating the graph.

**Tech Stack:** Python 3.12, FastAPI, Neo4j 5.26+, pytest, React 18, TypeScript 5.6, Vitest, Testing Library.

## Global Constraints

- The explorer is **read-only**: no delete, rename, move, version reassignment, ReviewRound mutation, or graph editing.
- Neo4j remains authoritative for project/document/version/canonical identity and relationships.
- File names never establish Plate/Drawing publication identity.
- Every node/children/detail query must prove ownership from the requested `Project`.
- Initial page load must not fetch the full project graph.
- Large collections default to 50 children and expose pagination.
- Existing candidate-centric `EvidenceGraphExplorer` keeps its current responsibility.
- The strict ReviewRound run contract from `2026-08-18-strict-review-round-run-and-case6-provenance-design.md` must not be weakened.
- External VLM remains `NOT VERIFIED / HOLD` and is not an acceptance criterion for this feature.

---

## File map

### Backend files to create
- `backend/app/api/project_structure_contract.py` — Pydantic request/response types and allow-listed node types.
- `backend/app/api/project_structure.py` — read-only root/children/detail routes.
- `backend/app/graph/project_structure_repository.py` — project-scoped Neo4j read queries only.
- `backend/app/services/project_structure_service.py` — labels, badges, storage status merge, relationship summaries.
- `backend/tests/test_project_structure_api.py` — API contract, validation, pagination, cross-project fail-closed.
- `backend/tests/test_project_structure_service.py` — transformation/storage-status unit tests.
- `backend/tests/integration/test_project_structure_real_neo4j.py` — real graph traversal and Case 6 regression.

### Backend files to modify
- `backend/app/services/file_store.py` — safe `inspect()` read-only presence check.
- `backend/app/main.py` — register the project-structure router and service/repository dependencies.
- `backend/tests/test_file_store.py` — FileStore presence/missing/traversal tests.
- `.github/workflows/remediation-ci.yml` — include the new real-Neo4j test if the existing integration glob does not already pick it up.

### Frontend files to create
- `frontend/src/api.project-structure.test.ts` — API client contract tests.
- `frontend/src/components/ProjectStructureExplorer.tsx` — state, lazy fetch, selection, refresh token.
- `frontend/src/components/ProjectStructureTree.tsx` — recursive tree rows and “more” pagination row.
- `frontend/src/components/ProjectStructureInspector.tsx` — selected node facts and graph relationship jump links.
- `frontend/src/components/ProjectStructureStatusBadge.tsx` — status badges.
- `frontend/src/components/ProjectStructureExplorer.test.tsx` — lazy loading/read-only/Case 6 UI tests.

### Frontend files to modify
- `frontend/src/api.ts` — types and project-structure fetch functions.
- `frontend/src/pages/ProjectDetailPage.tsx` — add `structure` view, refresh after upload/poll.
- `frontend/src/pages/ProjectDetailPage.test.tsx` — integration with upload and structure view.
- `frontend/src/styles.css` — tree/inspector layout and states.

---

### Task 1: Add safe FileStore presence inspection

**Files:**
- Modify: `backend/app/services/file_store.py`
- Test: `backend/tests/test_file_store.py`

**Interfaces:**
- Produces: `FileStore.inspect(uri: str) -> str`, returning exactly `"present"`, `"missing"`, or `"unknown"`.
- Constraint: never follows a symlink out of `DATA_ROOT`; never creates directories/files.

- [ ] **Step 1: Write the failing tests**

Add tests equivalent to:

```python
def test_inspect_reports_present_for_stored_file(tmp_path):
    store = FileStore(tmp_path)
    stored = store.store_bytes(PROJECT_ID, "body.pdf", b"pdf", "application/pdf")
    assert store.inspect(stored.uri) == "present"


def test_inspect_reports_missing_without_mutating_storage(tmp_path):
    store = FileStore(tmp_path)
    assert store.inspect(f"incoming/{PROJECT_ID}/deadbeef/missing.pdf") == "missing"
    assert list(tmp_path.rglob("*")) == []


def test_inspect_rejects_path_escape_as_unknown(tmp_path):
    store = FileStore(tmp_path)
    assert store.inspect("../outside.pdf") == "unknown"
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
cd backend
pytest -q tests/test_file_store.py -k inspect
```

Expected: FAIL because `FileStore.inspect` does not exist.

- [ ] **Step 3: Implement the minimal safe method**

Use path components relative to `DATA_ROOT`, reject absolute paths, `..`, empty components, and symlink traversal. Do not call `_write_once()` or `_open_or_create_directory()`.

Target signature:

```python
def inspect(self, uri: str) -> str:
    ...
```

Return `unknown` for invalid/unsafe locators, `missing` for a valid in-root path that does not exist, and `present` only for a regular file opened without following symlinks.

- [ ] **Step 4: Run GREEN**

```bash
cd backend
pytest -q tests/test_file_store.py -k inspect
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/file_store.py backend/tests/test_file_store.py
git commit -m "feat(storage): expose read-only file presence"
```

---

### Task 2: Define the stable project-structure API contract

**Files:**
- Create: `backend/app/api/project_structure_contract.py`
- Test: `backend/tests/test_project_structure_service.py`

**Interfaces:**
- Produces `ProjectStructureNode`, `ProjectStructureRelationship`, `ProjectStructureRootResponse`, `ProjectStructureChildrenResponse`, and allow-listed `ProjectStructureNodeType`.
- `sourceSystem` values: `neo4j`, `file_store`, `derived_group`, `reference`.

- [ ] **Step 1: Write contract tests**

Test representative serialization:

```python
def test_structure_node_serializes_archaeologist_and_graph_fields():
    node = ProjectStructureNode(
        id="version-1",
        node_type="document_version",
        label="3차교정본.pdf",
        subtitle="본문 · DocumentVersion",
        source_system="neo4j",
        status="completed",
        expandable=True,
        child_count=132,
        badges=["파일 존재", "ingest 완료", "Page 132"],
        details={"neo4jLabel": "DocumentVersion"},
        relationships=[],
    )
    payload = node.model_dump(by_alias=True)
    assert payload["nodeType"] == "document_version"
    assert payload["sourceSystem"] == "neo4j"
```

Also assert invalid arbitrary node types fail validation.

- [ ] **Step 2: Run RED**

```bash
cd backend
pytest -q tests/test_project_structure_service.py
```

Expected: import/definition failure.

- [ ] **Step 3: Implement Pydantic contract**

Define an explicit `Literal[...]` for supported node types. Do not accept arbitrary Neo4j labels from client input.

- [ ] **Step 4: Run GREEN**

```bash
cd backend
pytest -q tests/test_project_structure_service.py
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/project_structure_contract.py backend/tests/test_project_structure_service.py
git commit -m "feat(structure): define explorer API contract"
```

---

### Task 3: Build the project-scoped Neo4j read repository

**Files:**
- Create: `backend/app/graph/project_structure_repository.py`
- Test: `backend/tests/integration/test_project_structure_real_neo4j.py`

**Interfaces:**
- Produces:

```python
class ProjectStructureRepository:
    def get_root_summary(self, project_id: str) -> dict: ...
    def get_children(
        self,
        project_id: str,
        node_type: str,
        node_id: str,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[dict], int]: ...
    def get_node_detail(self, project_id: str, node_type: str, node_id: str) -> dict | None: ...
```

- Every query starts from `MATCH (project:Project {id:$project_id})` and proves the requested node belongs to that project.

- [ ] **Step 1: Add real-Neo4j fixture and failing root test**

Fixture must create one project with:
- one logical `Document` for each kind: `report_body`, `plate_book`, `drawing_book`
- body versions v1 and v2
- plate version p1 with `Plate 45`, `PlatePanel`
- drawing version d1 with `Drawing 30`, `DrawingRegion`
- one `Reference(type=plate, number=45)-[:RESOLVES_TO]->Plate 45`
- one unresolved `Reference(type=plate, number=91)`
- at least one `ArchaeologyObject`
- two ReviewRounds where round 2 reuses p1/d1

Root test:

```python
def test_root_summary_counts_materials_rounds_and_objects(real_repo):
    summary = real_repo.get_root_summary(PROJECT_ID)
    assert summary["document_version_counts"]["report_body"] == 2
    assert summary["document_version_counts"]["plate_book"] == 1
    assert summary["document_version_counts"]["drawing_book"] == 1
    assert summary["review_round_count"] == 2
    assert summary["archaeology_object_count"] >= 1
```

- [ ] **Step 2: Run RED**

```bash
cd backend
RUN_NEO4J_INTEGRATION=1 pytest -q tests/integration/test_project_structure_real_neo4j.py -s
```

Expected: missing repository.

- [ ] **Step 3: Implement root summary with count subqueries**

Avoid a large OPTIONAL MATCH cross product. Use separate scoped count subqueries or separate bounded queries.

- [ ] **Step 4: Add failing children tests**

Cover:
- material group -> Document
- Document -> DocumentVersions in creation order
- body version -> Page group and canonical child groups
- plate version -> Plate group -> Plate -> PlatePanel
- drawing version -> Drawing group -> Drawing -> DrawingRegion
- ReviewRound group -> rounds -> body/plate/drawing jump targets
- archaeology object group -> objects
- page -> Reference group

Also create project B with a node ID from project A and assert project B cannot fetch it.

- [ ] **Step 5: Implement allow-listed child query dispatch**

Use Python dispatch keyed by validated node type; do not interpolate arbitrary client labels into Cypher.

- [ ] **Step 6: Add node-detail relationship tests**

For `Reference 45`, assert detail contains exactly a `RESOLVES_TO` jump to canonical Plate 45. For Plate 45, assert reverse reference relationship and any `DEPICTS` relationship actually present in graph.

- [ ] **Step 7: Add Case 6 filename trap regression**

Create a decoy OriginalAsset/source record named `4. 조사 후_45.JPG` and another `_91.JPG`. Assert:

```python
ref45 = repo.get_node_detail(PROJECT_ID, "reference", REF45_ID)
assert [r["target_id"] for r in ref45["relationships"] if r["type"] == "RESOLVES_TO"] == [PLATE45_ID]

ref91 = repo.get_node_detail(PROJECT_ID, "reference", REF91_ID)
assert not [r for r in ref91["relationships"] if r["type"] == "RESOLVES_TO"]
```

The filenames must not appear as the reason for resolution.

- [ ] **Step 8: Run GREEN**

```bash
cd backend
RUN_NEO4J_INTEGRATION=1 pytest -q tests/integration/test_project_structure_real_neo4j.py -s
```

- [ ] **Step 9: Commit**

```bash
git add backend/app/graph/project_structure_repository.py backend/tests/integration/test_project_structure_real_neo4j.py
git commit -m "feat(graph): expose project structure read model"
```

---

### Task 4: Merge graph facts with FileStore state in a service

**Files:**
- Create: `backend/app/services/project_structure_service.py`
- Modify: `backend/tests/test_project_structure_service.py`

**Interfaces:**
- Consumes: `ProjectStructureRepository`, `FileStore.inspect()`.
- Produces:

```python
class ProjectStructureService:
    def get_root(self, project_id: str) -> ProjectStructureRootResponse: ...
    def get_children(self, project_id: str, node_type: str, node_id: str, offset: int, limit: int) -> ProjectStructureChildrenResponse: ...
    def get_node(self, project_id: str, node_type: str, node_id: str) -> ProjectStructureNode | None: ...
```

- [ ] **Step 1: Write failing service tests**

Mock repository rows for a DocumentVersion with `uri`, `sha256`, ingest state, and page counts. Assert badges are factual and separate:

```python
assert node.details["storageStatus"] == "present"
assert "파일 존재" in node.badges
assert "ingest 완료" in node.badges
assert "Page 132" in node.badges
```

Also test `missing` storage does not change the Neo4j/ingest status.

- [ ] **Step 2: Run RED**

```bash
cd backend
pytest -q tests/test_project_structure_service.py
```

- [ ] **Step 3: Implement minimal transformations**

Use Korean-friendly labels while preserving technical fields in `details`:
- `neo4jLabel`
- `neo4jId`
- `storageSystem`
- `storageUri`
- `storageStatus`
- `sha256`
- `ingestStatus`

Do not synthesize canonical children that are absent in graph.

- [ ] **Step 4: Run GREEN**

```bash
cd backend
pytest -q tests/test_project_structure_service.py
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/project_structure_service.py backend/tests/test_project_structure_service.py
git commit -m "feat(structure): combine graph and storage status"
```

---

### Task 5: Expose read-only root, children, and detail API

**Files:**
- Create: `backend/app/api/project_structure.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_project_structure_api.py`

**Interfaces:**
- `GET /api/projects/{project_id}/structure`
- `GET /api/projects/{project_id}/structure/nodes/{node_type}/{node_id}/children?offset=0&limit=50`
- `GET /api/projects/{project_id}/structure/nodes/{node_type}/{node_id}`

- [ ] **Step 1: Write failing API tests**

Required cases:

```python
def test_structure_root_is_read_only_and_returns_groups(client): ...
def test_structure_children_defaults_to_limit_50(client): ...
def test_structure_children_rejects_limit_over_100(client): ...
def test_structure_rejects_unknown_node_type(client): ...
def test_structure_cross_project_node_returns_404(client): ...
def test_structure_routes_have_only_get_methods(app): ...
```

The last test inspects application routes and proves no POST/PATCH/PUT/DELETE structure route exists.

- [ ] **Step 2: Run RED**

```bash
cd backend
pytest -q tests/test_project_structure_api.py
```

- [ ] **Step 3: Implement router and dependency setup**

Keep error responses aligned with existing project API conventions. Register the router in `create_app()`.

Do not modify `/api/v1/projects/{project_id}/runs` or its request contract in this task.

- [ ] **Step 4: Run GREEN**

```bash
cd backend
pytest -q tests/test_project_structure_api.py tests/test_project_structure_service.py
```

- [ ] **Step 5: Run backend regression slice**

```bash
cd backend
pytest -q tests --ignore=tests/integration --ignore=tests/test_real_neo4j_remediation.py --ignore=tests/test_project_repository.py
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/project_structure.py backend/app/main.py backend/tests/test_project_structure_api.py
git commit -m "feat(api): add read-only project structure endpoints"
```

---

### Task 6: Add frontend API client and typed lazy-node cache

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/api.project-structure.test.ts`

**Interfaces:**
- Produces TypeScript types mirroring backend aliases:

```ts
export type ProjectStructureNode = {
  id: string;
  nodeType: string;
  label: string;
  subtitle?: string | null;
  sourceSystem: 'neo4j' | 'file_store' | 'derived_group' | 'reference';
  status?: string | null;
  expandable: boolean;
  childCount: number;
  badges: string[];
  details: Record<string, unknown>;
  relationships: ProjectStructureRelationship[];
};
```

Functions:

```ts
fetchProjectStructure(projectId: string): Promise<ProjectStructureRootResponse>
fetchProjectStructureChildren(projectId: string, nodeType: string, nodeId: string, offset?: number, limit?: number): Promise<ProjectStructureChildrenResponse>
fetchProjectStructureNode(projectId: string, nodeType: string, nodeId: string): Promise<ProjectStructureNode>
```

- [ ] **Step 1: Write failing fetch tests**

Mock `fetch` and assert correct URL encoding and camelCase payload usage.

- [ ] **Step 2: Run RED**

```bash
cd frontend
npm test -- --run src/api.project-structure.test.ts
```

- [ ] **Step 3: Implement typed client**

Do not infer missing relationships in the client.

- [ ] **Step 4: Run GREEN and typecheck**

```bash
cd frontend
npm test -- --run src/api.project-structure.test.ts
npm run typecheck
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/api.project-structure.test.ts
git commit -m "feat(frontend): add project structure API client"
```

---

### Task 7: Build the lazy read-only tree and inspector

**Files:**
- Create: `frontend/src/components/ProjectStructureExplorer.tsx`
- Create: `frontend/src/components/ProjectStructureTree.tsx`
- Create: `frontend/src/components/ProjectStructureInspector.tsx`
- Create: `frontend/src/components/ProjectStructureStatusBadge.tsx`
- Create: `frontend/src/components/ProjectStructureExplorer.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- `ProjectStructureExplorer` props:

```ts
type Props = {
  projectId: string;
  refreshToken: number;
  onNavigateToVersion?: (versionId: string) => void;
};
```

- `refreshToken` change clears only affected cached root/branch data and refetches root; it does not reload the whole page.

- [ ] **Step 1: Write initial shallow-load RED test**

Mock root API and assert only project/material/round/object groups render. Assert no children API call occurs until a row is expanded.

- [ ] **Step 2: Run RED**

```bash
cd frontend
npm test -- --run src/components/ProjectStructureExplorer.test.tsx
```

- [ ] **Step 3: Implement root and expand/collapse**

Use `aria-expanded`, keyboard-operable buttons, and a cache keyed by `${nodeType}:${id}`.

- [ ] **Step 4: Add RED test for one-branch lazy loading**

Expand `도판 / 사진`; assert exactly one children request for that group. Expanding `본문` must trigger a different request and preserve the first branch cache.

- [ ] **Step 5: Implement lazy child fetch + pagination**

When `hasMore` is true, render a `더 보기` row that requests the next offset and appends results without replacing existing children.

- [ ] **Step 6: Add RED inspector test**

Select a DocumentVersion and assert:
- `FileStore`
- storage URI
- SHA-256
- `DocumentVersion`
- ingest status
- actual graph count badges

Select `Reference: 도판 45` and assert inspector shows `RESOLVES_TO` and `【도판 45】` from API response.

- [ ] **Step 7: Implement inspector**

Render relationships as read-only jump buttons. No edit/delete/move/relink controls.

- [ ] **Step 8: Add explicit read-only regression**

```ts
expect(screen.queryByRole('button', { name: /삭제|이동|이름 변경|연결 수정/ })).not.toBeInTheDocument();
```

- [ ] **Step 9: Add Case 6 display regression**

Given a Reference 45 detail whose only `RESOLVES_TO` target is `【도판 45】` and details contain a decoy `_45.JPG`, assert the relationship panel labels canonical target as the resolution source and never labels `_45.JPG` as identity evidence.

- [ ] **Step 10: Run GREEN + typecheck**

```bash
cd frontend
npm test -- --run src/components/ProjectStructureExplorer.test.tsx
npm run typecheck
```

- [ ] **Step 11: Commit**

```bash
git add frontend/src/components/ProjectStructure*.tsx frontend/src/components/ProjectStructureExplorer.test.tsx frontend/src/styles.css
git commit -m "feat(frontend): add lazy project structure explorer"
```

---

### Task 8: Integrate the structure view into ProjectDetailPage and upload refresh

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.test.tsx`

**Interfaces:**
- Extend `TabType` to include `structure`.
- Add `structureRefreshToken` state.
- On each successful upload batch and terminal ingest poll, increment the token.

- [ ] **Step 1: Write RED integration test**

Render `ProjectDetailPage`, click `프로젝트 구조`, and assert `ProjectStructureExplorer` receives the current project ID.

- [ ] **Step 2: Add RED upload refresh test**

Mock one upload. After upload resolves, assert structure root is fetched again and the new DocumentVersion appears with `ingest queued` rather than optimistic Plate/Drawing children.

- [ ] **Step 3: Implement structure tab and conditional UI**

When `activeTab === 'structure'`:
- render `ProjectStructureExplorer`
- hide candidate-only filters/navigation
- leave upload and ReviewRound management visible above

When `activeTab` is `split` or `graph`, preserve current behavior.

- [ ] **Step 4: Implement refresh token**

Increment after `loadProject()` following upload and after polling reaches `completed`/`failed`.

- [ ] **Step 5: Run GREEN**

```bash
cd frontend
npm test -- --run src/pages/ProjectDetailPage.test.tsx src/components/ProjectStructureExplorer.test.tsx
npm run typecheck
npm run build
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.test.tsx
git commit -m "feat(frontend): integrate project structure view"
```

---

### Task 9: Full verification, CI coverage, and handoff evidence

**Files:**
- Modify if necessary: `.github/workflows/remediation-ci.yml`
- Create: `docs/superpowers/reviews/2026-08-18-project-structure-explorer-verification.md`

**Interfaces:**
- No product interface change; this task proves all acceptance gates.

- [ ] **Step 1: Confirm workflow picks up the new real-Neo4j test**

If `tests/integration` is already run recursively, make no workflow change. Otherwise add only `tests/integration/test_project_structure_real_neo4j.py` to the real Neo4j command.

- [ ] **Step 2: Run backend hermetic suite**

Use the official workflow command, but do not add new deselections for project-structure tests.

Expected: all new structure API/service/FileStore tests included and passing.

- [ ] **Step 3: Run Real Neo4j suite**

Expected evidence includes:
- body v1/v2
- plate 45/panel
- drawing 30/region
- ReviewRound reuse
- `Reference(45)-[:RESOLVES_TO]->Plate 45`
- unresolved Reference 91 despite `_91.JPG` decoy

- [ ] **Step 4: Run frontend gate**

```bash
cd frontend
npm run typecheck
npm test -- --run
npm run build
```

- [ ] **Step 5: Re-run strict ReviewRound run-contract negative tests**

Verify this feature did not weaken:

```text
missing reviewRoundId -> 422
reviewRoundId + legacy bodyVersionId/versionStage/*PdfPath -> 422
```

- [ ] **Step 6: Write verification handoff**

The handoff must require screenshots/API JSON for:
1. collapsed project tree
2. one body version expanded to Page/Reference
3. plate 45 expanded to panel
4. drawing 30 expanded to region
5. ReviewRound showing exact three version jump targets and reuse
6. DocumentVersion inspector showing FileStore + Neo4j + ingest states
7. Reference 45 inspector showing `RESOLVES_TO -> 【도판 45】`
8. `_45.JPG`/`_91.JPG` decoy filenames not establishing identity

Also record exact tested SHA and CI run ID.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/remediation-ci.yml docs/superpowers/reviews/2026-08-18-project-structure-explorer-verification.md
git commit -m "docs(review): hand off project structure verification"
```

---

## Plan self-review

### Spec coverage
- Read-only tree: Tasks 5, 7, 8.
- Click-to-expand/lazy loading: Tasks 3, 5, 7.
- FileStore + Neo4j + ingest state: Tasks 1, 4, 7.
- Body/plate/drawing hierarchy: Tasks 3, 7.
- ReviewRound membership/reuse: Tasks 3, 7, 9.
- ArchaeologyObject visibility: Tasks 3, 7.
- Canonical relationship audit: Tasks 3, 7, 9.
- Case 6 filename trap: Tasks 3, 7, 9.
- Project scoping/security: Tasks 3, 5.
- Pagination/performance: Tasks 3, 5, 7.
- Upload refresh: Task 8.
- No VLM dependency: Global constraints + Task 9.

### Placeholder scan
No `TBD`, `TODO`, “implement later”, or unspecified test steps are permitted in this plan.

### Type consistency
- Backend uses `offset`/`limit`; frontend uses the same pagination semantics.
- All client node types come from the backend allow-list.
- `FileStore.inspect()` always returns one of `present|missing|unknown`.
- The frontend never invents relationships absent from API responses.

## Execution dependency

Implement the strict ReviewRound run-contract remediation first or in a separate isolated execution branch. The Project Structure Explorer may read ReviewRound/DocumentVersion relationships, but it must not be used as a reason to reintroduce the legacy `/runs` compatibility path.
