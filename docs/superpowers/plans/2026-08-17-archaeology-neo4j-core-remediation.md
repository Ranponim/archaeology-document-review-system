# Archaeology Document Review System — Neo4j-Centric Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Repair the current archaeology document review implementation so that Neo4j is not a passive persistence target but the canonical identity, evidence, consistency, traceability, and expert-review backbone of the real production pipeline.

**Architecture:** Every uploaded body/plate/drawing document is registered as a real `DocumentVersion`, parsed into canonical graph nodes, and linked before analysis. References resolve only to canonical `Plate`/`Drawing`/region nodes already present in Neo4j; archaeological objects are connected to textual and visual evidence; consistency rules and AI analysis consume evidence retrieved by graph traversal. VLM is an observer of already-resolved canonical visual targets, never an identity resolver. Every correction remains `pending_review` until an append-only expert `ReviewDecision` is recorded.

**Tech Stack:** Python 3.12, FastAPI, Neo4j 5.26, RQ/Redis, PyMuPDF, pypdf, Pillow, httpx/OpenRouter, React/TypeScript, Docker Compose, pytest.

---

## 1. Global Constraints

- **Neo4j must be operationally required for the real proofreading path.** A run that skips canonical graph construction or graph retrieval must fail closed, not silently return `completed`.
- **Do not treat Neo4j as an output sink.** The graph must be queried to build object evidence, resolve relationships, run cross-source consistency checks, and serve traceability.
- **Canonical identity must never be inferred from arbitrary numeric filename coincidences.** `4. 조사 후_45.JPG` is not `Plate 45` merely because it contains `45`.
- `Reference(plate,45)` may resolve only through canonical publication identifiers/indexes such as `【도판 45】` / `Plate.number=45`.
- `Reference(drawing,N)` may resolve only through canonical drawing identifiers/indexes, not through filename numbers.
- VLM may produce `SUPPORTED`, `PARTIAL`, `CONTRADICTED`, or `INSUFFICIENT_EVIDENCE`; it must never create or change canonical identity or expert acceptance.
- Every machine-generated `CorrectionCandidate` starts as `pending_review`.
- Expert decisions are append-only `ReviewDecision` records with `accepted`, `rejected`, `modified`, or `deferred` semantics.
- Every document-bound `Evidence` must carry real `source_sha256`, `document_version_id`, `page_id`, and when available `bbox`/`region_id`.
- Do not invent fallback document IDs, page IDs, hashes, graph relations, or success states in production paths.
- A proofreading run with no resolvable body `DocumentVersion` or zero parsed body pages must not return a normal successful result.
- Existing unsafe/legacy analysis paths must be removed, disabled, or delegate to the canonical orchestrator. There must be one authoritative production pipeline.
- Tests using fake Neo4j drivers are unit tests only. MVP acceptance requires tests against a real Neo4j instance and must assert persisted nodes **and relationships**.
- Current Golden Dataset entries are not authoritative solely because they are labeled `VALID_GROUND_TRUTH`; only expert-verified fixtures may be used for final precision/recall gates.
- **Case 6 is an invariant regression gate:** `Reference(plate,45)` must resolve to canonical publication `Plate 45`, and `4. 조사 후_45.JPG` must never appear in identity evidence.

---

## 2. Why This Remediation Exists

The current branch contains many correct components (`PDFParser`, `PlateParser`, `ObjectResolver`, `RuleEngine`, `CanonicalRepository`, `ProofreadingOrchestrator`, VLM/LLM services, review APIs, UI), but the system can still run while Neo4j relationships are incomplete or unused.

The remediation must optimize for **graph correctness and graph use**, not component count or superficial test coverage.

A successful implementation must make this path real:

