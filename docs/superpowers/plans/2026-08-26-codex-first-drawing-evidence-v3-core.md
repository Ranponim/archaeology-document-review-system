# Codex-first Drawing Evidence v3 Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Codex-first drawing identity resolver that sends every source drawing through one grounded multimodal Codex decision path while preserving deterministic fail-closed safety and measurable operational gates.

**Architecture:** Keep v1/v2 unchanged and add `drawing-evidence-v3`. Local code extracts source/body evidence, ranks a broad Top-10 candidate set, renders source/candidate crops when available, calls Codex synchronously for every source with at most one Top-20 expansion, validates the closed-world JSON response, then routes to `AUTO_VERIFIED`, `REVIEW_REQUIRED`, or `UNRESOLVED`. Neo4j persists candidates, evidence, Codex decisions, and final provenance; real API evaluation remains local and `/src` read-only.

**Tech Stack:** Python 3, PyMuPDF, Neo4j, httpx synchronous client, OpenAI Responses API, pytest, existing FastAPI/service assembly.

**Spec:** `docs/superpowers/specs/2026-08-26-codex-first-drawing-evidence-v3-design.md`

## Global Constraints

- Every drawing source must be submitted to Codex in v3; no deterministic shortcut bypasses the Codex call.
- Codex is the only AI service in the first v3 implementation; do not add a separate VLM, LLM judge, cross-encoder, embedding service, vector DB, GNN, or learned calibrator.
- External payload contains only the current source render/crop, candidate crops, captions/minimal context, structured facts, and evidence IDs.
- `/src` is read-only; generated images/JSON/reports must be outside the source root.
- Filename/path/sequence evidence cannot independently create `AUTO_VERIFIED`.
- Explicit publication-kind, site/grid, and feature-type+feature-number contradictions can never be auto-promoted.
- Invented candidate IDs/evidence IDs, malformed output, API failure, assignment conflict, `ambiguous`, or insufficient evidence fail closed.
- Candidate Recall@10 target is >=99% on human-verified gold-known rows.
- Operational target is 75-85% auto coverage at >=99% auto precision, review <=25%, unsafe-promotion counters all zero.
- v1/v2 remain available and the production default is unchanged until explicit later rollout approval.
- Hermetic CI never calls OpenAI; live Codex evaluation is local only.

---

## File Structure

### New files
- `backend/app/domain/drawing_evidence_v3.py` — v3 evidence/body/source/candidate/Codex/result contracts.
- `backend/app/services/drawing_visual_extractor.py` — Adobe-free source rendering and body-PDF crop extraction.
- `backend/app/services/drawing_candidate_generator_v3.py` — hard filtering and broad transparent Top-K ranking.
- `backend/app/services/codex_drawing_resolver_client.py` — synchronous Responses API client and strict response validator.
- `backend/app/services/drawing_evidence_resolver_v3.py` — mandatory Codex orchestration, bounded expansion, safety gate, final states.
- `tools/build_drawing_gold_template.py` — unknown-first human gold template generator.
- `tools/evaluate_drawing_evidence_v3.py` — gold-aware local v3 evaluator.

### Existing files modified
- `backend/app/graph/drawing_evidence_repository.py` — v3 body metadata and Codex provenance persistence.
- `backend/app/services/drawing_evidence_corpus_service.py` — explicit v3 path and shadow behavior.
- `backend/app/config.py` — v3 and Codex config.
- `backend/app/main.py` — dependency wiring only.

### Tests
- `backend/tests/test_drawing_evidence_v3_models.py`
- `backend/tests/test_drawing_visual_extractor.py`
- `backend/tests/test_drawing_candidate_generator_v3.py`
- `backend/tests/test_codex_drawing_resolver_client.py`
- `backend/tests/test_drawing_evidence_graph_resolver_v3.py`
- `backend/tests/test_drawing_evidence_repository_v3.py`
- `backend/tests/test_drawing_evidence_corpus_service_v3.py`
- `backend/tests/test_drawing_evidence_resolver_config.py`
- `backend/tests/test_drawing_evidence_v3_evaluator_contract.py`

