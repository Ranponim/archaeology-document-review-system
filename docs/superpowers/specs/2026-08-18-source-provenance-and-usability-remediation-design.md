# Source Provenance and Usability Remediation Design

**Date:** 2026-08-18  
**Baseline:** `a6a54f282e22bdfc1d86b7e6f81a71f663d19269`  
**Branch:** `feature/source-provenance-remediation-20260818`  
**Status:** Approved design, pending implementation plan  
**Scope:** Four follow-up tasks from `SPEC-20260818-ARCH-01`, corrected to preserve canonical graph authority and strict source provenance.

## 1. Goals

This remediation makes the system easier for archaeologists to understand while preserving the core architecture:

1. Fix frontend visibility so project cards and secondary actions are readable without hover.
2. Complete project timestamp support and deterministic newest-first listing.
3. Replace UUID-first graph presentation with domain-semantic labels and Korean relationship descriptions.
4. Add a source-ingest layer for HWP/HWPX, AI, INDD, JPG/TIFF/PNG and `src/` folder bundles without allowing filenames to establish publication identity.

The Neo4j canonical graph remains authoritative. Source files are provenance inputs, not canonical publication identity.

## 2. Non-negotiable invariants

### 2.1 Canonical identity is never inferred from a filename

The following are forbidden as identity evidence:

- `4. 조사 후_45.JPG` -> Plate 45
- `도면30. 1지점 6호 석관묘.ai` -> Drawing 30
- `22 (1).jpg` -> Plate 22 / Panel 1
- any suffix, prefix, sequence number, folder name or filename token used by itself to create or resolve a canonical Plate, PlatePanel, Drawing or DrawingRegion.

Filenames may be retained as provenance metadata and displayed to users, but contribute zero authority to canonical identity.

### 2.2 Canonical publication nodes are established only from explicit content or existing graph identity

A canonical Plate / PlatePanel / Drawing / DrawingRegion may be established or linked only by one of these mechanisms:

1. An explicit printed identifier parsed from the publication artifact itself, e.g. `【도판 45】`, `도판 45`, `【도면 30】` inside a PDF-compatible source.
2. An existing canonical node already established in Neo4j and addressed by a provenance manifest entry that explicitly targets that node or publication identifier.
3. A human-verified mapping persisted as provenance evidence.

A provenance manifest can link a source asset to an existing canonical node, but must not silently create a canonical target from a filename-derived number.

### 2.3 Case 6 remains the regression sentinel

For body text containing `도판 45`, the deterministic identity path is:

```text
TextBlock/Caption
  -> Reference(ref_type=plate, number=45)
  -> RESOLVES_TO
  -> canonical Plate / PlatePanel
```

Only after that target is established may a source image be displayed as provenance when the graph contains an explicit provenance relationship from the canonical target to that source asset.

A file named `_45.JPG` with no provenanced mapping must remain unlinked and must never be selected as the canonical visual.

### 2.4 VLM acceptance remains HOLD

This remediation does not use VLM output as acceptance evidence. VLM may consume the resulting canonical/provenance graph later, but VLM reruns happen after deterministic identity and source provenance pass.

## 3. Architecture choice

### 3.1 Chosen approach: SourceBundle + OriginalAsset provenance layer

We introduce a provenance layer alongside, not inside, canonical publication identity.

```text
Project
├─ HAS_DOCUMENT -> Document -> HAS_VERSION -> DocumentVersion
│                                      └─ Page / Plate / Drawing / ...
│
└─ HAS_SOURCE_BUNDLE -> SourceBundle
      └─ CONTAINS -> OriginalAsset
            ├─ HWP/HWPX
            ├─ AI
            ├─ INDD
            ├─ JPG/JPEG
            ├─ PNG
            └─ TIFF

DocumentVersion -[:DERIVED_FROM]-> OriginalAsset
Plate/PlatePanel/Drawing/DrawingRegion -[:PROVENANCED_BY]-> OriginalAsset
```

`OriginalAsset` stores physical source facts. It does not imply a canonical identity.

### 3.2 Why not attach every source file directly as a DocumentVersion

DocumentVersion represents a reviewable publication/version input. A raw Links photograph, an INDD binary or an Illustrator source file can exist without being directly parseable or canonically identifiable. Treating every source file as a DocumentVersion would conflate storage with publication identity and recreate the filename trap.

