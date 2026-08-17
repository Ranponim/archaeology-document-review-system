from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from neo4j import GraphDatabase

from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.graph.production_review_repository import ProductionReviewRepository
from app.graph.review_project_repository import ReviewProjectRepository
from app.graph.strict_asset_repository import StrictAssetRepository
from app.services.review_budget import make_run_candidate_id
from app.services.review_round_execution import resolve_review_round_inputs
from app.services.strict_visual_asset_service import StrictVisualAssetService


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_NEO4J_INTEGRATION") != "1",
    reason="set RUN_NEO4J_INTEGRATION=1 to run real Neo4j remediation tests",
)


@pytest.fixture(scope="module")
def driver():
    uri = os.environ.get("TEST_NEO4J_URI", "bolt://localhost:7687")
    password = os.environ.get("TEST_NEO4J_PASSWORD", "testpassword")
    drv = GraphDatabase.driver(uri, auth=("neo4j", password))
    deadline = time.monotonic() + 45
    last_error = None
    while time.monotonic() < deadline:
        try:
            drv.verify_connectivity()
            break
        except Exception as exc:  # service boot race
            last_error = exc
            time.sleep(1)
    else:
        drv.close()
        raise RuntimeError(f"Neo4j did not become ready: {last_error}")
    yield drv
    with drv.session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()
    drv.close()


@pytest.fixture(autouse=True)
def clean_graph(driver):
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()
    yield


def _seed_project_graph(driver, tmp_path: Path) -> None:
    import fitz

    def make_pdf(path: Path, text: str) -> None:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), text)
        doc.save(path)
        doc.close()

    body_pdf = tmp_path / "body.pdf"
    plate_pdf = tmp_path / "plate.pdf"
    drawing_pdf = tmp_path / "drawing.pdf"
    make_pdf(body_pdf, "body reference plate 45")
    make_pdf(plate_pdf, "plate 45")
    make_pdf(drawing_pdf, "drawing 30")

    with driver.session() as session:
        session.run(
            """
            CREATE (p:Project {id:'p1', name:'P1'})
            CREATE (other:Project {id:'p2', name:'P2'})
            CREATE (bodyDoc:Document {id:'body_doc', projectId:'p1', kind:'report_body'})
            CREATE (plateDoc:Document {id:'plate_doc', projectId:'p1', kind:'plate_book'})
            CREATE (drawDoc:Document {id:'draw_doc', projectId:'p1', kind:'drawing_book'})
            CREATE (body:DocumentVersion {id:'body_v2', stage:'2차', uri:$body_uri, sha256:'bodysha'})
            CREATE (plateV:DocumentVersion {id:'plate_v1', stage:'1차', uri:$plate_uri, sha256:'platesha'})
            CREATE (drawV:DocumentVersion {id:'draw_v1', stage:'1차', uri:$draw_uri, sha256:'drawsha'})
            CREATE (p)-[:HAS_DOCUMENT]->(bodyDoc)
            CREATE (p)-[:HAS_DOCUMENT]->(plateDoc)
            CREATE (p)-[:HAS_DOCUMENT]->(drawDoc)
            CREATE (bodyDoc)-[:HAS_VERSION]->(body)
            CREATE (plateDoc)-[:HAS_VERSION]->(plateV)
            CREATE (drawDoc)-[:HAS_VERSION]->(drawV)
            CREATE (page:Page {id:'page_body_1', physical_page:1, printed_page:1})
            CREATE (body)-[:HAS_PAGE]->(page)
            CREATE (block:TextBlock {id:'block_1', text:'본문 도판 45 확인', normalized_text:'본문 도판 45 확인'})
            CREATE (page)-[:HAS_BLOCK]->(block)
            CREATE (obj:ArchaeologyObject {id:'obj_1', canonical_name:'6호 석관묘', projectId:'p1'})
            CREATE (p)-[:HAS_OBJECT]->(obj)
            CREATE (block)-[:MENTIONS]->(obj)
            CREATE (ref:Reference {id:'ref_plate_45', ref_type:'plate', number:'45'})
            CREATE (block)-[:REFERENCES]->(ref)
            CREATE (plate:Plate {
                id:'plate_45', number:'45', raw_identifier:'【도판 45】',
                title:'6호 석관묘', physical_page:1,
                document_version_id:'plate_v1', source_sha256:'platesha'
            })
            CREATE (plateV)-[:HAS_PLATE]->(plate)
            CREATE (ref)-[:RESOLVES_TO]->(plate)
            CREATE (plate)-[:DEPICTS]->(obj)
            CREATE (drawing:Drawing {
                id:'drawing_30', number:'30', raw_identifier:'【도면 30】',
                title:'6호 석관묘', physical_page:1,
                document_version_id:'draw_v1', source_sha256:'drawsha'
            })
            CREATE (drawV)-[:HAS_DRAWING]->(drawing)
            """,
            body_uri=str(body_pdf),
            plate_uri=str(plate_pdf),
            draw_uri=str(drawing_pdf),
        ).consume()


