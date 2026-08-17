# Project Structure Explorer Design

## Status
Approved direction from the user: **read-only**, **click-to-expand**, project-wide structure visualization for archaeologists. This feature supplements the candidate-centric `EvidenceGraphExplorer`; it does not replace it.

## Problem
The current UI can show uploaded documents and candidate-level evidence, but an archaeologist cannot easily answer these project-level questions:

- What source material has been uploaded to this project?
- Is each original file physically stored?
- Is the uploaded item represented in Neo4j?
- Has ingest/parsing completed, failed, or remained pending?
- How many pages, plates, plate panels, drawings, drawing regions, references, and archaeology objects were extracted?
- Which document versions are used by each ReviewRound?
- For a specific reference such as `도판 45`, what canonical graph relationship resolves it to the real Plate/Panel?

The project needs a read-only **Project Structure Explorer** that visualizes the storage and graph state incrementally as body documents, plate/photo material, and drawings are added.

## Goals
1. Give archaeologists a simple project-wide tree before exposing technical graph complexity.
2. Show original-file storage state, Neo4j persistence state, and ingest/extraction state together.
3. Update visibly when a new body, plate/photo, or drawing upload is added.
4. Let users expand only the branch they care about instead of loading the whole graph.
5. Keep Neo4j authoritative: tree nodes and relationships must come from backend/project-scoped graph queries, not client guesses.
6. Make ReviewRound membership understandable by showing exactly which body/plate/drawing DocumentVersions each round uses.
7. Make canonical reference resolution auditable, including Case 6-style `Reference(45) -> RESOLVES_TO -> 【도판 45】` paths.
8. Remain read-only: no delete, rename, move, version reassignment, ReviewRound mutation, or graph editing from this explorer.

## Non-goals
- No generic Neo4j browser clone.
- No force-directed full-project graph on first load.
- No write or admin operations.
- No filename-based inference of plate/drawing identity.
- No VLM execution or VLM acceptance logic.
- No loading thousands of TextBlocks/References into the browser in one response.

## 1. User-facing information architecture

The explorer has two coordinated areas:

1. **Left: lazy project tree** — simple hierarchy for understanding.
2. **Right: selected-node inspector** — storage details, Neo4j labels/relationships, counts, IDs, and jump links.

A project starts collapsed:

```text
Project: 논산 산노리
├─ 자료
│  ├─ 본문
│  ├─ 도판 / 사진
│  └─ 도면
├─ 검수 세트 (ReviewRounds)
└─ 고고학 객체
```

The three material groups show summary badges immediately, for example:

```text
본문          파일 3  · ingest 완료 3  · pages 396
도판 / 사진  파일 2  · plates 89     · panels 214
도면          파일 1  · drawings 59   · regions 127
```

The groups are explanatory UI grouping nodes. They are explicitly marked `sourceSystem=derived_group` so they are never confused with persisted Neo4j nodes.

## 2. Lazy hierarchy

### 2.1 Body (`report_body`)

```text
본문
└─ Document
   ├─ DocumentVersion: 2차교정본.pdf
   │  ├─ 페이지 (132)
   │  │  └─ Page 78
   │  │     ├─ 본문 블록 (N)
   │  │     ├─ 캡션 (N)
   │  │     └─ 참조 (N)
   │  │        └─ Reference: 도판 45
   │  └─ 추출 상태
   └─ DocumentVersion: 3차교정본.pdf
```

A Page branch is only expanded on demand. Large TextBlock/Caption/Reference collections are paginated.

### 2.2 Plate/photo (`plate_book`)

```text
도판 / 사진
└─ Document
   └─ DocumentVersion: 도판집.pdf
      ├─ 페이지 (N)
      └─ 표준 도판 (89)
         └─ 【도판 45】
            └─ 패널 (N)
               └─ PlatePanel 1
```

The canonical plate identifier comes from persisted Plate properties (`raw_identifier`, `number`) and graph identity, never from a source filename suffix.

### 2.3 Drawing (`drawing_book`)

```text
도면
└─ Document
   └─ DocumentVersion: 도면집.pdf
      ├─ 페이지 (N)
      └─ 표준 도면 (59)
         └─ 【도면 30】
            └─ 영역 (N)
               └─ DrawingRegion 1
```

### 2.4 ReviewRounds

```text
검수 세트
├─ Round #1
│  ├─ 본문 → body v1
│  ├─ 도판 → plate v1
│  └─ 도면 → drawing v1
├─ Round #2
│  ├─ 본문 → body v2
│  ├─ 도판 → plate v1 (재사용)
│  └─ 도면 → drawing v1 (재사용)
└─ Round #3 ...
```

Version rows under a ReviewRound are **reference/jump nodes**, not duplicated ownership. Clicking one selects the canonical DocumentVersion node in the material tree. ReviewRound `PRECEDES` lineage is shown in the inspector.

### 2.5 Archaeology objects

```text
고고학 객체
└─ ArchaeologyObject (N)
   └─ 1지점 청동기 6호 석관묘
```

Object branches remain shallow. `MENTIONS` and `DEPICTS` are shown as relationships in the right inspector rather than recursively nesting every source/asset, which prevents cycles and duplicated branches.

