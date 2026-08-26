# Codex-first Drawing Evidence v3 Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Codex-first drawing identity resolver that sends every source drawing through one grounded multimodal Codex decision path while preserving deterministic fail-closed safety and measurable operational gates.

**Architecture:** Keep v1/v2 unchanged and add a new `drawing-evidence-v3` path. Local code extracts source/body evidence, produces a broad Top-10 candidate packet, renders source/candidate crops, calls Codex once per source with at most one Top-20 expansion, validates the closed-world JSON response, then routes to `AUTO_VERIFIED`, `REVIEW_REQUIRED`, or `UNRESOLVED`. Neo4j persists candidate evidence, Codex decisions, and final provenance; real API evaluation remains local and `/src` read-only.

**Tech Stack:** Python 3, FastAPI service assembly, PyMuPDF, Neo4j, httpx, OpenAI Responses API, pytest, NetworkX only where existing global assignment logic remains useful.

**Spec:** `docs/superpowers/specs/2026-08-26-codex-first-drawing-evidence-v3-design.md`

## Global Constraints

- Every drawing source must be submitted to Codex in v3; no deterministic shortcut may bypass the call.
- Codex is the only AI model/service in the first v3 implementation; do not add a separate VLM, LLM judge, cross-encoder, embedding service, vector DB, GNN, or learned calibrator.
- External payload is limited to the current source render/crop plus candidate crops, captions/minimal context, structured facts, and evidence IDs.
- `/src` is read-only; generated images, JSON, and reports must be written outside the source root.
- Filename/path/sequence evidence cannot independently create `AUTO_VERIFIED`.
- Explicit publication-kind, site/grid, and feature-type+feature-number hard contradictions can never be auto-promoted.
- Invalid/invented candidate IDs or evidence IDs from Codex invalidate the decision.
- Codex `ambiguous`/`none`, repeated transport/format failure, assignment conflict, or insufficient evidence must fail closed.
- Candidate Recall@10 target is >= 99% on human-verified gold-known rows.
- Operational target is 75-85% auto coverage at >= 99% auto precision, with human review <= 25% and all unsafe-promotion counters equal to zero.
- v1/v2 remain available and production default remains unchanged until local `/src` v3 acceptance passes.
- Hermetic CI uses fakes/mocks only; real Codex/API evaluation is local.

---

## File Structure

### New core files

- `backend/app/domain/drawing_evidence_v3.py` — v3-only packet, visual-region, Codex-decision, and per-source-result types so v1/v2 models stay stable.
- `backend/app/services/drawing_visual_extractor.py` — Adobe-free source rendering and body-PDF crop extraction from existing page/source bboxes.
- `backend/app/services/drawing_candidate_generator_v3.py` — hard filtering, broad deterministic ranking, Top-10/Top-20 candidate packet creation.
- `backend/app/services/codex_drawing_resolver_client.py` — OpenAI Responses API request construction, image serialization, response parsing, and bounded retry.
- `backend/app/services/drawing_evidence_resolver_v3.py` — per-source orchestration, mandatory Codex call, bounded expansion, safety gate, and final resolution assembly.
- `tools/evaluate_drawing_evidence_v3.py` — local gold-aware v3 evaluator and operational metrics.
- `tools/build_drawing_gold_template.py` — generates a human-reviewable gold template without inferring truth from filename numbers.

### Existing files modified

- `backend/app/domain/drawing_evidence.py` — only compatibility fields needed by shared persistence; avoid moving v1/v2 behavior.
- `backend/app/services/drawing_source_observer.py` — expose relative path and optional rendered source evidence through v3 adapter use; preserve v1/v2 output semantics.
- `backend/app/graph/drawing_evidence_repository.py` — v3 body context metadata, Codex decision persistence, review-status persistence, and v3-safe TARGETS gating.
- `backend/app/services/drawing_evidence_corpus_service.py` — construct and run v3 resolver when explicitly selected.
- `backend/app/config.py` — v3 resolver alias and Codex-specific configuration getters.
- `backend/app/main.py` — wire v3 dependencies without changing existing OpenRouter review wiring.
- `tools/evaluate_drawing_evidence_graph.py` — only shared helpers/compatibility if required; do not fold the v3 live evaluator into this already multi-version tool.

