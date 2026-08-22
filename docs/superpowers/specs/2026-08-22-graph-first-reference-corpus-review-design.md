# Graph-First Reference Corpus Review Architecture

**Date:** 2026-08-22  
**Status:** Written design awaiting user review  
**Branch:** `feature/source-provenance-remediation-20260818`

## 1. Purpose

The system must treat archaeological visual sources as project reference data, not as proofreading PDFs.

- **Body**: the reviewed publication body is supplied as PDF and may change every review round.
- **Plates**: the authoritative source is Adobe InDesign (`.indd`) plus its placed Links assets.
- **Drawings**: the authoritative source is Adobe Illustrator (`.ai`).
- **Neo4j**: canonical graph identity and deterministic relationships are the primary review authority.
- **AI/VLM**: optional deep-review modules only. They must never create or mutate canonical identity.
- **Human reviewer**: final approval authority.

The system must complete its core review successfully with both AI and VLM disabled.

## 2. Top-Level Architecture

The product is split into two independently understandable pipelines.

### 2.1 Reference Corpus Build

```text
INDD + Links          AI files
     |                   |
     v                   v
OriginalAsset       OriginalAsset
     \                 /
      \               /
       Adobe Converter Agent
                |
        structured manifest
        + PDF/PNG/SVG render
                |
                v
       Deterministic Canonicalizer
                |
                v
          ReferenceCorpus
          /             \
       Plate           Drawing
         |                |
    PlatePanel      DrawingRegion
```

### 2.2 Body Review Runtime

```text
Body PDF
   |
DocumentVersion
   |
Page/TextBlock/Caption
   |
Reference + ArchaeologyObject
   |
   +------------------------------+
   |                              |
   v                              v
selected ReferenceCorpus      Graph Rule Engine
   |                              |
Plate/Drawing/Panel/Region         +--> deterministic finding
   |                              |
   +----- RESOLVES_TO/DEPICTS ----+--> semantic review required
                                      |
                                      v
                                 optional LLM/VLM
                                      |
                                      v
                                   human review
```

## 3. Architectural Invariants

1. **Canonical identity precedes AI.**
2. **Filenames never establish Plate, PlatePanel, Drawing, or DrawingRegion identity.**
3. **Explicit identifiers inside INDD/AI document structure may establish identity when unique and project/corpus scoped.**
4. **OriginalAsset stores provenance; it is not canonical publication identity.**
5. **Derived PDF/PNG/SVG files are render/evidence artifacts, not identity authorities.**
6. **READY ReferenceCorpus revisions are immutable.**
7. **ReviewRound is the sole public `/runs` input authority.**
8. **Graph ambiguity fails closed. AI must not choose among ambiguous canonical identities.**
9. **All correction findings remain pending review until a human decides.**
10. **Core review must work with `enable_ai_review=false` and `enable_vlm=false`.**

## 4. Reference Corpus Domain Model

Add two primary graph labels.

### 4.1 ReferenceCorpus

Required properties:

- `id`
- `projectId`
- `revision`
- `status`: `staging | converting | validating | canonicalizing | ready | failed`
- `sourceSetHash`
- `converterVersion`
- `manifestSchemaVersion`
- `canonicalizerVersion`
- `createdAt`
- `readyAt`
- `failureCode`

Relationships:

```text
(Project)-[:HAS_REFERENCE_CORPUS]->(ReferenceCorpus)
(older:ReferenceCorpus)-[:PRECEDES]->(newer:ReferenceCorpus)
(ReferenceCorpus)-[:USES_SOURCE]->(OriginalAsset)
(ReferenceCorpus)-[:HAS_ARTIFACT]->(DerivedArtifact)
(ReferenceCorpus)-[:HAS_PLATE]->(Plate)
(ReferenceCorpus)-[:HAS_DRAWING]->(Drawing)
```

### 4.2 DerivedArtifact

Required properties:

- `id`
- `referenceCorpusId`
- `artifactType`: `manifest | pdf | png | svg | render`
- `uri`
- `sha256`
- `mimeType`
- `sourceAssetId`
- `converterVersion`
- `createdAt`

The artifact is always traceable to its source and corpus revision.

### 4.3 Corpus-Scoped Canonical IDs

Canonical visual IDs include corpus identity:

```text
plate:{corpusId}:{number}
plate-panel:{corpusId}:{plateNumber}:{panelIndex}
drawing:{corpusId}:{number}
drawing-region:{corpusId}:{drawingNumber}:{regionNumber}
```

A Plate 45 in corpus V1 and Plate 45 in corpus V2 are distinct immutable nodes.

## 5. Adobe Converter Agent

Adobe automation runs in a separate converter process/agent from FastAPI and RQ workers.

```text
FastAPI/RQ
   |
ConversionJob
   |
AdobeConversionClient
   |
Adobe Converter Agent
   +-- InDesign
   +-- Illustrator
```

The backend must not embed business rules in Adobe scripts. Adobe scripts are structural extractors only.

### 5.1 Converter Contract

Input:

- conversion job ID
- project ID
- corpus ID
- source asset IDs/paths
- requested output directory
- manifest schema version

Output:

- manifest JSON
- preview/render artifacts
- artifact checksums
- Adobe application/version
- extractor script version
- structured warnings/errors

The Python application understands only the manifest schema, not Adobe DOM internals.

## 6. INDD to Plate/PlatePanel Rules

An INDD source set contains the `.indd` file and its linked assets.

The extractor records at minimum:

- document/page identifiers
- page labels and indices
- text frames and their text/bounds
- graphic frames and bounds
- InDesign Link IDs and resolved link paths
- object IDs

The Canonicalizer may create `Plate(number=45)` only when an explicit internal publication identifier such as `【도판 45】` is uniquely associated with the relevant page/layout scope.

`PlatePanel` linkage uses actual InDesign placement information:

```text
PlatePanel
  -> graphic frame
  -> InDesign Link ID
  -> linked OriginalAsset
```

A filename such as `조사후_45.JPG` cannot create Plate 45 or select it as canonical evidence.

Missing links, conflicting identifiers, or non-unique panel placement keep the corpus from READY status.

## 7. AI to Drawing/DrawingRegion Rules

The Illustrator extractor records at minimum:

- artboards
- text frames and text/bounds
- layers/groups
- placed items
- object IDs
- render artifacts

A filename `도면30.ai` has no identity authority.

`Drawing(number=30)` may be created only when the Illustrator document itself provides a unique explicit publication identifier such as `【도면 30】` in the deterministic artboard/document scope.

If one scope contains conflicting identifiers, return `AMBIGUOUS_IDENTIFIER` and do not create the canonical node.

If multiple sources in the same corpus resolve to the same publication number, return `DUPLICATE_CANONICAL_IDENTIFIER` and do not mark the corpus READY.

DrawingRegion is created only when region identity and spatial ownership are deterministic. Otherwise the Drawing may exist without regions.

## 8. Reference Corpus Build State Machine

```text
STAGING
  -> CONVERTING
  -> VALIDATING
  -> CANONICALIZING
  -> GRAPH_VALIDATING
  -> READY
```

Terminal failure codes include:

- `ADOBE_UNAVAILABLE`
- `CONVERSION_TIMEOUT`
- `CONVERTER_ERROR`
- `MANIFEST_INVALID`
- `LINK_MISSING`
- `IDENTIFIER_UNRESOLVED`
- `AMBIGUOUS_IDENTIFIER`
- `DUPLICATE_CANONICAL_IDENTIFIER`
- `EMPTY_CANONICAL_GRAPH`
- `CROSS_PROJECT_SOURCE`
- `PROVENANCE_INCOMPLETE`

