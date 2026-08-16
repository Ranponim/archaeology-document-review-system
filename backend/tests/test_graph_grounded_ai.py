"""Task 10 tests: VLM and LLM review grounded on refreshed graph evidence bundles.

- VLM input path: canonical Reference -> RESOLVES_TO -> canonical
  PlatePanel/DrawingRegion render -> crop -> VLM. The VLM service receives ONLY
  the cropped canonical panel render and never writes RESOLVES_TO/DEPICTS
  identity (anti-pattern #8).
- Post-VLM bundle refresh: after VLM observations are persisted as Evidence
  (kind=vlm_observation, linked via candidate SUPPORTED_BY), the graph evidence
  bundle is re-queried so subsequent LLM consumption sees the observation in
  visual_observations.
- LLM input path: AIReviewService.review_object_bundle builds the prompt from
  bundle fields ONLY (object identity, text_claims, references, plate_claims,
  drawing_claims, visual_observations, version_claims + rule findings) — no
  full-document text (anti-pattern #9).
- DEGRADED: without graph evidence the LLM falls back to the in-memory path
  with an explicit warning (never silent).
"""
from typing import Any, Callable
import io
import json
import os
import uuid

import pytest

from PIL import Image

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    PlateData,
    PlatePanelData,
    ReferenceData,
)
from app.domain.document_structure import ParsedPage, TextBlockData
from app.domain.evidence_bundle import ObjectEvidenceBundle
from app.domain.review_models import EvidenceData
from app.graph.canonical_repository import CanonicalRepository
from app.graph.review_repository import ReviewRepository
from app.services.ai_review_service import AIReviewService
from app.services.asset_cache import AssetHashCache
from app.services.asset_review_pipeline import AssetReviewPipeline
from app.services.image_processor import ImageProcessor
from app.services.proofreading_orchestrator import ProofreadingOrchestrator
from app.services.vlm_review_service import VLMReviewResult

pytestmark = pytest.mark.anyio


class FakeNeo4jRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class EmptyFakeNeo4jDriver:
    """Fake driver returning no records for every query (no graph evidence)."""

    def __init__(self, events: list[str] | None = None):
        self.queries: list[dict[str, Any]] = []
        self.events = events

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        if self.events is not None:
            self.events.append(query)
        return [], None, None


class QueueFakeNeo4jDriver:
    """Fake driver returning per-query-shaped record batches in FIFO order.

    A marker registered with a single batch repeats that batch on every call;
    a marker registered with multiple batches pops them in order (the
    "first bundle query empty -> VLM persists -> second query returns vlm row"
    sequence).
    """

    def __init__(self):
        self.queries: list[dict[str, Any]] = []
        self._responses: list[tuple[Callable[[str], bool], list[list[dict[str, Any]]]]] = []

    def respond(self, marker: str, batches: list[list[dict[str, Any]]]) -> "QueueFakeNeo4jDriver":
        self._responses.append((lambda q, m=marker: m in q, batches))
        return self

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        for predicate, batches in self._responses:
            if predicate(query):
                if not batches:
                    return [], None, None
                batch = batches[0] if len(batches) == 1 else batches.pop(0)
                return [FakeNeo4jRecord(r) for r in batch], None, None
        return [], None, None


class CapturingVLMService:
    """Duck-typed VLMReviewService recording the exact bytes it receives and
    appending a marker to the shared event log (for identity-write ordering)."""

    def __init__(self, events: list[str] | None = None):
        self.calls: list[bytes] = []
        self.events = events

    async def verify_plate_photo(
        self,
        image_bytes: bytes,
        expected_feature: str,
        expected_site: str = "",
        claims: list[str] | None = None,
        mime_type: str = "image/jpeg",
    ) -> VLMReviewResult:
        self.calls.append(image_bytes)
        if self.events is not None:
            self.events.append("VLM_CALL")
        return VLMReviewResult(
            status="SUPPORTED",
            observations={"site_label": expected_site or "테스트"},
            supported_claims=[f"{expected_feature} 일치"],
            confidence=0.9,
            rationale="mock vlm",
        )


