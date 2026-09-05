# Archaeology Review System Redesign

Date: 2026-09-05
Status: Architecture approved in chat; written spec awaiting user review
Branch context: `feat/revision-aware-panel-provenance`

## 1. Purpose

Redesign the archaeology document review system around two explicit product capabilities while preserving useful proven components from the current repository:

1. **Canonical Asset QA** — compare photos and drawings embedded in the current proof against human-approved canonical originals and metadata.
2. **Intelligent Editorial QA** — review the entire current proof for language errors, internal contradictions, and contradictions between current-document claims and human-approved canonical entity facts.

The system must not treat previous proof revisions as semantic ground truth. Previous revisions are audit/history and cache-reuse inputs only.

The system must preserve human authority: AI produces findings, evidence, and suggested corrections; humans accept, reject, modify, or defer. The system does not automatically rewrite PDF/HWP/HWPX source files and does not auto-approve canonical truth.

## 2. Product Boundaries

### 2.1 Canonical Asset QA

Canonical photos and drawings are the ground truth for asset identity after human approval. The system checks:

- wrong asset
- missing asset
- duplicate asset
- crop/rotation/layout mismatch where detectable
- wrong plate/drawing number
- caption mismatch
- wrong linked archaeology entity
- canonical metadata mismatches such as view direction or drawing type when those facts are known and human-verified

### 2.2 Intelligent Editorial QA

Editorial QA has two internal engines.

#### B1. Whole-document Editorial QA

Input scope is the entire current proof, preserving block type and location:

- heading
- body text
- table
- caption
- footnote

Checks include:

- typo/spelling/spacing
- grammar and awkward phrasing
- terminology and notation inconsistency
- numeric/direction/period/name inconsistency
- cross-page and long-distance contradictions
- body ↔ table contradictions
- body ↔ caption contradictions
- other document-internal semantic inconsistencies

A document-internal contradiction may be proposed without canonical evidence, but it remains a review candidate requiring human judgment.

#### B2. Canonical Entity QA

The system aligns current-proof entity mentions and claims with canonical entities and human-approved canonical facts. Only reliable entity links may produce deterministic canonical contradictions.

Example:

- canonical: `pit-003.axis_direction = N-S`
- proof claim: `pit-003.axis_direction = E-W`
- finding: `CANONICAL_CONTRADICTION`

AI general archaeology knowledge may not create a canonical contradiction when no canonical fact supports it.

## 3. Authority Model

The authority order is explicit:

1. Human-approved canonical asset identity and canonical facts
2. Current-proof source evidence
3. Deterministic extraction and comparison results
4. AI/Codex observations and suggestions
5. Previous revision history only for audit/cache reuse

AI confidence is not canonical evidence.

Canonical metadata fields use explicit states:

- `KNOWN`
- `UNKNOWN`
- `DISPUTED`

Only `KNOWN + human_verified` facts participate in automatic canonical contradiction checks.

## 4. Source of Truth and Storage

This is a single-PC, effectively single-user local application.

### 4.1 SQLite

SQLite is the sole structured source of truth for:

- projects
- review requests
- intake snapshots
- canonical corpus state
- canonical assets/entities/facts
- current document revisions
- document blocks
- entity mentions
- document claims
- analysis runs
- findings
- evidence
- suggested corrections
- human decisions
- publication/package records
- evaluation metadata

### 4.2 Artifact Store

Large immutable files and derived features live outside SQLite in a content-addressed artifact store.

Initial convention:

```text
/data
  originals/
  canonical/
  derived/pages/
  derived/panels/
  derived/thumbnails/
  features/sift/
  features/embeddings/
  cache/
  intake/
  review-packages/
```

Artifacts are keyed by SHA256 plus algorithm/version/configuration where applicable.

### 4.3 Neo4j

Neo4j is a derived, rebuildable relationship/search projection only. It is never the source of truth.

Projected nodes may include:

- CanonicalEntity
- CanonicalAsset
- DocumentEntity
- DocumentBlock
- DocumentClaim
- CanonicalFact
- Finding