---

### Task 1: Define exact v3 domain contracts

**Files:**
- Create: `backend/app/domain/drawing_evidence_v3.py`
- Test: `backend/tests/test_drawing_evidence_v3_models.py`

**Interfaces:**
- Produces `DrawingV3Evidence`, `DrawingVisualRegion`, `BodyDrawingEvidencePacket`, `DrawingSourceEvidencePacket`, `DrawingCandidatePacket`, `CodexDrawingDecision`, `DrawingV3SourceResult`, `DrawingV3Resolution`.

- [ ] **Step 1: Write failing contract test**

```python
from app.domain.drawing_evidence_v3 import (
    BodyDrawingEvidencePacket,
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
    DrawingV3SourceResult,
    DrawingVisualRegion,
)


def test_v3_contracts_carry_body_bbox_and_evidence_family():
    ev = DrawingV3Evidence(
        id="ev:feature", family="archaeology_signature",
        method="exact_feature_pair", value="토광묘:1", supports=True, weak=False,
    )
    body = BodyDrawingEvidencePacket(
        publication_kind="drawing", number="52",
        raw_texts=("도면 52. 2지점 조선시대 1호 토광묘",),
        source_node_ids=("block-52",), source_sha256="bodysha",
        document_version_id="version-1", physical_page=12,
        source_bbox=(10.0, 20.0, 110.0, 220.0), visual_regions=(),
    )
    assert body.physical_page == 12
    assert ev.family == "archaeology_signature"
```

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_v3_models.py`

Expected: module missing.

- [ ] **Step 3: Implement the exact contracts**

```python
from dataclasses import dataclass, field
from typing import Literal

from app.domain.drawing_evidence import ContextFact

CodexVerdict = Literal["match", "ambiguous", "none"]
DrawingV3Status = Literal["AUTO_VERIFIED", "REVIEW_REQUIRED", "UNRESOLVED"]

@dataclass(frozen=True, slots=True)
class DrawingV3Evidence:
    id: str
    family: str
    method: str
    value: str
    supports: bool = True
    weak: bool = False

@dataclass(frozen=True, slots=True)
class DrawingVisualRegion:
    region_id: str
    image_path: str
    page: int | None
    bbox: tuple[float, float, float, float] | None
    confidence: float
    source_sha256: str | None = None

@dataclass(frozen=True, slots=True)
class BodyDrawingEvidencePacket:
    publication_kind: str
    number: str
    raw_texts: tuple[str, ...]
    source_node_ids: tuple[str, ...]
    source_sha256: str | None
    document_version_id: str | None
    physical_page: int | None
    source_bbox: tuple[float, float, float, float] | None
    visual_regions: tuple[DrawingVisualRegion, ...]

@dataclass(frozen=True, slots=True)
class DrawingSourceEvidencePacket:
    source_asset_id: str
    source_sha256: str
    original_name: str
    source_path: str
    raw_text: str
    publication_kind: str | None
    internal_numbers: tuple[str, ...]
    facts: tuple[ContextFact, ...]
    visual_regions: tuple[DrawingVisualRegion, ...]
    evidence: tuple[DrawingV3Evidence, ...]

@dataclass(frozen=True, slots=True)
class DrawingCandidatePacket:
    candidate_id: str
    publication_kind: str
    number: str
    raw_texts: tuple[str, ...]
    facts: tuple[ContextFact, ...]
    visual_regions: tuple[DrawingVisualRegion, ...]
    local_score: float
    evidence: tuple[DrawingV3Evidence, ...]
    hard_contradiction: bool
    strong_contradiction_ids: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CodexDrawingDecision:
    run_id: str
    model: str
    verdict: CodexVerdict
    candidate_id: str | None
    confidence: float
    cited_support_ids: tuple[str, ...]
    cited_contradiction_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    summary: str