### Core tests

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

### Task 1: Define stable v3 domain contracts

**Files:**
- Create: `backend/app/domain/drawing_evidence_v3.py`
- Test: `backend/tests/test_drawing_evidence_v3_models.py`

**Interfaces:**
- Produces: `DrawingVisualRegion`, `DrawingSourceEvidencePacket`, `DrawingCandidatePacket`, `CodexDrawingDecision`, `DrawingV3SourceResult`, and `DrawingV3Resolution`.
- Consumes: existing `ContextFact`, `BodyDrawingContext`, `DrawingCandidateEvidence`, `DrawingData`, and `EvidenceLevel`.

- [ ] **Step 1: Write failing model contract tests**

```python
from app.domain.drawing_evidence_v3 import (
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3SourceResult,
    DrawingVisualRegion,
)


def test_v3_packet_and_decision_contracts_are_immutable():
    region = DrawingVisualRegion(
        region_id="region:source:1",
        image_path="/tmp/source-1.png",
        page=1,
        bbox=(0.0, 0.0, 100.0, 100.0),
        confidence=1.0,
        source_sha256="sha",
    )
    source = DrawingSourceEvidencePacket(
        source_asset_id="asset-1",
        source_sha256="sha",
        original_name="x.ai",
        source_path="본문 도면/1지점/x.ai",
        raw_text="1지점 조선시대 1호 토광묘",
        publication_kind="drawing",
        internal_numbers=(),
        facts=(),
        visual_regions=(region,),
        evidence_ids=("ev:source",),
    )
    candidate = DrawingCandidatePacket(
        candidate_id="candidate:drawing:52",
        publication_kind="drawing",
        number="52",
        raw_texts=("도면 52. 1지점 조선시대 1호 토광묘",),
        facts=(),
        visual_regions=(),
        local_score=3.0,
        evidence_ids=("ev:body",),
        hard_contradiction=False,
        strong_contradiction_ids=(),
    )
    decision = CodexDrawingDecision(
        run_id="resp_1",
        model="codex-model",
        verdict="match",
        candidate_id=candidate.candidate_id,
        confidence=0.99,
        cited_support_ids=("ev:source", "ev:body"),
        cited_contradiction_ids=(),
        reason_codes=("feature_pair_match",),
        summary="match",
    )
    result = DrawingV3SourceResult(
        source_asset_id=source.source_asset_id,
        status="AUTO_VERIFIED",
        candidates=(candidate,),
        decision=decision,
        selected_candidate_id=candidate.candidate_id,
    )
    assert result.status == "AUTO_VERIFIED"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_v3_models.py`

Expected: import failure because `app.domain.drawing_evidence_v3` does not exist.

- [ ] **Step 3: Add the v3 dataclasses and literal status/verdict types**

```python
from dataclasses import dataclass, field
from typing import Literal

from app.domain.drawing_evidence import ContextFact

CodexVerdict = Literal["match", "ambiguous", "none"]
DrawingV3Status = Literal["AUTO_VERIFIED", "REVIEW_REQUIRED", "UNRESOLVED"]

@dataclass(frozen=True, slots=True)
class DrawingVisualRegion:
    region_id: str
    image_path: str
    page: int | None
    bbox: tuple[float, float, float, float] | None
    confidence: float
    source_sha256: str | None = None

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
    evidence_ids: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class DrawingCandidatePacket:
    candidate_id: str
    publication_kind: str
    number: str
    raw_texts: tuple[str, ...]
    facts: tuple[ContextFact, ...]
    visual_regions: tuple[DrawingVisualRegion, ...]
    local_score: float
    evidence_ids: tuple[str, ...]
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

- [ ] **Step 4: Run model tests**

Run: `cd backend && pytest -q tests/test_drawing_evidence_v3_models.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/drawing_evidence_v3.py backend/tests/test_drawing_evidence_v3_models.py
git commit -m "feat: add drawing evidence v3 domain contracts"
```

---

### Task 2: Render source AI and body drawing regions without Adobe

**Files:**
- Create: `backend/app/services/drawing_visual_extractor.py`
- Modify: `backend/app/graph/drawing_evidence_repository.py`
- Test: `backend/tests/test_drawing_visual_extractor.py`
- Test: `backend/tests/test_drawing_evidence_repository_v3.py`

**Interfaces:**
- Produces: `DrawingVisualExtractor.render_source(path: Path, output_dir: Path, source_asset_id: str, source_sha256: str) -> DrawingVisualRegion`.
- Produces: `DrawingVisualExtractor.crop_body_region(pdf_path: Path, output_dir: Path, region_id: str, page: int, bbox: tuple[float,float,float,float]) -> DrawingVisualRegion`.
- Produces repository method `list_body_drawing_contexts(project_id, resolver_version="v3")` with physical-page and bbox metadata available to the v3 packet builder while preserving v1/v2 outputs.

- [ ] **Step 1: Add failing render/crop tests using a tiny generated PDF fixture**

```python
from pathlib import Path
import fitz

