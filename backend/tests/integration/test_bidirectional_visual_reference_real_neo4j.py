from app.domain.canonical_models import ArchaeologyObjectData
from app.graph.coverage_canonical_repository import CoverageCanonicalRepository
from app.services.visual_reference_coverage import VisualReferenceCoverageService


def _seed_graph(driver, scope: str) -> dict[str, str]:
    ids = {
        "project": f"{scope}_project",
        "body": f"{scope}_body_v",
        "plate": f"{scope}_plate_v",
        "plateOld": f"{scope}_plate_old_v",
        "drawing": f"{scope}_drawing_v",
        "object": f"{scope}_obj6",
        "block": f"{scope}_block",
        "page": f"{scope}_page",
        "plate45": f"{scope}_plate45",
        "plate44": f"{scope}_plate44",
        "drawing30": f"{scope}_drawing30",
    }
    driver.execute_query(
        """
        CREATE (p:Project {id: $project})
        CREATE (bodyDoc:Document {id: $bodyDoc, kind: 'report_body'})
        CREATE (plateDoc:Document {id: $plateDoc, kind: 'plate_book'})
        CREATE (drawingDoc:Document {id: $drawingDoc, kind: 'drawing_book'})
        CREATE (body:DocumentVersion {id: $body, sha256: 'body-sha', uri: 'body.pdf'})
        CREATE (plateV:DocumentVersion {id: $plate, sha256: 'plate-sha', uri: 'plate.pdf'})
        CREATE (plateOld:DocumentVersion {id: $plateOld, sha256: 'plate-old-sha', uri: 'plate-old.pdf'})
        CREATE (drawingV:DocumentVersion {id: $drawing, sha256: 'drawing-sha', uri: 'drawing.pdf'})
        CREATE (page:Page {id: $page, physical_page: 10, source_sha256: 'body-sha'})
        CREATE (block:TextBlock {id: $block, text: '6호 석관묘는 구릉 정상부에 위치한다.', source_sha256: 'body-sha'})
        CREATE (obj:ArchaeologyObject {
            id: $object, projectId: $project, canonical_name: '1지점 6호 석관묘',
            site: '산노리', point: '1지점', type: '석관묘', number: '6호'
        })
        CREATE (plate45:Plate {
            id: $plate45, number: '45', title: '6호 석관묘 조사 후 전경',
            physical_page: 45, source_sha256: 'plate-sha', document_version_id: $plate,
            raw_identifier: '【도판 45】'
        })
        CREATE (plate44:Plate {
            id: $plate44, number: '44', title: '다른 유구',
            physical_page: 44, source_sha256: 'plate-sha', document_version_id: $plate,
            raw_identifier: '【도판 44】'
        })
        CREATE (drawing30:Drawing {
            id: $drawing30, number: '30', title: '6호 석관묘 평·단면도',
            physical_page: 30, source_sha256: 'drawing-sha', document_version_id: $drawing,
            raw_identifier: '【도면 30】'
        })
        CREATE (p)-[:HAS_DOCUMENT]->(bodyDoc)
        CREATE (p)-[:HAS_DOCUMENT]->(plateDoc)
        CREATE (p)-[:HAS_DOCUMENT]->(drawingDoc)
        CREATE (bodyDoc)-[:HAS_VERSION]->(body)
        CREATE (plateDoc)-[:HAS_VERSION]->(plateV)
        CREATE (plateDoc)-[:HAS_VERSION]->(plateOld)
        CREATE (drawingDoc)-[:HAS_VERSION]->(drawingV)
        CREATE (body)-[:HAS_PAGE]->(page)
        CREATE (page)-[:HAS_BLOCK]->(block)
        CREATE (block)-[:MENTIONS]->(obj)
        CREATE (plateV)-[:HAS_PLATE]->(plate45)
        CREATE (plateV)-[:HAS_PLATE]->(plate44)
        CREATE (drawingV)-[:HAS_DRAWING]->(drawing30)
        CREATE (plate45)-[:DEPICTS]->(obj)
        CREATE (drawing30)-[:DEPICTS]->(obj)
        """,
        **ids,
        bodyDoc=f"{scope}_body_doc",
        plateDoc=f"{scope}_plate_doc",
        drawingDoc=f"{scope}_drawing_doc",
    )
    return ids


