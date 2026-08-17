import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
import pytest

from pypdf import PdfWriter

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    PlateData,
    PlatePanelData,
    ReferenceData,
    ResolutionStatus,
)
from app.domain.document_structure import CaptionData, ParsedPage, TextBlockData
from app.domain.review_models import (
    CorrectionCandidateData,
    EvidenceData,
    ReviewStatus,
)
from app.graph.canonical_repository import CanonicalRepository
from app.graph.review_repository import ReviewRepository
from app.services.ai_review_service import AIReviewService
from app.services.asset_matcher import AssetMatcher, ResolutionResult
from app.services.asset_review_pipeline import AssetReviewPipeline
from app.services.drawing_parser import DrawingIndex
from app.services.object_resolver import ObjectResolver
from app.services.pdf_parser import PDFParser
from app.services.plate_parser import PlateIndex, PlateParser
from app.services.proofreading_orchestrator import (
    OrchestratorResult,
    ProofreadingOrchestrator,
    run_proofreading,
)
from app.services.rule_engine import RuleEngine
from app.services.vlm_review_service import VLMReviewResult, VLMReviewService


class FakeNeo4jRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class FakeNeo4jDriver:
    def __init__(self, records_to_return: list[dict[str, Any]] | None = None):
        self.queries: list[dict[str, Any]] = []
        self.records_to_return = [FakeNeo4jRecord(r) for r in (records_to_return or [])]

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        return self.records_to_return, None, None


GOLDEN_FIXTURE = Path(__file__).parent / "fixtures/golden/plate_45_fixture.pdf"


def _create_sample_parsed_pages(version_id: str = "ver_sannori_1") -> list[ParsedPage]:
    page1 = ParsedPage(
        physical_page=105,
        printed_page=101,
        header="백제문화유산연구원 | 101",
        raw_text=(
            "1지점 청동기시대 6호 석관묘는 구릉 남사면에 위치한다.\n"
            "평면 형태는 장방형이며, 규모는 길이 210cm, 너비 60cm, 잔존깊이 35cm이다.\n"
            "내부에서 마제석검 1점이 출토되었다(도판 : 45, 도면 : 57).\n"
            "또한 2지점 2호 토광묘(도면 : , 도판 : ) 조사를 진행하였다.\n"
        ),
        normalized_text=(
            "1지점 청동기시대 6호 석관묘는 구릉 남사면에 위치한다. "
            "평면 형태는 장방형이며, 규모는 길이 210cm, 너비 60cm, 잔존깊이 35cm이다. "
            "내부에서 마제석검 1점이 출토되었다(도판 : 45, 도면 : 57). "
            "또한 2지점 2호 토광묘(도면 : , 도판 : ) 조사를 진행하였다."
        ),
        text_blocks=[
            TextBlockData(
                block_id="p105_b1",
                text="1지점 청동기시대 6호 석관묘는 구릉 남사면에 위치한다.",
                normalized_text="1지점 청동기시대 6호 석관묘는 구릉 남사면에 위치한다.",
                order=1,
                block_type="paragraph",
                bbox=(50.0, 100.0, 400.0, 120.0),
                source_sha256="sha256_body_sample",
            ),
            TextBlockData(
                block_id="p105_b2",
                text="평면 형태는 장방형이며, 규모는 길이 2.1m, 너비 60cm, 잔존깊이 35cm이다.",
                normalized_text="평면 형태는 장방형이며, 규모는 길이 2.1m, 너비 60cm, 잔존깊이 35cm이다.",
                order=2,
                block_type="paragraph",
                bbox=(50.0, 130.0, 400.0, 150.0),
                source_sha256="sha256_body_sample",
            ),
            TextBlockData(
                block_id="p105_b3",
                text="내부에서 마제석검 1점이 출토되었다(도판 : 45, 도면 : 57).",
                normalized_text="내부에서 마제석검 1점이 출토되었다(도판 : 45, 도면 : 57).",
                order=3,
                block_type="paragraph",
                bbox=(50.0, 160.0, 400.0, 180.0),
                source_sha256="sha256_body_sample",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number="45",
                        source_block_id="p105_b3",
                        raw_text="도판 : 45",
                        source_sha256="sha256_body_sample",
                        bbox=(50.0, 160.0, 400.0, 180.0),
                        physical_page=105,
                    ),
                    ReferenceData(
                        ref_type="drawing",
                        number="57",
                        source_block_id="p105_b3",
                        raw_text="도면 : 57",
                        source_sha256="sha256_body_sample",
                        bbox=(50.0, 160.0, 400.0, 180.0),
                        physical_page=105,
                    ),
                ],
            ),
            TextBlockData(
                block_id="p105_b4",
                text="또한 2지점 2호 토광묘(도면 : , 도판 : ) 조사를 진행하였다.",
                normalized_text="또한 2지점 2호 토광묘(도면 : , 도판 : ) 조사를 진행하였다.",
                order=4,
                block_type="paragraph",
                bbox=(50.0, 190.0, 400.0, 210.0),
                source_sha256="sha256_body_sample",
            ),
        ],
        captions=[
            CaptionData(
                caption_id="p105_c1",
                raw_text="【도면 57】 1지점 청동기시대 6호 석관묘",
                drawing_number="57",
                bbox=(50.0, 300.0, 300.0, 320.0),
                source_sha256="sha256_body_sample",
                references=[
                    ReferenceData(
                        ref_type="drawing",
                        number="57",
                        source_block_id="p105_c1",
                        raw_text="【도면 57】 1지점 청동기시대 6호 석관묘",
                        source_sha256="sha256_body_sample",
                        physical_page=105,
                    )
                ],
            )
        ],
        source_sha256="sha256_body_sample",
    )
    return [page1]