```text
Project
└─ HAS_DOCUMENT → Document(kind=report_body)
   ├─ HAS_VERSION → DocumentVersion(stage=1차)
   ├─ PRECEDES    → DocumentVersion(stage=2차)
   └─ PRECEDES    → DocumentVersion(stage=3차/final)

DocumentVersion
└─ HAS_PAGE → Page
   ├─ HAS_BLOCK   → TextBlock
   │  ├─ MENTIONS   → ArchaeologyObject
   │  └─ REFERENCES → Reference
   └─ HAS_CAPTION → Caption
      ├─ MENTIONS   → ArchaeologyObject
      └─ REFERENCES → Reference

Reference
└─ RESOLVES_TO → Plate | PlatePanel | Drawing | DrawingRegion

Plate / PlatePanel / Drawing / DrawingRegion
└─ DEPICTS → ArchaeologyObject

ArchaeologyObject
└─ graph traversal gathers:
   Text claims + captions + references + plates + drawings + VLM observations + version evidence

CorrectionCandidate
├─ ABOUT → ArchaeologyObject
└─ SUPPORTED_BY → Evidence
   ├─ EXTRACTED_FROM → Page
   └─ FROM_VERSION   → DocumentVersion

AnalysisRun
└─ PRODUCED → CorrectionCandidate

CorrectionCandidate
└─ HAS_DECISION → ReviewDecision
```

**Critical requirement:** Rule/LLM/VLM orchestration must consume evidence found through this graph. A parallel in-memory relationship structure that is merely written to Neo4j afterward does not satisfy the architecture.

---

## 3. Non-Negotiable MVP Gates

### Gate A — Real graph construction

Given a body PDF and plate PDF registered as real `DocumentVersion` nodes, after ingest Neo4j must contain:

```text
DocumentVersion
→ Page
→ TextBlock/Caption
→ Reference
→ RESOLVES_TO
→ Plate/PlatePanel
```

and at least one:

```text
TextBlock/Caption → MENTIONS → ArchaeologyObject
Plate/PlatePanel  → DEPICTS → ArchaeologyObject
```

The test must query the running Neo4j database after pipeline execution. Checking emitted Cypher strings is insufficient.

### Gate B — Graph is required for analysis

Consistency analysis for an object such as `1지점 청동기시대 6호 석관묘` must obtain its evidence through repository graph traversal.

Representative semantics:

```cypher
MATCH (obj:ArchaeologyObject {id:$object_id})
OPTIONAL MATCH (source)-[:MENTIONS]->(obj)
OPTIONAL MATCH (source)-[:REFERENCES]->(ref:Reference)-[:RESOLVES_TO]->(asset)
OPTIONAL MATCH (asset)-[:DEPICTS]->(obj)
OPTIONAL MATCH (cand:CorrectionCandidate)-[:ABOUT]->(obj)
OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
RETURN ...
```

The orchestrator must pass this graph-retrieved evidence bundle to Rule/LLM/VLM consumers.

**Negative test:** remove a required graph relation. The relevant analysis must become `unresolved`/`manual_review` or fail closed. It must not silently continue using hidden Python lists.

### Gate C — Case 6 canonical identity

With these files present:

```text
4. 조사 후_45.JPG
photo_45.JPG
조사후_45.JPG
```

and a plate PDF containing `【도판 45】`, Neo4j must persist:

```text
Reference(type=plate, number=45)
→ RESOLVES_TO
→ Plate(number=45, raw_identifier="【도판 45】")
```

No `OriginalAsset`, `Evidence`, `identity_evidence`, or canonical target may claim that `4. 조사 후_45.JPG` is Plate 45 solely due to filename digits.

### Gate D — Graph-backed discrepancy

Create one `ArchaeologyObject` with two graph-backed text claims:

```text
Page A: 길이 275cm
Page B: 길이 2.45m
```

Graph-driven consistency analysis must generate exactly one `numeric_value` candidate in `pending_review`, supported by Evidence from both source pages.

Equivalent values:

```text
275cm
2.75m
```

must produce no numeric conflict.

### Gate E — Real review traceability

Every candidate returned by API must support this real Neo4j traversal:

```text
CorrectionCandidate
→ ABOUT → ArchaeologyObject
→ SUPPORTED_BY → Evidence
→ EXTRACTED_FROM → Page
→ FROM_VERSION → DocumentVersion
```

Reference-related candidates must additionally expose:

```text
source
→ REFERENCES → Reference
→ RESOLVES_TO → Plate/Drawing/Region
→ DEPICTS → ArchaeologyObject
```

The UI must render returned graph data only. It must not fabricate relations such as `HAS_BBOX` or `VERIFIED_HASH` unless those relationships truly exist.

