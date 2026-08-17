# Source Provenance Remediation Spec Review

**Date:** 2026-08-18  
**Baseline audited:** `a6a54f282e22bdfc1d86b7e6f81a71f663d19269`  
**Draft reviewed:** `docs/superpowers/specs/2026-08-18-source-provenance-and-usability-remediation-design.md` at commit `6a4f96d6861b71f7e875114114ec66a674fdd6de`

## Verdict

**Do not implement the draft as written.** The direction is correct, but several draft choices either add unnecessary graph concepts or weaken the already-approved canonical publication identity model. The spec must be revised before an implementation plan is written.

## Findings

### P0-1 — `SourceBundle` is unnecessary persistent graph state

The current Neo4j schema already declares `OriginalAsset` as a first-class canonical node type, while there is no existing `SourceBundle` schema, repository contract, or graph invariant. Persisting `SourceBundle` would add another ownership layer solely to represent an import session.

Decision: **remove persistent `SourceBundle`.** Import grouping is provenance metadata on `OriginalAsset` (`importBatchId`, `sourceRootName`, `relativePath`) and may be rendered as a derived UI group when useful.

### P0-2 — The draft invented two overlapping provenance edges

The draft used both `PROVENANCED_BY` and `DERIVED_FROM`. Existing production graph code has no implemented OriginalAsset provenance edge. Two new relationships would create ambiguous semantics.

Decision: introduce only:

```text
(Project)-[:HAS_ORIGINAL_ASSET]->(OriginalAsset)
(source-derived node)-[:DERIVED_FROM {method,status,evidence...}]->(OriginalAsset)
```

`DERIVED_FROM` is optional and evidence-bearing. It may originate from `DocumentVersion`, `PlatePanel`, `Drawing`, or `DrawingRegion` when an explicit mapping proves that provenance. A raw source file is never linked by filename inference.

### P0-3 — PDF-compatible AI must not create canonical Drawing identity

The draft allowed an Illustrator file containing an internal `도면 30` token to create a canonical `Drawing`. That weakens the system rule that publication identity is established from the reviewable publication artifact / already-existing canonical graph.

Decision: `.ai` is always ingested first as `OriginalAsset`. If PDF-compatible, an AI inspector may extract text, explicit identifiers, dimensions, and a thumbnail as **source observations only**. It does not create `Drawing`/`DrawingRegion` nodes in this remediation.

An AI source can be linked to an already-existing canonical Drawing only through an explicit, project-scoped provenance mapping.

### P0-4 — Manifest targets require DocumentVersion scope

A target such as `{plateNumber: 45, panelIndex: 1}` is not sufficient because one project may contain multiple plate-book versions, each with a Plate 45.

Decision: every manifest target must use either:

1. exact `nodeId` plus `documentVersionId`, or
2. `documentVersionId + nodeType + publication identifier fields` that resolve to exactly one canonical node.

The repository must verify that the target DocumentVersion belongs to the same project and that the target is reachable from that version through `HAS_PLATE/HAS_PANEL` or `HAS_DRAWING/HAS_REGION`.

### P0-5 — Manifest provenance is not expert truth

A manifest can explicitly declare provenance without using filename inference, but the declaration can still be wrong.

Decision: `DERIVED_FROM` carries a status. In this batch:

- `declared`: explicit manifest mapping
- `verified`: human-verified mapping (read support / service contract; no write UI required)

Declared source assets may be displayed as supplementary provenance, but they do **not** replace the canonical PDF render and are not used as the VLM canonical visual in this remediation.

### P0-6 — Source root symlink must be supported safely

The real project documentation states that `src` itself is a Git-untracked symbolic link. Rejecting any symlink would reject the real source layout.

Decision: resolve the user-supplied source root once and treat the resolved directory as the trust boundary. Child paths and manifest asset paths must resolve inside that boundary. A nested symlink that escapes the boundary is rejected. The source-root symlink itself is allowed.

### P0-7 — Publication upload and source-asset import must be separate contracts

`FileStore` already accepts HWP/HWPX, images, and AI, but `/api/projects/{id}/documents` creates a `DocumentVersion` and enqueues canonical ingest. Source-only files must not enter that path accidentally.

Decision:

- `FileStore` remains a reusable byte store and may accept source formats.
- public `documents` upload remains the reviewable publication-input path and must fail closed for source-only formats during this remediation; canonical document ingest remains PDF-based.
- `SourceImportService` + CLI is the source-only path and creates `OriginalAsset`, never `DocumentVersion` unless an explicit later mapping says a publication version was derived from that source.

### P1-1 — `canonicalLinkStatus` must not pretend identity ownership

A source asset needs UI status, but a mutable property named `canonicalLinkStatus` can be confused with canonical resolution.

Decision: use `provenanceStatus` with values such as `unlinked`, `declared`, `verified`, `ambiguous`, `missing_target`, `conflict`. Canonical identity remains represented by the canonical nodes and `RESOLVES_TO` path.

### P1-2 — Project Structure should show source categories, not a database-only bundle concept

Decision: add a derived `원천 자료` root group with derived category groups (`본문 원본`, `도면 원본`, `조판 원본`, `링크 사진`, `기타`). Persist only `OriginalAsset`; import batch metadata appears in badges/details.

### P1-3 — Semantic graph labels cannot be a single cross-language helper

`ProjectStructureService` already constructs server-side tree labels, while `EvidenceGraphExplorer` constructs raw traceability nodes client-side. A single TypeScript helper cannot be the sole source for both without unnecessary API rewrites.

Decision:

- frontend `graphPresentation.ts` handles EvidenceGraphExplorer node titles, relationship localization, inspector field labels, and technical-info disclosure;
- backend `ProjectStructureService` retains tree-label responsibility but follows the same documented semantic rules and tests;
- `ProjectStructureInspector` uses frontend relationship/detail formatting and hides technical IDs by default.

### P1-4 — OriginalAsset idempotency must preserve immutable history

Decision: `OriginalAsset.id` is deterministic from project + normalized relative path + source SHA-256. Re-importing the same bytes at the same relative path reuses the node; changed bytes at the same path create a new immutable OriginalAsset instead of overwriting history.

## Final architecture selected by this review

```text
Project
├─ HAS_DOCUMENT -> Document -> HAS_VERSION -> DocumentVersion
│                                      ├─ HAS_PLATE -> Plate -> HAS_PANEL -> PlatePanel
│                                      └─ HAS_DRAWING -> Drawing -> HAS_REGION -> DrawingRegion
│
└─ HAS_ORIGINAL_ASSET -> OriginalAsset

DocumentVersion ──DERIVED_FROM──> OriginalAsset      (explicit mapping only)
PlatePanel       ──DERIVED_FROM──> OriginalAsset      (explicit mapping only)
Drawing          ──DERIVED_FROM──> OriginalAsset      (explicit mapping only)
DrawingRegion    ──DERIVED_FROM──> OriginalAsset      (explicit mapping only)
```

The canonical identity path remains unchanged:

```text
TextBlock/Caption
  -> Reference(type=plate, number=45)
  -> RESOLVES_TO
  -> canonical Plate/PlatePanel established from publication content
```

`OriginalAsset` is supplementary provenance and cannot satisfy a missing `Reference` target.

## Implementation ordering recommended after final spec approval

1. project timestamps
2. UI visibility
3. semantic graph presentation
4. OriginalAsset source import + Project Structure source view + Case 6 provenance regression

Each slice must use RED -> GREEN -> refactor, and the fourth slice must pass Real Neo4j tests before any VLM acceptance work resumes.