Representative relationships:

- `DocumentEntity-[:MENTIONED_IN]->DocumentBlock`
- `DocumentEntity-[:ASSERTS]->DocumentClaim`
- `DocumentEntity-[:RESOLVES_TO]->CanonicalEntity`
- `CanonicalEntity-[:HAS_FACT]->CanonicalFact`
- `CanonicalEntity-[:HAS_ASSET]->CanonicalAsset`
- `Finding-[:SUPPORTED_BY]->DocumentClaim`
- `Finding-[:CONTRADICTS]->CanonicalFact`

Neo4j projections must use deterministic IDs and idempotent upserts. Losing Neo4j must not lose review state.

## 5. Core Data Model

### 5.1 Project

Top-level workspace for one archaeology review corpus and its review requests.

### 5.2 CanonicalCorpus

Fields include:

- id
- project_id
- revision
- source_set_hash
- status
- created_at
- approved_at

Changes in canonical input files change `source_set_hash` and invalidate dependent derived artifacts as needed.

### 5.3 CanonicalAsset

Represents a human-approved original photo or drawing.

Key fields:

- id
- corpus_id
- sha256
- asset_type (`PHOTO`, `DRAWING`)
- original_name
- artifact_uri
- identity_status
- human_verified

File identity may become canonical even when optional metadata is unknown.

### 5.4 CanonicalMetadata

Property-record structure rather than an ever-growing column set:

- id
- asset_id
- key
- value
- status (`KNOWN`, `UNKNOWN`, `DISPUTED`)
- evidence_id
- human_verified

### 5.5 CanonicalEntity

Represents archaeological objects or approved reference entities.

Examples:

- feature/structure
- artifact
- drawing
- photo
- other approved entity types

Key fields:

- id
- corpus_id
- entity_type
- canonical_name
- normalized_key
- status
- human_verified

### 5.6 CanonicalFact

Represents human-approved facts used by B2.

- id
- entity_id
- predicate
- value
- value_type
- status
- evidence_id
- human_verified

### 5.7 ReviewDocument / DocumentRevision

Represents the proof file being reviewed. Revision lineage is audit/cache metadata, not semantic truth.

Fields include:

- id
- project_id
- source_sha256
- filename
- document_type
- imported_at
- parse_status

### 5.8 DocumentBlock

Preserves source structure and location:

- id
- document_revision_id
- block_type (`HEADING`, `TEXT`, `TABLE`, `CAPTION`, `FOOTNOTE`)
- raw_text
- normalized_text
- physical_page
- printed_page
- bbox
- section_id
- order_index
- source_sha256

### 5.9 EntityMention

Represents a textual reference to a possible canonical entity.

Resolution states:

- `EXACT`
- `DERIVED_VERIFIED`
- `AMBIGUOUS`
- `UNRESOLVED`

`AMBIGUOUS` and `UNRESOLVED` mentions may not create deterministic canonical contradictions.

### 5.10 DocumentClaim

Represents what the current document claims, not what the system believes to be true.

Fields include:

- id
- revision_id
- subject_mention_id
- predicate
- value
- value_type
- source_block_id
- evidence_id
- extraction_method
- confidence

B1 compares DocumentClaim ↔ DocumentClaim. B2 compares DocumentClaim ↔ CanonicalFact.

### 5.11 Finding

New root review aggregate. Existing revision-diff-oriented correction candidate models become migration/adapter inputs rather than the new root concept.

Fields include:

- id
- revision_id
- engine (`ASSET_QA`, `EDITORIAL_QA`, `CANONICAL_ENTITY_QA`)
- finding_type
- severity
- status
- subject_entity_id
- canonical_entity_id
- original_text
- suggested_text
- analysis_run_id
- fingerprint
- created_at

### 5.12 Evidence

Immutable evidence object. Types may include:

- DOCUMENT_BLOCK
- CANONICAL_FACT
- CANONICAL_ASSET
- VISUAL_MATCH
- RULE_RESULT
- AGENT_OBSERVATION

