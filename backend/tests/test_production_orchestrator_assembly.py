"""Task 11 tests: production orchestrator assembly (anti-pattern #14 fix),
Task 8 M1 fold-in (production POST /runs passes version_pages/version_ids so
PRECEDES + ALIGNED_TO persist on real runs), DEGRADED warning surfacing, and
fail-closed behavior for missing body version files / non-contiguous stages.
"""
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from neo4j import GraphDatabase

from app.api.reviews import get_orchestrator
from app.domain.document_structure import ParsedPage, make_page_id
from app.domain.models import Document, DocumentVersion, Project, VersionInput
from app.graph.canonical_repository import CanonicalRepository
from app.graph.project_repository import ProjectNotFoundError
from app.graph.review_repository import ReviewRepository
from app.main import create_app
from app.services.ai_review_service import AIReviewService
from app.services.drawing_parser import DrawingParser
from app.services.object_resolver import ObjectResolver
from app.services.orchestrator_factory import build_proofreading_orchestrator
from app.services.pdf_parser import PDFParser
from app.services.plate_parser import PlateParser
from app.services.proofreading_orchestrator import (
    OrchestratorResult,
    ProofreadingOrchestrator,
)
from app.services.rule_engine import RuleEngine
from app.services.vlm_review_service import VLMReviewService


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


def _make_text_pdf(tmp_path: Path, name: str, text: str) -> Path:
    import pymupdf

    pdf_path = tmp_path / name
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class FakeProjectRepository:
    def __init__(self, versions_by_stage: dict[str, DocumentVersion]):
        self.project = Project(id="p1", name="산노리", internal_code=None)
        self.versions_by_stage = versions_by_stage
        self.documents = [
            Document(id="doc_body", project_id="p1", kind="report_body", title="본문")
        ]

    def get_project(self, project_id: str) -> dict:
        if project_id != "p1":
            raise ProjectNotFoundError(project_id)
        return {
            "project": self.project,
            "documents": self.documents,
            "document_versions": list(self.versions_by_stage.values()),
            "analysis_runs": [],
        }

    def get_document_version_by_id(self, version_id: str) -> DocumentVersion | None:
        for v in self.versions_by_stage.values():
            if v.id == version_id:
                return v
        return None

    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ) -> VersionInput | None:
        if project_id != "p1":
            return None
        for st, v in self.versions_by_stage.items():
            if kind != "report_body":
                continue
            if stage is not None and st != stage:
                continue
            if version_id is not None and v.id != version_id:
                continue
            return VersionInput(
                version_id=v.id,
                document_id=v.document_id,
                project_id=project_id,
                kind="report_body",
                stage=st,
                uri=v.uri,
                sha256=v.sha256,
                mime_type=v.mime_type,
            )
        return None


def _body_version(version_id: str, stage: str, pdf_path: Path) -> DocumentVersion:
    return DocumentVersion(
        id=version_id,
        document_id="doc_body",
        analysis_run_id=f"run_{version_id}",
        uri=str(pdf_path),
        sha256="a" * 64,
        size_bytes=1,
        mime_type="application/pdf",
        original_name=f"{stage}.pdf",
        stage=stage,
    )


