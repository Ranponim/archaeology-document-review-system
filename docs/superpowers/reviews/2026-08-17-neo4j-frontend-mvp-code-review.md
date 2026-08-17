# Archaeology Document Review System — Neo4j / Frontend MVP Code Review

**Review date:** 2026-08-17  
**Repository:** `Ranponim/archaeology-document-review-system`  
**Reviewed branch:** `windows-docker-foundation`  
**Reviewed HEAD:** `66d851adda8931f185d88392235550f0d00cdf56`  
**Purpose:** implementation handoff document for the next coding agent

---

## 1. Executive Summary

The implementation is materially better than the previous review. Neo4j is no longer used only as a passive result store: the code now persists canonical document/object/reference relationships, traverses them to build `ObjectEvidenceBundle`, and uses graph-derived evidence in RuleEngine / AI review paths. Real Neo4j integration tests also verify core relationships such as `REFERENCES`, `RESOLVES_TO`, `MENTIONS`, `DEPICTS`, `SUPPORTED_BY`, `EXTRACTED_FROM`, `FROM_VERSION`, `PRECEDES`, and `ALIGNED_TO`.

However, the system is **not yet a complete MVP for the original product goal**:

> Review archaeological report **text, photographs/plates, and drawings together**, compare them against canonical publication evidence, surface inconsistencies, and allow an expert to inspect the real source material and make an auditable decision.

The biggest remaining problems are not cosmetic. They are integration gaps between the selected `DocumentVersion`s, the production worker, the canonical graph, VLM inputs, and the frontend visual review experience.

### Current assessment

| Area | Score | Assessment |
|---|---:|---|
| Neo4j canonical graph structure | 8.5/10 | Strong improvement; real relationships exist |
| Real Neo4j integration tests | 9/10 | Good gate tests using real DB |
| Text proofreading / consistency | 7.5/10 | Mostly functional |
| Text ↔ plate/photo validation | 4.5/10 | Canonical identity improved, production connection still incomplete |
| Text ↔ drawing validation | 3/10 | Drawing identity exists, visual review incomplete |
| Case 6 regression safety | 9/10 | Filename-number trap is explicitly blocked |
| Project / upload frontend | 6/10 | Useful flow, but version-kind persistence bug exists |
| Candidate review frontend | 8/10 | Good expert decision workflow |
| Real document/photo/drawing split view | 2.5/10 | Still mostly metadata/text, not real visual comparison |
| Overall MVP readiness | ~6/10 | Architecture is on the right path but key integration gaps remain |

The highest priority is to ensure that **Neo4j is a required operational dependency of the proofreading flow**, not an optional side channel that can silently fall back to in-memory evidence.

---

# 2. Original Product Goal

The system exists to review large archaeological reports containing mixed content:

1. **Text / photo / drawing consistency**
2. **Typographical proofreading**
3. **Contextual correctness**
4. **Cross-checking drawings and photographs against report claims**
5. **Human expert final decision with full evidence provenance**

The intended canonical flow is:

```text
Document / DocumentVersion
        │
        ├─ Page
        │   ├─ TextBlock
        │   └─ Caption
        │       │
        │       ├─ MENTIONS ──────────────┐
        │       └─ REFERENCES             │
        │              │                  │
        │              ▼                  ▼
        │          Reference      ArchaeologyObject
        │              │                  ▲
        │       RESOLVES_TO               │ DEPICTS
        │              │                  │
        │        Plate / Drawing ─────────┘
        │         │           │
        │     PlatePanel   DrawingRegion
        │
        ▼
ObjectEvidenceBundle
        │
        ├─ RuleEngine
        ├─ LLM
        └─ VLM
             │
             ▼
CorrectionCandidate
        │
        ├─ ABOUT → ArchaeologyObject
        ├─ SUPPORTED_BY → Evidence
        │                   │
        │              EXTRACTED_FROM → Page
        │              FROM_VERSION → DocumentVersion
        │
        └─ HAS_DECISION → ReviewDecision
```

This graph is not only for visualization. It is intended to be the **canonical identity and evidence retrieval layer** that determines which text, plate, panel, drawing, and evidence belong together.

---

# 3. Important Domain Constraint from Archaeologist Feedback

The final MVP must never repeat the previous Case 6 failure.

## 3.1 The critical rule

**A numeric suffix in an InDesign `Links` filename is NOT a plate number.**