A failed build retains OriginalAsset, artifacts, manifest, and diagnostics for audit/retry.

## 9. Idempotency and Revisioning

Build identity is derived from:

```text
sourceSetHash
+ converterVersion
+ manifestSchemaVersion
+ canonicalizerVersion
```

The same build identity reuses an existing READY corpus instead of creating a new revision.

A changed source, converter contract, or canonicalizer version produces a new immutable revision linked with `PRECEDES`.

## 10. Upload/API Boundary

### 10.1 Body PDF

`POST /api/projects/{project_id}/documents` becomes the normal body-document upload endpoint and accepts publication-body PDF only for new workflows.

### 10.2 Reference Corpus

New endpoints:

```text
POST /api/projects/{project_id}/reference-corpora
POST /api/projects/{project_id}/reference-corpora/{corpus_id}/sources
POST /api/projects/{project_id}/reference-corpora/{corpus_id}/build
GET  /api/projects/{project_id}/reference-corpora
GET  /api/projects/{project_id}/reference-corpora/{corpus_id}
```

Source roles:

- `plate_layout` -> `.indd`
- `plate_link` -> linked image assets
- `drawing_source` -> `.ai`

Upload completion does not mean graph-build completion.

## 11. ReviewRound Contract

New ReviewRounds use exactly:

```text
ReviewRound
  -[:USES_BODY_VERSION]-> DocumentVersion(report_body)
  -[:USES_REFERENCE_CORPUS]-> ReferenceCorpus(ready)
```

New creation payload:

```json
{
  "body_version_id": "...",
  "reference_corpus_id": "...",
  "notes": "..."
}
```

Rules:

- body must be a PDF DocumentVersion owned by the project;
- corpus must be READY and owned by the same project;
- new rounds cannot mix `reference_corpus_id` with legacy `plate_version_id` or `drawing_version_id`;
- `/api/v1/projects/{project_id}/runs` continues accepting only ReviewRound identity plus optional AI/VLM flags.

Legacy rounds may remain readable/executable through an explicit compatibility path while migration is in progress.

## 12. Graph-First Rule Engine

The deterministic engine is split into four layers.

### L1. Corpus Integrity

Before body review:

- duplicate Plate/Drawing numbers
- unresolved identifiers
- missing links
- incomplete provenance
- missing required render/manifest artifacts
- cross-project relationships
- empty canonical graph
- mutation of READY corpus

Any hard failure blocks ReviewRound execution.

### L2. Reference Resolution

Body `Reference(type, number)` resolves only inside the ReviewRound-selected corpus.

Statuses:

- `RESOLVED`
- `MISSING`
- `AMBIGUOUS`
- `INVALID`

No AI is used for identity resolution.

Resolution evidence is AnalysisRun/corpus scoped so results from corpus V1 and V2 never overwrite each other.

### L3. Coverage and Consistency

The body produces `ArchaeologyObject` mentions. Corpus visual descriptors are deterministically linked to objects when strong identifiers are unique.

```text
TextBlock/Caption -[:MENTIONS]-> ArchaeologyObject
Plate/PlatePanel/Drawing/DrawingRegion -[:DEPICTS]-> ArchaeologyObject
```

Bidirectional rules:

- body Reference -> canonical target -> depicted object consistency;
- visual target -> depicted object -> missing body Reference coverage;
- wrong existing reference replacement when the existing target is proven wrong/unresolved and exactly one correct same-type target exists;
- blank placeholder filling when canonical target and insertion location are deterministic.

Automatic proposed text requires all three:

1. canonical target is unique;
2. body insertion/replacement location is unique;
3. graph provenance is complete.

Otherwise `proposed_text = null` and human review is required.

### L4. Semantic Escalation

The deterministic layer may emit `SEMANTIC_REVIEW_REQUIRED` for claims the graph cannot prove, such as visual geometry, orientation, or nuanced textual interpretation.