### Gate F — Expert decision semantics

All candidates begin `pending_review`. Expert actions append:

```text
accepted
rejected
modified
deferred
```

Previous decisions remain queryable. Metrics use the latest decision while preserving full audit history.

### Gate G — No false-success run

The run must fail/reject when:

- body `DocumentVersion` does not exist;
- stored body file cannot be found;
- parser unexpectedly returns zero pages;
- required canonical graph persistence fails.

Never return normal `completed` with `0 pages / 0 objects / 0 references` because fake IDs or missing paths were substituted.

---

## 4. P0 Implementation Tasks

### Task 1 — Unify canonical IDs

**Files:**
- `backend/app/domain/document_structure.py`
- `backend/app/services/pdf_parser.py`
- `backend/app/graph/review_repository.py`
- `backend/app/graph/canonical_repository.py`

Use exactly one ID source for Page/TextBlock/Caption/Reference. Do not let parser emit `p105_b1` while Neo4j stores `ver_body_p105_b1` and then attempt to match the former.

Required concept:

```python
def page_id(version_id: str, physical_page: int) -> str: ...
def block_id(version_id: str, physical_page: int, order: int) -> str: ...
def caption_id(version_id: str, physical_page: int, order: int) -> str: ...
def reference_id(source_node_id: str, ref_type: str, number: str) -> str: ...
```

All downstream references, mentions, evidence, and API traceability must use the same bound IDs.

### Task 2 — Persist complete body graph

**Files:**
- `backend/app/graph/review_repository.py`
- `backend/app/graph/canonical_repository.py`
- `backend/app/services/proofreading_orchestrator.py`

Persist:

```text
DocumentVersion-[:HAS_PAGE]->Page
Page-[:HAS_BLOCK]->TextBlock
Page-[:HAS_CAPTION]->Caption
TextBlock/Caption-[:REFERENCES]->Reference
TextBlock/Caption-[:MENTIONS]->ArchaeologyObject
```

Fix `MENTIONS` direction to `source → object`.

**Ordering:** save Reference nodes before calling `link_reference_to_target()`. The current `MATCH (ref:Reference...)` cannot create `RESOLVES_TO` when the node does not yet exist.

### Task 3 — Resolve real DocumentVersion inputs

**Files:**
- `backend/app/graph/project_repository.py`
- `backend/app/api/reviews.py`
- `backend/app/api/schemas.py`
- `backend/app/services/proofreading_orchestrator.py`

Add an authoritative repository contract like:

```python
@dataclass(frozen=True)
class VersionInput:
    version_id: str
    document_id: str
    project_id: str
    kind: str
    stage: str
    uri: str
    sha256: str
    mime_type: str
```

No production fallback such as `f"ver_{project_id}_body"`.

Normal browser clients should select DocumentVersions, not arbitrary server filesystem paths.

### Task 4 — Make canonical graph construction an ingest prerequisite

**Files:**
- `backend/app/jobs/worker.py`
- `backend/app/jobs/ingest.py`
- `backend/app/services/proofreading_orchestrator.py`

Ingest must build graph-ready document versions before proofreading claims success.

Body ingest:

```text
Page / TextBlock / Caption / Reference / ArchaeologyObject / MENTIONS
```

Plate ingest:

```text
Plate / PlatePanel
```

Drawing ingest:

```text
Drawing / DrawingRegion
```

Do not swallow graph persistence errors and mark run complete.

### Task 5 — Enforce canonical Plate/Drawing identity

**Files:**
- `backend/app/services/asset_matcher.py`
- `backend/app/services/asset_review_pipeline.py`
- create `backend/app/services/drawing_parser.py`
- `backend/app/services/proofreading_orchestrator.py`

Remove/isolate production use of legacy filename-number matching.

Canonical resolver outputs only:

```text
resolved
missing
unresolved
semantic_review
```

Implement `DrawingParser` for MVP drawing PDFs using explicit publication identifiers such as `【도면 30】`.

Do not claim raw `.ai/.dwg/.dxf` support until deterministic parsing/rendering exists.

### Task 6 — Persist `DEPICTS` and use ArchaeologyObject as semantic join key

**Files:**
- `backend/app/graph/canonical_repository.py`
- `backend/app/services/object_resolver.py`
- `backend/app/services/proofreading_orchestrator.py`