Example trap:

```text
4. 조사 후_45.JPG
```

The `45` above may have been created automatically by InDesign to avoid duplicate filenames and is not canonical evidence for `도판 45`.

Therefore this is forbidden:

```text
본문: 도판 45
  ↓
search filenames containing "45"
  ↓
4. 조사 후_45.JPG
  ↓
VLM
```

The correct canonical chain is:

```text
본문: "도판 45"
  ↓
Reference(type=plate, number=45)
  ↓
plate PDF explicit publication identifier
  ↓
【도판 45】
  ↓
Plate(number=45)
  ↓
PlatePanel 45-1 / 45-2 / ...
  ↓
render/crop real panel image
  ↓
VLM
```

Do **not** assume physical PDF page number equals plate number. The parser must locate the canonical printed identifier `【도판 N】` and store physical page as separate provenance.

---

# 4. What Is Implemented Well

## 4.1 Neo4j is now genuinely used

The code now persists and queries the following real relationships:

```text
Project -[:HAS_DOCUMENT]-> Document
Document -[:HAS_VERSION]-> DocumentVersion
DocumentVersion -[:HAS_PAGE]-> Page
Page -[:HAS_BLOCK]-> TextBlock
Page -[:HAS_CAPTION]-> Caption
TextBlock/Caption -[:REFERENCES]-> Reference
Reference -[:RESOLVES_TO]-> Plate/PlatePanel/Drawing/DrawingRegion
TextBlock/Caption -[:MENTIONS]-> ArchaeologyObject
Plate/PlatePanel/Drawing/DrawingRegion -[:DEPICTS]-> ArchaeologyObject
CorrectionCandidate -[:ABOUT]-> ArchaeologyObject
CorrectionCandidate -[:SUPPORTED_BY]-> Evidence
Evidence -[:EXTRACTED_FROM]-> Page
Evidence -[:FROM_VERSION]-> DocumentVersion
CorrectionCandidate -[:HAS_DECISION]-> ReviewDecision
DocumentVersion -[:PRECEDES]-> DocumentVersion
Page -[:ALIGNED_TO]-> Page
```

`CanonicalRepository.get_object_evidence_bundle()` is especially important: it traverses Neo4j and reconstructs text claims, references, plate claims, drawing claims, VLM observations, and version claims from DB rows.

This is the correct architectural direction.

## 4.2 Real Neo4j integration tests are meaningful

The integration suite verifies the DB after real execution rather than only asserting mocked repository calls.

The existing tests cover:

- canonical body / plate graph
- Case 6 filename trap
- graph-driven consistency
- review traceability
- version graph

This is substantially better than FakeDriver-only tests.

## 4.3 Canonical `AssetMatcher.resolve_reference()` direction is correct

Plate references are resolved against explicit `PlateIndex` identity. Drawing references are resolved against explicit `DrawingIndex` identity.

The code explicitly states that filenames such as:

```text
4. 조사 후_45.JPG
_91.JPG
```

must never establish publication identity.

This is a major correction and must not be regressed.

## 4.4 Frontend expert review workflow is strong

The frontend already supports many useful expert-review functions:

- project list / open / create
- project restore via URL / localStorage
- upload kind selection (`report_body`, `plate_book`, `drawing_book`)
- upload stage selection (`1차`, `2차`, `3차`, `final`)
- proofreading run trigger
- VLM / AI switches
- candidate list
- filters and search
- previous / next candidate navigation
- candidate traceability retrieval
- expert decisions: `accepted`, `rejected`, `modified`, `deferred`
- review history
- evidence graph view
- metrics

The candidate-review interaction model is a good base for the final MVP.

---

# 5. P0 Findings — Must Fix Before Calling This MVP

---

## P0-1. Selected plate/drawing `DocumentVersion`s are not reliably used by the production proofreading run

### Current behavior

The frontend correctly sends:

```text
bodyVersionId
plateVersionId
drawingVersionId
```

The backend run endpoint persists those IDs.

The worker then resolves the **body version** into a real input / path, but does not equivalently resolve the selected plate and drawing versions into usable PDF paths or graph-reconstructed indexes before calling the orchestrator.

This can cause the orchestrator to enter:

```python
active_plate_index = PlateIndex()
active_drawing_index = DrawingIndex()
```