With AI/VLM disabled these remain pending review without failing the run.

## 13. AI/VLM Optional Review

Default product behavior:

```text
enable_ai_review = false
enable_vlm = false
```

AI/VLM is invoked only for findings explicitly marked as requiring semantic review.

### 13.1 LLM Role

Allowed:

- contextual contradiction review
- terminology/wording review
- semantic consistency review
- proposed wording draft

### 13.2 VLM Role

Allowed only after graph identity is already resolved:

- compare a specific body claim with a specific canonical Plate/Panel/Drawing/Region render;
- visual geometry/orientation/content checks.

VLM is a comparison tool, never an identity-discovery authority.

### 13.3 AI Cannot Mutate Canonical Graph

AI/VLM must not directly create or modify:

- Plate/Drawing identity
- publication number
- `RESOLVES_TO`
- `DEPICTS`
- corpus membership
- provenance relationships

AI output is stored separately as `AIReviewFinding` linked to Evidence/Candidate/Object.

Required audit fields include model/provider, prompt version, input hash, confidence, verdict, rationale, and proposed text.

AI failure is non-fatal to a graph-successful review run and is reported as an optional-review warning.

## 14. AI Cost Control and Cache

Only semantic-review findings are eligible for AI.

Optional run budgets may cap LLM/VLM reviews. Priority order:

1. high-severity graph inconsistency;
2. body vs canonical visual contradiction;
3. numeric/shape/orientation claims;
4. general contextual review.

Cache identity:

```text
sourceTextHash
+ canonicalTargetRenderHash
+ model
+ promptVersion
```

Unchanged evidence reuses prior AI results.

## 15. UI Design

The UI separates project reference-data construction from body review.

### 15.1 Reference Data Panel

Shows:

- current corpus revision/status;
- INDD source;
- linked-photo count/status;
- AI source count/status;
- extracted Plate/Panel/Drawing/Region counts;
- build/rebuild action;
- diagnostics on failed corpus builds.

Source selectors accept INDD/linked images/AI rather than plate/drawing PDFs.

### 15.2 Body Review Panel

Shows:

- selected READY ReferenceCorpus;
- body PDF upload/version;
- ReviewRound creation.

Review execution displays:

```text
Graph-based review: always enabled
AI contextual deep review: optional, default OFF
VLM visual deep review: optional, default OFF
```

Results distinguish provenance:

- `Graph confirmed`
- `AI reviewed`
- `Human confirmation required`

## 16. Legacy Migration

Legacy ReviewRounds using plate/drawing DocumentVersions remain readable through an explicit compatibility path.

New UI and new ReviewRound creation use only body PDF + ReferenceCorpus.

Mixed new/legacy authority is forbidden.

```text
reference_corpus_id + plate_version_id/drawing_version_id -> reject
```

Legacy removal is a later migration task after corpus-based operation is proven.

## 17. Component Boundaries

New focused units:

```text
backend/app/domain/reference_corpus.py
backend/app/domain/adobe_manifest.py
backend/app/services/adobe_conversion_client.py
backend/app/services/reference_corpus_service.py
backend/app/services/reference_canonicalizer.py
backend/app/services/corpus_object_linker.py
backend/app/services/graph_rules/
  corpus_integrity.py
  reference_resolution.py
  visual_coverage.py
  visual_consistency.py
  semantic_escalation.py
  engine.py
backend/app/graph/reference_corpus_repository.py
backend/app/graph/graph_review_repository.py
backend/app/api/reference_corpora.py
```

Existing large orchestration files should call these focused units rather than absorb Adobe/corpus logic.

## 18. End-to-End Data Flow