from app.services.drawing_visual_extractor import DrawingVisualExtractor


def test_render_source_and_crop_body_region(tmp_path: Path):
    pdf_path = tmp_path / "sample.ai"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(20, 20, 180, 180))
    page.insert_text((30, 40), "drawing")
    doc.save(pdf_path)
    doc.close()

    extractor = DrawingVisualExtractor(render_scale=2.0)
    source = extractor.render_source(pdf_path, tmp_path / "out", "asset-1", "sha")
    crop = extractor.crop_body_region(
        pdf_path, tmp_path / "out", "body:1", 1, (10.0, 10.0, 190.0, 190.0)
    )
    assert Path(source.image_path).exists()
    assert Path(crop.image_path).exists()
    assert source.confidence == 1.0
```

- [ ] **Step 2: Run the visual test and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_visual_extractor.py`

Expected: import failure because extractor does not exist.

- [ ] **Step 3: Implement deterministic PyMuPDF rendering and bbox clipping**

```python
class DrawingVisualExtractor:
    def __init__(self, render_scale: float = 2.0) -> None:
        self._matrix = pymupdf.Matrix(render_scale, render_scale)

    def render_source(self, path, output_dir, source_asset_id, source_sha256):
        output_dir.mkdir(parents=True, exist_ok=True)
        document = pymupdf.open(str(path))
        try:
            page = document[0]
            pix = page.get_pixmap(matrix=self._matrix, alpha=False)
            target = output_dir / f"{source_asset_id}.png"
            pix.save(str(target))
            return DrawingVisualRegion(
                region_id=f"source:{source_asset_id}", image_path=str(target), page=1,
                bbox=None, confidence=1.0, source_sha256=source_sha256,
            )
        finally:
            document.close()
```

Implement `crop_body_region()` with `page = document[page_number - 1]`, `clip=pymupdf.Rect(*bbox)`, and the same pixmap path discipline. Clamp the bbox to `page.rect`; invalid/empty clips raise `ValueError` and are caught by the packet builder as visual-unavailable, never as identity evidence.

- [ ] **Step 4: Extend v3 body-context query metadata with page/bbox without changing v1/v2 grouping**

Add the physical page and source bbox to the query return, and only attach them for `resolver_version == "v3"`. Keep the v2 mention-grouping semantics unchanged. The v3-specific body metadata can be carried in a new v3 dataclass or a repository-side auxiliary mapping; do not reinterpret neighbor blocks as extra mentions.

Test with a fake driver record containing `physical_page=12` and `source_bbox=[10,20,110,220]` and assert v3 returns those values while v2 still returns the existing `BodyDrawingContext` shape.

- [ ] **Step 5: Run focused tests**

Run: `cd backend && pytest -q tests/test_drawing_visual_extractor.py tests/test_drawing_evidence_repository_v2_context.py tests/test_drawing_evidence_repository_v3.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/drawing_visual_extractor.py backend/app/graph/drawing_evidence_repository.py backend/tests/test_drawing_visual_extractor.py backend/tests/test_drawing_evidence_repository_v3.py
git commit -m "feat: add drawing visual evidence extraction"
```

---

### Task 3: Build a high-recall deterministic Top-K candidate generator

