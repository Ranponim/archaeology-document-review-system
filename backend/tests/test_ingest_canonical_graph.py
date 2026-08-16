from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
import pytest
from pypdf import PdfWriter

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    DrawingRegionData,
    PlateData,
    PlatePanelData,
    ReferenceData,
)
from app.domain.document_structure import CaptionData, ParsedPage, TextBlockData
from app.graph.canonical_repository import CanonicalRepository
from app.graph.review_repository import ReviewRepository
from app.jobs.ingest import (
    ConversionError,
    IngestContext,
    IngestResult,
    InputError,
    run_ingest_job,
)
from app.jobs.worker import execute_ingest_job
from app.services.drawing_parser import DrawingIndex, DrawingParser
from app.services.pdf_parser import PDFParser
from app.services.plate_parser import PlateIndex, PlateParser
from app.services.proofreading_orchestrator import ProofreadingOrchestrator


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


GOLDEN_PLATE_FIXTURE = Path(__file__).parent / "fixtures/golden/plate_45_fixture.pdf"


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "sample_doc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


@pytest.fixture
def corrupt_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "corrupt.pdf"
    pdf_path.write_bytes(b"not a valid pdf content")
    return pdf_path


def test_ingest_report_body_canonical_graph_persistence(tmp_path: Path, sample_pdf: Path):
    """Verify report_body ingestion parses PDF, extracts objects, and persists full graph:
    (DocumentVersion)-[:HAS_PAGE]->(Page)-[:HAS_BLOCK]->(TextBlock),
    (Page)-[:HAS_CAPTION]->(Caption),
    (source)-[:REFERENCES]->(Reference),
    (source)-[:MENTIONS]->(ArchaeologyObject).
    """
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")
    review_repo = ReviewRepository(driver=driver, database="test_db")

    mock_pdf_parser = MagicMock(spec=PDFParser)
    page = ParsedPage(
        page_id="v_body_p1",
        physical_page=1,
        printed_page=1,
        header="Header",
        raw_text="1지점 청동기시대 1호 석관묘에서 마제석검 출토 (도판 : 45).\n【도판 45】 1호 석관묘",
        normalized_text="1지점 청동기시대 1호 석관묘에서 마제석검 출토 (도판 : 45). 【도판 45】 1호 석관묘",
        text_blocks=[
            TextBlockData(
                block_id="b1",
                text="1지점 청동기시대 1호 석관묘에서 마제석검 출토 (도판 : 45).",
                normalized_text="1지점 청동기시대 1호 석관묘에서 마제석검 출토 (도판 : 45).",
                order=1,
                block_type="paragraph",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number="45",
                        source_block_id="b1",
                        raw_text="도판 : 45",
                        physical_page=1,
                    )
                ],
            )
        ],
        captions=[
            CaptionData(
                caption_id="c1",
                raw_text="【도판 45】 1호 석관묘",
                plate_number="45",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number="45",
                        source_block_id="c1",
                        raw_text="【도판 45】",
                        physical_page=1,
                    )
                ],
            )
        ],
    )
    mock_pdf_parser.parse_pdf.return_value = [page]

    result = run_ingest_job(
        project_id="proj_1",
        version_id="v_body",
        kind="report_body",
        file_path=sample_pdf,
        canonical_repo=canonical_repo,
        review_repo=review_repo,
        pdf_parser=mock_pdf_parser,
    )

    assert isinstance(result, IngestResult)
    assert result.status == "completed"
    assert result.kind == "report_body"
    assert result.pages_count == 1
    assert result.objects_count >= 1
    assert result.references_count >= 1

    all_cypher = [q["query"] for q in driver.queries]

    # Verify structural hierarchy
    assert any("HAS_PAGE" in c and "HAS_BLOCK" in c and "HAS_CAPTION" in c for c in all_cypher)
    # Verify references
    assert any("[:REFERENCES]->(ref)" in c for c in all_cypher)
    # Verify mentions with source -> obj direction
    assert any("MERGE (b)-[:MENTIONS]->(obj)" in c and "MERGE (c)-[:MENTIONS]->(obj)" in c for c in all_cypher)