Evidence preserves source SHA, page/block/bbox or asset/fact references, method, value, and analysis run.

Findings connect to evidence through roles such as `SUPPORTS`, `CONTRADICTS`, and `CONTEXT`.

### 5.13 HumanDecision

Append-only human decision record:

- ACCEPT
- REJECT
- MODIFY
- DEFER

AI output and human decision remain separate.

### 5.14 AnalysisRun

Tracks deterministic and AI executions. For AI runs it records:

- task_type
- runtime (`CODEX_SDK`, `DIRECT_API`)
- provider
- endpoint profile
- model
- reasoning level
- prompt/skill version
- toolset version
- input hash
- output hash
- timestamps/status

No AgentBudget subsystem is part of the design.

## 6. Processing Pipelines

### 6.1 A — Canonical Asset QA

Canonical preparation:

```text
Original photo/drawing
  -> SHA256
  -> persistent normalized visual hash / thumbnail / SIFT
  -> optional embedding later if justified by evaluation
  -> metadata draft from deterministic sources and AI assistance
  -> human approval
  -> CanonicalAsset / CanonicalMetadata / CanonicalEntity / CanonicalFact
```

Current-proof comparison:

```text
Extracted panel/region
  -> exact/normalized hash shortcut where safe
  -> candidate retrieval
  -> SIFT matching
  -> Lowe ratio
  -> RANSAC
  -> uniqueness/collision guards
  -> asset identity result
  -> canonical number/caption/entity/metadata comparison
  -> Finding + Evidence
```

Filename, path, caption, pixel similarity, or VLM opinion alone may not establish canonical identity.

Collision, near-tie, and one-to-many ambiguity remain unresolved or ambiguous rather than auto-promoted.

### 6.2 B1 — Whole-document Editorial QA

Pipeline:

```text
Current proof
  -> parse into typed DocumentBlocks
  -> language review
  -> entity extraction
  -> DocumentClaim extraction
  -> global entity/claim index
  -> deterministic contradiction candidate generation
  -> Codex investigation with evidence tools
  -> schema/evidence validation
  -> Finding + Evidence + suggested correction
```

The design explicitly avoids treating independent chunk summaries as whole-document consistency analysis.

### 6.3 B2 — Canonical Entity QA

Pipeline:

```text
EntityMention
  -> entity resolution
  -> EXACT / DERIVED_VERIFIED only for deterministic canonical comparison
  -> DocumentClaim vs KNOWN+human_verified CanonicalFact
  -> deterministic mismatch detection
  -> Codex used for semantic/entity-context investigation where useful
  -> Finding + Evidence
```

The code performs the actual canonical fact comparison; AI helps interpret semantics and context but cannot establish unsupported canonical truth.

## 7. AI Execution Architecture

### 7.1 Default Runtime

Codex SDK is the primary runtime. The expected normal operating profile uses Luna with max/xhigh reasoning according to task configuration.

Direct API is a secondary runtime for model/provider replacement, experiments, cheaper text workloads, local/internal endpoints, or workflows that do not require the full Codex harness.

### 7.2 Runtime Abstraction

Business logic uses a common service boundary:

```text
AIReviewService
  -> CodexSdkRuntime
  -> DirectApiRuntime
```

Both implement the same request/result contract.

Conceptual request:

- task_type
- revision_id
- candidate_ids
- tool permissions
- model profile
- output schema version

Conceptual result:

- proposals
- observations
- used evidence IDs
- runtime metadata
- status

### 7.3 Model/Endpoint Switching

Business logic must not hard-code provider endpoints.

Configuration selects runtime/provider/model/endpoint. Example profiles:

```yaml
editorial_review:
  runtime: codex_sdk
  model: luna
  reasoning: max

contradiction_review:
  runtime: codex_sdk
  model: luna
  reasoning: xhigh

alternative_text_review:
  runtime: direct_api
  provider: deepseek
  endpoint: configured-endpoint
  model: configured-model
```

No automatic cost router, provider escalation policy, max-hop budget system, or auto-fallback-to-paid-provider behavior is included.