class CapturingAIService:
    """Duck-typed AIReviewService recording which review entry point is used."""

    def __init__(self):
        self.bundle_calls: list[tuple[Any, Any, Any]] = []
        self.in_memory_calls: list[tuple[Any, Any]] = []

    async def review_object_bundle(
        self,
        archaeology_object: ArchaeologyObjectData | None = None,
        bundle: ObjectEvidenceBundle | None = None,
        rule_findings: list[Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        self.bundle_calls.append((archaeology_object, bundle, rule_findings))
        return []

    async def review_object_evidence(
        self,
        archaeology_object: ArchaeologyObjectData | None = None,
        evidences: list[EvidenceData] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        self.in_memory_calls.append((archaeology_object, evidences))
        return []


class MockOpenRouterClient:
    def __init__(self, mock_response: dict):
        self.mock_response = mock_response
        self.last_prompt = None
        self.last_context = None

    async def analyze_text_discrepancy(self, prompt: str, context: dict) -> dict:
        self.last_prompt = prompt
        self.last_context = context
        return self.mock_response


def _png_bytes(size: tuple[int, int], rgb: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="PNG")
    return buf.getvalue()


def _body_page_with_reference() -> ParsedPage:
    """One page whose block mentions an object and references plate 45."""
    return ParsedPage(
        page_id="ver_g_p1",
        physical_page=1,
        printed_page=1,
        header="",
        raw_text=(
            "FULL_DOCUMENT_SECRET_PAGE_TEXT 1지점 청동기시대 1호 주거지 규모는 길이 275cm이다. "
            "1지점 청동기시대 1호 주거지(도판 : 45) 조사를 진행하였다."
        ),
        normalized_text=(
            "1지점 청동기시대 1호 주거지 규모는 길이 275cm이다. "
            "1지점 청동기시대 1호 주거지(도판 : 45) 조사를 진행하였다."
        ),
        text_blocks=[
            TextBlockData(
                block_id="p1_b1",
                text="1지점 청동기시대 1호 주거지 규모는 길이 275cm이다.",
                normalized_text="1지점 청동기시대 1호 주거지 규모는 길이 275cm이다.",
                block_type="paragraph",
                order=1,
                source_sha256="sha256_g",
            ),
            TextBlockData(
                block_id="p1_b2",
                text="1지점 청동기시대 1호 주거지(도판 : 45) 조사를 진행하였다.",
                normalized_text="1지점 청동기시대 1호 주거지(도판 : 45) 조사를 진행하였다.",
                block_type="paragraph",
                order=2,
                source_sha256="sha256_g",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number="45",
                        source_block_id="p1_b2",
                        raw_text="도판 : 45",
                        source_sha256="sha256_g",
                        physical_page=1,
                    )
                ],
            ),
        ],
        captions=[],
        source_sha256="sha256_g",
    )


def _plate_with_panel(render_uri: str | None = None) -> list[PlateData]:
    panel = PlatePanelData(
        panel_id="plate_45_panel_1",
        plate_id="plate_45",
        panel_index=1,
        caption="1지점 청동기시대 1호 주거지",
        bbox=(0.1, 0.1, 0.5, 0.5),
        bbox_status="segmented",
        physical_page=47,
        render_uri=render_uri,
        source_sha256="sha256_plate",
    )
    return [
        PlateData(
            plate_id="plate_45",
            number="45",
            physical_page=47,
            title="1지점 청동기시대 1호 주거지",
            source_sha256="sha256_plate",
            document_version_id="ver_plate",
            panels=[panel],
            raw_identifier="【도판 45】",
        )
    ]


def _text_claim_row() -> dict[str, Any]:
    return {
        "source": {"id": "g_b1", "text": "규모는 길이 275cm이다"},
        "page": {"id": "ver_g_p1", "physical_page": 1},
        "version": {"id": "ver_g", "stage": "1차", "sha256": "sha256_g"},
    }


def _vlm_row() -> dict[str, Any]:
    return {
        "cand": {"id": "cand_vlm_x", "rule_category": "figure_plate_table_photo_ref"},
        "ev": {
            "id": "ev_vlm_obj_t",
            "kind": "vlm_observation",
            "source_sha256": "sha256_plate",
            "document_version_id": "ver_g",
            "page_id": "ver_g_p1",
            "value": '{"status": "SUPPORTED", "observations": {"site_label": "1지점 청동기시대 1호 주거지"}}',
            "confidence": 0.9,
            "analysis_run_id": "run_old",
        },
        "page": {"id": "ver_g_p1"},
        "version": {"id": "ver_g", "sha256": "sha256_g"},
    }


def _version_row() -> dict[str, Any]:
    return {
        "cand": {"id": "cand_ver_x"},
        "ev": {
            "id": "ev_ver_obj_t",
            "kind": "version_change",
            "source_sha256": "sha256_g",
            "document_version_id": "ver_g",
            "page_id": "ver_g_p1",
            "value": "2차 교정에서 수정됨",
        },
        "page": {"id": "ver_g_p1"},
        "version": {"id": "ver_g", "sha256": "sha256_g"},
    }


def _bundle_driver(
    candidate_evidences_batches: list[list[dict[str, Any]]],
) -> QueueFakeNeo4jDriver:
    """Driver shaped for get_object_evidence_bundle's five targeted queries.

    Registration order matters: the references query also contains the text
    claims marker, so the more specific REFERENCES marker is registered first.
    """
    return (
        QueueFakeNeo4jDriver()
        .respond(
            "RETURN properties(obj) AS obj",
            [[{"obj": {"canonical_name": "1지점 청동기시대 1호 주거지"}}]],
        )
        .respond("[:REFERENCES]->(ref:Reference)", [[]])
        .respond("[:MENTIONS]->(obj:ArchaeologyObject", [[_text_claim_row()]])
        .respond("[:DEPICTS]->(obj:ArchaeologyObject", [[]])
        .respond("[:SUPPORTED_BY]->(ev:Evidence)", candidate_evidences_batches)
    )


async def test_orchestrator_vlm_input_is_canonical_render_only_and_never_writes_identity(tmp_path):
    """VLM receives ONLY the cropped canonical panel render (render_uri ->
    crop), and no RESOLVES_TO/DEPICTS write is executed during the VLM phase —
    VLM is an observer, never an identity writer (anti-pattern #8)."""
    render_path = tmp_path / "render.png"
    render_path.write_bytes(_png_bytes((200, 200), (180, 30, 30)))
    render_bytes = render_path.read_bytes()

    events: list[str] = []
    driver = EmptyFakeNeo4jDriver(events=events)
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    vlm = CapturingVLMService(events=events)
    pipeline = AssetReviewPipeline(
        vlm_service=vlm,
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        asset_review_pipeline=pipeline,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_vlm_canonical",
        body_version_id="ver_g",
        plate_version_id="ver_plate",
        body_pages=[_body_page_with_reference()],
        plates=_plate_with_panel(render_uri=str(render_path)),
        enable_vlm=True,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert len(vlm.calls) == 1, "VLM must be invoked exactly once for the resolved panel"
    panel = _plate_with_panel()[0].panels[0]
    expected_crop = ImageProcessor.crop_region(render_bytes, panel.bbox)
    assert vlm.calls[0] == expected_crop, "VLM must receive the cropped canonical panel"
    assert vlm.calls[0] != render_bytes, "VLM must never receive the whole page render"
    assert ImageProcessor.is_valid_image(vlm.calls[0])

    # Identity-write ordering: every RESOLVES_TO/DEPICTS write (MERGE/CREATE)
    # happens in steps 5b/6 — strictly BEFORE the first VLM call.
    assert "VLM_CALL" in events
    vlm_pos = events.index("VLM_CALL")
    identity_writes = [
        q
        for q in events
        if ("RESOLVES_TO" in q or "DEPICTS" in q) and ("MERGE" in q or "CREATE" in q)
    ]
    assert identity_writes, "steps 5b/6 must persist DEPICTS/RESOLVES_TO before VLM"
    assert all(events.index(q) < vlm_pos for q in identity_writes), (
        "VLM must never create/modify RESOLVES_TO or DEPICTS identity"
    )


async def test_orchestrator_refreshes_graph_bundle_after_vlm_evidence_persisted(tmp_path):
    """After VLM observations are persisted as Evidence (candidate SUPPORTED_BY),
    the graph bundle is re-queried and the refreshed bundle exposes the
    vlm_observation in visual_observations for the LLM step."""
    driver = _bundle_driver(candidate_evidences_batches=[[], [_vlm_row()]])
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    render_path = tmp_path / "render.png"
    render_path.write_bytes(_png_bytes((200, 200), (180, 30, 30)))
    vlm = CapturingVLMService()
    pipeline = AssetReviewPipeline(
        vlm_service=vlm,
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )
    ai = CapturingAIService()

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        asset_review_pipeline=pipeline,
        ai_review_service=ai,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_refresh",
        body_version_id="ver_g",
        plate_version_id="ver_plate",
        body_pages=[_body_page_with_reference()],
        plates=_plate_with_panel(render_uri=str(render_path)),
        enable_vlm=True,
        enable_ai_review=True,
    )

    assert result.status == "completed"
    assert len(vlm.calls) == 1
    assert len(ai.bundle_calls) == 1, "LLM must consume the refreshed graph bundle"
    assert ai.in_memory_calls == [], "LLM must not fall back when graph evidence exists"
    bundle = ai.bundle_calls[0][1]
    assert bundle is not None
    assert bundle.visual_observations, "refreshed bundle must expose the vlm_observation"
    vlm_ev = bundle.visual_observations[0]
    assert vlm_ev.kind == "vlm_observation"
    assert vlm_ev.id == "ev_vlm_obj_t"
    assert not any("DEGRADED" in w for w in result.warnings), result.warnings


async def test_llm_receives_graph_bundle_fields_only_and_no_full_document_text(tmp_path):
    """The LLM input is built strictly from bundle fields (text_claims,
    visual_observations, version_claims, ...) — the full-document page text
    never reaches the prompt (anti-pattern #9)."""
    driver = _bundle_driver(
        candidate_evidences_batches=[[], [_vlm_row(), _version_row()]]
    )
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    render_path = tmp_path / "render.png"
    render_path.write_bytes(_png_bytes((200, 200), (180, 30, 30)))
    vlm = CapturingVLMService()
    pipeline = AssetReviewPipeline(
        vlm_service=vlm,
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )
    mock_client = MockOpenRouterClient(
        {"choices": [{"message": {"content": json.dumps({"candidates": []})}}]}
    )
    ai_service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        asset_review_pipeline=pipeline,
        ai_review_service=ai_service,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_llm_fields",
        body_version_id="ver_g",
        plate_version_id="ver_plate",
        body_pages=[_body_page_with_reference()],
        plates=_plate_with_panel(render_uri=str(render_path)),
        enable_vlm=True,
        enable_ai_review=True,
    )

    assert result.status == "completed"
    assert mock_client.last_context is not None
    bundle_ctx = mock_client.last_context["evidence_bundle"]
    assert bundle_ctx["text_claims"], "text_claims must be present"
    assert bundle_ctx["visual_observations"], "visual_observations must be present"
    assert bundle_ctx["version_claims"], "version_claims must be present"
    assert bundle_ctx["references"] == []
    assert bundle_ctx["plate_claims"] == []
    assert bundle_ctx["drawing_claims"] == []

    serialized = json.dumps(mock_client.last_context, ensure_ascii=False)
    assert "FULL_DOCUMENT_SECRET_PAGE_TEXT" not in serialized, (
        "full-document page text must never reach the LLM input"
    )
    assert "FULL_DOCUMENT_SECRET_PAGE_TEXT" not in (mock_client.last_prompt or "")