Persist:

```text
TextBlock/Caption-[:MENTIONS]->ArchaeologyObject
Plate/PlatePanel/Drawing/DrawingRegion-[:DEPICTS]->ArchaeologyObject
```

Deterministic caption/title matches can create high-confidence links. Ambiguous mappings remain semantic review and must not be guessed.

### Task 7 — Add graph evidence bundle queries

**Files:**
- `backend/app/graph/canonical_repository.py`
- create `backend/app/domain/evidence_bundle.py`
- `backend/app/services/rule_engine.py`
- `backend/app/services/proofreading_orchestrator.py`

Preferred contract:

```python
@dataclass(frozen=True)
class ObjectEvidenceBundle:
    object_id: str
    canonical_name: str
    text_claims: list[EvidenceData]
    references: list[EvidenceData]
    plate_claims: list[EvidenceData]
    drawing_claims: list[EvidenceData]
    visual_observations: list[EvidenceData]
    version_claims: list[EvidenceData]
```

Repository method:

```python
def get_object_evidence_bundle(object_id: str) -> ObjectEvidenceBundle: ...
```

`RuleEngine` must consume this graph-derived bundle rather than `objects_with_evidences` generated exclusively in memory.

Do not mine generated `rationale` strings as if they were source facts unless explicitly typed as source observations.

### Task 8 — Integrate PageAligner into the graph

Persist:

```text
DocumentVersion(1차)-[:PRECEDES]->DocumentVersion(2차)
DocumentVersion(2차)-[:PRECEDES]->DocumentVersion(3차)

Page(A)-[:ALIGNED_TO {score,status,method,run_id}]->Page(B)
```

Allowed alignment status:

```text
exact | probable | manual_review | unmatched
```

Fix the current DTW preference for unrelated diagonal matches; unrelated pages must not become confident mappings merely because match cost is cheaper than delete+insert.

### Task 9 — Complete actual PlatePanel visual data flow

**Files:**
- `backend/app/services/plate_parser.py`
- `backend/app/services/image_processor.py`
- `backend/app/services/asset_review_pipeline.py`

`PlatePanel.bbox` must represent the actual photo/panel region, not merely the bbox of a circled label (`①`, `②`, etc.).

Required path:

```text
Plate PDF page
→ high-resolution page render
→ panel segmentation
→ PlatePanel.bbox/render_uri
→ crop
→ VLM observation
```

If a region cannot be safely isolated, return insufficient evidence rather than sending unrelated content.

### Task 10 — Make VLM and LLM graph-grounded

VLM input:

```text
canonical Reference
→ RESOLVES_TO
→ canonical PlatePanel/DrawingRegion render
→ VLM
```

VLM cannot create/modify `RESOLVES_TO` or `DEPICTS` identity.

After VLM observations are stored as Evidence, refresh the graph evidence bundle.

LLM should receive only relevant graph-grounded context:

```text
target object
source text blocks
canonical captions/references
rule findings
VLM observations
version evidence
```

Do not use full-document ungrounded input when graph evidence exists.

### Task 11 — Make the production app construct the complete orchestrator

**Files:**
- `backend/app/main.py`
- `.env.example`
- `compose.yml`

The production `ProofreadingOrchestrator` must receive:

```text
ProjectRepository
CanonicalRepository
ReviewRepository
PDFParser
PlateParser
DrawingParser
ObjectResolver
RuleEngine
VLMReviewService
AIReviewService
```

It is not acceptable for production to instantiate only `ProofreadingOrchestrator(review_repo=...)` and still claim graph-backed analysis.

Unify OpenRouter env config (`OPENROUTER_API_KEY` vs `AI_API_KEY`).

### Task 12 — Move canonical analysis to the RQ worker

`POST /api/v1/projects/{id}/runs` should:

```text
validate inputs
→ create AnalysisRun(status=queued)
→ enqueue RQ job
→ return run ID
```

Worker executes canonical graph-first proofreading and updates status.

Large PDF/VLM work must not run inside a long FastAPI HTTP request.

Remove/redirect legacy `/analyze` no-op paths.

### Task 13 — Fix upload UX and run selection