Standard timeout, retry, and error handling remain required.

### 7.4 ReviewToolGateway

Codex SDK and Direct API tool loops use the same read-oriented gateway.

Document tools:

- `search_document`
- `get_block`
- `get_block_context`
- `get_section`
- `get_table`
- `get_caption`

Entity tools:

- `search_entity`
- `get_entity_mentions`
- `get_document_claims`
- `get_related_entities`

Canonical tools:

- `get_canonical_entity`
- `get_canonical_facts`
- `get_canonical_assets`
- `get_canonical_metadata`

Visual/evidence tools:

- `get_visual_region`
- `get_canonical_image`
- `get_visual_match_evidence`
- `get_evidence`
- `get_finding_context`

Codex may use a read-only analysis workspace for structured files and selected images. It may not mutate originals, canonical truth, SQLite review state, or human decisions directly.

### 7.5 Evidence Enforcement

An AI proposal without valid evidence IDs is rejected before Finding creation.

Validation checks include:

- evidence exists
- evidence belongs to the relevant intake/revision/canonical corpus
- evidence is valid for the claimed role
- canonical contradictions cite an approved canonical fact

AI output is an observation/proposal until deterministic schema and evidence validation succeed.

## 8. Discord + Google Drive Input Interface

### 8.1 Interface Roles

- Discord = request, progress, notification, links
- Google Drive = input/output transport
- SQLite = request/review source of truth
- artifact store = immutable analysis snapshots and derived assets
- Review Web UI = human review interface

Repository search found no existing Discord/Google Drive subsystem to preserve, so this is a new integration subsystem around the existing review core.

### 8.2 Structured Discord Request Contract

Request intake should prefer a structured slash-command or equivalent Discord form rather than relying on free-text interpretation. Required semantic inputs are:

- project or project selector
- `canonical_drive_ref`
- `proof_drive_ref`

An optional note may remain free text. Free text must not be the sole mechanism for resolving an ambiguous Drive input.

Representative interaction:

```text
/review
project: 논산 산노리
canonical: <Google Drive folder URL>
proof: <Google Drive file URL>
note: 3차 교정본 검수
```

Discord requests create a `ReviewRequest` containing:

- id
- project_id
- source = DISCORD
- discord guild/channel/message IDs
- requester metadata
- canonical_drive_ref
- proof_drive_ref
- intake_snapshot_id
- status
- created_at
- completed_at

Request states are:

- RECEIVED
- IMPORTING
- WAITING_CANONICAL_APPROVAL
- ANALYZING
- READY_FOR_REVIEW
- REVIEWING
- FINALIZED
- PUBLISHED
- FAILED

### 8.3 Drive Snapshot Rule

The review engine never depends on mutable Drive content during analysis.

```text
Google Drive refs
  -> list/fetch metadata
  -> download local snapshot
  -> SHA256
  -> immutable IntakeSnapshot
  -> review pipeline
```

`DriveResource` records Drive file ID/URL/name/MIME/modified time/size/local SHA.

If a Drive file changes after snapshot creation, the current run remains reproducible from the snapshot. A later request sees a new SHA.

### 8.4 Canonical Drive Intake

A Drive folder being labelled “canonical” does not automatically establish truth.

For each file:

- already-approved SHA -> reuse canonical identity/features
- new or changed SHA -> canonical draft
- draft metadata -> deterministic extraction plus optional AI assistance
- human approval -> canonical promotion

Only new/changed canonical material needs review.

## 9. Human Review UI

The user-facing product presents two top-level functional areas:

- Canonical Comparison
- Editorial Review

Internal B1/B2 distinctions remain visible through finding filters, not as the primary product navigation.

Finding cards must make evidence inspection easy.

For text contradictions, show source passages/pages and suggested correction.

For canonical contradictions, show current claim and canonical fact side-by-side with direct evidence links.

For asset findings, show current image and canonical image side-by-side with identity and metadata mismatch details.

Actions:

- Accept
- Reject
- Modify and accept
- Defer