async def test_llm_degrades_explicitly_to_in_memory_without_graph_evidence():
    """No graph evidence -> LLM falls back to the in-memory path with an
    explicit DEGRADED warning (never silent), consistent with Task 7."""
    driver = EmptyFakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")
    ai = CapturingAIService()

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        ai_review_service=ai,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_llm_deg",
        body_version_id="ver_g",
        body_pages=[_body_page_with_reference()],
        enable_vlm=False,
        enable_ai_review=True,
    )

    assert result.status == "completed"
    assert len(ai.in_memory_calls) == 1, "LLM must fall back to in-memory evidences"
    assert ai.bundle_calls == [], "bundle path must not be used without graph evidence"
    assert any("DEGRADED" in w for w in result.warnings), (
        "degradation must be explicit and recorded, never silent"
    )


async def test_review_object_bundle_builds_context_from_bundle_fields_only():
    """AIReviewService.review_object_bundle builds the LLM context from bundle
    fields only and grounds candidates on cited bundle evidence ids."""
    from app.domain.canonical_models import ArchaeologyObjectData

    obj = ArchaeologyObjectData(
        object_id="obj_1",
        site="1지점",
        point="1지점",
        period="청동기시대",
        type="주거지",
        number="1호",
        canonical_name="1지점 청동기시대 1호 주거지",
    )
    bundle = ObjectEvidenceBundle(
        object_id="obj_1",
        canonical_name="1지점 청동기시대 1호 주거지",
        text_claims=[
            EvidenceData(
                id="ev_text_1",
                kind="text_claim",
                source_sha256="sha256_g",
                document_version_id="ver_g",
                page_id="ver_g_p1",
                value="규모는 길이 275cm이다",
            )
        ],
        visual_observations=[
            EvidenceData(
                id="ev_vlm_1",
                kind="vlm_observation",
                source_sha256="sha256_plate",
                document_version_id="ver_g",
                page_id="ver_g_p1",
                value={"status": "SUPPORTED", "observations": {"site_label": "1지점"}},
                confidence=0.9,
            )
        ],
        version_claims=[
            EvidenceData(
                id="ev_ver_1",
                kind="version_change",
                source_sha256="sha256_g",
                document_version_id="ver_g",
                page_id="ver_g_p1",
                value="2차 교정에서 수정됨",
            )
        ],
    )
    mock_client = MockOpenRouterClient(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "candidates": [
                                    {
                                        "category": "numeric_value",
                                        "original_text": "길이 275cm",
                                        "proposed_text": "길이 2.75m",
                                        "change_type": "modified",
                                        "rationale": "VLM 관측과 불일치",
                                        "cited_evidence_ids": ["ev_vlm_1"],
                                        "confidence": 0.9,
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }
    )
    service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")

    from app.domain.review_models import CorrectionCandidateData

    rule_finding = CorrectionCandidateData(
        candidate_id="cand_rule_1",
        rule_category="numeric_value",
        change_type="modified",
        status="pending_review",
        original_text="길이 275cm",
        proposed_text="길이 2.75m",
        evidence=EvidenceData(
            id="ev_text_1",
            kind="text_claim",
            source_sha256="sha256_g",
            document_version_id="ver_g",
            page_id="ver_g_p1",
            value="규모는 길이 275cm이다",
        ),
        archaeology_object_id="obj_1",
        confidence=0.8,
    )

    candidates = await service.review_object_bundle(
        archaeology_object=obj,
        bundle=bundle,
        rule_findings=[rule_finding],
        project_id="p1",
        version_stage="1차",
        analysis_run_id="run_10",
    )

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.status == "pending_review"
    assert cand.archaeology_object_id == "obj_1"
    assert cand.evidence is not None and cand.evidence.id == "ev_vlm_1"
    assert cand.analysis_run_id == "run_10"

    ctx = mock_client.last_context
    assert ctx["archaeology_object"]["object_id"] == "obj_1"
    assert ctx["archaeology_object"]["canonical_name"] == "1지점 청동기시대 1호 주거지"
    assert len(ctx["evidence_bundle"]["text_claims"]) == 1
    assert ctx["evidence_bundle"]["text_claims"][0]["evidence_id"] == "ev_text_1"
    assert len(ctx["evidence_bundle"]["visual_observations"]) == 1
    assert ctx["evidence_bundle"]["visual_observations"][0]["evidence_id"] == "ev_vlm_1"
    assert len(ctx["evidence_bundle"]["version_claims"]) == 1
    assert ctx["rule_findings"] == [
        {
            "rule_category": "numeric_value",
            "change_type": "modified",
            "original_text": "길이 275cm",
            "proposed_text": "길이 2.75m",
            "confidence": 0.8,
            "evidence_ids": ["ev_text_1"],
        }
    ]
    serialized = json.dumps(ctx, ensure_ascii=False)
    assert "FULL_DOCUMENT" not in serialized


async def test_review_object_bundle_refuses_without_bundle_or_object():
    from app.domain.canonical_models import ArchaeologyObjectData

    mock_client = MockOpenRouterClient({})
    service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")
    obj = ArchaeologyObjectData(object_id="obj_x", site="1지점", canonical_name="X")

    assert await service.review_object_bundle(archaeology_object=None, bundle=None) == []
    assert await service.review_object_bundle(archaeology_object=obj, bundle=None) == []
    empty_bundle = ObjectEvidenceBundle(object_id="obj_x", canonical_name="X")
    assert await service.review_object_bundle(archaeology_object=obj, bundle=empty_bundle) == []
    assert mock_client.last_prompt is None


def test_real_neo4j_bundle_refresh_includes_vlm_observation():
    """Real Neo4j (optional): object -> text claim -> VLM observation evidence
    persisted via candidate SUPPORTED_BY -> re-queried bundle includes the
    vlm_observation in visual_observations. Scoped ai_test_* ids, cleanup in
    finally."""
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    from neo4j import GraphDatabase

    try:
        driver = GraphDatabase.driver(
            "bolt://127.0.0.1:7687", auth=("neo4j", password)
        )
        driver.verify_connectivity()
    except Exception:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    scope = f"ai_test_{uuid.uuid4().hex[:8]}"
    project_id = f"{scope}_proj"
    version_id = f"{scope}_ver"
    page_id = f"{scope}_p1"
    block_id = f"{scope}_b1"
    obj_id = f"{scope}_obj"
    ref_id = f"{scope}_ref"
    plate_id = f"{scope}_plate45"
    cand_id = f"{scope}_cand"
    vlm_ev_id = f"{scope}_vlm_ev"
    try:
        driver.execute_query(
            """
            CREATE (proj:Project {id: $project_id})
            CREATE (v:DocumentVersion {id: $version_id, stage: '1차', sha256: 'sha256_body'})
            CREATE (p:Page {id: $page_id, physical_page: 5, printed_page: 5})
            CREATE (b:TextBlock {id: $block_id, text: '규모는 길이 275cm이다', order: 1, block_type: 'paragraph'})
            CREATE (obj:ArchaeologyObject {id: $obj_id, canonical_name: '1지점 청동기시대 6호 석관묘',
                    point: '1지점', period: '청동기시대', type: '석관묘', number: '6호'})
            CREATE (ref:Reference {id: $ref_id, ref_type: 'plate', number: '45', raw_text: '도판 : 45',
                    source_block_id: $block_id, source_sha256: 'sha256_body', physical_page: 5})
            CREATE (plate:Plate {id: $plate_id, number: '45', physical_page: 47,
                    title: '1지점 청동기시대 6호 석관묘', source_sha256: 'sha256_plate',
                    document_version_id: $version_id, raw_identifier: '【도판 45】'})
            CREATE (v)-[:HAS_PAGE]->(p)
            CREATE (p)-[:HAS_BLOCK]->(b)
            CREATE (b)-[:MENTIONS]->(obj)
            CREATE (b)-[:REFERENCES]->(ref)
            CREATE (ref)-[:RESOLVES_TO]->(plate)
            CREATE (plate)-[:DEPICTS]->(obj)
            """,
            project_id=project_id,
            version_id=version_id,
            page_id=page_id,
            block_id=block_id,
            obj_id=obj_id,
            ref_id=ref_id,
            plate_id=plate_id,
        )
        repo = CanonicalRepository(driver=driver)
        review_repo = ReviewRepository(driver=driver)

        # Before VLM persistence: text claims present, no visual observations.
        bundle_before = repo.get_object_evidence_bundle(obj_id)
        assert bundle_before.text_claims, "text claim must be traversable"
        assert bundle_before.visual_observations == []

        # Simulate the orchestrator's post-VLM persistence: a candidate ABOUT
        # the object SUPPORTED_BY the vlm_observation evidence.
        vlm_ev = EvidenceData(
            id=vlm_ev_id,
            kind="vlm_observation",
            source_sha256="sha256_plate",
            document_version_id=version_id,
            page_id=page_id,
            value={"status": "SUPPORTED", "observations": {"site_label": "1지점"}},
            confidence=0.9,
            analysis_run_id="run_ai_test",
        )
        from app.domain.review_models import CorrectionCandidateData

        cand = CorrectionCandidateData(
            candidate_id=cand_id,
            rule_category="figure_plate_table_photo_ref",
            change_type="modified",
            status="pending_review",
            original_text="도판 : 45",
            evidence=vlm_ev,
            evidence_list=[vlm_ev],
            archaeology_object_id=obj_id,
            confidence=0.9,
            analysis_run_id="run_ai_test",
        )
        review_repo.save_candidates(
            project_id=project_id,
            candidates=[cand],
            analysis_run_id="run_ai_test",
        )

        # After refresh: the bundle exposes the vlm_observation.
        bundle_after = repo.get_object_evidence_bundle(obj_id)
        assert any(ev.kind == "vlm_observation" for ev in bundle_after.visual_observations), (
            "refreshed bundle must include the persisted vlm_observation"
        )
        assert bundle_after.visual_observations[0].id == vlm_ev_id
    finally:
        driver.execute_query(
            "MATCH (n) WHERE n.id STARTS WITH $scope DETACH DELETE n",
            scope=scope,
        )
        driver.close()

# ---------------------------------------------------------------------------
# task-10-review §6 nit fold-ins
# ---------------------------------------------------------------------------


def _ambiguous_body_page_with_reference() -> ParsedPage:
    """One page whose reference block mentions TWO objects (ambiguous source
    block): the VLM candidate must not be silently linked to either."""
    return ParsedPage(
        page_id="ver_g_p1",
        physical_page=1,
        printed_page=1,
        header="",
        raw_text=(
            "본문 첫째 블록은 무관한 내용이다. "
            "1지점 청동기시대 1호 주거지와 2호 주거지(도판 : 45) 조사를 진행하였다."
        ),
        normalized_text=(
            "1지점 청동기시대 1호 주거지와 2호 주거지(도판 : 45) 조사를 진행하였다."
        ),
        text_blocks=[
            TextBlockData(
                block_id="p1_b1",
                text="본문 첫째 블록은 무관한 내용이다.",
                normalized_text="본문 첫째 블록은 무관한 내용이다.",
                block_type="paragraph",
                order=1,
                source_sha256="sha256_g",
            ),
            TextBlockData(
                block_id="p1_b2",
                text="1지점 청동기시대 1호 주거지와 2호 주거지(도판 : 45) 조사를 진행하였다.",
                normalized_text=(
                    "1지점 청동기시대 1호 주거지와 2호 주거지(도판 : 45) 조사를 진행하였다."
                ),
                block_type="paragraph",
                order=2,
                source_sha256="sha256_g",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number="45",
                        source_block_id="p1_b2",
                        raw_text="도판 : 45",
                        source_sha256="sha256_g",
                        physical_page=1,
                    )
                ],
            ),
        ],
        captions=[],
        source_sha256="sha256_g",
    )