while still receiving non-null `plate_version_id` / `drawing_version_id` values.

### Why this is severe

The UI can show that the user selected:

```text
본문 3차
도판 3차
도면 3차
```

but the actual run may behave as:

```text
본문: available
도판: empty canonical index
도면: empty canonical index
```

This means the frontend selection is not yet a trustworthy execution contract.

### Required fix

Preferred solution: **reconstruct the canonical index from Neo4j using the selected version IDs**.

```text
plateVersionId
  ↓
MATCH (v:DocumentVersion {id})-[:HAS_PLATE]->(p:Plate)
OPTIONAL MATCH (p)-[:HAS_PANEL]->(panel)
  ↓
PlateIndex
```

```text
drawingVersionId
  ↓
MATCH (v:DocumentVersion {id})-[:HAS_DRAWING]->(d:Drawing)
OPTIONAL MATCH (d)-[:HAS_REGION]->(region)
  ↓
DrawingIndex
```

Fallback alternative: resolve `DocumentVersion.uri` and reparse the correct PDF.

The graph reconstruction approach is preferred because it reinforces Neo4j as the canonical operational data source.

### Acceptance criteria

- Given a body/plate/drawing run with three selected version IDs, the worker must resolve all three.
- The orchestrator must receive a non-empty canonical plate/drawing index when those documents were successfully ingested.
- Deleting `HAS_PLATE` / `HAS_DRAWING` relationships must break or block the corresponding validation in production mode.
- The worker must never silently treat a selected canonical asset version as an empty index.

---

## P0-2. Neo4j is still optional because production analysis can fall back to in-memory evidence

### Current behavior

The orchestrator queries graph evidence first, which is correct.

But when graph evidence retrieval fails or returns empty data, it records a warning and falls back to in-memory evidence.

Therefore this is still possible:

```text
Neo4j evidence path broken
    ↓
warning
    ↓
in-memory RuleEngine / LLM
    ↓
Candidate generated
    ↓
AnalysisRun completed
```

### Why this violates the design

The product requirement is not merely "store results in Neo4j".

The requirement is:

> The canonical Document–Object–Evidence graph must be a **core dependency of identity and evidence resolution**.

If the production result can be produced with the graph broken, Neo4j is still not truly mandatory.

### Required fix

Introduce an explicit mode:

```python
allow_degraded_mode = False  # production default
```

Production behavior:

```text
Graph DB unavailable
→ AnalysisRun failed

Required object graph bundle missing
→ unresolved / manual_review
→ do not execute semantic consistency check for that object

Required canonical relation missing
→ fail closed, never substitute a guessed relationship
```

Degraded fallback may exist only in local development or specific tests.

### Mandatory kill-switch test

Create a test that:

1. ingests valid body / plate / object graph
2. verifies analysis produces a specific candidate
3. deletes one load-bearing relationship such as:
   - `MENTIONS`
   - `RESOLVES_TO`
   - `DEPICTS`
4. runs production-mode analysis again
5. verifies the candidate is not normally produced and the run becomes failed/unresolved/manual-review as designed

A test that only checks node counts is insufficient.

---

## P0-3. VLM review is not yet truly comparing body claims against the image

### Current behavior

`AssetReviewPipeline.review_canonical_reference()` supports:

```text
expected_feature
expected_site
claims
```

But the orchestrator currently invokes it without supplying the body/object claim bundle.

As a result, the pipeline may derive its expected feature primarily from the plate panel caption/title itself.

This means the semantic comparison is closer to:

```text
PlatePanel caption/title
        ↕
actual panel image
```

than the intended:

```text
body/object claims
        ↕
actual panel image
```

### Required fix

Build VLM input from `ObjectEvidenceBundle`, not only from the canonical asset metadata.

Example:

```text
ArchaeologyObject
  canonical_name: 1지점 청동기시대 6호 석관묘

text_claims:
  - 동벽 세부...
  - 토층 A-A'...
  - 유물 출토 상태...

reference:
  - 도판 45

plate_claim:
  - 【도판 45】
  - ③ 토층 A-A'
  - ④ 동벽 세부
```

Then VLM should answer per claim:

```text
SUPPORTED
PARTIAL
CONTRADICTED
INSUFFICIENT_EVIDENCE
```

Do not reduce the result to a vague boolean `is_match`.

### Acceptance criteria