No automatic source-file edit occurs.

## 10. Output and Publication

### 10.1 Output Roles

- Discord: compact status/summary and links
- Review UI: actual human-in-the-loop review
- Google Drive: final ReviewPackage

Discord does not become a finding-by-finding review UI.

### 10.2 Draft vs Final

```text
AI analysis complete
  -> draft findings
  -> human review
  -> explicit Finalize action
  -> final ReviewPackage
  -> Drive publish
  -> Discord completion notification
```

### 10.3 ReviewPackage

The initial final package is:

1. `01_review_summary.pdf` — report/approval summary
2. `02_review_findings.xlsx` — operational correction list
3. `03_annotated_proof.pdf` — derived copy with highlights/comments/finding IDs
4. `04_review.json` — machine-readable audit/integration output
5. `manifest.json` — internal provenance manifest

The original Drive proof remains unchanged.

Annotated HWP/HWPX editing is not required for the initial product; PDF-render-based annotation is sufficient.

### 10.4 Drive Publication

Publish into a separate result folder under or adjacent to the request context, for example:

```text
project/
  canonical/
  proof/
    3rd-proof.pdf
  AI_review_results/
    R-20260905-001/
      01_review_summary.pdf
      02_review_findings.xlsx
      03_annotated_proof.pdf
      04_review.json
      manifest.json
```

## 11. Fail-Closed Rules

The system must refuse to guess when evidence is insufficient.

- visual near-tie/collision -> AMBIGUOUS/UNRESOLVED
- ambiguous entity -> no deterministic canonical contradiction
- UNKNOWN canonical fact -> no comparison
- DISPUTED canonical fact -> no canonical contradiction
- AI finding without evidence -> reject
- Drive permission failure -> request failure with explicit reason
- ambiguous proof selection -> do not guess input
- Neo4j failure -> retain SQLite truth; mark projection stale and rebuild later
- cache loss -> recompute; canonical/review truth remains intact
- AI endpoint failure -> `FAILED` or `PARTIAL`; deterministic results remain available
- no automatic provider fallback that changes model/cost silently

## 12. Explicit Lessons from Previous Experiments

The redesign encodes prior failures as permanent design constraints.

1. Filename/path/caption alone cannot establish canonical identity.
2. Successful open/render/parse is not identity or provenance success.
3. Pixel similarity alone is not a general identity proof.
4. Near-tie, collision, and one-to-many candidates are never auto-promoted.
5. Guessed graph edges are prohibited.
6. Full cold source scanning on every proof is prohibited; canonical features persist by content identity.
7. Chunked LLM output merging is not whole-document contradiction analysis; a global entity/claim index is required.
8. No gold set means no precision/recall claim.
9. AI general domain knowledge cannot create unsupported canonical contradictions.
10. IDs and projections are deterministic/idempotent.
11. The product does not require Adobe or Windows-only runtime behavior.
12. Ingestion, parsing, entity extraction, asset identity, editorial accuracy, canonical accuracy, and human acceptance are separate KPIs.

Visual matching retains the proven safety model from previous SIFT/RANSAC work while avoiding unnecessary matcher churn. Persistent source features and incremental proof work are higher priority than switching BF to FLANN without demonstrated benefit.

## 13. Evaluation and Regression Strategy

Evaluation is a first-class design component, not an afterthought.

### 13.1 Asset QA Gold

Human-verified panel/region -> CanonicalAsset pairs.

Metrics:

- Top-1 accuracy
- precision
- recall
- false promotion rate
- ambiguous rate

False promotion is a primary safety metric.

### 13.2 Editorial QA Gold

Curated examples include:

- spelling/typo/spacing
- grammar
- terminology mismatch
- number/direction inconsistency
- body ↔ table contradiction
- body ↔ caption contradiction
- long-distance entity contradiction

Metrics:

- issue precision
- issue recall
- false positives per page

### 13.3 Canonical Entity QA Gold

Human-verified:

- Document Entity ↔ CanonicalEntity links
- DocumentClaim ↔ CanonicalFact expectations