**Files:**
- Create: `backend/app/services/drawing_candidate_generator_v3.py`
- Test: `backend/tests/test_drawing_candidate_generator_v3.py`

**Interfaces:**
- Consumes: `DrawingSourceEvidencePacket`, `BodyDrawingContext`/v3 body metadata, `DrawingContextNormalizer`.
- Produces: `generate(source, body_candidates, limit=10) -> tuple[DrawingCandidatePacket, ...]`.
- Produces: `expand(source, body_candidates, existing_ids, limit=20) -> tuple[DrawingCandidatePacket, ...]`.

- [ ] **Step 1: Write RED tests for hard filters and broad recall behavior**

```python
def test_candidate_generator_filters_hard_feature_pair_but_keeps_missing_fields(generator):
    source = source_packet("2지점 조선시대 1호 토광묘")
    candidates = [
        body("drawing", "51", "2지점 조선시대 2호 토광묘"),
        body("drawing", "52", "2지점 조선시대 1호 토광묘 평단면"),
        body("drawing", "53", "2지점 평단면"),
    ]
    rows = generator.generate(source, candidates, limit=10)
    ids = [row.number for row in rows]
    assert "51" not in ids
    assert ids[0] == "52"
    assert "53" in ids
```

Also test that filename-only equality does not make an otherwise unsupported candidate the sole verified/authoritative result; filename/path appear only in evidence IDs/tie-break diagnostics.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_candidate_generator_v3.py`

Expected: import failure.

- [ ] **Step 3: Implement explicit scoring signals, not a hidden aggregate**

Use the existing normalizer for structured facts. Hard-filter only when both sides explicitly disagree on publication kind, site point, grid, or feature-type+feature-number pair. Rank survivors with transparent contributions:

```python
SIGNAL_WEIGHTS = {
    "site_point": 8.0,
    "grid": 10.0,
    "feature_pair": 10.0,
    "period": 4.0,
    "drawing_type": 3.0,
    "map_type": 4.0,
    "year": 4.0,
    "token_overlap": 2.0,
    "sequence_neighbor": 1.0,
    "filename": 0.25,
    "path": 0.25,
}
```

For every contribution, create a `DrawingCandidateEvidence`-compatible evidence ID with method names such as `v3_exact_feature_pair`, `v3_exact_site_point`, `v3_token_overlap`, `v3_weak_filename`. The absolute numeric weights are retrieval rank features only; they are never treated as calibrated probability or auto-verification confidence.

- [ ] **Step 4: Add Top-10/Top-20 stability tests**

Create at least 25 synthetic candidates and assert: correct structured candidate is retained in Top-10; `expand(... limit=20)` returns a superset without duplicates; hard contradictions never re-enter on expansion.

- [ ] **Step 5: Run candidate tests plus v2 regression**

Run: `cd backend && pytest -q tests/test_drawing_candidate_generator_v3.py tests/test_drawing_evidence_graph_resolver_v2.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/drawing_candidate_generator_v3.py backend/tests/test_drawing_candidate_generator_v3.py
git commit -m "feat: add high-recall v3 drawing candidates"
```

---

### Task 4: Add the single Codex multimodal client

**Files:**
- Create: `backend/app/services/codex_drawing_resolver_client.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_codex_drawing_resolver_client.py`
- Test: `backend/tests/test_drawing_evidence_resolver_config.py`

**Interfaces:**
- Produces: `CodexDrawingResolverConfig.from_env()`.
- Produces async `CodexDrawingResolverClient.resolve(source, candidates) -> CodexDrawingDecision`.
- Config keys: `OPENAI_API_KEY`, `DRAWING_CODEX_MODEL`, `DRAWING_CODEX_TIMEOUT_SECONDS`, `DRAWING_CODEX_AUTO_CONFIDENCE`, `DRAWING_CODEX_MAX_CANDIDATES`, `DRAWING_CODEX_MAX_EXPANSIONS`.

- [ ] **Step 1: Write failing config and request-contract tests**

```python
async def test_codex_request_is_closed_world_and_contains_images(fake_http, tmp_path):
    client = CodexDrawingResolverClient(config=test_config(), transport=fake_http)
    decision = await client.resolve(source_packet_with_png(tmp_path), (candidate_with_png(tmp_path),))
    payload = fake_http.last_json
    text = str(payload)
    assert "compare only the supplied candidates" in text.lower()
    assert "candidate:drawing:52" in text
    assert "input_image" in text
    assert decision.candidate_id == "candidate:drawing:52"