- The VLM prompt must include body claims derived from graph evidence.
- The VLM target must be canonically resolved before the VLM is called.
- VLM must never establish identity.
- A wrong or missing canonical mapping must stop the VLM call.
- VLM result remains `pending_review`; never auto-accept.

---

## P0-4. Drawing parsing exists, but drawing visual validation is incomplete

### Current behavior

`DrawingParser` can create:

```text
Drawing
DrawingRegion
```

from explicit identifiers such as `【도면 30】`.

However it does not yet provide the same visual pipeline as `PlateParser`:

```text
high-resolution page render
region bbox
render_uri
cropped region PNG
```

Therefore text ↔ drawing identity/caption checks are possible, but full visual VLM comparison is not.

### Required fix

Implement a drawing visual path parallel to plates:

```text
Drawing PDF
  ↓
explicit drawing identifier
  ↓
Drawing
  ↓
DrawingRegion
  ↓
page render
  ↓
region bbox
  ↓
crop PNG
  ↓
VLM
```

For AI/EPS/DWG/DXF source files, do not send original vector bytes pretending they are JPEG/PNG. Convert/render to raster first or mark `INSUFFICIENT_EVIDENCE / conversion_error`.

### Acceptance criteria

- Drawing evidence has a real renderable image.
- `DrawingRegion` can carry `bbox`, `render_uri`, `source_sha256`.
- VLM can compare graph-derived body claims against actual drawing regions.
- Unsupported vector inputs fail closed instead of being mislabeled.

---

## P0-5. Proofreading `AnalysisRun` status querying is structurally inconsistent

### Current graph patterns

Ingest runs are attached through:

```text
AnalysisRun -[:ANALYZES]-> DocumentVersion
```

Proofreading runs are attached through:

```text
Project -[:HAS_RUN]-> AnalysisRun
```

But `ProjectRepository.get_project()` primarily obtains runs through the `ANALYZES` relation associated with document versions.

The frontend polls `getProject()` and expects to find the new proofreading run ID.

This can break real-time status updates for proofreading runs.

### Required graph model

Use a consistent run model:

```text
(Project)-[:HAS_RUN]->(AnalysisRun)
(AnalysisRun)-[:ANALYZES]->(bodyVersion)
(AnalysisRun)-[:USES_PLATE]->(plateVersion)
(AnalysisRun)-[:USES_DRAWING]->(drawingVersion)
```

Project run listing should use:

```cypher
MATCH (p:Project)-[:HAS_RUN]->(run:AnalysisRun)
```

and optionally traverse input versions.

### Acceptance criteria

- A run returned by `POST /runs` must appear in `GET /api/projects/{id}` immediately.
- `queued → running → completed/failed` must be observable by frontend polling.
- Selected body/plate/drawing versions must be inspectable from the run graph.

---

## P0-6. Frontend loses document kind after reload

### Current backend response

Backend project detail already returns both:

```text
documents[]
documentVersions[]
```

`Document` contains the canonical `kind`:

```text
report_body
plate_book
drawing_book
```

### Current frontend issue

Frontend `ProjectDetail` does not retain `documents[]` and instead keeps an optional `DocumentVersion.kind` that is assigned locally only immediately after upload.

After a page reload, that local `kind` is lost.

The frontend then treats `kind === undefined` as `report_body`, causing plate/drawing versions to disappear from the correct selectors or be treated as body versions.

### Required fix

Either:

**Option A — recommended frontend mapping**

```text
Document.id -> Document.kind
DocumentVersion.documentId -> Document.id
```

or:

**Option B — backend convenience field**

Add `kind` directly to `DocumentVersionResponse`.

### Acceptance criteria

After full browser reload:

- body versions remain body versions
- plate versions remain plate versions
- drawing versions remain drawing versions
- run selector lists remain correct

---

# 6. Additional Functional Bugs

## 6.1 Selected body stage may be sent incorrectly as `1차`

The run trigger selects a body `DocumentVersion`, but the frontend does not always send the selected version's actual `stage`.

The API wrapper defaults:

```text
version_stage = 1차
```

Therefore selecting a 3차 version can produce:

```text
bodyVersionId = <3차 uuid>
versionStage = 1차
```

which conflicts with backend authoritative version resolution.

### Fix

Send:

```typescript
version_stage: selectedBodyVersion.stage
```

### Test