def _refresh_empty_driver() -> QueueFakeNeo4jDriver:
    """Bundle driver whose SECOND pass (the post-VLM refresh) returns no
    identity row: a successful-but-empty refresh."""
    return (
        QueueFakeNeo4jDriver()
        .respond(
            "RETURN properties(obj) AS obj",
            [[{"obj": {"canonical_name": "1지점 청동기시대 1호 주거지"}}], []],
        )
        .respond("[:REFERENCES]->(ref:Reference)", [[]])
        .respond("[:MENTIONS]->(obj:ArchaeologyObject", [[_text_claim_row()], []])
        .respond("[:DEPICTS]->(obj:ArchaeologyObject", [[]])
        .respond("[:SUPPORTED_BY]->(ev:Evidence)", [[], []])
    )


async def test_orchestrator_warns_when_bundle_refresh_succeeds_but_is_empty(tmp_path):
    """task-10-review §6 nit: a successful-but-empty post-VLM refresh keeps
    the pre-VLM bundle WITH an explicit warning — never silent."""
    driver = _refresh_empty_driver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    render_path = tmp_path / "render.png"
    render_path.write_bytes(_png_bytes((200, 200), (180, 30, 30)))
    vlm = CapturingVLMService()
    pipeline = AssetReviewPipeline(
        vlm_service=vlm,
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )
    ai = CapturingAIService()

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        asset_review_pipeline=pipeline,
        ai_review_service=ai,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_refresh_empty",
        body_version_id="ver_g",
        plate_version_id="ver_plate",
        body_pages=[_body_page_with_reference()],
        plates=_plate_with_panel(render_uri=str(render_path)),
        enable_vlm=True,
        enable_ai_review=True,
    )

    assert result.status == "completed"
    warnings = "\n".join(result.warnings)
    assert "refresh" in warnings and "empty bundle" in warnings, result.warnings
    assert len(ai.bundle_calls) == 1, "the pre-VLM bundle is still used for the LLM"
    assert ai.in_memory_calls == []
    assert not any("DEGRADED" in w for w in result.warnings), result.warnings