def _create_sample_plates(version_id: str = "ver_plate_1") -> list[PlateData]:
    panel1 = PlatePanelData(
        panel_id=f"{version_id}_plate_45_panel_1",
        plate_id=f"{version_id}_plate_45",
        panel_index=1,
        caption="1지점 청동기시대 6호 석관묘 마제석검",
        bbox=(10.0, 10.0, 200.0, 200.0),
        physical_page=47,
        source_sha256="sha256_plate_sample",
    )
    plate45 = PlateData(
        plate_id=f"{version_id}_plate_45",
        number="45",
        physical_page=47,
        title="1지점 청동기시대 6호 석관묘",
        bbox=(50.0, 50.0, 500.0, 700.0),
        source_sha256="sha256_plate_sample",
        document_version_id=version_id,
        panels=[panel1],
        raw_identifier="【도판 45】",
    )
    return [plate45]


def _create_sample_drawings(version_id: str = "ver_drawing_1") -> list[DrawingData]:
    drawing57 = DrawingData(
        drawing_id=f"{version_id}_drawing_57",
        number="57",
        physical_page=60,
        title="1지점 청동기시대 6호 석관묘",
        bbox=(50.0, 50.0, 500.0, 700.0),
        source_sha256="sha256_drawing_sample",
        document_version_id=version_id,
        raw_identifier="【도면 57】",
    )
    return [drawing57]


@pytest.mark.anyio
async def test_full_pipeline_execution_with_preparsed_data():
    pages = _create_sample_parsed_pages()
    plates = _create_sample_plates()
    drawings = _create_sample_drawings()

    plate_index = PlateIndex(
        plates_by_number={p.number: p for p in plates}, plates=plates
    )

    mock_client = MagicMock()
    mock_client.analyze_text_discrepancy = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "candidates": [
                                {
                                    "category": "annotation_resolution",
                                    "change_type": "modified",
                                    "original_text": "남사면에 위치한다",
                                    "proposed_text": "남쪽 사면에 위치한다",
                                    "rationale": "표현 명확화",
                                    "cited_evidence_ids": [
                                        "ev_claim_obj_3e1a0b3f5451_p105_b1"
                                    ],
                                    "confidence": 0.9,
                                }
                            ]
                        })
                    }
                }
            ],
            "usage": {"total_tokens": 120},
        }
    )

    ai_service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")

    orchestrator = ProofreadingOrchestrator(
        pdf_parser=PDFParser(),
        plate_parser=PlateParser(),
        object_resolver=ObjectResolver(),
        asset_matcher=AssetMatcher(plate_index=plate_index),
        rule_engine=RuleEngine(),
        ai_review_service=ai_service,
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_sannori",
        body_version_id="ver_sannori_1",
        plate_version_id="ver_plate_1",
        body_pages=pages,
        plates=plates,
        drawings=drawings,
        enable_vlm=False,
        enable_ai_review=True,
    )

    assert isinstance(result, OrchestratorResult)
    assert result.status == "completed"
    assert result.project_id == "proj_sannori"
    assert result.pages_parsed == 1
    assert result.objects_resolved >= 2
    assert result.references_resolved >= 1
    assert len(result.evidences) >= 3

    # Verify all candidates strictly have status == "pending_review"
    assert len(result.candidates) > 0
    for cand in result.candidates:
        assert cand.status == "pending_review"
        assert cand.analysis_run_id == result.analysis_run_id
        assert cand.evidence is not None or len(cand.evidence_list) > 0

    # Summary metrics verification
    assert "total_candidates" in result.summary
    assert "by_category" in result.summary
    assert "by_status" in result.summary
    assert result.summary["by_status"].get("pending_review") == len(result.candidates)