- upload 1차, 2차, 3차 body versions
- select 3차
- verify request contains `version_stage=3차`
- verify backend resolves the same ID and stage

---

## 6.2 Frontend category filters do not match backend rule categories

Frontend currently exposes categories such as:

```text
plate_reference
drawing_reference
dimension_unit
typo
```

Backend `RuleCategory` values are:

```text
figure_plate_table_photo_ref
annotation_resolution
feature_or_artifact_id
numeric_value
site_or_area_name
direction_period_term
```

The filter must use backend canonical values while displaying user-friendly Korean labels.

Example:

```text
UI label: "도판/도면 참조"
API value: figure_plate_table_photo_ref
```

---

## 6.3 Severity filter is accepted by API but not applied in repository query

The route accepts a `severity` parameter, but the repository query must actually filter `cand.severity`.

Either implement it fully or remove it from the frontend until supported.

Do not present a filter that silently does nothing.

---

## 6.4 Backend retry exists but frontend does not expose it

Backend already provides an ingest retry endpoint.

Frontend should display for retryable failures:

```text
FAILED
error: ...
[재시도]
```

This is especially important for large PDF processing where infrastructure errors are realistic.

---

# 7. Neo4j Graph Semantics Review

## 7.1 Good graph responsibilities

Neo4j should own:

1. canonical identity
2. document/version lineage
3. object identity
4. text/reference/visual relationships
5. evidence provenance
6. candidate provenance
7. expert decision history

The current code is moving correctly in this direction.

## 7.2 `PRECEDES` must mean semantic stage order, not upload order

A remaining graph semantic risk exists if repository upload order creates:

```text
previous upload -[:PRECEDES]-> new upload
```

without checking stage meaning.

Example:

```text
user uploads 3차 first
user uploads 1차 later
```

The graph must **not** become:

```text
3차 → PRECEDES → 1차
```

`PRECEDES` must represent semantic version progression:

```text
1차 → 2차 → 3차 → final
```

not ingestion chronology.

### Required behavior

- upload timestamp should be stored separately
- lineage edges should be rebuilt/maintained by `stage`
- do not create contradictory `PRECEDES` edges

---

# 8. Frontend Product Review

The frontend is now useful for managing projects and reviewing candidate decisions, but the original product goal requires more than a candidate table.

The key missing UI capability is **real visual source comparison**.

---

## 8.1 Project Document Matrix — recommended

Instead of only a flat upload list, present documents by kind and stage:

```text
                 1차       2차       3차       최종
---------------------------------------------------
본문             ✅         ✅         ✅          -
도판              -          -         ✅          -
도면              -          -         ✅          -
```

Each cell should show:

```text
filename
page count
sha256 short hash
ingest status
graph status
```

Example:

```text
본문 3차
282 pages
Graph: READY
Objects: 147
References: 382
```

---

## 8.2 Analysis Readiness Panel — recommended

Before enabling `새 검수 실행`, show:

```text
검수 준비 상태

✅ 본문 3차      282 pages
✅ 도판 3차      106 plates / 487 panels
✅ 도면 3차      92 drawings / 214 regions
✅ canonical graph ready
⚠ unresolved references: 4

[검수 시작]
```

This prevents incorrect runs and makes graph ingest state visible to users.

The run button should be disabled if required inputs are selected but their canonical graph ingestion failed.

---

# 9. Real Split View — Required for MVP

The current `SplitViewInspector` mostly shows text and metadata.

The final MVP should show real source material.

## Required layout

```text
┌─────────────────────────────┬─────────────────────────────┐
│ 본문 PDF                    │ Canonical Plate / Photo     │
│                             │                             │
│ physical page 54            │ 【도판 45】                 │
│                             │                             │
│ [actual rendered page]      │ [actual panel image]        │
│                             │                             │
│ [source bbox highlight]     │ [panel bbox highlight]      │
│                             │                             │
│ selected text claim         │ panel caption               │
└─────────────────────────────┴─────────────────────────────┘

┌───────────────────────────────────────────────────────────┐
│ Canonical Drawing                                         │
│ [actual drawing render + region highlight]                │
└───────────────────────────────────────────────────────────┘

Rule finding
VLM finding
LLM finding

[승인] [반려] [수정 승인] [보류]
```

The user should be able to answer:

> "What exactly in the original report caused this candidate, and what exact photo/drawing is the system comparing it against?"