Metrics:

- entity-link accuracy
- canonical contradiction precision
- canonical contradiction recall
- false canonical contradiction rate

### 13.4 Model Regression

The same gold sets compare model/runtime configurations such as Luna max, Luna xhigh, and alternate direct-API models. Model changes are judged by measurable review quality rather than subjective impressions.

### 13.5 Historical Failure Fixtures

Past real-corpus failures become small permanent regression fixtures, including cases such as:

- rasterized labels/badges
- composite panels
- continuation captions
- filename-only drawing candidates
- collision panels
- near-ties
- missing canonical references

## 14. CI and Acceptance Separation

CI remains hermetic and small:

- unit tests
- SQLite/domain tests
- parser fixtures
- Codex runtime contract mocks
- Direct API contract mocks
- small SIFT fixtures
- B1/B2 gold subsets
- Neo4j projection E2E

Full local corpus acceptance is separate and measures:

- canonical cold build
- actual panel/asset matching
- real AI execution
- end-to-end review results
- performance

Performance reports must distinguish:

- cold canonical build
- warm/incremental proof analysis

The user-facing operational KPI is incremental review latency, not full cold rebuild latency.

## 15. Implementation Decomposition

This architecture is too broad for one big-bang implementation. It is implemented through phased plans under one umbrella design.

### Phase 0 — Foundation + Evaluation

- SQLite new domain schema
- artifact store conventions
- Finding/Evidence/HumanDecision/AnalysisRun
- ReviewRequest and IntakeSnapshot abstractions
- Drive snapshot interfaces with test fixtures
- gold/evaluation harness
- adapters from useful legacy models

### Phase 1 — Canonical + Asset QA

- CanonicalAsset/Metadata/Entity/Fact
- canonical approval flow
- persistent SIFT/features
- incremental asset matching
- A Review UI
- Asset QA gold regression

### Phase 2 — B1 Editorial QA

- complete typed DocumentBlock ingestion
- EntityMention and DocumentClaim
- AIReviewService
- Codex SDK runtime
- ReviewToolGateway
- language review and whole-document contradiction review
- B1 gold regression

### Phase 3 — B2 Canonical Entity QA

- robust entity resolution
- deterministic DocumentClaim ↔ CanonicalFact comparison
- semantic investigation support
- Neo4j projection
- B2 gold regression

### Phase 4 — Product Integration

- Discord bot adapter
- Google Drive adapter
- Review UI integration
- PDF/XLSX/annotated-PDF/JSON package generation
- Drive publish
- Discord notifications
- Direct API/model switching
- HWP/HWPX acceptance
- cross-platform hardening
- full local acceptance

Implementation must not start by deeply building Discord or Drive integrations before the core review domain/evaluation harness exists; early phases may use local fixtures behind the same interfaces.

## 16. Final Architecture Summary

```text
Discord
  -> ReviewRequest
  -> Google Drive refs
  -> immutable IntakeSnapshot
  -> Canonical Intake / Current Document Intake

Canonical side:
  CanonicalAsset + CanonicalEntity + CanonicalFact

Current-proof side:
  DocumentBlock + EntityMention + DocumentClaim

Review engines:
  A  Canonical Asset QA
  B1 Whole-document Editorial QA
  B2 Canonical Entity QA

AI:
  primary Codex SDK + configurable Luna reasoning profile
  secondary Direct API + configurable provider/endpoint/model
  shared ReviewToolGateway

Outputs:
  Finding + immutable Evidence
  -> HumanDecision
  -> ReviewPackage
  -> Google Drive publish
  -> Discord summary/links

Persistence:
  SQLite = source of truth
  Artifact Store = immutable/derived file data
  Neo4j = rebuildable projection
```

The defining principle is separation of truth, claims, evidence, AI judgment, and human authority. The system combines canonical assets, whole-document structure, entity/claim modeling, deterministic verification, agentic multi-hop investigation, auditable evidence, and human approval without allowing any one subsystem to silently become the source of truth.