```

Add tests for: `ambiguous`; `none`; invented candidate ID; invented evidence ID; confidence outside [0,1]; malformed JSON; one retry on format/transport error; second failure raising a typed `CodexDrawingDecisionError` for the resolver to route to review.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && pytest -q tests/test_codex_drawing_resolver_client.py tests/test_drawing_evidence_resolver_config.py`

Expected: missing v3 config/client failures.

- [ ] **Step 3: Implement config with masked repr and no OpenRouter coupling**

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

`from_env()` must require `OPENAI_API_KEY` only when the client is actually constructed for live use; tests can inject config/transport. Keep existing `OPENROUTER_API_KEY` behavior untouched.

- [ ] **Step 4: Implement Responses API multimodal serialization**

Build one closed-world prompt and an `input` content array containing `input_text` and `input_image` data URLs for source and candidate PNGs. Include only supplied candidate IDs/evidence IDs. Request structured JSON and parse the model output into `CodexDrawingDecision`.

Validation must enforce:

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

- [ ] **Step 5: Run focused tests**

Run: `cd backend && pytest -q tests/test_codex_drawing_resolver_client.py tests/test_drawing_evidence_resolver_config.py`

Expected: PASS with no real network calls.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/codex_drawing_resolver_client.py backend/app/config.py backend/tests/test_codex_drawing_resolver_client.py backend/tests/test_drawing_evidence_resolver_config.py
git commit -m "feat: add Codex drawing resolver client"
```

---

### Task 5: Orchestrate mandatory Codex decisions and fail-closed final states

**Files:**
- Create: `backend/app/services/drawing_evidence_resolver_v3.py`
- Test: `backend/tests/test_drawing_evidence_graph_resolver_v3.py`

**Interfaces:**
- Consumes candidate generator, visual packet builder, and `CodexDrawingResolverClient`.
- Produces async `resolve_observations(...) -> DrawingV3Resolution`.
- Every source calls `codex_client.resolve(...)` at least once, including sources with explicit internal numbers.

- [ ] **Step 1: Write RED tests for every state transition**

Test matrix:

```python
@pytest.mark.parametrize(
    "verdict,confidence,hard,status",
    [
        ("match", 0.99, False, "AUTO_VERIFIED"),
        ("match", 0.70, False, "REVIEW_REQUIRED"),
        ("match", 0.99, True, "REVIEW_REQUIRED"),
        ("ambiguous", 0.80, False, "REVIEW_REQUIRED"),
        ("none", 0.20, False, "UNRESOLVED"),
    ],
)
def test_v3_routes_codex_decisions(...): ...
```

Also assert: every source increments fake client call count; `none`/`ambiguous` triggers at most one bounded Top-20 expansion; repeated client failure routes to `REVIEW_REQUIRED`; direct internal ID is still sent to Codex; Codex disagreement with direct evidence does not create TARGETS; two sources selecting one exclusive target route the conflicting lower-priority case to review instead of silently duplicating.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_graph_resolver_v3.py`

Expected: import failure.

- [ ] **Step 3: Implement the v3 safety gate**

```python
def _final_status(self, candidate, decision, submitted_evidence_ids):
    if decision.verdict == "none":
        return "UNRESOLVED"
    if decision.verdict != "match":
        return "REVIEW_REQUIRED"
    if candidate is None or candidate.hard_contradiction:
        return "REVIEW_REQUIRED"
    if decision.confidence < self._auto_confidence:
        return "REVIEW_REQUIRED"
    if not set(decision.cited_support_ids) <= set(submitted_evidence_ids):
        return "REVIEW_REQUIRED"
    support_families = self._support_families(decision.cited_support_ids)
    nonweak = {f for f in support_families if f not in {"filename", "path", "sequence"}}
    if len(support_families) < 2 or not nonweak:
        return "REVIEW_REQUIRED"
    return "AUTO_VERIFIED"
```