Frontend must explicitly support:

```text
kind: report_body | plate_book | drawing_book
stage: 1차 | 2차 | 3차 | final
```

Run UI chooses real uploaded DocumentVersions. Do not send arbitrary local server paths from browser.

### Task 14 — Restore true expert decision semantics

Keep candidate generation status separate from review decisions.

Candidate generation:

```text
pending_review
```

Decision values:

```text
accepted
rejected
modified
deferred
```

`layout_noise` may remain a rule classification but must not be overloaded as generic expert rejection.

### Task 15 — Make traceability UI render real graph paths

`EvidenceGraphExplorer` must visualize actual API-returned nodes/edges from Neo4j.

Do not synthesize fake nodes/relations when fields are absent.

If the graph only persists bbox/hash as properties, show them as properties—not invented `HAS_BBOX` or `VERIFIED_HASH` edges.

---

## 5. Golden Dataset Requirements

The implementing agent must **not** make the Golden Dataset “pass” by inventing expected archaeological facts.

Current entries labeled `VALID_GROUND_TRUTH` are provisional unless expert confirmation is recorded.

Each final Golden fixture must contain at least:

```yaml
case_id: GT_CASE_006
expert_verified: true
verified_by: "<archaeologist>"
verified_at: "<date>"
source_document_sha256: "..."
body_page: 78
body_text: "... 도판 45·46 ..."
reference:
  type: plate
  number: "45"
canonical_target:
  explicit_identifier: "【도판 45】"
  physical_page: 47
  title: "1지점 청동기시대 6호 석관묘"
forbidden_filename_matches:
  - "4. 조사 후_45.JPG"
expert_note: "Links의 _45는 도판번호가 아님"
```

Case 6 remains `INVALID_GROUND_TRUTH_MAPPING` for the old Links-based experiment and becomes the mandatory canonical regression case for the new system.

---

## 6. Real Neo4j Integration Tests — Mandatory

Create at minimum:

```text
compose.test.yml
backend/tests/integration/test_neo4j_canonical_graph.py
backend/tests/integration/test_case6_real_graph.py
backend/tests/integration/test_graph_driven_consistency.py
backend/tests/integration/test_review_traceability_graph.py
backend/tests/integration/test_version_alignment_graph.py
```

These tests must use a running Neo4j instance, execute the real repositories, then query the database to verify nodes and relationships.

FakeDriver tests remain useful unit tests but are **not** MVP evidence.

### Test 1 — Canonical body/plate graph

Assert relationship counts and actual traversal:

```cypher
MATCH (v:DocumentVersion)-[:HAS_PAGE]->(p:Page)-[:HAS_BLOCK|HAS_CAPTION]->(s)
MATCH (s)-[:REFERENCES]->(r:Reference)-[:RESOLVES_TO]->(plate:Plate)
RETURN v,p,s,r,plate
```

### Test 2 — Case 6 real graph

Assert:

```text
Reference(plate,45)-[:RESOLVES_TO]->Plate(45)
```

and verify that `4. 조사 후_45.JPG` does not appear as canonical identity evidence.

### Test 3 — Graph dependency kill-switch

1. Build a valid object evidence graph.
2. Verify a numeric mismatch candidate is generated.
3. Delete/break the required `MENTIONS` or evidence path.
4. Re-run.
5. Assert analysis no longer produces the same grounded candidate and returns unresolved/manual-review/failure according to contract.

This test proves Neo4j is functionally required rather than decorative.

### Test 4 — Candidate traceability

Persist a candidate and assert the full traversal exists in real DB:

```text
Candidate
→ ABOUT Object
→ SUPPORTED_BY Evidence
→ EXTRACTED_FROM Page
→ FROM_VERSION DocumentVersion
```

### Test 5 — Version graph

Persist 1차/2차/3차 versions and page alignment; verify `PRECEDES` and `ALIGNED_TO` are real relationships.

---

## 7. Required Production Flow