@dataclass(frozen=True, slots=True)
class DrawingV3SourceResult:
    source_asset_id: str
    status: DrawingV3Status
    candidates: tuple[DrawingCandidatePacket, ...]
    decision: CodexDrawingDecision | None
    selected_candidate_id: str | None
    diagnostics: dict[str, object] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class DrawingV3Resolution:
    source_results: tuple[DrawingV3SourceResult, ...]
    diagnostics: dict[str, object] = field(default_factory=dict)
```

- [ ] **Step 4: Run and verify GREEN**

Run: `cd backend && pytest -q tests/test_drawing_evidence_v3_models.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/drawing_evidence_v3.py backend/tests/test_drawing_evidence_v3_models.py
git commit -m "feat: add drawing evidence v3 contracts"
```

---

### Task 2: Expose body page/bbox metadata and render visual regions

**Files:**
- Create: `backend/app/services/drawing_visual_extractor.py`
- Modify: `backend/app/graph/drawing_evidence_repository.py`
- Test: `backend/tests/test_drawing_visual_extractor.py`
- Test: `backend/tests/test_drawing_evidence_repository_v3.py`

**Interfaces:**
- Repository produces `list_body_drawing_v3_contexts(project_id: str) -> list[BodyDrawingEvidencePacket]`.
- Extractor produces `render_source(...) -> DrawingVisualRegion` and `crop_body_region(...) -> DrawingVisualRegion`.
- v1/v2 `list_body_drawing_contexts()` remains unchanged.

- [ ] **Step 1: Write RED repository metadata test**

Use a fake Neo4j record with `publication_kind="drawing"`, `number="52"`, `physical_page=12`, `source_bbox=[10,20,110,220]`, `document_version_id="version-1"`. Assert `list_body_drawing_v3_contexts()` returns exactly those values in `BodyDrawingEvidencePacket` and preserves one-reference=one-mention grouping.

- [ ] **Step 2: Write RED PyMuPDF render/crop test**

```python
def test_render_source_and_crop_body_region(tmp_path):
    pdf = make_tiny_pdf(tmp_path / "sample.ai")
    extractor = DrawingVisualExtractor(render_scale=2.0)
    source = extractor.render_source(pdf, tmp_path / "out", "asset-1", "sha")
    crop = extractor.crop_body_region(
        pdf, tmp_path / "out", "body:52", page_number=1,
        bbox=(10.0, 10.0, 190.0, 190.0), source_sha256="bodysha",
    )
    assert Path(source.image_path).exists()
    assert Path(crop.image_path).exists()
```

- [ ] **Step 3: Run and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_visual_extractor.py tests/test_drawing_evidence_repository_v3.py`

Expected: method/module missing.

- [ ] **Step 4: Implement a separate v3 body query**

Do not overload the v1/v2 return type. Query the latest body document version, return `v.id AS document_version_id`, page physical number, source bbox, source/reference text, neighbor text, source SHA. Group by `(publication_kind, number, source_id)` and construct `BodyDrawingEvidencePacket` with `visual_regions=()`.

- [ ] **Step 5: Implement deterministic rendering/cropping**

```python
class DrawingVisualExtractor:
    def __init__(self, render_scale: float = 2.0) -> None:
        self._matrix = pymupdf.Matrix(render_scale, render_scale)

    def render_source(self, path, output_dir, source_asset_id, source_sha256):
        output_dir.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open(str(path))
        try:
            pix = doc[0].get_pixmap(matrix=self._matrix, alpha=False)
            target = output_dir / f"source-{source_asset_id}.png"
            pix.save(str(target))
            return DrawingVisualRegion(f"source:{source_asset_id}", str(target), 1, None, 1.0, source_sha256)
        finally:
            doc.close()
```

`crop_body_region()` uses `page_number - 1`, clamps `pymupdf.Rect(*bbox)` to `page.rect`, rejects empty clips with `ValueError`, and writes outside `/src`. A missing/invalid bbox yields no visual region; it never creates identity evidence.

- [ ] **Step 6: Run focused regression tests**

