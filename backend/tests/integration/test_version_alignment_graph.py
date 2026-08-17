"""Gate Test 5 — version graph (plan §6 Test 5).

Persist 1차/2차/3차 DocumentVersions + pages, run PageAligner via the real
orchestrator (persist_version_alignment), and verify PRECEDES (1차→2차→3차) and
ALIGNED_TO {score,status,method,run_id} are real relationships with allowed
status values. Scoped ids (it_<uuid8>_) are deleted in finally.
"""
import uuid

from app.domain.document_structure import ParsedPage, make_page_id
from app.domain.models import StoredFile
from app.graph.project_repository import ProjectRepository
from app.graph.review_repository import ReviewRepository
from app.services.orchestrator_factory import build_proofreading_orchestrator

ALLOWED_ALIGNMENT_STATUS = {"exact", "probable", "manual_review"}


def _stored(scope: str, name: str) -> StoredFile:
    return StoredFile(
        uri=f"incoming/{scope}/{name}",
        sha256=f"sha256_{scope}_{name}",
        size_bytes=1,
        mime_type="application/pdf",
        original_name=name,
    )


def _page(version_id: str, physical_page: int, text: str) -> ParsedPage:
    return ParsedPage(
        page_id=make_page_id(version_id, physical_page),
        physical_page=physical_page,
        printed_page=physical_page,
        header="",
        raw_text=text,
        normalized_text=text,
        source_sha256=f"sha256_{version_id}",
    )


def test_real_neo4j_version_alignment_graph(neo4j_driver, scoped_prefix, cleanup, create_project):
    """Gate Test 5: PRECEDES (1차→2차→3차) and ALIGNED_TO persist as real
    relationships with allowed status values."""
    scope = scoped_prefix
    project_repo = ProjectRepository(neo4j_driver)
    project_id = create_project(scope, f"{scope} project")

    versions = {}
    for stage in ("1차", "2차", "3차"):
        _doc, version = project_repo.create_document_with_version(
            project_id=project_id,
            stored=_stored(scope, f"{stage}.pdf"),
            stage=stage,
            kind="report_body",
        )
        versions[stage] = version

    text = "논산 산노리 유적 1호 토광묘 조사 개요"
    version_pages = {}
    version_ids = {}
    review_repo = ReviewRepository(neo4j_driver)
    for stage, version in versions.items():
        page = _page(version.id, 1, text)
        review_repo.save_pages_and_blocks(version_id=version.id, pages=[page])
        version_pages[stage] = [page]
        version_ids[stage] = version.id

    run_id = f"{scope}_run"
    try:
        orchestrator = build_proofreading_orchestrator(neo4j_driver)
        orchestrator.persist_version_alignment(
            project_id=project_id,
            version_pages=version_pages,
            version_ids=version_ids,
            run_id=run_id,
        )

        # PRECEDES: 1차→2차 and 2차→3차
        recs, _, _ = neo4j_driver.execute_query(
            """
            MATCH (a:DocumentVersion {id: $v1})-[:PRECEDES]->(b:DocumentVersion {id: $v2})
            RETURN count(*) AS c
            """,
            v1=versions["1차"].id,
            v2=versions["2차"].id,
        )
        assert recs[0]["c"] == 1, "1차 must PRECEDES 2차"
        recs2, _, _ = neo4j_driver.execute_query(
            """
            MATCH (a:DocumentVersion {id: $v2})-[:PRECEDES]->(b:DocumentVersion {id: $v3})
            RETURN count(*) AS c
            """,
            v2=versions["2차"].id,
            v3=versions["3차"].id,
        )
        assert recs2[0]["c"] == 1, "2차 must PRECEDES 3차"

        # ALIGNED_TO between the three pages with the exact property set
        p1 = make_page_id(versions["1차"].id, 1)
        p2 = make_page_id(versions["2차"].id, 1)
        p3 = make_page_id(versions["3차"].id, 1)
        recs_a, _, _ = neo4j_driver.execute_query(
            """
            MATCH (a:Page {id: $p1})-[r:ALIGNED_TO]->(b:Page {id: $p2})
            RETURN r.status AS status, r.score AS score,
                   r.method AS method, r.run_id AS run_id
            """,
            p1=p1,
            p2=p2,
        )
        assert len(recs_a) == 1, "ALIGNED_TO must exist between 1차 and 2차 pages"
        assert recs_a[0]["status"] in ALLOWED_ALIGNMENT_STATUS
        assert recs_a[0]["method"] == "dtw_weighted"
        assert recs_a[0]["run_id"] == run_id

        recs_a2, _, _ = neo4j_driver.execute_query(
            """
            MATCH (a:Page {id: $p1})-[r:ALIGNED_TO]->(b:Page {id: $p3})
            RETURN r.status AS status
            """,
            p1=p1,
            p3=p3,
        )
        assert len(recs_a2) == 1, "ALIGNED_TO must exist between 1차 and 3차 pages"
        assert recs_a2[0]["status"] in ALLOWED_ALIGNMENT_STATUS
    finally:
        cleanup(scope)