## 3. Selected-node inspector

The right-hand inspector translates system internals into archaeologist-readable facts while preserving technical evidence.

### DocumentVersion example

```text
파일
  이름: 3차교정본.pdf
  저장소: FileStore
  저장 URI: incoming/<project>/<sha256>/3차교정본.pdf
  파일 상태: 존재
  SHA-256: ...
  크기: ...
  MIME: application/pdf

Neo4j
  Node: DocumentVersion
  ID: ...
  관계: Project-HAS_DOCUMENT->Document-HAS_VERSION->DocumentVersion

처리 상태
  ingest: completed
  pageCount: 132
  textExtractable: true
  Page: 132
  TextBlock: ...
  Caption: ...
  Reference: ...
```

### Plate example

```text
표준 식별자: 【도판 45】
Neo4j Node: Plate
소유 버전: plate DocumentVersion ...
물리 PDF 페이지: 78
패널: 2

연결 관계
  Reference(ref_type=plate, number=45) -RESOLVES_TO-> this Plate
  this Plate -DEPICTS-> ArchaeologyObject ...
```

Cross-relationships are shown here as clickable jump links. The explorer does not convert the graph into a recursive tree because that would produce cycles and duplicate nodes.

## 4. Storage and processing status

The explorer reports factual states separately rather than inventing one misleading all-purpose status.

### File storage
- `present`: FileStore URI is recorded and the file exists below `DATA_ROOT`.
- `missing`: URI is recorded but the file no longer exists.
- `unknown`: storage presence cannot be safely checked.

The UI displays the stored SHA-256 but does **not** recompute the entire file hash on every tree refresh. Integrity re-hashing is outside this feature.

### Ingest
Use the real AnalysisRun state associated with the upload:
- queued
- running
- completed
- failed
- cancelled

### Graph materialization
Display actual counts rather than a guessed pass/fail:
- body: Page, TextBlock, Caption, Reference
- plate/photo: Page, Plate, PlatePanel
- drawing: Page, Drawing, DrawingRegion
- project-wide: ArchaeologyObject, resolved/unresolved Reference counts, ReviewRound count

This distinction lets an archaeologist see cases such as “file stored, ingest failed” or “ingest completed, but no Plate nodes extracted.”

## 5. Backend architecture

### 5.1 `ProjectStructureRepository`
Create a focused read-only repository rather than growing `ProjectRepository` further.

Responsibilities:
- project-scoped root summaries
- child lookup by supported node type
- aggregate counts
- ReviewRound membership and lineage
- canonical relationship summaries for selected nodes

Every query must be anchored to the requested Project. A raw global node ID is never sufficient to retrieve children.

### 5.2 `ProjectStructureService`
Combines graph information with FileStore presence information.

Responsibilities:
- convert graph rows into stable API tree nodes
- inspect DocumentVersion storage status through FileStore
- calculate archaeologist-readable labels/status badges
- preserve Neo4j relationship names in the inspector payload
- never infer Plate/Drawing identity from filenames

### 5.3 FileStore read-only inspection
Add a safe read-only inspection method, conceptually:

```python
inspect(uri) -> present | missing | unknown
```

It must resolve only inside `DATA_ROOT`, refuse traversal/symlink escapes, and must not mutate storage.

## 6. API contract

### Root

`GET /api/projects/{project_id}/structure`

Returns:
- Project root node
- first-level material groups
- ReviewRound group
- ArchaeologyObject group
- aggregate counts/statuses

### Lazy children

`GET /api/projects/{project_id}/structure/nodes/{node_type}/{node_id}/children?cursor=...&limit=50`

Supported node types are allow-listed, e.g.:
- material_group
- document
- document_version
- page_group
- page
- textblock_group
- caption_group
- reference_group
- plate_group
- plate
- panel_group
- drawing_group
- drawing
- region_group
- review_round_group
- review_round
- archaeology_object_group

No arbitrary Cypher/label input is accepted from the client.

### Node details

`GET /api/projects/{project_id}/structure/nodes/{node_type}/{node_id}`

Returns node facts plus project-scoped relationship summaries/jump targets.

### Stable node response

```json
{
  "id": "...",
  "nodeType": "document_version",
  "label": "3차교정본.pdf",
  "subtitle": "본문 · DocumentVersion",
  "sourceSystem": "neo4j",
  "status": "completed",
  "expandable": true,
  "childCount": 132,
  "badges": ["파일 존재", "ingest 완료", "Page 132"],
  "details": {
    "neo4jLabel": "DocumentVersion",
    "storageSystem": "FileStore",
    "storageUri": "incoming/...",
    "sha256": "..."
  },
  "relationships": []
}
```

The API, not the frontend, owns the meaning of persisted relationships and storage state.

## 7. Pagination and performance

The explorer must never fetch the entire project graph on first load.

Rules:
- root response contains summaries and shallow groups only
- children default to 50 items
- large groups return a cursor / `hasMore`
- expanding one Page loads only that Page's child groups/counts
- expanding References/TextBlocks loads that collection only
- aggregate queries use project/version-scoped counts and avoid cartesian-product explosions