Keep filename/path/sequence as evidence but never let them satisfy the non-weak requirement by themselves.

- [ ] **Step 4: Implement bounded expansion and one-source/one-target conflict routing**

First call uses Top-10. On `none`, `ambiguous`, or a typed invalid-decision error where the packet may be insufficient, expand once to Top-20 and call again. Never exceed configured `max_expansions=1` in first v3. Resolve duplicate target selections deterministically: direct-evidence agreement first, then higher Codex confidence, then higher nonweak support count; all losing conflicts become `REVIEW_REQUIRED`.

- [ ] **Step 5: Run resolver tests and all v2 resolver tests**

Run: `cd backend && pytest -q tests/test_drawing_evidence_graph_resolver_v3.py tests/test_drawing_evidence_graph_resolver_v2.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/drawing_evidence_resolver_v3.py backend/tests/test_drawing_evidence_graph_resolver_v3.py
git commit -m "feat: add Codex-first drawing resolver v3"
```

---

### Task 6: Persist Codex decisions and v3 provenance in Neo4j

**Files:**
- Modify: `backend/app/graph/drawing_evidence_repository.py`
- Test: `backend/tests/test_drawing_evidence_repository_v3.py`
- Test: `backend/tests/integration/test_drawing_evidence_repository_v3_neo4j.py`

**Interfaces:**
- Produces: `save_v3_resolution(project_id: str, corpus_id: str, resolution: DrawingV3Resolution) -> None`.
- Persists `CodexDecision` nodes keyed by `run_id` and edges to submitted/selected candidates and cited evidence.
- Creates canonical `TARGETS` only for safe v3 auto/direct/human verified outcomes; never for review/unresolved.

- [ ] **Step 1: Write payload-level RED tests**

Assert persisted decision properties include `model`, `verdict`, `confidence`, `reasonCodes`, source ID, selected candidate ID, and final status. Assert `REVIEW_REQUIRED` and `UNRESOLVED` produce zero TARGETS payload rows.

- [ ] **Step 2: Run repository test and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_repository_v3.py`

Expected: `save_v3_resolution` missing.

- [ ] **Step 3: Implement v3 Neo4j persistence**

Use project/corpus-scoped MERGE patterns. Required graph shape:

```text
(OriginalAsset)-[:HAS_CODEX_DECISION]->(CodexDecision)
(CodexDecision)-[:CONSIDERED]->(DrawingCandidate)
(CodexDecision)-[:SELECTED]->(DrawingCandidate)        # match only
(CodexDecision)-[:CITES_SUPPORT]->(ResolutionEvidence)
(CodexDecision)-[:CITES_CONTRADICTION]->(ResolutionEvidence)
```

Store `resolverVersion="drawing-evidence-v3"` and `finalStatus`. Do not delete v1/v2 nodes.

- [ ] **Step 4: Add real Neo4j integration assertions**

Create a temporary project/corpus/source fixture, persist one AUTO and one REVIEW result, and query counts: AUTO has one safe target; REVIEW has zero target; Codex decision/evidence citation edges exist for both.

- [ ] **Step 5: Run repository unit and Neo4j integration suite**

Run: `cd backend && pytest -q tests/test_drawing_evidence_repository_v3.py tests/integration/test_drawing_evidence_repository_v3_neo4j.py`

Expected: PASS where Neo4j test is enabled; hermetic unit tests remain independent of a live DB.

- [ ] **Step 6: Commit**

```bash
git add backend/app/graph/drawing_evidence_repository.py backend/tests/test_drawing_evidence_repository_v3.py backend/tests/integration/test_drawing_evidence_repository_v3_neo4j.py
git commit -m "feat: persist Codex drawing provenance"
```

---

### Task 7: Wire v3 into production assembly behind explicit shadow-safe configuration

**Files:**
- Modify: `backend/app/services/drawing_evidence_corpus_service.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_drawing_evidence_corpus_service_v3.py`
- Test: `backend/tests/test_drawing_evidence_resolver_config.py`

**Interfaces:**
- `DRAWING_EVIDENCE_RESOLVER_VERSION=v3` selects `drawing-evidence-v3`.
- `DRAWING_EVIDENCE_V3_AUTO_PROMOTE=false` is the default shadow gate.
- `EvidenceGraphReferenceCorpusService` uses async-compatible v3 orchestration without changing v1/v2 code paths.

- [ ] **Step 1: Write failing selection/shadow tests**

```python
def test_v3_is_explicit_and_default_remains_v1(monkeypatch):
    monkeypatch.delenv("DRAWING_EVIDENCE_RESOLVER_VERSION", raising=False)
    assert get_drawing_evidence_resolver_version() == "v1"
    monkeypatch.setenv("DRAWING_EVIDENCE_RESOLVER_VERSION", "v3")
    assert get_drawing_evidence_resolver_version() == "v3"