without opening external files manually.

---

# 10. Required Asset / Evidence API

The current review APIs return metadata but do not provide a complete visual asset delivery contract.

Recommended options:

```http
GET /api/v1/evidence/{evidence_id}/visual
```

or more explicit routes:

```http
GET /api/v1/assets/pages/{page_id}/render
GET /api/v1/assets/plates/{plate_id}/render
GET /api/v1/assets/plate-panels/{panel_id}/render
GET /api/v1/assets/drawings/{drawing_id}/render
GET /api/v1/assets/drawing-regions/{region_id}/render
```

Suggested response metadata:

```json
{
  "assetType": "plate_panel",
  "imageUrl": "/api/...",
  "documentVersionId": "...",
  "sourceSha256": "...",
  "physicalPage": 45,
  "printedIdentifier": "【도판 45】",
  "regionId": "...",
  "bbox": [0.1, 0.2, 0.8, 0.7],
  "caption": "③ 토층 A-A'"
}
```

Do not expose arbitrary filesystem paths to the browser.

---

# 11. Evidence Graph Frontend — Expand to Canonical Identity Path

The current graph explorer is improved because it no longer invents fake relationships. It visualizes candidate traceability relationships returned by the backend.

However, it mainly displays:

```text
Candidate
  ├─ ABOUT → ArchaeologyObject
  ├─ SUPPORTED_BY → Evidence
  │                   ├─ EXTRACTED_FROM → Page
  │                   └─ FROM_VERSION → DocumentVersion
  └─ HAS_DECISION → ReviewDecision
```

This is good provenance, but it does not expose the most important canonical identity path:

```text
TextBlock / Caption
     ↓ REFERENCES
Reference
     ↓ RESOLVES_TO
Plate / Drawing
     ↓ DEPICTS
ArchaeologyObject
```

The graph UI should be expanded so a reviewer can understand **why this particular image or drawing was chosen**.

Recommended candidate-centered graph:

```text
                      TextBlock p54
                           │
                     REFERENCES
                           ▼
Candidate ─ABOUT→ ArchaeologyObject
   │                       ▲
   │                       │ DEPICTS
   │                    Plate45
   │                       ▲
   │                 RESOLVES_TO
   │                       │
   │                   Reference45
   │
   └─SUPPORTED_BY→ Evidence → Page → DocumentVersion
```

This is the best frontend demonstration of why Neo4j is central to the product.

---

# 12. Backend ↔ Frontend Feature Coverage Matrix

| Capability | Backend | Frontend | Status |
|---|---|---|---|
| Create project | ✅ | ✅ | Good |
| List projects | ✅ | ✅ | Good |
| Restore project | API supports | ✅ URL/localStorage | Good |
| `internalCode` | ✅ | partial/no creation input | Improve |
| Upload body | ✅ | ✅ | Good |
| Upload plate | ✅ | ✅ | Reload bug |
| Upload drawing | ✅ | ✅ | Reload bug |
| Stages 1/2/3/final | ✅ | ✅ | Good |
| Ingest progress | ✅ | ✅ polling | Good |
| Retry ingest | ✅ | ❌ | Missing UI |
| Trigger proofreading | ✅ | ✅ | Integration bug |
| Select body version | ✅ | ✅ | stage bug |
| Select plate version | ✅ | ✅ | production worker gap |
| Select drawing version | ✅ | ✅ | production worker gap |
| Rule candidates | ✅ | ✅ | Good |
| VLM findings | partial | text only | Visual review incomplete |
| LLM findings | ✅ | ✅ | Good |
| Candidate search | partial API / client | ✅ | Good frontend-only feature |
| Prev/next candidate | — | ✅ | Good frontend-only feature |
| Status filter | ✅ | ✅ | Good |
| Category filter | ✅ | ⚠ values mismatch | Fix |
| Severity filter | API accepts | UI exists | Repository filter missing |
| Metrics | ✅ | partial display | Improve |
| Accept | ✅ | ✅ | Good |
| Reject | ✅ | ✅ | Good |
| Modify | ✅ | ✅ | Good |
| Defer | ✅ | ✅ | Good |
| Decision history | ✅ | ✅ | Good |
| Candidate provenance graph | ✅ | ✅ | Good |
| Canonical reference path | backend partial | ❌ | Important gap |
| Real body PDF viewer | missing/partial asset API | ❌ | Core gap |
| Real plate/photo viewer | render exists internally | ❌ | Core gap |
| Real drawing viewer | incomplete | ❌ | Core gap |
| BBox highlight | evidence data exists | ❌ visual highlight | Core gap |