def test_ingest_plate_book_canonical_graph_persistence(tmp_path: Path, sample_pdf: Path):
    """Verify plate_book ingestion parses Plate PDF and persists:
    (DocumentVersion)-[:HAS_PLATE]->(Plate)-[:HAS_PANEL]->(PlatePanel).
    """
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")

    mock_plate_parser = MagicMock(spec=PlateParser)
    plate = PlateData(
        plate_id="plate_45",
        number="45",
        physical_page=10,
        title="1호 석관묘",
        raw_identifier="【도판 45】",
        document_version_id="v_plate",
        panels=[
            PlatePanelData(
                panel_id="panel_45_1",
                plate_id="plate_45",
                panel_index=1,
                caption="마제석검",
            )
        ],
    )
    mock_plate_parser.parse.return_value = PlateIndex(
        plates_by_number={"45": plate},
        plates=[plate],
    )

    result = run_ingest_job(
        project_id="proj_1",
        version_id="v_plate",
        kind="plate_book",
        file_path=sample_pdf,
        canonical_repo=canonical_repo,
        plate_parser=mock_plate_parser,
    )

    assert isinstance(result, IngestResult)
    assert result.status == "completed"
    assert result.kind == "plate_book"
    assert result.plates_count == 1
    assert result.panels_count == 1

    all_cypher = [q["query"] for q in driver.queries]
    # Verify plate persistence
    assert any("HAS_PLATE" in c for c in all_cypher)
    # Verify panel persistence
    assert any("HAS_PANEL" in c for c in all_cypher)


def test_ingest_drawing_book_canonical_graph_persistence(tmp_path: Path, sample_pdf: Path):
    """Verify drawing_book ingestion parses Drawing PDF and persists:
    (DocumentVersion)-[:HAS_DRAWING]->(Drawing)-[:HAS_REGION]->(DrawingRegion).
    """
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver, database="test_db")

    mock_drawing_parser = MagicMock(spec=DrawingParser)
    drawing = DrawingData(
        drawing_id="drawing_12",
        number="12",
        physical_page=5,
        title="1호 석관묘 평단면도",
        raw_identifier="【도면 12】",
        document_version_id="v_drawing",
        regions=[
            DrawingRegionData(
                region_id="region_12_1",
                drawing_id="drawing_12",
                number="1",
                title="평면도",
            )
        ],
    )
    mock_drawing_parser.parse.return_value = DrawingIndex(
        drawings_by_number={"12": drawing},
        drawings=[drawing],
    )

    result = run_ingest_job(
        project_id="proj_1",
        version_id="v_drawing",
        kind="drawing_book",
        file_path=sample_pdf,
        canonical_repo=canonical_repo,
        drawing_parser=mock_drawing_parser,
    )

    assert isinstance(result, IngestResult)
    assert result.status == "completed"
    assert result.kind == "drawing_book"
    assert result.drawings_count == 1
    assert result.regions_count == 1

    all_cypher = [q["query"] for q in driver.queries]
    # Verify drawing persistence
    assert any("HAS_DRAWING" in c for c in all_cypher)
    # Verify region persistence
    assert any("HAS_REGION" in c for c in all_cypher)


def test_ingest_fail_closed_missing_file():
    """Verify fail-closed error handling when file path does not exist."""
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver)

    missing_path = Path("/nonexistent/file/path/doc.pdf")
    with pytest.raises((FileNotFoundError, InputError)):
        run_ingest_job(
            project_id="proj_1",
            version_id="v_missing",
            kind="report_body",
            file_path=missing_path,
            canonical_repo=canonical_repo,
        )


def test_ingest_fail_closed_corrupt_file(corrupt_pdf: Path):
    """Verify fail-closed error handling when file is corrupted."""
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver)

    with pytest.raises(ConversionError):
        run_ingest_job(
            project_id="proj_1",
            version_id="v_corrupt",
            kind="report_body",
            file_path=corrupt_pdf,
            canonical_repo=canonical_repo,
        )


def test_ingest_fail_closed_graph_persistence_failure(sample_pdf: Path):
    """Verify fail-closed behavior when graph persistence fails."""
    driver = FakeNeo4jDriver()
    driver.execute_query = MagicMock(side_effect=RuntimeError("Database connection lost"))
    canonical_repo = CanonicalRepository(driver=driver)
    review_repo = ReviewRepository(driver=driver)

    mock_pdf_parser = MagicMock(spec=PDFParser)
    page = ParsedPage(
        page_id="v_p1",
        physical_page=1,
        printed_page=1,
        header="Header",
        raw_text="Sample text",
        normalized_text="Sample text",
    )
    mock_pdf_parser.parse_pdf.return_value = [page]

    with pytest.raises(RuntimeError, match="Database connection lost"):
        run_ingest_job(
            project_id="proj_1",
            version_id="v_fail",
            kind="report_body",
            file_path=sample_pdf,
            canonical_repo=canonical_repo,
            review_repo=review_repo,
            pdf_parser=mock_pdf_parser,
        )