def test_v3_auto_promote_defaults_false(monkeypatch):
    monkeypatch.delenv("DRAWING_EVIDENCE_V3_AUTO_PROMOTE", raising=False)
    assert get_drawing_evidence_v3_auto_promote() is False
```

Service test: fake v3 resolver returns AUTO but shadow mode must persist the decision without changing the existing canonical target list.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_corpus_service_v3.py tests/test_drawing_evidence_resolver_config.py`

Expected: v3 alias/getter/service assembly missing.

- [ ] **Step 3: Add v3 aliases and shadow getter**

Extend aliases with `v3` / `drawing-evidence-v3`; error text becomes `must be v1, v2, or v3`. Add boolean parser for `DRAWING_EVIDENCE_V3_AUTO_PROMOTE`, default false.

- [ ] **Step 4: Wire the v3 client/resolver only when v3 is selected**

Do not construct a live OpenAI client when v1/v2 is selected. In v3, construct `CodexDrawingResolverClient`, `DrawingCandidateGeneratorV3`, `DrawingVisualExtractor`, and `DrawingEvidenceResolverV3`; preserve dependency injection hooks for tests. Shadow mode persists v3 decisions/metrics but returns existing safe canonical targets rather than creating new v3 TARGETS.

- [ ] **Step 5: Run service/config plus existing v1/v2 tests**

Run: `cd backend && pytest -q tests/test_drawing_evidence_corpus_service_v3.py tests/test_drawing_evidence_corpus_service_v2.py tests/test_drawing_evidence_resolver_config.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/drawing_evidence_corpus_service.py backend/app/config.py backend/app/main.py backend/tests/test_drawing_evidence_corpus_service_v3.py backend/tests/test_drawing_evidence_resolver_config.py
git commit -m "feat: wire drawing evidence v3 shadow mode"
```

---

### Task 8: Add gold-template and v3 evaluator contracts

**Files:**
- Create: `tools/build_drawing_gold_template.py`
- Create: `tools/evaluate_drawing_evidence_v3.py`
- Create: `backend/tests/fixtures/drawing_evidence_v3_gold_sample.json`
- Create: `backend/tests/test_drawing_evidence_v3_evaluator_contract.py`
- Modify: `docs/local_drawing_evidence_v2_revalidation.md` only to point to the new v3 procedure; do not overwrite v1/v2 historical results.

**Interfaces:**
- Gold row schema: `{source, publication_kind, number, verification, notes}` where `verification` is `human` or `unknown`.
- Evaluator metrics: Recall@5/10/20, Codex Top-1, ambiguous/none rate, auto coverage, auto precision, review rate, invalid response count, hard contradiction promoted, filename-only promoted, kind collision, API-unsafe-promotion count.

- [ ] **Step 1: Write RED evaluator tests**

```python
def test_gold_unknown_rows_are_excluded_from_accuracy():
    metrics = evaluate_fixture(gold_rows=[
        {"source": "a.ai", "publication_kind": "drawing", "number": "52", "verification": "human", "notes": ""},
        {"source": "b.ai", "publication_kind": None, "number": None, "verification": "unknown", "notes": ""},
    ])
    assert metrics["gold_known"] == 1


def test_operational_metrics_separate_coverage_and_precision():
    metrics = summarize_results(auto=[True, True], correct=[True, False], total=4)
    assert metrics["auto_coverage"] == 0.5
    assert metrics["auto_precision"] == 0.5
```