def _object(ids: dict[str, str]) -> ArchaeologyObjectData:
    return ArchaeologyObjectData(
        object_id=ids["object"],
        site="산노리",
        point="1지점",
        type="석관묘",
        number="6호",
        canonical_name="1지점 6호 석관묘",
        project_id=ids["project"],
    )


def test_real_graph_missing_body_reference_proposes_selected_visuals(
    neo4j_driver, scoped_prefix, cleanup
):
    ids = _seed_graph(neo4j_driver, scoped_prefix)
    repo = CoverageCanonicalRepository(neo4j_driver)
    service = VisualReferenceCoverageService()
    try:
        bundle = repo.get_object_evidence_bundle(
            ids["object"],
            analysis_run_id=f"{scoped_prefix}_run",
            document_version_ids=[ids["body"], ids["plate"], ids["drawing"]],
        )
        result = service.review_object(
            bundle=bundle,
            archaeology_object=_object(ids),
            analysis_run_id=f"{scoped_prefix}_run",
        )

        assert {(ev.value.get("plate_number")) for ev in bundle.plate_claims} == {"45"}
        assert {(ev.value.get("drawing_number")) for ev in bundle.drawing_claims} == {"30"}
        assert len(result) == 1
        assert result[0].proposed_text == "(도면 30, 도판 45)"
    finally:
        cleanup(scoped_prefix)


def test_real_graph_removing_depicts_prevents_reverse_coverage(
    neo4j_driver, scoped_prefix, cleanup
):
    ids = _seed_graph(neo4j_driver, scoped_prefix)
    repo = CoverageCanonicalRepository(neo4j_driver)
    service = VisualReferenceCoverageService()
    try:
        neo4j_driver.execute_query(
            "MATCH (asset)-[r:DEPICTS]->(o:ArchaeologyObject {id: $object}) DELETE r",
            object=ids["object"],
        )
        bundle = repo.get_object_evidence_bundle(
            ids["object"],
            analysis_run_id=f"{scoped_prefix}_run",
            document_version_ids=[ids["body"], ids["plate"], ids["drawing"]],
        )
        assert bundle.plate_claims == []
        assert bundle.drawing_claims == []
        assert service.review_object(
            bundle=bundle,
            archaeology_object=_object(ids),
            analysis_run_id=f"{scoped_prefix}_run",
        ) == []
    finally:
        cleanup(scoped_prefix)


def test_real_graph_wrong_existing_reference_is_replaced_not_appended(
    neo4j_driver, scoped_prefix, cleanup
):
    ids = _seed_graph(neo4j_driver, scoped_prefix)
    repo = CoverageCanonicalRepository(neo4j_driver)
    service = VisualReferenceCoverageService()
    try:
        neo4j_driver.execute_query(
            """
            MATCH (block:TextBlock {id: $block}), (plate44:Plate {id: $plate44})
            CREATE (ref:Reference {
                id: $ref, ref_type: 'plate', number: '44', raw_text: '도판 44',
                source_block_id: $block, source_sha256: 'body-sha', physical_page: 10
            })
            CREATE (block)-[:REFERENCES]->(ref)
            CREATE (ref)-[:RESOLVES_TO]->(plate44)
            """,
            block=ids["block"],
            plate44=ids["plate44"],
            ref=f"{scoped_prefix}_ref44",
        )
        bundle = repo.get_object_evidence_bundle(
            ids["object"],
            analysis_run_id=f"{scoped_prefix}_run",
            document_version_ids=[ids["body"], ids["plate"]],
        )
        ref_evidence = next(ev for ev in bundle.references if ev.value.get("number") == "44")
        assert ref_evidence.value["resolved_target_id"] == ids["plate44"]
        assert ref_evidence.value["resolved_depicts_object"] is False

        result = service.review_object(
            bundle=bundle,
            archaeology_object=_object(ids),
            analysis_run_id=f"{scoped_prefix}_run",
        )
        wrong = next(c for c in result if c.evidence and c.evidence.rule_name == "visual_reference_wrong_target")
        assert wrong.original_text == "도판 44"
        assert wrong.proposed_text == "도판 45"
    finally:
        cleanup(scoped_prefix)