@pytest.fixture
def asset_cache_dir(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "asset_cache"
    monkeypatch.setenv("ASSET_CACHE_DIR", str(cache_dir))
    return cache_dir


def _full_orchestrator(driver, proj_repo) -> ProofreadingOrchestrator:
    return ProofreadingOrchestrator(
        project_repo=proj_repo,
        canonical_repo=CanonicalRepository(driver=driver, database="test_db"),
        review_repo=ReviewRepository(driver=driver, database="test_db"),
        pdf_parser=PDFParser(),
        plate_parser=PlateParser(),
        drawing_parser=DrawingParser(),
        object_resolver=ObjectResolver(),
        rule_engine=RuleEngine(),
        vlm_service=VLMReviewService(),
        ai_review_service=AIReviewService(),
    )


# ---------------------------------------------------------------------------
# 1. Production orchestrator assembly (anti-pattern #14)
# ---------------------------------------------------------------------------


def test_build_proofreading_orchestrator_assembles_all_collaborators(
    asset_cache_dir,
):
    """The production factory assembles all 10 collaborators — never the
    reduced ProofreadingOrchestrator(review_repo=...) form."""
    driver = FakeNeo4jDriver()
    orch = build_proofreading_orchestrator(driver)

    assert isinstance(orch, ProofreadingOrchestrator)
    assert orch.project_repo is not None
    assert orch.canonical_repo is not None
    assert orch.review_repo is not None
    assert orch.pdf_parser is not None
    assert orch.plate_parser is not None
    assert orch.drawing_parser is not None
    assert orch.object_resolver is not None
    assert orch.rule_engine is not None
    assert orch.vlm_service is not None
    assert orch.ai_review_service is not None


class _FakeRequest:
    def __init__(self, app):
        self.app = app


def test_get_orchestrator_builds_full_orchestrator_from_driver(asset_cache_dir):
    """get_orchestrator builds the complete orchestrator from the app state's
    driver and caches it on the app state."""
    driver = FakeNeo4jDriver()
    app = create_app(
        project_repository=FakeProjectRepository({}),
        review_repository=None,
    )
    app.state.neo4j_driver = driver

    orch = get_orchestrator(_FakeRequest(app))

    assert isinstance(orch, ProofreadingOrchestrator)
    assert orch.canonical_repo is not None
    assert orch.review_repo is not None
    assert orch.project_repo is not None
    assert orch.pdf_parser is not None
    assert orch.plate_parser is not None
    assert orch.drawing_parser is not None
    assert orch.object_resolver is not None
    assert orch.rule_engine is not None
    assert orch.vlm_service is not None
    assert orch.ai_review_service is not None
    assert app.state.orchestrator is orch


def _make_page(version_id: str, physical_page: int, text: str) -> ParsedPage:
    return ParsedPage(
        page_id=make_page_id(version_id, physical_page),
        physical_page=physical_page,
        printed_page=physical_page,
        header="",
        raw_text=text,
        normalized_text=text,
    )


def test_persist_version_alignment_orders_stages_by_rank_not_insertion_order():
    """L1: PRECEDES pairs follow explicit stage rank (1차<2차<3차<final), not
    the caller's dict insertion order."""
    driver = FakeNeo4jDriver()
    review_repo = ReviewRepository(driver=driver, database="test_db")
    orchestrator = ProofreadingOrchestrator(review_repo=review_repo)

    p1 = _make_page("v1", 1, "논산 산노리 유적 1호 토광묘 조사 개요")
    p2 = _make_page("v2", 1, "논산 산노리 유적 1호 토광묘 조사 개요")
    p3 = _make_page("v3", 1, "논산 산노리 유적 1호 토광묘 조사 개요")

    orchestrator.persist_version_alignment(
        project_id="proj_align",
        version_pages={"3차": [p3], "1차": [p1], "2차": [p2]},
        version_ids={"3차": "v3", "1차": "v1", "2차": "v2"},
        run_id="run_align",
    )

    precedes = next(q for q in driver.queries if "PRECEDES" in q["query"])
    assert precedes["kwargs"]["pairs"] == [
        {"from_id": "v1", "to_id": "v2"},
        {"from_id": "v2", "to_id": "v3"},
    ]


def test_persist_version_alignment_raises_when_stage_missing_from_version_ids():
    """L2: a stage present in version_pages but missing from version_ids raises
    (never silently drops it and bridges 1차→3차)."""
    driver = FakeNeo4jDriver()
    review_repo = ReviewRepository(driver=driver, database="test_db")
    orchestrator = ProofreadingOrchestrator(review_repo=review_repo)

    p1 = _make_page("v1", 1, "text")
    p3 = _make_page("v3", 1, "text")

    with pytest.raises(ValueError, match="version_ids missing entries"):
        orchestrator.persist_version_alignment(
            project_id="proj_align",
            version_pages={"1차": [p1], "3차": [p3]},
            version_ids={"1차": "v1"},
            run_id="run_align",
        )


# ---------------------------------------------------------------------------
# 2. Task 8 M1 fold-in: production POST /runs passes version_pages/version_ids
# ---------------------------------------------------------------------------


def test_trigger_proofreading_run_passes_version_pages_and_ids(
    tmp_path: Path, asset_cache_dir
):
    """Production POST /runs resolves body versions by stage, parses their
    stored PDFs, and passes version_pages/version_ids so PRECEDES (1차→2차→3차)
    and ALIGNED_TO persist on a real run."""
    text = "Nonsan Sannori site report page one"
    pdf1 = _make_text_pdf(tmp_path, "1.pdf", text)
    pdf2 = _make_text_pdf(tmp_path, "2.pdf", text)
    pdf3 = _make_text_pdf(tmp_path, "3.pdf", text)
    proj_repo = FakeProjectRepository(
        {
            "1차": _body_version("ver_1cha", "1차", pdf1),
            "2차": _body_version("ver_2cha", "2차", pdf2),
            "3차": _body_version("ver_3cha", "3차", pdf3),
        }
    )
    driver = FakeNeo4jDriver()
    orch = _full_orchestrator(driver, proj_repo)
    app = create_app(
        project_repository=proj_repo,
        review_repository=orch.review_repo,
        orchestrator=orch,
    )
    client = TestClient(app)

    resp = client.post(
        "/api/v1/projects/p1/runs",
        json={
            "bodyVersionId": "ver_1cha",
            "versionStage": "1차",
            "enableVlm": False,
            "enableAiReview": False,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["warnings"] == []

    all_queries = "\n".join(q["query"] for q in driver.queries)
    assert "PRECEDES" in all_queries
    assert "ALIGNED_TO" in all_queries

    precedes = next(q for q in driver.queries if "PRECEDES" in q["query"])
    assert precedes["kwargs"]["pairs"] == [
        {"from_id": "ver_1cha", "to_id": "ver_2cha"},
        {"from_id": "ver_2cha", "to_id": "ver_3cha"},
    ]

    aligned = next(q for q in driver.queries if "ALIGNED_TO" in q["query"])
    edges = aligned["kwargs"]["edges"]
    assert len(edges) == 3
    pairs = {(e["from_id"], e["to_id"]) for e in edges}
    assert pairs == {
        ("ver_1cha_p1", "ver_2cha_p1"),
        ("ver_1cha_p1", "ver_3cha_p1"),
        ("ver_2cha_p1", "ver_3cha_p1"),
    }


def test_trigger_proofreading_run_missing_body_version_file_fails_closed(
    tmp_path: Path, asset_cache_dir
):
    """Gate G: a body version whose stored PDF is missing on disk fails closed
    (404), never silently skipped."""
    text = "Nonsan Sannori site report page one"
    pdf1 = _make_text_pdf(tmp_path, "1.pdf", text)
    pdf3 = _make_text_pdf(tmp_path, "3.pdf", text)
    missing_pdf = tmp_path / "missing-2.pdf"  # never created
    proj_repo = FakeProjectRepository(
        {
            "1차": _body_version("ver_1cha", "1차", pdf1),
            "2차": _body_version("ver_2cha", "2차", missing_pdf),
            "3차": _body_version("ver_3cha", "3차", pdf3),
        }
    )
    driver = FakeNeo4jDriver()
    orch = _full_orchestrator(driver, proj_repo)
    app = create_app(
        project_repository=proj_repo,
        review_repository=orch.review_repo,
        orchestrator=orch,
    )
    client = TestClient(app)

    resp = client.post(
        "/api/v1/projects/p1/runs",
        json={"bodyVersionId": "ver_1cha", "versionStage": "1차"},
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


def test_trigger_proofreading_run_non_contiguous_stages_fail_closed(
    tmp_path: Path, asset_cache_dir
):
    """Never silently bridge 1차→3차: a project with only 1차 and 3차 body
    versions fails closed (400) instead of writing a bogus PRECEDES edge."""
    text = "Nonsan Sannori site report page one"
    pdf1 = _make_text_pdf(tmp_path, "1.pdf", text)
    pdf3 = _make_text_pdf(tmp_path, "3.pdf", text)
    proj_repo = FakeProjectRepository(
        {
            "1차": _body_version("ver_1cha", "1차", pdf1),
            "3차": _body_version("ver_3cha", "3차", pdf3),
        }
    )
    driver = FakeNeo4jDriver()
    orch = _full_orchestrator(driver, proj_repo)
    app = create_app(
        project_repository=proj_repo,
        review_repository=orch.review_repo,
        orchestrator=orch,
    )
    client = TestClient(app)

    resp = client.post(
        "/api/v1/projects/p1/runs",
        json={"bodyVersionId": "ver_1cha", "versionStage": "1차"},
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "input_error"
    # No PRECEDES / ALIGNED_TO write happened
    all_queries = "\n".join(q["query"] for q in driver.queries)
    assert "PRECEDES" not in all_queries
    assert "ALIGNED_TO" not in all_queries


# ---------------------------------------------------------------------------
# 3. DEGRADED warnings surfaced on RunTriggerResponse (task-7-review §5.7)
# ---------------------------------------------------------------------------


def test_run_trigger_response_surfaces_orchestrator_warnings():
    """DEGRADED orchestrator warnings are surfaced on RunTriggerResponse so a
    degraded run is visible to API clients."""

    class WarningOrchestrator:
        async def run_proofreading(self, **kwargs) -> OrchestratorResult:
            return OrchestratorResult(
                project_id="p1",
                analysis_run_id="run_warn",
                status="completed",
                pages_parsed=1,
                objects_resolved=0,
                references_resolved=0,
                candidates=[],
                evidences=[],
                objects=[],
                plates=[],
                drawings=[],
                warnings=[
                    "graph evidence unavailable for object 'obj_1' — "
                    "falling back to in-memory evidence (DEGRADED)"
                ],
            )

    proj_repo = FakeProjectRepository(
        {"1차": _body_version("ver_1cha", "1차", Path("/nonexistent/1.pdf"))}
    )
    app = create_app(
        project_repository=proj_repo,
        review_repository=None,
        orchestrator=WarningOrchestrator(),
    )
    client = TestClient(app)

    resp = client.post(
        "/api/v1/projects/p1/runs",
        json={"bodyVersionId": "ver_1cha", "versionStage": "1차"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["warnings"] == [
        "graph evidence unavailable for object 'obj_1' — "
        "falling back to in-memory evidence (DEGRADED)"
    ]


# ---------------------------------------------------------------------------
# 4. Real Neo4j: production-shaped run persists PRECEDES + ALIGNED_TO
# ---------------------------------------------------------------------------


def _real_driver():
    """Connect to a real Neo4j using NEO4J_* env vars; None when unavailable."""
    uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        return None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return driver
    except Exception:
        return None


@pytest.mark.anyio
async def test_real_neo4j_production_shaped_run_persists_precedes_and_aligned(
    tmp_path: Path,
):
    """Real Neo4j: a production-shaped run (factory-assembled orchestrator +
    version_pages/version_ids) writes DocumentVersion PRECEDES and Page
    ALIGNED_TO. Scoped ids; cleanup in finally."""
    driver = _real_driver()
    if driver is None:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    scope = f"prod_test_{uuid.uuid4().hex[:8]}"
    project_id = f"{scope}_project"
    doc_id = f"{scope}_doc"
    v1, v2, v3 = f"{scope}_v1", f"{scope}_v2", f"{scope}_v3"
    p1, p2, p3 = make_page_id(v1, 1), make_page_id(v2, 1), make_page_id(v3, 1)
    text = "Nonsan Sannori site report page one"
    pdf1 = _make_text_pdf(tmp_path, "1.pdf", text)
    pdf2 = _make_text_pdf(tmp_path, "2.pdf", text)
    pdf3 = _make_text_pdf(tmp_path, "3.pdf", text)
    try:
        driver.execute_query(
            """
            CREATE (p:Project {id: $project_id, name: $project_id})
            CREATE (d:Document {id: $doc_id, projectId: $project_id, kind: 'report_body', title: $project_id})
            CREATE (p)-[:HAS_DOCUMENT]->(d)
            CREATE (v1:DocumentVersion {id: $v1, uri: $uri1, sha256: $sha1, sizeBytes: 1, mimeType: 'application/pdf', originalName: '1.pdf', stage: '1차', createdAt: datetime()})
            CREATE (v2:DocumentVersion {id: $v2, uri: $uri2, sha256: $sha2, sizeBytes: 1, mimeType: 'application/pdf', originalName: '2.pdf', stage: '2차', createdAt: datetime()})
            CREATE (v3:DocumentVersion {id: $v3, uri: $uri3, sha256: $sha3, sizeBytes: 1, mimeType: 'application/pdf', originalName: '3.pdf', stage: '3차', createdAt: datetime()})
            CREATE (d)-[:HAS_VERSION]->(v1)
            CREATE (d)-[:HAS_VERSION]->(v2)
            CREATE (d)-[:HAS_VERSION]->(v3)
            CREATE (p1:Page {id: $p1, physical_page: 1})
            CREATE (p2:Page {id: $p2, physical_page: 1})
            CREATE (p3:Page {id: $p3, physical_page: 1})
            CREATE (v1)-[:HAS_PAGE]->(p1)
            CREATE (v2)-[:HAS_PAGE]->(p2)
            CREATE (v3)-[:HAS_PAGE]->(p3)
            """,
            project_id=project_id,
            doc_id=doc_id,
            v1=v1, v2=v2, v3=v3,
            p1=p1, p2=p2, p3=p3,
            uri1=str(pdf1), uri2=str(pdf2), uri3=str(pdf3),
            sha1="a" * 64, sha2="b" * 64, sha3="c" * 64,
        )

        orch = build_proofreading_orchestrator(driver)
        parser = PDFParser()
        version_pages = {
            "1차": parser.parse_pdf(pdf1, version_id=v1),
            "2차": parser.parse_pdf(pdf2, version_id=v2),
            "3차": parser.parse_pdf(pdf3, version_id=v3),
        }
        version_ids = {"1차": v1, "2차": v2, "3차": v3}

        result = await orch.run_proofreading(
            project_id=project_id,
            body_version_id=v1,
            body_pdf_path=pdf1,
            version_pages=version_pages,
            version_ids=version_ids,
            analysis_run_id=f"{scope}_run",
            enable_vlm=False,
            enable_ai_review=False,
        )
        assert result.status == "completed"

        # PRECEDES: 1차→2차 and 2차→3차
        recs, _, _ = driver.execute_query(
            "MATCH (a:DocumentVersion {id: $v1})-[:PRECEDES]->"
            "(b:DocumentVersion {id: $v2}) RETURN count(*) AS c",
            v1=v1, v2=v2,
        )
        assert recs[0]["c"] == 1
        recs2, _, _ = driver.execute_query(
            "MATCH (a:DocumentVersion {id: $v2})-[:PRECEDES]->"
            "(b:DocumentVersion {id: $v3}) RETURN count(*) AS c",
            v2=v2, v3=v3,
        )
        assert recs2[0]["c"] == 1

        # ALIGNED_TO between the three pages
        recs3, _, _ = driver.execute_query(
            "MATCH (a:Page {id: $p1})-[:ALIGNED_TO]->(b:Page {id: $p2}) "
            "RETURN count(*) AS c",
            p1=p1, p2=p2,
        )
        assert recs3[0]["c"] == 1
        recs4, _, _ = driver.execute_query(
            "MATCH (a:Page {id: $p1})-[:ALIGNED_TO]->(b:Page {id: $p3}) "
            "RETURN count(*) AS c",
            p1=p1, p3=p3,
        )
        assert recs4[0]["c"] == 1
    finally:
        driver.execute_query(
            "MATCH (n) WHERE n.id STARTS WITH $scope DETACH DELETE n",
            scope=scope,
        )
        driver.close()