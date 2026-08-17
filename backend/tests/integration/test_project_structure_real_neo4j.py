from app.api.project_structure_contract import ProjectStructureNodeType
from app.graph.project_structure_repository import ProjectStructureRepository


def test_project_structure_traverses_real_graph_and_case6_ignores_filename_decoy(
    neo4j_driver, scoped_prefix, cleanup
):
    scope = scoped_prefix
    project_id = f"{scope}project"
    other_project_id = f"{scope}other_project"
    body_doc = f"{scope}body_doc"
    body_version = f"{scope}body_v1"
    plate_doc = f"{scope}plate_doc"
    plate_version = f"{scope}plate_v1"
    page_id = f"{scope}page78"
    block_id = f"{scope}block78"
    ref_id = f"{scope}ref45"
    plate_id = f"{scope}plate45"
    panel_id = f"{scope}panel45a"
    object_id = f"{scope}obj6"
    decoy_id = f"{scope}decoy45"
    round1 = f"{scope}round1"
    round2 = f"{scope}round2"

    try:
        neo4j_driver.execute_query(
            """
            CREATE (p:Project {id: $project_id, name: '산노리 유적'})
            CREATE (other:Project {id: $other_project_id, name: '다른 프로젝트'})
            CREATE (body:Document {id: $body_doc, kind: 'report_body', title: '보고서 본문'})
            CREATE (bodyv:DocumentVersion {
                id: $body_version, originalName: '3차교정본.pdf', uri: 'incoming/example/body.pdf',
                sha256: 'bodysha', sizeBytes: 100, mimeType: 'application/pdf', stage: 'source'
            })
            CREATE (bodyrun:AnalysisRun {id: $body_run, status: 'completed', step: 'ingest'})
            CREATE (plateDoc:Document {id: $plate_doc, kind: 'plate_book', title: '도판집'})
            CREATE (platev:DocumentVersion {
                id: $plate_version, originalName: '도판집.pdf', uri: 'incoming/example/plate.pdf',
                sha256: 'platesha', sizeBytes: 100, mimeType: 'application/pdf', stage: 'source'
            })
            CREATE (platerun:AnalysisRun {id: $plate_run, status: 'completed', step: 'ingest'})
            CREATE (page:Page {id: $page_id, physical_page: 78, printed_page: '74'})
            CREATE (block:TextBlock {id: $block_id, text: '세부 내용은 도판 45 참조', order: 1})
            CREATE (ref:Reference {id: $ref_id, ref_type: 'plate', number: '45', raw_text: '도판 45', physical_page: 78})
            CREATE (plate:Plate {
                id: $plate_id, number: '45', raw_identifier: '【도판 45】', physical_page: 12,
                document_version_id: $plate_version, title: '6호 석관묘'
            })
            CREATE (panel:PlatePanel {id: $panel_id, plate_id: $plate_id, panel_index: 1, caption: '6호 석관묘 전경'})
            CREATE (obj:ArchaeologyObject {id: $object_id, canonical_name: '1지점 청동기 6호 석관묘'})
            CREATE (decoy:OriginalAsset {id: $decoy_id, originalName: '4. 조사 후_45.JPG'})
            CREATE (r1:ReviewRound {id: $round1, sequence: 1, status: 'approved'})
            CREATE (r2:ReviewRound {id: $round2, sequence: 2, status: 'reviewing'})
            CREATE (p)-[:HAS_DOCUMENT]->(body)
            CREATE (body)-[:HAS_VERSION]->(bodyv)
            CREATE (bodyrun)-[:ANALYZES]->(bodyv)
            CREATE (p)-[:HAS_DOCUMENT]->(plateDoc)
            CREATE (plateDoc)-[:HAS_VERSION]->(platev)
            CREATE (platerun)-[:ANALYZES]->(platev)
            CREATE (bodyv)-[:HAS_PAGE]->(page)
            CREATE (page)-[:HAS_BLOCK]->(block)
            CREATE (block)-[:REFERENCES]->(ref)
            CREATE (platev)-[:HAS_PLATE]->(plate)
            CREATE (plate)-[:HAS_PANEL]->(panel)
            CREATE (ref)-[:RESOLVES_TO]->(plate)
            CREATE (plate)-[:DEPICTS]->(obj)
            CREATE (p)-[:HAS_OBJECT]->(obj)
            CREATE (p)-[:HAS_REVIEW_ROUND]->(r1)
            CREATE (p)-[:HAS_REVIEW_ROUND]->(r2)
            CREATE (r1)-[:PRECEDES]->(r2)
            CREATE (r1)-[:USES_BODY_VERSION]->(bodyv)
            CREATE (r1)-[:USES_PLATE_VERSION]->(platev)
            CREATE (r2)-[:USES_BODY_VERSION]->(bodyv)
            CREATE (r2)-[:USES_PLATE_VERSION]->(platev)
            """,
            project_id=project_id,
            other_project_id=other_project_id,
            body_doc=body_doc,
            body_version=body_version,
            body_run=f"{scope}body_run",
            plate_doc=plate_doc,
            plate_version=plate_version,
            plate_run=f"{scope}plate_run",
            page_id=page_id,
            block_id=block_id,
            ref_id=ref_id,
            plate_id=plate_id,
            panel_id=panel_id,
            object_id=object_id,
            decoy_id=decoy_id,
            round1=round1,
            round2=round2,
        )

        repository = ProjectStructureRepository(neo4j_driver)
        summary = repository.project_summary(project_id)
        materials = {row["kind"]: row for row in summary["materials"]}
        assert materials["report_body"]["version_count"] == 1
        assert materials["plate_book"]["plate_count"] == 1
        assert materials["plate_book"]["panel_count"] == 1
        assert summary["review_round_count"] == 2
        assert summary["object_count"] == 1

        documents, total = repository.list_children(
            project_id,
            ProjectStructureNodeType.material_group,
            "material:report_body",
            0,
            50,
        )
        assert total == 1
        assert documents[0]["id"] == body_doc

        pages, page_total = repository.list_children(
            project_id,
            ProjectStructureNodeType.page_group,
            f"pages:{body_version}",
            0,
            50,
        )
        assert page_total == 1
        assert pages[0]["id"] == page_id
        assert pages[0]["reference_count"] == 1

        reference = repository.get_detail(
            project_id, ProjectStructureNodeType.reference, ref_id
        )
        assert reference is not None
        assert reference["target_id"] == plate_id
        assert reference["target_label"] == "Plate"
        assert reference["target_properties"]["raw_identifier"] == "【도판 45】"
        assert reference["target_id"] != decoy_id

        # The same globally unique node id is invisible through another project.
        assert repository.get_detail(
            other_project_id, ProjectStructureNodeType.reference, ref_id
        ) is None

        round_detail = repository.get_detail(
            project_id, ProjectStructureNodeType.review_round, round2
        )
        assert round_detail is not None
        assert round_detail["previous_round_id"] == round1
        assert round_detail["body_id"] == body_version
        assert round_detail["plate_id"] == plate_version
    finally:
        cleanup(scope)