Run: `cd backend && pytest -q tests/test_drawing_visual_extractor.py tests/test_drawing_evidence_repository_v3.py tests/test_drawing_evidence_repository_v2_context.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/drawing_visual_extractor.py backend/app/graph/drawing_evidence_repository.py backend/tests/test_drawing_visual_extractor.py backend/tests/test_drawing_evidence_repository_v3.py
git commit -m "feat: add v3 drawing visual packets"
```

---

### Task 3: Build transparent high-recall Top-10/Top-20 candidates

**Files:**
- Create: `backend/app/services/drawing_candidate_generator_v3.py`
- Test: `backend/tests/test_drawing_candidate_generator_v3.py`

**Interfaces:**
- `generate(source: DrawingSourceEvidencePacket, bodies: list[BodyDrawingEvidencePacket], limit: int = 10) -> tuple[DrawingCandidatePacket, ...]`
- `expand(..., existing_candidate_ids: set[str], limit: int = 20) -> tuple[DrawingCandidatePacket, ...]`

- [ ] **Step 1: Write RED hard-filter and high-recall synthetic tests**

```python
def test_feature_pair_contradiction_is_removed_but_missing_feature_is_kept(generator):
    source = source_packet("2지점 조선시대 1호 토광묘")
    rows = generator.generate(source, [
        body("51", "2지점 조선시대 2호 토광묘"),
        body("52", "2지점 조선시대 1호 토광묘 평단면"),
        body("53", "2지점 평단면"),
    ])
    assert "51" not in [r.number for r in rows]
    assert rows[0].number == "52"
    assert "53" in [r.number for r in rows]
```

Add a 25-candidate test proving Top-10 retains the correct candidate and Top-20 expansion is a duplicate-free superset.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_drawing_candidate_generator_v3.py`

Expected: module missing.

- [ ] **Step 3: Implement hard filters and explicit rank evidence**

Use the existing `DrawingContextNormalizer`. Hard-filter only explicit publication-kind, site, grid, and feature-type+feature-number contradictions. Missing fields are not contradictions.

Use transparent retrieval weights only for ordering:

```python
WEIGHTS = {
    "site_point": 8.0, "grid": 10.0, "feature_pair": 10.0,
    "period": 4.0, "drawing_type": 3.0, "map_type": 4.0,
    "year": 4.0, "token_overlap": 2.0,
    "sequence_neighbor": 1.0, "filename": 0.25, "path": 0.25,
}
```

Create `DrawingV3Evidence` for every contribution. Mark filename/path/sequence evidence `weak=True`; all structured/text evidence `weak=False`. Numeric rank score is never interpreted as probability.

- [ ] **Step 4: Run v3 and v2 regression tests**

Run: `cd backend && pytest -q tests/test_drawing_candidate_generator_v3.py tests/test_drawing_evidence_graph_resolver_v2.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/drawing_candidate_generator_v3.py backend/tests/test_drawing_candidate_generator_v3.py
git commit -m "feat: add v3 drawing candidate retrieval"
```

---

### Task 4: Add the synchronous Codex multimodal client

**Files:**
- Create: `backend/app/services/codex_drawing_resolver_client.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_codex_drawing_resolver_client.py`
- Test: `backend/tests/test_drawing_evidence_resolver_config.py`

**Interfaces:**
- `CodexDrawingResolverConfig.from_env()`.
- `CodexDrawingResolverClient.resolve(source, candidates) -> CodexDrawingDecision` is synchronous because `EvidenceGraphReferenceCorpusService._adobe_free_visuals()` is synchronous.
- Config keys: `OPENAI_API_KEY`, `DRAWING_CODEX_MODEL`, `DRAWING_CODEX_TIMEOUT_SECONDS`, `DRAWING_CODEX_AUTO_CONFIDENCE`, `DRAWING_CODEX_MAX_CANDIDATES`, `DRAWING_CODEX_MAX_EXPANSIONS`.

- [ ] **Step 1: Write RED request/validation tests with injected `httpx.Client` transport**

Test closed-world prompt, source/candidate `input_image` entries, `match`, `ambiguous`, `none`, invented candidate ID, invented evidence ID, malformed JSON, invalid confidence, one retry, and typed failure after retry.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_codex_drawing_resolver_client.py tests/test_drawing_evidence_resolver_config.py`