```text
[1] User registers documents
    ├─ report_body / 1차, 2차, 3차/final
    ├─ plate_book / matching publication version
    └─ drawing_book / matching publication version

[2] Ingest worker
    ├─ immutable file + SHA-256
    ├─ body → Page/TextBlock/Caption/Reference
    ├─ plate → Plate/PlatePanel + renders
    ├─ drawing → Drawing/DrawingRegion + renders
    └─ ObjectResolver → ArchaeologyObject + MENTIONS

[3] Canonical graph persistence
    ├─ REFERENCES
    ├─ RESOLVES_TO
    ├─ DEPICTS
    ├─ PRECEDES
    └─ ALIGNED_TO

[4] Proofreading worker — GRAPH FIRST
    ├─ query ArchaeologyObjects for scope
    ├─ graph traversal → ObjectEvidenceBundle
    ├─ RuleEngine(ObjectEvidenceBundle)
    ├─ VLM(canonical render only) → Evidence
    ├─ refresh graph evidence bundle
    ├─ LLM(graph-grounded bundle) → candidate proposals
    └─ persist candidates/evidence/run links

[5] Review API/UI
    ├─ candidate list from Neo4j
    ├─ traceability path from Neo4j
    ├─ source/canonical visual comparison
    └─ append-only ReviewDecision
```

---

## 8. Required Neo4j Query Semantics

### Find canonical references for a source

```cypher
MATCH (source)-[:REFERENCES]->(ref:Reference)
OPTIONAL MATCH (ref)-[:RESOLVES_TO]->(target)
RETURN source, ref, labels(target) AS target_labels, target
```

### Get evidence for one ArchaeologyObject

```cypher
MATCH (obj:ArchaeologyObject {id:$object_id})
OPTIONAL MATCH (source)-[:MENTIONS]->(obj)
OPTIONAL MATCH (page:Page)-[:HAS_BLOCK|HAS_CAPTION]->(source)
OPTIONAL MATCH (version:DocumentVersion)-[:HAS_PAGE]->(page)
OPTIONAL MATCH (source)-[:REFERENCES]->(ref:Reference)-[:RESOLVES_TO]->(asset)
OPTIONAL MATCH (asset)-[:DEPICTS]->(obj)
OPTIONAL MATCH (cand:CorrectionCandidate)-[:ABOUT]->(obj)
OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
RETURN obj, source, page, version, ref, asset, collect(DISTINCT ev) AS evidence
```

If this creates a Cartesian explosion, split it into targeted queries. The semantic requirement is that relationships are queried rather than bypassed.

### Candidate traceability

```cypher
MATCH (cand:CorrectionCandidate {id:$candidate_id})
OPTIONAL MATCH (cand)-[:ABOUT]->(obj:ArchaeologyObject)
OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
OPTIONAL MATCH (ev)-[:EXTRACTED_FROM]->(page:Page)
OPTIONAL MATCH (ev)-[:FROM_VERSION]->(version:DocumentVersion)
RETURN cand, obj, collect(DISTINCT ev), collect(DISTINCT page), collect(DISTINCT version)
```

### Reference canonical path

```cypher
MATCH (source)-[:REFERENCES]->(ref:Reference {id:$reference_id})
OPTIONAL MATCH (ref)-[:RESOLVES_TO]->(asset)
OPTIONAL MATCH (asset)-[:DEPICTS]->(obj:ArchaeologyObject)
RETURN source, ref, asset, obj
```

---

## 9. Explicit Anti-Patterns — Reject PRs That Do These

Reject implementation if any is true:

1. Neo4j is only written at the end; analysis occurs entirely in Python lists/dicts.
2. FakeDriver tests are presented as proof of graph correctness.
3. Run returns `completed` with zero parsed pages because inputs were missing.
4. Reference is linked before its node is persisted.
5. Parser IDs and graph IDs are independently reconstructed.
6. Caption exists in Python but is omitted from Neo4j.
7. `*_45.JPG` becomes `Plate 45` without canonical publication identity.
8. VLM changes `RESOLVES_TO`, creates canonical identity, or directly accepts candidate.
9. LLM receives ungrounded full pages while graph evidence exists.
10. UI displays graph edges that do not exist in Neo4j.
11. `layout_noise` is used as synonym for expert rejection.
12. Golden Dataset is modified by implementation agent to make tests pass without expert verification.
13. `drawing_index=None` remains in production while drawing consistency is claimed complete.
14. Production app instantiates orchestrator without `CanonicalRepository` and still claims graph-backed analysis.
15. Browser passes arbitrary server file paths as normal source selection.
16. Candidate/Evidence IDs can collide across projects/versions.