def test_real_neo4j_round_run_candidate_and_visual_path(driver, tmp_path):
    _seed_project_graph(driver, tmp_path)
    projects = ReviewProjectRepository(driver)

    # Real ReviewRound Cypher must create the canonical three-version set.
    round2 = projects.create_review_round(
        "p1",
        body_version_id="body_v2",
        plate_version_id="plate_v1",
        drawing_version_id="draw_v1",
        notes="real neo4j round",
    )
    assert round2.sequence == 1  # first round node in this isolated graph
    resolved = resolve_review_round_inputs(projects, "p1", round2.id)
    assert resolved.body.version_id == "body_v2"
    assert resolved.plate.version_id == "plate_v1"
    assert resolved.drawing.version_id == "draw_v1"

    reviews = ProductionReviewRepository(driver)
    reviews.create_analysis_run(
        "p1",
        "run_real_1",
        review_round_id=round2.id,
        body_version_id="body_v2",
        plate_version_id="plate_v1",
        drawing_version_id="draw_v1",
        enable_vlm=False,
        enable_ai_review=False,
        version_stage="1차",
    )

    finding = CorrectionCandidateData(
        candidate_id="legacy_rule_id",
        rule_category="figure_plate_table_photo_ref",
        status="pending_review",
        original_text="본문 도판 45 확인",
        proposed_text="본문 도판 45 확인",
        archaeology_object_id="obj_1",
        analysis_run_id="run_real_1",
        severity="high",
        evidence=EvidenceData(
            id="ev_rule_1",
            kind="rule_finding",
            source_sha256="bodysha",
            document_version_id="body_v2",
            page_id="page_body_1",
            value="본문 도판 45 확인",
            rationale="explicit publication reference check",
        ),
    )
    reviews.save_candidates("p1", [finding], analysis_run_id="run_real_1")
    candidate_id = make_run_candidate_id("run_real_1", finding)

    with driver.session() as session:
        record = session.run(
            """
            MATCH (p:Project {id:'p1'})-[:HAS_REVIEW_ROUND]->(rr:ReviewRound)
            MATCH (rr)-[:USES_BODY_VERSION]->(b:DocumentVersion {id:'body_v2'})
            MATCH (rr)-[:USES_PLATE_VERSION]->(pv:DocumentVersion {id:'plate_v1'})
            MATCH (rr)-[:USES_DRAWING_VERSION]->(dv:DocumentVersion {id:'draw_v1'})
            MATCH (p)-[:HAS_RUN]->(run:AnalysisRun {id:'run_real_1'})-[:FOR_ROUND]->(rr)
            MATCH (run)-[:PRODUCED]->(cand:CorrectionCandidate {id:$candidate_id})
            MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)-[:FROM_VERSION]->(b)
            RETURN cand.severity AS severity, cand.findingFingerprint AS fingerprint,
                   ev.analysis_run_id AS evidence_run
            """,
            candidate_id=candidate_id,
        ).single()
    assert record is not None
    assert record["severity"] == "high"
    assert record["fingerprint"]
    assert record["evidence_run"] == "run_real_1"

    # Candidate access is project scoped.
    assert reviews.get_candidate("p1", candidate_id) is not None
    assert reviews.get_candidate("p2", candidate_id) is None

    # Execute the real strict visual Cypher, including explicit
    # Reference->RESOLVES_TO and owning DocumentVersion traversal.
    assets = StrictAssetRepository(driver)
    raw_bundle = assets.get_candidate_visual_bundle(candidate_id, "p1")
    assert raw_bundle is not None
    assert len(raw_bundle["canonical_assets"]) == 1
    canonical = raw_bundle["canonical_assets"][0]
    assert canonical["ref"]["number"] == "45"
    assert canonical["props"]["id"] == "plate_45"
    assert canonical["document_version"]["id"] == "plate_v1"
    assert assets.get_candidate_visual_bundle(candidate_id, "p2") is None

    # Render from the owning PDF resolved through the graph.
    visual_service = StrictVisualAssetService(asset_repo=assets, data_root=tmp_path)
    bundle = visual_service.get_candidate_visual_bundle(candidate_id, "p1")
    assert bundle is not None
    assert bundle["source"] is not None
    assert bundle["canonical"] is not None
    assert bundle["canonical"]["region_id"] == "plate_45"
    assert bundle["canonical"]["document_version_id"] == "plate_v1"
    assert bundle["unresolved_reason"] is None

    page_render = visual_service.get_page_render("page_body_1")
    plate_render = visual_service.get_plate_render("plate_45")
    assert page_render["bytes"].startswith(b"\x89PNG")
    assert plate_render["bytes"].startswith(b"\x89PNG")