Expected: client/config missing.

- [ ] **Step 3: Implement config**

```python
@dataclass(frozen=True, slots=True)
class CodexDrawingResolverConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1/responses"
    timeout_seconds: float = 60.0
    auto_confidence: float = 0.95
    max_candidates: int = 10
    max_expansions: int = 1
```

Do not alter existing OpenRouter config. Tests inject config and transport; live construction requires `OPENAI_API_KEY`.

- [ ] **Step 4: Implement synchronous Responses API serialization**

Serialize source/candidate PNGs as data URLs plus a closed-world text packet listing only submitted candidate/evidence IDs. Parse structured JSON into `CodexDrawingDecision`.

Validator:

```python
if verdict == "match" and candidate_id not in submitted_candidate_ids:
    raise CodexDrawingDecisionError("invented candidate id")
if not set(cited_support_ids) <= submitted_evidence_ids:
    raise CodexDrawingDecisionError("invented support evidence id")
if not set(cited_contradiction_ids) <= submitted_evidence_ids:
    raise CodexDrawingDecisionError("invented contradiction evidence id")
if not 0.0 <= confidence <= 1.0:
    raise CodexDrawingDecisionError("invalid confidence")
```

- [ ] **Step 5: Run GREEN**

Run: `cd backend && pytest -q tests/test_codex_drawing_resolver_client.py tests/test_drawing_evidence_resolver_config.py`

Expected: PASS with zero network traffic.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/codex_drawing_resolver_client.py backend/app/config.py backend/tests/test_codex_drawing_resolver_client.py backend/tests/test_drawing_evidence_resolver_config.py
git commit -m "feat: add Codex drawing resolver client"
```

---

### Task 5: Orchestrate mandatory Codex decisions and final states

**Files:**
- Create: `backend/app/services/drawing_evidence_resolver_v3.py`
- Test: `backend/tests/test_drawing_evidence_graph_resolver_v3.py`

**Interfaces:**
- Synchronous `resolve_observations(corpus_id, sources, bodies, body_pdf_path=None, render_dir=None) -> DrawingV3Resolution`.
- Every source calls the Codex client at least once, including explicit internal-ID sources.

- [ ] **Step 1: Write RED state-transition matrix**

```python
@pytest.mark.parametrize("verdict,confidence,hard,expected", [
    ("match", 0.99, False, "AUTO_VERIFIED"),
    ("match", 0.70, False, "REVIEW_REQUIRED"),
    ("match", 0.99, True, "REVIEW_REQUIRED"),
    ("ambiguous", 0.80, False, "REVIEW_REQUIRED"),
    ("none", 0.20, False, "UNRESOLVED"),
])
def test_v3_final_states(verdict, confidence, hard, expected): ...
```

Also assert: mandatory call count; explicit internal ID still calls Codex; one Top-20 expansion maximum; repeated client error -> review; duplicate target selections route losing sources to review.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_graph_resolver_v3.py`

Expected: resolver missing.

- [ ] **Step 3: Implement the exact safety gate**

```python
def final_status(candidate, decision):
    if decision.verdict == "none":
        return "UNRESOLVED"
    if decision.verdict != "match" or candidate is None:
        return "REVIEW_REQUIRED"
    if candidate.hard_contradiction or decision.confidence < self._auto_confidence:
        return "REVIEW_REQUIRED"
    evidence_by_id = {ev.id: ev for ev in candidate.evidence}
    cited = [evidence_by_id[eid] for eid in decision.cited_support_ids if eid in evidence_by_id]
    families = {ev.family for ev in cited}
    nonweak = [ev for ev in cited if not ev.weak]
    if len(families) < 2 or not nonweak:
        return "REVIEW_REQUIRED"
    return "AUTO_VERIFIED"
```