Target UX: the initial structure view should remain fast even for 100+ page reports and hundreds of plate panels.

## 8. Frontend architecture

Add `ProjectStructureExplorer` as a new read-only project-level view.

Suggested components:
- `ProjectStructureExplorer.tsx` — state, lazy loading, selection
- `ProjectStructureTree.tsx` — recursive rows, expand/collapse, pagination row
- `ProjectStructureInspector.tsx` — node facts and graph relationships
- `ProjectStructureStatusBadge.tsx` — consistent file/ingest/graph status rendering

Add a `structure` tab to `ProjectDetailPage` alongside the existing review/evidence views.

The existing `EvidenceGraphExplorer` remains candidate-centric and unchanged in responsibility.

## 9. Upload refresh behavior

When an upload succeeds:
1. the normal upload API creates FileStore bytes + DocumentVersion + ingest AnalysisRun
2. the structure cache/state is invalidated
3. the relevant material branch (`본문`, `도판/사진`, or `도면`) refreshes
4. the new DocumentVersion appears immediately with its factual current state, e.g. `파일 존재 · ingest queued`
5. existing project polling updates the status as ingest moves `queued -> running -> completed/failed`

No optimistic fake Plate/Drawing nodes are created in the browser. Derived nodes appear only after Neo4j contains them.

## 10. Archaeologist-friendly presentation

Primary labels use domain language, not database jargon:
- 본문
- 도판 / 사진
- 도면
- 페이지
- 표준 도판
- 표준 도면
- 검수 세트
- 고고학 객체

Technical names remain visible in the inspector for audit:
- `DocumentVersion`
- `HAS_VERSION`
- `HAS_PLATE`
- `HAS_PANEL`
- `HAS_DRAWING`
- `HAS_REGION`
- `REFERENCES`
- `RESOLVES_TO`
- `MENTIONS`
- `DEPICTS`
- `PRECEDES`

This gives archaeologists an understandable front layer while preserving exact graph evidence for developers/reviewers.

## 11. Case 6 audit use

The explorer must make the filename-trap scenario visually auditable.

Expected navigation:

```text
본문
 -> body DocumentVersion
 -> Page 78
 -> 참조
 -> Reference: 도판 45
```

Selecting the Reference must show:

```text
Reference(number=45)
  -RESOLVES_TO-> 【도판 45】 (Plate/PlatePanel)
```

The Plate inspector can then show provenanced render/source assets if such graph provenance exists. A file named `_45.JPG` is never shown as the reason the Reference resolved.

## 12. Testing strategy

### Backend hermetic
- root tree groups and counts
- DocumentVersion storage status mapping
- node-type allow-list rejects invalid types
- project ownership prevents cross-project node access
- pagination contract
- missing FileStore item is displayed as missing without mutating graph

### Real Neo4j
Construct one project with:
- 2 body DocumentVersions
- 1 plate DocumentVersion with Plates/Panels
- 1 drawing DocumentVersion with Drawings/Regions
- References, one resolved and one unresolved
- ArchaeologyObjects and DEPICTS/MENTIONS
- 2 ReviewRounds with plate/drawing reuse

Verify all lazy paths and exact relationship summaries.

### Case 6 regression
- Reference number 45 resolves only to canonical `【도판 45】`
- decoy source filename `_45.JPG` cannot create or repair identity
- unresolved Reference 91 remains unresolved even when `_91.JPG` exists

### Frontend
- initial tree is shallow
- clicking expands only requested branch
- storage + ingest + graph counts render
- new upload refresh adds one new version row
- node click shows details and relationships
- no mutation controls exist
- ReviewRound version jump selects the canonical version node
- Reference 45 detail displays `RESOLVES_TO` canonical target

## 13. Acceptance criteria

The feature is complete when an archaeologist can open one project and, without knowing Neo4j, answer:

1. Which body, plate/photo, and drawing files are stored?
2. Which versions exist for each material type?
3. Is the original file still present?
4. Is ingest queued/running/completed/failed?
5. How many pages/plates/panels/drawings/regions were extracted?
6. Which three versions form each ReviewRound?
7. What canonical Plate/Drawing does a Reference resolve to?
8. Which graph relationships support that answer?

And the implementation must prove:
- no whole-project eager graph load
- all node fetches are project-scoped
- no filename identity inference
- no write operations from the explorer
- the existing strict ReviewRound run contract remains unaffected
- external VLM remains HOLD and is not required for this explorer

## 14. Implementation order

1. Add backend read model + ProjectStructureRepository tests.
2. Add FileStore read-only presence inspection tests.
3. Add root/children/detail API contract tests.
4. Add Real Neo4j project-structure integration fixture/tests.
5. Add frontend API types/client tests.
6. Build lazy tree + inspector components with frontend tests.
7. Integrate `structure` tab and upload/poll refresh.
8. Add Case 6 visual audit regression to structure explorer tests.
9. Run backend hermetic, Real Neo4j, frontend typecheck/unit/build.
10. Add verification-agent handoff with screenshots/API/Neo4j evidence requirements.