---

# 13. Required Implementation Order

The next coding agent should **not** start with UI polish.

Follow this order.

---

## Phase P0-A — Fix execution input integrity

### Tasks

1. Resolve selected `plateVersionId` and `drawingVersionId` in worker.
2. Reconstruct `PlateIndex` / `DrawingIndex` from Neo4j or load exact selected files.
3. Fix frontend body `version_stage` payload.
4. Fix frontend `Document.kind` reload behavior.
5. Make proofreading runs visible in project polling.
6. Normalize AnalysisRun graph relations.

### Exit gate

A browser-selected body/plate/drawing tuple must exactly match the versions actually used by the worker.

---

## Phase P0-B — Make Neo4j mandatory

### Tasks

1. production `allow_degraded_mode=False`
2. no silent in-memory fallback
3. unresolved graph bundle blocks semantic checks
4. add graph dependency kill-switch tests
5. persist explicit failure/unresolved reasons

### Exit gate

Removing a load-bearing graph relationship must change or block analysis output.

---

## Phase P0-C — Complete semantic visual validation

### Tasks

1. build VLM claims from `ObjectEvidenceBundle`
2. pass body/object claims into VLM
3. fix VLM evidence provenance so it points to the actual visual `DocumentVersion`
4. drawing render + crop + region pipeline
5. normalize VLM result classes

### Required result classes

```text
MATCH / SUPPORTED
PARTIAL
MISMATCH / CONTRADICTED
INSUFFICIENT_EVIDENCE
```

### Exit gate

The VLM must compare the body claim to a canonically identified image/drawing, not merely compare an asset caption to itself.

---

## Phase P0-D — Build real expert visual review UI

### Tasks

1. evidence visual API
2. body page renderer
3. source bbox highlight
4. plate panel image viewer
5. drawing region viewer
6. synchronized evidence selection
7. canonical identity graph path
8. retry button and run readiness UI

### Exit gate

A reviewer can complete the candidate decision without manually opening source PDFs outside the system.

---

# 14. Case 6 Mandatory Regression Scenario

This must remain a permanent MVP regression test.

## Fixture

Body claim:

```text
1지점 청동기시대 6호 석관묘
도판 45·46
```

Canonical plate PDF contains:

```text
【도판 45】
1지점 청동기시대 6호 석관묘
① 조사 전
② 조사 중
③ 토층 A-A'
④ 동벽 세부
⑤ 유물 출토 상태
```

Links/original asset folder also contains the trap:

```text
4. 조사 후_45.JPG
```

where that file is unrelated to the canonical plate identity.

## Expected

```text
Reference(plate,45)
  ↓ RESOLVES_TO
Plate(raw_identifier="【도판 45】")
```

and never:

```text
Reference(plate,45)
  ↓
filename contains "45"
```

The trap filename must have **zero influence** on canonical identity.

If a real photo provenance relation is later added, it must be derived through publication/layout provenance, not filename-number coincidence.

---

# 15. Mandatory MVP Tests

The implementation should not be accepted based only on unit tests.

## Test A — Browser-selected versions are the actual worker inputs

```text
upload body 3차
upload plate 3차
upload drawing 3차
select all three in UI
trigger run
```

Assert in Neo4j:

```text
AnalysisRun → body 3차
AnalysisRun → plate 3차
AnalysisRun → drawing 3차
```

and assert the actual canonical Plate/Drawing indexes came from those versions.

---

## Test B — Neo4j kill-switch

1. run known-valid candidate path
2. remove `RESOLVES_TO`
3. rerun production mode
4. verify semantic visual result is not produced normally

Repeat with `MENTIONS` or `DEPICTS`.

---

## Test C — Case 6

Assert:

- `【도판 45】` establishes identity
- `_45.JPG` does not
- the canonical Plate/Panel is used
- VLM receives canonical visual bytes only

---

## Test D — Real split view source integrity

For one candidate, frontend/API must expose:

```text
source body page
source bbox
source sha256
canonical plate/drawing
canonical visual bbox
canonical visual sha256
```

The user must be able to see both images rendered.