For source-level evidence cited by Codex, merge source and candidate evidence maps before validation. Missing IDs were already rejected by the client.

- [ ] **Step 4: Implement bounded expansion and target conflict policy**

Call Top-10 first. On `ambiguous`, `none`, or typed invalid-decision failure that may indicate insufficient packet, expand once to Top-20 and call again. Never exceed `max_expansions=1`.

For multiple sources selecting one exclusive target, retain in this order: matching explicit internal identifier, then higher Codex confidence, then greater count of nonweak cited evidence. All losing sources become `REVIEW_REQUIRED`; no silent duplicate target.

- [ ] **Step 5: Run v3/v2 tests**

Run: `cd backend && pytest -q tests/test_drawing_evidence_graph_resolver_v3.py tests/test_drawing_evidence_graph_resolver_v2.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/drawing_evidence_resolver_v3.py backend/tests/test_drawing_evidence_graph_resolver_v3.py
git commit -m "feat: add Codex-first drawing resolver v3"
```

---

### Task 6: Persist v3 candidates, Codex decisions, and safe targets

**Files:**
- Modify: `backend/app/graph/drawing_evidence_repository.py`
- Test: `backend/tests/test_drawing_evidence_repository_v3.py`
- Create: `backend/tests/integration/test_drawing_evidence_repository_v3_neo4j.py`

**Interfaces:**
- `save_v3_resolution(project_id: str, corpus_id: str, resolution: DrawingV3Resolution, auto_promote: bool) -> None`.
- Shadow mode persists all v3 evidence/decisions but creates no new v3 TARGETS.

- [ ] **Step 1: Write RED payload tests**

Assert decision payload stores run/model/verdict/confidence/reason codes/cited evidence/final status. Assert review/unresolved and shadow AUTO rows create zero TARGETS payloads.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_repository_v3.py`

Expected: `save_v3_resolution` missing.

- [ ] **Step 3: Implement graph persistence**

Persist:

```text
(OriginalAsset)-[:HAS_CODEX_DECISION]->(CodexDecision)
(CodexDecision)-[:CONSIDERED]->(DrawingCandidate)
(CodexDecision)-[:SELECTED]->(DrawingCandidate)        # match only
(CodexDecision)-[:CITES_SUPPORT]->(ResolutionEvidence)
(CodexDecision)-[:CITES_CONTRADICTION]->(ResolutionEvidence)
```

Use `resolverVersion="drawing-evidence-v3"`. Preserve v1/v2 nodes. Only `AUTO_VERIFIED` with `auto_promote=True`, or later human-verified results, may create derived TARGETS.

- [ ] **Step 4: Add Neo4j integration test**

Persist one AUTO and one REVIEW case; assert decisions/citation edges exist for both, and only non-shadow safe AUTO gets TARGETS.

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest -q tests/test_drawing_evidence_repository_v3.py tests/integration/test_drawing_evidence_repository_v3_neo4j.py`

Expected: PASS where Neo4j integration is enabled.

- [ ] **Step 6: Commit**

```bash
git add backend/app/graph/drawing_evidence_repository.py backend/tests/test_drawing_evidence_repository_v3.py backend/tests/integration/test_drawing_evidence_repository_v3_neo4j.py
git commit -m "feat: persist Codex drawing provenance"
```

---

### Task 7: Wire explicit v3 shadow mode into the synchronous corpus service

**Files:**
- Modify: `backend/app/services/drawing_evidence_corpus_service.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_drawing_evidence_corpus_service_v3.py`
- Test: `backend/tests/test_drawing_evidence_resolver_config.py`

**Interfaces:**
- `DRAWING_EVIDENCE_RESOLVER_VERSION=v3` selects v3.
- `DRAWING_EVIDENCE_V3_AUTO_PROMOTE=false` default.
- `EvidenceGraphReferenceCorpusService._adobe_free_visuals()` remains synchronous.

- [ ] **Step 1: Write RED config/service tests**