### 3.3 Why not build full native INDD parsing now

Native INDD parsing is outside this batch. The system will store INDD as an OriginalAsset and support pairing it with exported publication PDF and explicit provenance manifest. This gives reliable provenance without pretending to understand the binary layout.

## 4. Data model

### 4.1 SourceBundle

A SourceBundle groups source materials imported together for one project.

Required properties:

- `id`
- `projectId`
- `label`
- `createdAt`
- `sourceRootName` when imported from a directory
- `status`: `indexed`, `partial`, or `failed`

Relationship:

```text
(Project)-[:HAS_SOURCE_BUNDLE]->(SourceBundle)
```

### 4.2 OriginalAsset

Required properties:

- `id`
- `projectId`
- `bundleId`
- `uri`
- `sha256`
- `sizeBytes`
- `mimeType`
- `originalName`
- `relativePath`
- `assetKind`: `body_source`, `drawing_source`, `layout_source`, `linked_photo`, `other_source`
- `parseStatus`: `not_applicable`, `pending`, `parsed`, `unsupported`, `failed`
- `canonicalLinkStatus`: `unlinked`, `linked`, `ambiguous`
- `createdAt`

Relationship:

```text
(SourceBundle)-[:CONTAINS]->(OriginalAsset)
```

The `originalName` and `relativePath` are provenance/display facts only.

### 4.3 Provenance relationship

Canonical nodes may point to OriginalAsset via:

```text
(canonical)-[:PROVENANCED_BY {
  method,
  evidence,
  verifiedAt,
  verifiedBy
}]->(OriginalAsset)
```

Allowed `method` values in this batch:

- `explicit_source_identifier`
- `manifest_mapping`
- `human_verified_mapping`

`filename_match` is explicitly forbidden.

### 4.4 Derived publication versions

When a source asset is converted/exported to a publication PDF represented by DocumentVersion:

```text
(DocumentVersion)-[:DERIVED_FROM]->(OriginalAsset)
```

This relation establishes provenance of bytes/workflow, not canonical plate/drawing identity.

## 5. Source import behavior

### 5.1 Import entry point

Add a deterministic `scripts/ingest_src_folder.py` entry point backed by reusable service code. The script receives:

- project ID
- source root path
- optional bundle label
- optional provenance manifest path

It indexes files into FileStore and Neo4j source nodes. It must be idempotent by project + SHA-256 + relative path semantics and fail closed on cross-project references.

No web directory upload UI is required in this batch; the reusable backend service is designed so an API/UI can be added later.

### 5.2 Supported source categories

Folder heuristics classify storage role only; they do not create publication identity:

- `본문 및 부록 (글)` -> `body_source`
- `환경 도면` -> `drawing_source`
- `.indd` -> `layout_source`
- `도판(사진들)/Links` -> `linked_photo`

Unrecognized supported files become `other_source`.

### 5.3 HWP/HWPX

HWP/HWPX are stored as OriginalAsset. This batch does not invent a native body parser if none exists. They may be connected to a later exported PDF by `DERIVED_FROM` when explicitly mapped.

### 5.4 Illustrator AI

FileStore already accepts `.ai`. The source import layer must distinguish two cases:

1. PDF-compatible AI can be opened by PyMuPDF and its internal page text contains an explicit drawing identifier. In that case existing DrawingParser identifier rules may parse the publication identifier and canonical drawing data can be persisted with `source_kind="drawing_ai"` and provenance to the OriginalAsset.
2. AI cannot be opened or no explicit internal identifier is found. Store the OriginalAsset and mark it `unlinked`; do not derive Drawing identity from filename.

A thumbnail/render cache may be generated only when the AI can be safely rendered.

### 5.5 INDD

Add `.indd` storage MIME support. INDD is stored as `layout_source` and marked `unsupported` for native parsing in this batch.

If exported plate PDF and a manifest are provided, canonical Plate/Panel identity comes from the publication PDF and the manifest may add provenance from those canonical nodes to specific Links assets.

### 5.6 Linked photos

JPG/JPEG/PNG/TIFF under Links are always stored as OriginalAsset. They remain `canonicalLinkStatus=unlinked` unless a provenance mapping explicitly resolves them to an existing canonical target.

### 5.7 Provenance manifest

Support an explicit UTF-8 JSON manifest with entries such as:

```json
{
  "version": 1,
  "mappings": [
    {
      "asset": "도판(사진들)/Links/4. 조사 후_45.JPG",
      "target": {
        "type": "PlatePanel",
        "plateNumber": "45",
        "panelIndex": 1
      },
      "method": "manifest_mapping"
    }
  ]
}
```

Important rule: the target descriptor is resolved against canonical graph nodes already established from publication content. If zero or multiple targets match, no `PROVENANCED_BY` relationship is created and the import reports unresolved/ambiguous status.

The asset filename is used only to locate the source file named by the manifest; the filename contents are not parsed for identity.

## 6. Project timestamps

### 6.1 Domain/API

Extend `Project` with nullable `created_at` and `updated_at` fields. Extend `ProjectResponse` and project detail response with `createdAt` and `updatedAt`.

### 6.2 Neo4j persistence

Project creation writes both `createdAt` and `updatedAt` using Neo4j `datetime()`.

Project structural mutations update `updatedAt`, including at minimum:

- adding DocumentVersion / source bundle
- creating ReviewRound
- approving ReviewRound

### 6.3 Listing order and legacy records

Project listing order:

1. projects with a timestamp first
2. `createdAt DESC`
3. stable tie breaker `name ASC`, `id ASC`
4. legacy projects with no timestamp last

The API returns timestamps as ISO strings. Frontend renders localized display text but does not change authoritative ordering.

## 7. Frontend visibility remediation

### 7.1 Shared styles

Add a real `.secondary-button` definition with readable base state. Hover only changes emphasis.

Add `.project-card-item`, title, metadata and action styles. Remove visibility-critical inline color/background styles from `ProjectsPage`.

### 7.2 Accessibility behavior

Project card content and actions must meet these rules:

- title and metadata visible without hover
- secondary actions visible without hover
- keyboard focus visible
- disabled state distinguishable without making text effectively invisible

### 7.3 Project timestamp display

Project cards show creation time when available. Missing timestamps show a neutral legacy label rather than a fake date.

## 8. Archaeologist-friendly graph presentation

### 8.1 Shared semantic presentation module

Create one frontend presentation helper used by `EvidenceGraphExplorer` and `ProjectStructureInspector`/tree labels where applicable.

Responsibilities:

- derive domain label from node type and meaningful properties
- localize known relationship names
- group common archaeological metadata for inspector display
- never use UUID/hash prefixes as normal labels

### 8.2 Label rules

Examples:

- ArchaeologyObject -> `[유구] 1지점 6호 석관묘 (청동기시대)`
- Plate -> `[도판 45] 1지점 6호 석관묘 조사 후 전경`
- PlatePanel -> `[도판 45 · 패널 1] 조사 후 전경`
- Drawing -> `[도면 30] 1지점 6호 석관묘 평·단면도`
- Reference -> `[본문 인용] 도판 45`
- TextBlock -> `[본문 단락] "…"`
- CorrectionCandidate -> `[교열 제안] <category or concise change>`
- OriginalAsset -> `[원천 사진] 4. 조사 후_45.JPG · canonical 미연결`

When meaningful fields are missing, use a semantic fallback such as `[도판] 식별 정보 없음`, never `id.slice(...)`.

### 8.3 Relationship labels

At minimum:

- `RESOLVES_TO` -> `인용 대상 연결`
- `MENTIONS` -> `유구 언급`
- `DEPICTS` -> `유구 실물 묘사`
- `ABOUT` -> `대상 유구`
- `SUPPORTED_BY` -> `근거`
- `EXTRACTED_FROM` -> `추출 위치`
- `FROM_VERSION` -> `문서 버전`
- `HAS_PANEL` -> `세부 사진 포함`
- `HAS_REGION` -> `도면 영역 포함`
- `PRECEDES` -> `이전 검수 버전`
- `PROVENANCED_BY` -> `원천 자료`
- `DERIVED_FROM` -> `원천에서 생성`

Unknown relationship names may be shown in a technical details area but should not dominate the main visualization.

### 8.4 Technical information disclosure

Internal IDs, SHA-256, storage URI and raw Neo4j labels remain available under a collapsed `기술 정보` section in the inspector. They are not used as primary node titles.

## 9. Project Structure Explorer extension

Add a sixth root group: `원천 자료`.

Example:

```text
산노리 프로젝트
├─ 본문
├─ 도판 / 사진
├─ 도면
├─ 원천 자료
│  └─ 2026-08-18 src import
│     ├─ 산노리 본문.hwp       저장됨 · canonical 변환 필요
│     ├─ 도면30....ai          저장됨 · 내부 식별자 확인
│     ├─ 산노리_도판.indd      저장됨 · native parse 미지원
│     └─ Links
│        └─ 조사 후_45.JPG     저장됨 · canonical 미연결
├─ 검수 세트
└─ 고고학 객체
```

The tree remains read-only and lazy-loaded. SourceBundle and OriginalAsset children are project-scoped and paginated.

## 10. Error handling and fail-closed rules

Source import must reject or safely report:

- path traversal and symlink escape
- unsupported extensions
- unreadable files
- manifest path referencing a file outside the source root
- manifest target belonging to another project
- missing canonical target
- ambiguous canonical target
- duplicate/conflicting mappings for one asset

No error path may fall back to filename inference.

A partially imported bundle may exist with `status=partial`, preserving successfully stored OriginalAssets plus per-asset errors.

## 11. TDD acceptance plan

Implementation is split into four vertical slices, each RED -> GREEN -> refactor.

### Slice 1: project timestamps

Required tests:

- Project domain/API returns `createdAt` and `updatedAt`
- create_project stores both timestamps
- list_projects returns newest-created first and legacy-null last
- project structural mutation updates `updatedAt`
- frontend displays timestamp without re-sorting contrary to backend order

### Slice 2: frontend visibility

Required tests:

- `.secondary-button` has explicit base-state text/background/border styling
- project card uses semantic classes rather than visibility-critical inline styles
- refresh/open actions are visible in base render
- existing project navigation behavior remains unchanged

### Slice 3: semantic graph presentation

Required tests:

- canonical graph node with meaningful metadata renders archaeologist label
- missing metadata renders semantic fallback, never UUID prefix
- candidate/object titles do not expose internal ID as primary title
- known edges render Korean labels
- technical information retains raw ID only in detail section
- Project Structure source/canonical labels use the same helper semantics where applicable

### Slice 4: SourceBundle / OriginalAsset provenance

Unit tests:

- supported source files stored and classified
- `.indd` accepted as OriginalAsset
- filename-only AI does not create Drawing
- explicit identifier inside PDF-compatible AI may create Drawing
- filename-only Links JPG does not link Plate/Panel
- manifest mapping resolves only an existing canonical target
- missing/ambiguous manifest target creates no provenance edge
- cross-project manifest target fails closed
- path traversal/symlink escape rejected

Real Neo4j tests:

- source bundle and assets are isolated per project
- `PROVENANCED_BY` relationship requires explicit evidence method
- Case 6: `Reference(plate,45)-[:RESOLVES_TO]->canonical target` remains authoritative
- decoy `_45.JPG` without mapping remains unlinked
- provenanced Links image becomes visible only after canonical target is already established

Project Structure API/frontend tests:

- root includes `원천 자료`
- source bundles lazy-load
- OriginalAsset shows storage/parse/link status
- no source asset label implies canonical identity when unlinked

## 12. CI gates

A final accepted HEAD must pass:

- backend hermetic suite
- Real Neo4j integration/E2E suite
- frontend typecheck
- frontend unit tests
- frontend production build
- strict ReviewRound `/runs` negative contract tests already established on the baseline
- new source provenance Case 6 regression tests

No test is deselected merely because it conflicts with this architecture. Obsolete tests must be rewritten to the new contract.

## 13. Out of scope

- full native INDD document-layout parsing
- filename-based auto-linking, even as a convenience mode
- VLM acceptance rerun
- automatic human approval of ambiguous source mappings
- write/edit/delete controls in Project Structure Explorer
- arbitrary source directory access from public web API

## 14. Completion criteria

This remediation is complete when an archaeologist can:

1. see project cards and actions without hover;
2. see project creation time and newest projects first;
3. read graph nodes/relationships in archaeological language without needing UUIDs;
4. open Project Structure and see raw source materials separately from canonical publication assets;
5. distinguish `stored but unlinked` from `canonically provenanced` source assets;
6. inspect Case 6 and see that `도판 45 -> RESOLVES_TO -> canonical Plate/Panel` is established before any Links image is shown;
7. verify that a misleading `_45.JPG` filename alone cannot alter the result.