@pytest.mark.anyio
async def test_orchestrator_coordinates_with_ingest_prerequisite(sample_pdf: Path):
    """Verify ProofreadingOrchestrator can verify and execute canonical graph ingestion
    ensuring complete graph availability before rule/AI analysis.
    """
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver)
    review_repo = ReviewRepository(driver=driver)

    mock_pdf_parser = MagicMock(spec=PDFParser)
    page = ParsedPage(
        page_id="v_body_p1",
        physical_page=1,
        printed_page=1,
        header="Header",
        raw_text="1지점 청동기시대 1호 석관묘 (도판 : 45)",
        normalized_text="1지점 청동기시대 1호 석관묘 (도판 : 45)",
        text_blocks=[
            TextBlockData(
                block_id="b1",
                text="1지점 청동기시대 1호 석관묘 (도판 : 45)",
                normalized_text="1지점 청동기시대 1호 석관묘 (도판 : 45)",
                order=1,
                block_type="paragraph",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number="45",
                        source_block_id="b1",
                        raw_text="도판 : 45",
                    )
                ],
            )
        ],
    )
    mock_pdf_parser.parse_pdf.return_value = [page]

    orchestrator = ProofreadingOrchestrator(
        pdf_parser=mock_pdf_parser,
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )

    result = await orchestrator.run_proofreading(
        project_id="proj_coord",
        body_version_id="v_body",
        body_pdf_path=sample_pdf,
        enable_vlm=False,
        enable_ai_review=False,
    )

    assert result.status == "completed"
    assert result.pages_parsed == 1
    assert result.objects_resolved >= 1

    all_cypher = [q["query"] for q in driver.queries]
    # Check that canonical graph nodes are persisted
    assert any("HAS_PAGE" in c for c in all_cypher)
    assert any("[:REFERENCES]->(ref)" in c for c in all_cypher)
    assert any("MERGE (b)-[:MENTIONS]->(obj)" in c for c in all_cypher)


def test_drawing_parser_header_and_region_extraction():
    """Verify DrawingParser extracts identifier, number, title, and regions correctly."""
    header = "【도면 45】 1지점 6호 석관묘 ① 평면도 ② 단면도"
    parsed = DrawingParser.parse_text_header(header)
    assert parsed is not None
    raw_id, number, title, region_text = parsed
    assert raw_id == "【도면 45】"
    assert number == "45"
    assert "1지점 6호 석관묘" in title

    regions = DrawingParser.extract_regions_from_caption(region_text)
    assert 1 in regions
    assert regions[1] == "평면도"
    assert 2 in regions
    assert regions[2] == "단면도"


def test_worker_run_ingest_job_delegation(sample_pdf: Path):
    """Verify worker.run_ingest_job delegates properly when given explicit parameters."""
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver)
    review_repo = ReviewRepository(driver=driver)

    from app.jobs.worker import run_ingest_job as worker_run_ingest

    res = worker_run_ingest(
        analysis_run_id_or_project_id="proj_worker",
        version_id="ver_worker",
        kind="report_body",
        file_path=sample_pdf,
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )
    assert isinstance(res, dict)
    assert res["status"] == "completed"
    assert res["project_id"] == "proj_worker"
    assert res["version_id"] == "ver_worker"


def test_orchestrator_ensure_canonical_graph_ingested_helper(sample_pdf: Path):
    """Verify ProofreadingOrchestrator.ensure_canonical_graph_ingested invokes kind-aware ingest."""
    driver = FakeNeo4jDriver()
    canonical_repo = CanonicalRepository(driver=driver)
    review_repo = ReviewRepository(driver=driver)

    orchestrator = ProofreadingOrchestrator(
        canonical_repo=canonical_repo,
        review_repo=review_repo,
    )

    result = orchestrator.ensure_canonical_graph_ingested(
        project_id="proj_ensure",
        version_id="v_ensure",
        kind="report_body",
        file_path=sample_pdf,
    )

    assert result.status == "completed"
    assert result.project_id == "proj_ensure"
    assert result.version_id == "v_ensure"