---

## 10. P1 Follow-ups — Only After Graph Gates Pass

1. Stream large uploads instead of `await upload.read()` for 100MB+ PDFs.
2. Make HWP/HWPX/AI/DWG/DXF support truthful: either implement adapter or mark unsupported for analysis.
3. Add deterministic vector/CAD render path before VLM.
4. Persist model/prompt/preprocessor/request/response/token/cost provenance on AnalysisRun/Evidence.
5. Remove duplicate legacy candidate endpoints and make severity filtering real if UI exposes it.

These must not distract from Gates A–G.

---

## 11. Verification Commands Before Claiming Completion

```bash
# Unit tests
cd backend
pytest tests -q --ignore=tests/integration

# Real Neo4j integration tests
docker compose -f ../compose.yml -f ../compose.test.yml up -d neo4j-test redis
pytest tests/integration -q

# Compose/runtime
pytest ../tests/compose -q

# Frontend
cd ../frontend
npm test -- --run
npm run build

# Unsafe leftovers
cd ..
git grep -n 'f"ver_{project_id}_body"' -- backend || true
git grep -n 'match_reference(' -- backend/app || true
git grep -n 'drawing_index=None' -- backend/app || true
git grep -n 'AI_API_KEY' -- . ':!node_modules' || true
```

Any remaining unsafe match must be explained and proven outside production path.

Also run diagnostic graph queries and preserve output in implementation report:

```cypher
MATCH (n) RETURN labels(n) AS labels, count(*) AS count ORDER BY labels;
```

```cypher
MATCH ()-[r]->() RETURN type(r) AS relation, count(*) AS count ORDER BY relation;
```

```cypher
MATCH (source)-[:REFERENCES]->(ref:Reference)-[:RESOLVES_TO]->(target)
RETURN labels(source), ref.ref_type, ref.number, labels(target), target.number
LIMIT 50;
```

```cypher
MATCH (source)-[:MENTIONS]->(obj:ArchaeologyObject)<-[:DEPICTS]-(asset)
RETURN source.id, obj.canonical_name, labels(asset), asset.id
LIMIT 50;
```

A system with many nodes but `RESOLVES_TO`, `MENTIONS`, or `DEPICTS` counts near zero is **not** graph-functional.

---

## 12. Final Handoff Checklist

Before coding:

- [ ] Read this document completely.
- [ ] Read current Neo4j design/spec in `docs/superpowers/specs/`.
- [ ] Inspect current `windows-docker-foundation` branch; do not assume old review is exact.
- [ ] Use TDD for each task.
- [ ] Do not modify Golden truth merely to satisfy tests.

During coding:

- [ ] Keep one authoritative production path.
- [ ] Prefer canonical graph relationships over duplicate in-memory relationship maps.
- [ ] Add real Neo4j integration coverage whenever repository relationships change.
- [ ] Keep VLM/LLM subordinate to deterministic identity and expert review.
- [ ] Preserve source hash/page/bbox provenance.

Before declaring done:

- [ ] Gate A real graph construction passes.
- [ ] Gate B analysis demonstrably depends on graph traversal.
- [ ] Gate C Case 6 passes against real Neo4j.
- [ ] Gate D graph-backed numeric discrepancy passes.
- [ ] Gate E candidate traceability returns real graph paths.
- [ ] Gate F review decisions preserve semantics/history.
- [ ] Gate G false-success run is impossible.
- [ ] Full unit/integration/frontend/compose verification has run.
- [ ] Final report includes Neo4j node/relationship counts and sample canonical traversal output.

---

## 13. Core Success Statement

> **The archaeology review system cannot perform its core document/photo/drawing consistency analysis correctly if the canonical Neo4j graph is missing or broken, because canonical identity, object evidence aggregation, cross-source consistency, candidate provenance, and expert traceability all depend on real Neo4j relationships.**

If the system can still produce the same “successful” review while relationships such as `REFERENCES`, `RESOLVES_TO`, `MENTIONS`, and `DEPICTS` are absent, then the implementation has missed the central architecture and must not be accepted.