@pytest.mark.anyio
async def test_full_pipeline_with_real_plate_golden_fixture():
    assert GOLDEN_FIXTURE.is_file(), f"Golden fixture missing at {GOLDEN_FIXTURE}"
    pages = _create_sample_parsed_pages()

    orchestrator = ProofreadingOrchestrator()

    result = await orchestrator.run_proofreading(
        project_id="proj_golden_test",
        body_version_id="ver_body_1",
        plate_version_id="ver_plate_golden",
        body_pages=pages,
        plate_pdf_path=GOLDEN_FIXTURE,
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert len(result.plates) >= 4
    assert result.references_resolved >= 1

    # Check plate 45 was parsed and resolved
    plate45 = next((p for p in result.plates if p.number == "45"), None)
    assert plate45 is not None
    assert plate45.physical_page == 47


@pytest.mark.anyio
async def test_orchestrator_persists_to_neo4j_repositories():
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    pages = _create_sample_parsed_pages()
    plates = _create_sample_plates()
    drawings = _create_sample_drawings()

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_neo4j_audit",
        body_version_id="ver_body_audit",
        plate_version_id="ver_plate_audit",
        body_pages=pages,
        plates=plates,
        drawings=drawings,
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert len(driver.queries) > 0

    all_queries = " ".join(q["query"] for q in driver.queries)
    # Check that Neo4j commands for all core canonical and review nodes were executed
    assert "MERGE (page:Page" in all_queries
    assert "MERGE (plate:Plate" in all_queries
    assert "MERGE (drawing:Drawing" in all_queries
    assert "MERGE (obj:ArchaeologyObject" in all_queries
    assert "MERGE (ref:Reference" in all_queries
    assert "MERGE (ev:Evidence" in all_queries
    assert "MERGE (cand:CorrectionCandidate" in all_queries
    assert "MERGE (run:AnalysisRun" in all_queries


@pytest.mark.anyio
async def test_orchestrator_integrity_all_candidates_pending_review():
    pages = _create_sample_parsed_pages()
    plates = _create_sample_plates()

    # RuleEngine will detect blank references and other discrepancies
    orchestrator = ProofreadingOrchestrator()

    result = await orchestrator.run_proofreading(
        project_id="proj_integrity",
        body_version_id="ver_body_1",
        body_pages=pages,
        plates=plates,
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert len(result.candidates) > 0
    for cand in result.candidates:
        assert (
            cand.status == "pending_review"
        ), f"Candidate {cand.candidate_id} status is {cand.status}, expected pending_review"


@pytest.mark.anyio
async def test_orchestrator_vlm_integration(tmp_path: Path):
    pages = _create_sample_parsed_pages()
    plates = _create_sample_plates()

    mock_vlm = MagicMock(spec=VLMReviewService)
    mock_vlm.verify_plate_photo = AsyncMock(
        return_value=VLMReviewResult(
            status="match",
            confidence=0.95,
            rationale="1지점 6호 석관묘 마제석검 visual confirmed",
            observations=["Stone dagger present"],
            supported_claims=["마제석검 1점"],
            contradicted_claims=[],
            unobservable_claims=[],
        )
    )

    from app.services.asset_cache import AssetHashCache
    cache = AssetHashCache(cache_dir=tmp_path / "cache")
    vlm_pipeline = AssetReviewPipeline(vlm_service=mock_vlm, cache=cache)

    orchestrator = ProofreadingOrchestrator(
        asset_review_pipeline=vlm_pipeline,
        vlm_service=mock_vlm,
    )

    # Provide sample image bytes to simulate valid panel render
    # PNG 1x1 transparent dummy
    dummy_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf"
        b"\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    # Mock panel render uri / bytes
    plate_panel = PlatePanelData(
        panel_id="ver_plate_1_plate_45_panel_1",
        plate_id="ver_plate_1_plate_45",
        panel_index=1,
        caption="마제석검",
        bbox=(0.0, 0.0, 1.0, 1.0),
        physical_page=47,
        source_sha256="sha256_plate_sample",
    )
    plate_with_panel = PlateData(
        plate_id="ver_plate_1_plate_45",
        number="45",
        physical_page=47,
        title="1지점 청동기시대 6호 석관묘",
        panels=[plate_panel],
        raw_identifier="【도판 45】",
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_vlm_test",
        body_version_id="ver_body_1",
        plate_version_id="ver_plate_1",
        body_pages=pages,
        plates=[plate_with_panel],
        enable_vlm=True,
        enable_ai_review=False,
    )

    assert result.status == "completed"


@pytest.mark.anyio
async def test_orchestrator_uses_provided_drawing_index():
    """P0-1: a reconstructed DrawingIndex passed by the worker is used directly
    (no PDF reparse) and its drawings feed resolution + persistence."""
    from app.domain.canonical_models import DrawingData

    pages = _create_sample_parsed_pages()
    drawing = DrawingData(
        drawing_id="ver_draw_1_drawing_16",
        number="16",
        physical_page=18,
        title="1지점 6호 석관묘 실측도",
        document_version_id="ver_draw_1",
    )
    drawing_index = DrawingIndex(
        drawings_by_number={"16": drawing}, drawings=[drawing]
    )
    driver = FakeNeo4jDriver()
    orchestrator = ProofreadingOrchestrator(
        canonical_repo=CanonicalRepository(driver=driver, database="test_db"),
        review_repo=ReviewRepository(driver=driver, database="test_db"),
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_draw_index",
        body_version_id="ver_body_1",
        drawing_version_id="ver_draw_1",
        body_pages=pages,
        drawing_index=drawing_index,
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert len(result.drawings) == 1
    assert result.drawings[0].drawing_id == "ver_draw_1_drawing_16"
    all_queries = " ".join(q["query"] for q in driver.queries)
    assert "MERGE (drawing:Drawing" in all_queries


@pytest.mark.anyio
async def test_orchestrator_fails_closed_when_selected_plate_version_has_no_index():
    """P0-1 / anti-pattern #5: a selected plate version with no index, no
    plates list, and no PDF must fail closed — never an empty PlateIndex."""
    pages = _create_sample_parsed_pages()
    orchestrator = ProofreadingOrchestrator()

    with pytest.raises(ValueError, match="empty canonical index"):
        await orchestrator.run_proofreading(
            project_id="proj_empty_plate",
            body_version_id="ver_body_1",
            plate_version_id="ver_plate_1",
            body_pages=pages,
            enable_vlm=False,
            enable_ai_review=False,
        )


@pytest.mark.anyio
async def test_orchestrator_fails_closed_when_selected_drawing_version_has_no_index():
    """P0-1 / anti-pattern #5: same fail-closed contract for a selected drawing
    version with no index, no drawings list, and no PDF."""
    pages = _create_sample_parsed_pages()
    orchestrator = ProofreadingOrchestrator()

    with pytest.raises(ValueError, match="empty canonical index"):
        await orchestrator.run_proofreading(
            project_id="proj_empty_drawing",
            body_version_id="ver_body_1",
            drawing_version_id="ver_draw_1",
            body_pages=pages,
            enable_vlm=False,
            enable_ai_review=False,
        )


@pytest.mark.anyio
async def test_orchestrator_fails_closed_on_zero_parsed_body_pages():
    """Gate G: a run whose body parses to zero pages must not return a normal
    completed result — it must raise ValueError (previous behavior returned
    status='completed' with 0 pages / 0 objects / 0 references)."""
    orchestrator = ProofreadingOrchestrator()

    with pytest.raises(ValueError, match="zero parsed pages"):
        await orchestrator.run_proofreading(
            project_id="proj_empty",
            body_version_id="ver_empty",
            body_pages=[],
            plates=[],
            drawings=[],
            enable_vlm=False,
            enable_ai_review=False,
        )


@pytest.mark.anyio
async def test_orchestrator_zero_pages_persists_failed_run(tmp_path: Path):
    """Gate G: the zero-page failure is persisted as status='failed',
    step='ingest', error_code='ZERO_PAGES_PARSED' before the ValueError is
    raised."""
    driver = FakeNeo4jDriver()
    review_repo = ReviewRepository(driver=driver, database="test_db")
    orchestrator = ProofreadingOrchestrator(review_repo=review_repo)

    pdf_path = tmp_path / "empty_body.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    empty_parser = MagicMock()
    empty_parser.parse_pdf.return_value = []
    orchestrator.pdf_parser = empty_parser

    with pytest.raises(ValueError, match="zero parsed pages"):
        await orchestrator.run_proofreading(
            project_id="proj_empty",
            body_version_id="ver_empty",
            body_pdf_path=pdf_path,
            enable_vlm=False,
            enable_ai_review=False,
        )

    failed_saves = [
        q
        for q in driver.queries
        if "AnalysisRun" in q["query"] and q["kwargs"].get("error_code")
    ]
    assert failed_saves, "expected a failed AnalysisRun save with error_code"
    assert failed_saves[0]["kwargs"]["status"] == "failed"
    assert failed_saves[0]["kwargs"]["error_code"] == "ZERO_PAGES_PARSED"


@pytest.mark.anyio
async def test_orchestrator_module_level_run_proofreading_helper():
    pages = _create_sample_parsed_pages()
    plates = _create_sample_plates()

    result = await run_proofreading(
        project_id="proj_helper",
        body_version_id="ver_helper",
        body_pages=pages,
        plates=plates,
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert isinstance(result, OrchestratorResult)
    assert result.status == "completed"
    assert result.project_id == "proj_helper"
    assert len(result.candidates) > 0


@pytest.mark.anyio
async def test_orchestrator_detects_archaeological_discrepancies_end_to_end():
    # Construct a page with conflicting dimensions and blank reference for the same object
    page_discrepant = ParsedPage(
        physical_page=120,
        printed_page=116,
        header="백제문화유산연구원 | 116",
        raw_text=(
            "1지점 청동기시대 1호 주거지 규모는 길이 350cm, 너비 200cm이다.\n"
            "1지점 청동기시대 1호 주거지 평면조사에서는 길이 450cm로 기록되었다(도면 : , 도판 : ).\n"
        ),
        normalized_text=(
            "1지점 청동기시대 1호 주거지 규모는 길이 350cm, 너비 200cm이다. "
            "1지점 청동기시대 1호 주거지 평면조사에서는 길이 450cm로 기록되었다(도면 : , 도판 : )."
        ),
        text_blocks=[
            TextBlockData(
                block_id="p120_b1",
                text="1지점 청동기시대 1호 주거지 규모는 길이 350cm, 너비 200cm이다.",
                normalized_text="1지점 청동기시대 1호 주거지 규모는 길이 350cm, 너비 200cm이다.",
                order=1,
                block_type="paragraph",
                bbox=(50.0, 100.0, 400.0, 120.0),
                source_sha256="sha256_disc",
            ),
            TextBlockData(
                block_id="p120_b2",
                text="1지점 청동기시대 1호 주거지 평면조사에서는 길이 450cm로 기록되었다(도면 : , 도판 : ).",
                normalized_text="1지점 청동기시대 1호 주거지 평면조사에서는 길이 450cm로 기록되었다(도면 : , 도판 : ).",
                order=2,
                block_type="paragraph",
                bbox=(50.0, 130.0, 400.0, 150.0),
                source_sha256="sha256_disc",
            ),
        ],
        captions=[],
        source_sha256="sha256_disc",
    )

    orchestrator = ProofreadingOrchestrator()

    result = await orchestrator.run_proofreading(
        project_id="proj_discrepancy",
        body_version_id="ver_disc_1",
        body_pages=[page_discrepant],
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert len(result.candidates) >= 1

    # Check that candidates have pending_review and valid evidences
    for c in result.candidates:
        assert c.status == "pending_review"
        assert c.evidence is not None or len(c.evidence_list) > 0
        assert c.analysis_run_id == result.analysis_run_id


@pytest.mark.anyio
async def test_orchestrator_ai_grounding_rejects_hallucinated_candidates():
    pages = _create_sample_parsed_pages()

    # Mock AI client returning a candidate citing a non-existent/hallucinated evidence ID
    mock_client = MagicMock()
    mock_client.analyze_text_discrepancy = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "candidates": [
                                {
                                    "category": "numeric_value",
                                    "original_text": "길이 210cm",
                                    "proposed_text": "길이 500cm",
                                    "rationale": "Hallucinated claim",
                                    "cited_evidence_ids": ["ev_non_existent_fake_id"],
                                    "confidence": 0.9,
                                }
                            ]
                        })
                    }
                }
            ],
            "usage": {"total_tokens": 50},
        }
    )

    ai_service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")
    orchestrator = ProofreadingOrchestrator(ai_review_service=ai_service)

    result = await orchestrator.run_proofreading(
        project_id="proj_grounding_test",
        body_version_id="ver_grounding",
        body_pages=pages,
        enable_vlm=False,
        enable_ai_review=True,
    )

    # Hallucinated candidate should have been rejected by AIReviewService
    assert not any(
        c.proposed_text == "길이 500cm" for c in result.candidates
    )