---

## Test E — Decision traceability

After expert action:

```text
Candidate
  ↓ HAS_DECISION
ReviewDecision
```

Must preserve previous decision history and the evidence path back to real source pages / versions.

---

## Test F — Stage/order integrity

Upload versions out of order:

```text
3차
1차
2차
```

Final graph must still represent:

```text
1차 → PRECEDES → 2차 → PRECEDES → 3차
```

not upload chronology.

---

# 16. Anti-Patterns — Implementation Must Be Rejected If Any Appear

Do not accept an implementation that does any of the following:

1. Uses filename numeric suffix to establish plate/drawing identity.
2. Calls VLM before canonical reference resolution.
3. Uses physical PDF page number as plate number without reading `【도판 N】`.
4. Produces a normal completed analysis when required Neo4j evidence is unavailable.
5. Uses an empty `PlateIndex` / `DrawingIndex` while a version was explicitly selected.
6. Claims graph-backed analysis while Rule/LLM input came only from in-memory lists.
7. Shows a frontend "Graph" that invents relationships not returned from Neo4j.
8. Shows metadata-only split view and calls it document/photo/drawing comparison.
9. Sends AI/EPS/DWG/DXF bytes directly to VLM as if they were raster images.
10. Lets VLM convert `PARTIAL` into confirmed identity.
11. Auto-accepts correction candidates.
12. Creates `PRECEDES` from upload order instead of semantic stage order.
13. Exposes frontend filters that backend silently ignores.
14. Stores visual Evidence provenance against the body version when the evidence actually came from a plate/drawing version.
15. Allows page reload to change version kind classification.

---

# 17. Definition of Done for MVP

The project may be called a **Graph-based archaeological document/photo/drawing review MVP** only when all conditions below are true.

## Graph

- [ ] Neo4j contains real canonical document/object/reference/visual/evidence relationships.
- [ ] Production analysis depends on graph traversal.
- [ ] Graph failure does not silently degrade to normal success.
- [ ] Candidate provenance can be traversed to exact document version/page/evidence.
- [ ] Case 6 filename trap is permanently blocked.

## Text

- [ ] PDF parser stores page/text/caption provenance including bbox where available.
- [ ] RuleEngine can detect cross-document/object inconsistencies.
- [ ] LLM consumes graph-derived evidence.

## Photo / Plate

- [ ] `【도판 N】` is the canonical identifier.
- [ ] PlatePanel is extracted and rendered.
- [ ] VLM receives graph-derived body claims and canonical panel image.
- [ ] VLM returns structured observation classes.

## Drawing

- [ ] `【도면 N】` is the canonical identifier.
- [ ] DrawingRegion exists when applicable.
- [ ] drawing pages/regions are rendered to actual images.
- [ ] body claims can be visually compared against the drawing.

## Frontend

- [ ] Project can be created/opened/reloaded without losing document kinds.
- [ ] body/plate/drawing versions are explicitly selectable.
- [ ] selected versions exactly match worker inputs.
- [ ] real-time queued/running/completed/failed status is visible.
- [ ] failed retryable jobs can be retried.
- [ ] actual body page image is visible.
- [ ] actual plate/photo panel is visible.
- [ ] actual drawing region is visible.
- [ ] bbox highlight is visible.
- [ ] canonical graph identity path is visible.
- [ ] expert can accept/reject/modify/defer.
- [ ] decision history and evidence provenance remain auditable.

---

# 18. Final Recommendation

The implementation should **not be rewritten**. The core architecture is now good enough to continue.

The next work should focus on closing the connections around the existing canonical graph:

```text
Frontend selected versions
        ↓
AnalysisRun input graph
        ↓
Neo4j canonical Plate/Drawing/Object retrieval
        ↓
ObjectEvidenceBundle
        ↓
Rule / LLM / VLM
        ↓
CorrectionCandidate
        ↓
real visual Split View
        ↓
expert ReviewDecision
```

The most important principle for the next coding agent is:

> **Neo4j must not merely store the result. It must determine and supply the canonical evidence that the result depends on.**

And the most important user-facing principle is:

> **A reviewer must see the actual body page, actual plate/photo, and actual drawing used by the system, with highlighted provenance, before making the final decision.**

When these two principles are fully implemented, the system will finally match its original purpose rather than only demonstrating a pipeline or graph database.