async def test_orchestrator_warns_when_vlm_reference_block_mentions_multiple_objects(
    tmp_path,
):
    """task-10-review §6 nit: a VLM candidate from a block mentioning multiple
    objects is never silently assigned; the warning is explicit."""
    driver = EmptyFakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    render_path = tmp_path / "render.png"
    render_path.write_bytes(_png_bytes((200, 200), (180, 30, 30)))
    vlm = CapturingVLMService()
    pipeline = AssetReviewPipeline(
        vlm_service=vlm,
        cache=AssetHashCache(cache_dir=tmp_path / "cache"),
    )

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        asset_review_pipeline=pipeline,
    )
    result = await orchestrator.run_proofreading(
        project_id="proj_ambiguous_vlm",
        body_version_id="ver_g",
        plate_version_id="ver_plate",
        body_pages=[_ambiguous_body_page_with_reference()],
        plates=_plate_with_panel(render_uri=str(render_path)),
        enable_vlm=True,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert len(vlm.calls) == 1
    warnings = "\n".join(result.warnings)
    assert "not linked to a single object" in warnings, result.warnings
    vlm_candidates = [
        c
        for c in result.candidates
        if c.candidate_id.startswith("cand_vlm_")
    ]
    assert vlm_candidates
    assert all(c.archaeology_object_id is None for c in vlm_candidates)
