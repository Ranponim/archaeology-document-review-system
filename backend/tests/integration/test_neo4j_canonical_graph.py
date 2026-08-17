"""Gate A — real graph construction (plan §3 Gate A, §6 Test 1).

Registers real DocumentVersion(body/plate/drawing) nodes via ProjectRepository,
runs the factory-assembled ProofreadingOrchestrator over real body pages, plates
and drawings, then queries the running Neo4j database to assert the persisted
canonical graph:

    DocumentVersion -[:HAS_PAGE]-> Page -[:HAS_BLOCK|HAS_CAPTION]-> source
    source -[:REFERENCES]-> Reference -[:RESOLVES_TO]-> Plate
    source -[:MENTIONS]-> ArchaeologyObject
    Plate -[:DEPICTS]-> ArchaeologyObject

The assertions query the actual DB (relationship counts + traversal), never
in-memory structures. Scoped ids (it_<uuid8>_) are deleted in finally.
"""
import uuid

import pytest

from app.domain.canonical_models import (
    DrawingData,
    PlateData,
    ReferenceData,
)
from app.domain.document_structure import ParsedPage, TextBlockData
from app.domain.models import StoredFile
from app.graph.project_repository import ProjectRepository
from app.services.orchestrator_factory import build_proofreading_orchestrator


def _body_page(scope: str, version_id: str, physical_page: int) -> ParsedPage:
    block_id = f"{scope}_b{physical_page}"
    text = (
        "1지점 청동기시대 6호 석관묘 규모는 길이 275cm이다. "
        "도판 : 45, 도면 : 30"
    )
    return ParsedPage(
        page_id=f"{scope}_p{physical_page}",
        physical_page=physical_page,
        printed_page=physical_page,
        header="",
        raw_text=text,
        normalized_text=text,
        text_blocks=[
            TextBlockData(
                block_id=block_id,
                text=text,
                normalized_text=text,
                block_type="paragraph",
                order=1,
                source_sha256=f"sha256_{scope}",
                references=[
                    ReferenceData(
                        ref_type="plate",
                        number="45",
                        source_block_id=block_id,
                        raw_text="도판 : 45",
                        source_sha256=f"sha256_{scope}",
                        physical_page=physical_page,
                    ),
                    ReferenceData(
                        ref_type="drawing",
                        number="30",
                        source_block_id=block_id,
                        raw_text="도면 : 30",
                        source_sha256=f"sha256_{scope}",
                        physical_page=physical_page,
                    ),
                ],
            )
        ],
        captions=[],
        source_sha256=f"sha256_{scope}",
    )


def _stored(scope: str, name: str) -> StoredFile:
    return StoredFile(
        uri=f"incoming/{scope}/{name}",
        sha256=f"sha256_{scope}_{name}",
        size_bytes=1,
        mime_type="application/pdf",
        original_name=name,
    )


@pytest.mark.anyio
async def test_real_neo4j_canonical_graph_construction(neo4j_driver, scoped_prefix, cleanup, create_project):
    """Gate A: the real orchestrator persists the full canonical body/plate
    graph and the DB traversal returns the expected nodes and relationships."""
    scope = scoped_prefix
    project_repo = ProjectRepository(neo4j_driver)
    project_id = create_project(scope, f"{scope} project")

    body_doc, body_ver = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "body.pdf"),
        stage="1차",
        kind="report_body",
    )
    plate_doc, plate_ver = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "plate.pdf"),
        stage="1차",
        kind="plate_book",
    )
    drawing_doc, drawing_ver = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "drawing.pdf"),
        stage="1차",
        kind="drawing_book",
    )

    body_pages = [_body_page(scope, body_ver.id, 1)]
    plate = PlateData(
        plate_id=f"{scope}_plate45",
        number="45",
        physical_page=47,
        title="1지점 청동기시대 6호 석관묘",
        source_sha256=f"sha256_{scope}_plate",
        document_version_id=plate_ver.id,
        raw_identifier="【도판 45】",
    )
    drawing = DrawingData(
        drawing_id=f"{scope}_drawing30",
        number="30",
        physical_page=12,
        title="1지점 청동기시대 6호 석관묘 실측",
        source_sha256=f"sha256_{scope}_drawing",
        document_version_id=drawing_ver.id,
        raw_identifier="【도면 30】",
    )

    run_id = f"{scope}_run"
    try:
        orchestrator = build_proofreading_orchestrator(neo4j_driver)
        result = await orchestrator.run_proofreading(
            project_id=project_id,
            body_version_id=body_ver.id,
            plate_version_id=plate_ver.id,
            drawing_version_id=drawing_ver.id,
            body_pages=body_pages,
            plates=[plate],
            drawings=[drawing],
            analysis_run_id=run_id,
            enable_vlm=False,
            enable_ai_review=False,
        )
        assert result.status == "completed"

        # Traversal: DocumentVersion -> Page -> source -> Reference -> Plate
        recs, _, _ = neo4j_driver.execute_query(
            """
            MATCH (v:DocumentVersion)-[:HAS_PAGE]->(p:Page)-[:HAS_BLOCK|HAS_CAPTION]->(s)
            MATCH (s)-[:REFERENCES]->(r:Reference)-[:RESOLVES_TO]->(plate:Plate)
            WHERE s.id STARTS WITH $scope
            RETURN v.id AS v, p.id AS p, s.id AS s, r.id AS r, plate.id AS plate
            """,
            scope=scope,
        )
        assert len(recs) >= 1, "no DocumentVersion->Page->source->Reference->Plate path"
        assert any(r["plate"] == plate.plate_id for r in recs)
        assert any(scope in r["r"] for r in recs)

        # MENTIONS: source -> ArchaeologyObject
        recs_m, _, _ = neo4j_driver.execute_query(
            """
            MATCH (s)-[:MENTIONS]->(obj:ArchaeologyObject)
            WHERE s.id STARTS WITH $scope
            RETURN count(DISTINCT s) AS mentions
            """,
            scope=scope,
        )
        assert recs_m[0]["mentions"] >= 1, "no source MENTIONS ArchaeologyObject"

        # DEPICTS: Plate -> ArchaeologyObject
        recs_d, _, _ = neo4j_driver.execute_query(
            """
            MATCH (plate:Plate)-[:DEPICTS]->(obj:ArchaeologyObject)
            WHERE plate.id STARTS WITH $scope
            RETURN count(DISTINCT plate) AS depicts
            """,
            scope=scope,
        )
        assert recs_d[0]["depicts"] >= 1, "no Plate DEPICTS ArchaeologyObject"

        # RESOLVES_TO count for the scoped reference
        recs_r, _, _ = neo4j_driver.execute_query(
            """
            MATCH (r:Reference)-[:RESOLVES_TO]->(plate:Plate)
            WHERE r.id CONTAINS $scope
            RETURN count(r) AS resolved
            """,
            scope=scope,
        )
        assert recs_r[0]["resolved"] >= 1, "no Reference RESOLVES_TO Plate"
    finally:
        cleanup(scope)