Also assert evaluator rejects output paths under the source root and never writes into `/src`.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && pytest -q tests/test_drawing_evidence_v3_evaluator_contract.py`

Expected: imports/tools absent.

- [ ] **Step 3: Implement gold template generation**

`build_drawing_gold_template.py --source-root src --output docs/local_drawing_evidence_v3_gold.json` enumerates drawing AI files but initializes every row with `verification="unknown"`, `publication_kind=null`, `number=null`; it must not copy filename numbers into truth fields.

- [ ] **Step 4: Implement v3 evaluator with injectable fake client mode**

CLI:

```text
python tools/evaluate_drawing_evidence_v3.py \
  --source-root src \
  --gold docs/local_drawing_evidence_v3_gold.json \
  --output-json docs/local_drawing_evidence_v3_metrics.json \
  --output-report docs/local_drawing_evidence_v3_report.md \
  --live-codex
```

Default mode without `--live-codex` must accept a deterministic decision fixture/client for tests. Live mode requires `OPENAI_API_KEY` and v3 config. Report both candidate recall and final Codex operational metrics.

- [ ] **Step 5: Run evaluator contract tests**

Run: `cd backend && pytest -q tests/test_drawing_evidence_v3_evaluator_contract.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/build_drawing_gold_template.py tools/evaluate_drawing_evidence_v3.py backend/tests/fixtures/drawing_evidence_v3_gold_sample.json backend/tests/test_drawing_evidence_v3_evaluator_contract.py docs/local_drawing_evidence_v2_revalidation.md
git commit -m "test: add drawing evidence v3 gold evaluator"
```

---

### Task 9: Run hermetic verification, then local live acceptance without enabling production auto-promotion

**Files:**
- Modify only if failures expose a real bug; any bug requires a focused RED regression test before the fix.
- Local generated outputs after human gold review:
  - `docs/local_drawing_evidence_v3_gold.json`
  - `docs/local_drawing_evidence_v3_metrics.json`
  - `docs/local_drawing_evidence_v3_report.md`

**Interfaces:**
- No new product interface; this task proves the plan's gates.

- [ ] **Step 1: Run compile and focused backend tests**

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

Expected: all PASS.

- [ ] **Step 2: Run full hermetic backend/frontend/Neo4j CI-equivalent suites**

Use the repository's existing CI commands/workflow. Required green jobs remain `backend-hermetic`, `frontend`, and `neo4j-e2e`. Real OpenAI calls must not occur in CI.

- [ ] **Step 3: Build and manually complete the 56-source gold file locally**

```powershell
python tools/build_drawing_gold_template.py `
  --source-root src `
  --output docs/local_drawing_evidence_v3_gold.json
```

Human-review each evaluable row against the body report. Set `verification="human"` only where the identity is defensible; leave uncertain rows as `unknown`. Do not infer truth from filename numbering.

- [ ] **Step 4: Run live Codex v3 locally in shadow mode**

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

Expected safety counters: hard contradiction promoted=0, filename-only promoted=0, kind collision=0, invalid/failed API unsafe promotion=0.

- [ ] **Step 5: Apply acceptance gates without relaxing them**

Pass only if gold-known rows satisfy Recall@10 >= 99% and the measured auto subset satisfies 75-85% coverage at >=99% precision with review <=25%. If Recall@10 fails, improve Task 3 retrieval. If precision fails, raise/reroute confidence/review behavior based on measured gold buckets; do not add another AI model under this plan. If coverage fails while precision passes, remain shadow/review-only and report the gap.

- [ ] **Step 6: Commit local acceptance outputs only after the human gold review and live run**

```bash
git add docs/local_drawing_evidence_v3_gold.json docs/local_drawing_evidence_v3_metrics.json docs/local_drawing_evidence_v3_report.md
git commit -m "test: record local drawing evidence v3 acceptance"
```

- [ ] **Step 7: Keep rollout and PR gates unchanged**

Do not set `DRAWING_EVIDENCE_V3_AUTO_PROMOTE=true`, do not change the production default, and do not merge PR #47 or PR #1 without explicit user approval. A passing local acceptance is evidence for a later explicit rollout decision, not automatic rollout authorization.