```text
1. User creates project.
2. User stages INDD + Links + AI files.
3. Sources are stored as OriginalAsset with hashes/provenance.
4. User triggers corpus build.
5. Adobe Converter Agent emits manifest + render artifacts.
6. Manifest validator rejects incomplete/ambiguous structures.
7. Canonicalizer creates corpus-scoped Plate/Panel/Drawing/Region nodes.
8. Graph integrity validation passes.
9. Corpus becomes READY and immutable.
10. User uploads body PDF.
11. User creates ReviewRound with bodyVersionId + referenceCorpusId.
12. Body ingest creates Page/TextBlock/Caption/Reference/ArchaeologyObject.
13. CorpusObjectLinker creates only deterministic DEPICTS relationships.
14. Graph Rule Engine performs L1-L4 review.
15. Deterministic findings become pending CorrectionCandidates.
16. Optional AI/VLM reviews only semantic-review findings when enabled.
17. Human accepts/rejects/modifies/defer candidates.
```

## 19. Failure and Retry Semantics

### Core failures

These fail/stop the relevant build/run:

- malformed/unreadable body PDF;
- invalid/non-READY/cross-project corpus;
- broken canonical identity/provenance;
- ambiguous identity where deterministic uniqueness is required;
- Adobe conversion failure during corpus build.

### Optional AI failures

Timeout, rate limiting, unavailable model, or malformed AI response do not erase graph findings and do not turn a graph-successful run into a core failure.

Retries must be idempotent by source/build/run identity.

## 20. Test and CI Strategy

### 20.1 Hermetic Unit/Integration CI

GitHub CI uses fake Adobe converter manifests and fixtures. It must test Graph/canonical behavior without requiring Adobe installation.

Required acceptance cases:

- INDD internal Plate45 + Link -> Plate45/Panel/provenance created;
- `_45.JPG` filename alone cannot create/select Plate45;
- `도면30.ai` filename alone cannot create Drawing30;
- Illustrator internal `【도면 30】` -> Drawing30 created;
- conflicting identifiers -> ambiguous, corpus not READY;
- duplicate Drawing30 -> duplicate failure;
- missing INDD link -> corpus not READY;
- same source/tool versions -> READY corpus reused;
- changed source or canonicalizer version -> new corpus revision;
- READY corpus mutation rejected;
- cross-project corpus ReviewRound rejected;
- non-READY corpus ReviewRound rejected;
- new round with legacy plate/drawing version IDs rejected;
- selected-corpus-only reference resolution;
- missing reference + unique DEPICTS -> deterministic insertion proposal;
- wrong reference + unique correct DEPICTS -> replacement proposal;
- ambiguous target/location -> no proposed text;
- AI/VLM OFF -> core run completes;
- AI/VLM failure -> graph results preserved;
- legacy ReviewRound compatibility remains operational.

### 20.2 Real Neo4j CI

Real Neo4j integration tests verify corpus scope, project isolation, immutable revisions, RESOLVES_TO run scope, DEPICTS scope, and ReviewRound ownership.

### 20.3 Frontend CI

Tests verify:

- INDD/Links/AI source selectors;
- no new plate/drawing PDF workflow;
- READY corpus selection;
- AI/VLM checkboxes default OFF;
- graph-vs-AI result labels;
- failed corpus diagnostics.

### 20.4 Adobe Smoke E2E

A separate Adobe-installed self-hosted runner executes real small fixture files:

- one INDD with linked image;
- one AI with explicit Drawing identifier;
- manifest schema validation;
- render output/checksum validation.

The regular hermetic CI does not depend on Adobe licensing or desktop availability.

## 21. Completion Gate

Implementation is complete only when:

1. all hermetic backend tests pass;
2. all real Neo4j tests pass;
3. frontend tests/typecheck/build pass;
4. new Graph-first behavior is covered by deterministic regression tests;
5. AI/VLM-disabled end-to-end review passes;
6. Adobe smoke E2E is either green on the configured self-hosted runner or explicitly reported as unavailable/HOLD without being misrepresented as verified;
7. no code path allows filenames or AI output to establish canonical identity;
8. no merge to `main` occurs without explicit user instruction.