```python
def test_default_stays_v1_and_v3_is_explicit(monkeypatch):
    monkeypatch.delenv("DRAWING_EVIDENCE_RESOLVER_VERSION", raising=False)
    assert get_drawing_evidence_resolver_version() == "v1"
    monkeypatch.setenv("DRAWING_EVIDENCE_RESOLVER_VERSION", "v3")
    assert get_drawing_evidence_resolver_version() == "v3"


def test_v3_auto_promote_defaults_false(monkeypatch):
    monkeypatch.delenv("DRAWING_EVIDENCE_V3_AUTO_PROMOTE", raising=False)
    assert get_drawing_evidence_v3_auto_promote() is False
```

Service test uses fake sync v3 resolver and asserts every source is processed, decisions persist, and shadow mode returns no new v3 canonical targets.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_corpus_service_v3.py tests/test_drawing_evidence_resolver_config.py`

Expected: v3 assembly missing.

- [ ] **Step 3: Add v3 aliases/shadow getter**

Aliases: `v3` and `drawing-evidence-v3`. Unknown version error lists v1/v2/v3. Boolean getter defaults false.

- [ ] **Step 4: Wire v3 dependencies lazily**

Construct `CodexDrawingResolverClient` only when v3 is selected. Inject `DrawingCandidateGeneratorV3`, `DrawingVisualExtractor`, and `DrawingEvidenceResolverV3`. Do not construct OpenAI client for v1/v2.

Get v3 body packets from `list_body_drawing_v3_contexts()`. If a body PDF path is available through the existing document/storage path in the current service assembly, render body crops; if not, leave `visual_regions=()` and continue with text/structured evidence exactly as the spec failure policy requires. Local evaluator always supplies the real body PDF path.

- [ ] **Step 5: Run service/config regressions**

Run: `cd backend && pytest -q tests/test_drawing_evidence_corpus_service_v3.py tests/test_drawing_evidence_corpus_service_v2.py tests/test_drawing_evidence_resolver_config.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/drawing_evidence_corpus_service.py backend/app/config.py backend/app/main.py backend/tests/test_drawing_evidence_corpus_service_v3.py backend/tests/test_drawing_evidence_resolver_config.py
git commit -m "feat: wire drawing evidence v3 shadow mode"
```

---

### Task 8: Add human-gold template and local v3 evaluator

**Files:**
- Create: `tools/build_drawing_gold_template.py`
- Create: `tools/evaluate_drawing_evidence_v3.py`
- Create: `backend/tests/fixtures/drawing_evidence_v3_gold_sample.json`
- Create: `backend/tests/test_drawing_evidence_v3_evaluator_contract.py`

**Interfaces:**
- Gold row: `{source, publication_kind, number, verification, notes}` with `verification` exactly `human` or `unknown`.
- Metrics: Recall@5/10/20, Codex Top-1, ambiguous/none rates, auto coverage, auto precision, review rate, invalid-response count, hard-contradiction promoted, filename-only promoted, kind collision, API-unsafe-promotion count.

- [ ] **Step 1: Write RED evaluator tests**

```python
def test_unknown_gold_rows_are_excluded_from_accuracy():
    metrics = summarize_gold([
        {"source": "a.ai", "publication_kind": "drawing", "number": "52", "verification": "human", "notes": ""},
        {"source": "b.ai", "publication_kind": None, "number": None, "verification": "unknown", "notes": ""},
    ])
    assert metrics["gold_known"] == 1
```

Also test output-under-source-root rejection and separate coverage/precision computation.

- [ ] **Step 2: Run RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_v3_evaluator_contract.py`

Expected: tools/helpers missing.

- [ ] **Step 3: Implement unknown-first gold template generator**

CLI:

```text
python tools/build_drawing_gold_template.py --source-root src --output docs/local_drawing_evidence_v3_gold.json
```

Every row starts with `verification="unknown"`, `publication_kind=null`, `number=null`. Never populate truth from filename number.

- [ ] **Step 4: Implement evaluator with fake/live modes**

CLI:

```text
python tools/evaluate_drawing_evidence_v3.py \
  --source-root src \
  --gold docs/local_drawing_evidence_v3_gold.json \
  --output-json docs/local_drawing_evidence_v3_metrics.json \
  --output-report docs/local_drawing_evidence_v3_report.md \
  --live-codex
```

Without `--live-codex`, tests inject deterministic fake decisions. With live mode, require `OPENAI_API_KEY`. Follow the existing evaluator’s Python-path bootstrap and source-root read-only guard.

- [ ] **Step 5: Run evaluator tests**

Run: `cd backend && pytest -q tests/test_drawing_evidence_v3_evaluator_contract.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/build_drawing_gold_template.py tools/evaluate_drawing_evidence_v3.py backend/tests/fixtures/drawing_evidence_v3_gold_sample.json backend/tests/test_drawing_evidence_v3_evaluator_contract.py
git commit -m "test: add drawing evidence v3 gold evaluator"
```

---

### Task 9: Verify hermetic CI and local live acceptance

**Files:**
- Generated locally after human review:
  - `docs/local_drawing_evidence_v3_gold.json`
  - `docs/local_drawing_evidence_v3_metrics.json`
  - `docs/local_drawing_evidence_v3_report.md`

- [ ] **Step 1: Run focused compile/tests**

```powershell
cd backend
python -m compileall -q app
pytest -q `
  tests/test_drawing_evidence_v3_models.py `
  tests/test_drawing_visual_extractor.py `
  tests/test_drawing_candidate_generator_v3.py `
  tests/test_codex_drawing_resolver_client.py `
  tests/test_drawing_evidence_graph_resolver_v3.py `
  tests/test_drawing_evidence_repository_v3.py `
  tests/test_drawing_evidence_corpus_service_v3.py `
  tests/test_drawing_evidence_resolver_config.py `
  tests/test_drawing_evidence_v3_evaluator_contract.py
cd ..
```

Expected: PASS.

- [ ] **Step 2: Run full repository CI-equivalent suites**

Required green jobs: `backend-hermetic`, `frontend`, `neo4j-e2e`. Real OpenAI traffic remains disabled.

- [ ] **Step 3: Build and manually complete the current-source gold file locally**

```powershell
python tools/build_drawing_gold_template.py `
  --source-root src `
  --output docs/local_drawing_evidence_v3_gold.json
```

Human-review every defensible source/body identity. Mark only defensible rows `verification="human"`; uncertain rows stay `unknown`.

- [ ] **Step 4: Run live Codex evaluation in shadow mode**

```powershell
$env:DRAWING_EVIDENCE_RESOLVER_VERSION="v3"
$env:DRAWING_EVIDENCE_V3_AUTO_PROMOTE="false"
python tools/evaluate_drawing_evidence_v3.py `
  --source-root src `
  --gold docs/local_drawing_evidence_v3_gold.json `
  --output-json docs/local_drawing_evidence_v3_metrics.json `
  --output-report docs/local_drawing_evidence_v3_report.md `
  --live-codex
```

- [ ] **Step 5: Apply fixed gates**

Pass only when gold-known rows achieve Recall@10 >=99%, auto coverage 75-85%, auto precision >=99%, review <=25%, and all unsafe counters are zero. If Recall@10 fails, improve Task 3 retrieval. If precision fails, tighten routing/threshold based on measured gold confidence buckets. If coverage fails while precision passes, remain shadow/review-only. Do not add another AI model under this plan and do not lower safety gates.

- [ ] **Step 6: Commit measured local artifacts only after human gold review/live run**

```bash
git add docs/local_drawing_evidence_v3_gold.json docs/local_drawing_evidence_v3_metrics.json docs/local_drawing_evidence_v3_report.md
git commit -m "test: record local drawing evidence v3 acceptance"
```

- [ ] **Step 7: Preserve rollout/merge gates**

Do not set `DRAWING_EVIDENCE_V3_AUTO_PROMOTE=true`, do not change the production default, and do not merge PR #47 or PR #1 without explicit user approval.
