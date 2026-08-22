from __future__ import annotations

from app.graph.graph_review_repository import GraphReviewRepository
from app.services.graph_rules import GraphBodyRegion, GraphRuleEngine


def test_selected_ready_corpus_scopes_resolution_findings_and_evidence(
    neo4j_driver, scoped_prefix, cleanup
):
    scope = scoped_prefix
    project_id = f"{scope}project"
    corpus_id = f"{scope}corpus_v1"
    decoy_corpus_id = f"{scope}corpus_v2"
    run_id = f"{scope}run"
    object_id = f"{scope}obj6"
    source_id = f"{scope}block1"
    ref_wrong = f"{scope}ref_wrong"
    ref_missing = f"{scope}ref_missing"
    selected_44 = f"{scope}plate_c1_44"
    selected_45 = f"{scope}plate_c1_45"
    decoy_44 = f"{scope}plate_c2_44"
    decoy_45 = f"{scope}plate_c2_45"
    decoy_drawing_999 = f"{scope}drawing_c2_999"

    try:
        neo4j_driver.execute_query(
            """
            CREATE (p:Project {id: $project_id, name: 'graph-first e2e'})
            CREATE (c1:ReferenceCorpus {
                id: $corpus_id, projectId: $project_id, status: 'ready', revision: 1
            })
            CREATE (c2:ReferenceCorpus {
                id: $decoy_corpus_id, projectId: $project_id, status: 'ready', revision: 2
            })
            CREATE (p)-[:HAS_REFERENCE_CORPUS]->(c1)
            CREATE (p)-[:HAS_REFERENCE_CORPUS]->(c2)
            CREATE (run:AnalysisRun {id: $run_id, status: 'running'})
            CREATE (p)-[:HAS_RUN]->(run)
            CREATE (obj:ArchaeologyObject {
                id: $object_id, projectId: $project_id,
                canonical_name: '1지점 6호 석관묘', point: '1지점', number: '6호', type: '석관묘'
            })
            CREATE (p)-[:HAS_OBJECT]->(obj)
            CREATE (source:TextBlock {id: $source_id, text: '도판 44와 도면 999'})
            CREATE (source)-[:MENTIONS]->(obj)
            CREATE (r1:Reference {
                id: $ref_wrong, ref_type: 'plate', number: '44', raw_text: '도판 44',
                source_block_id: $source_id
            })
            CREATE (r2:Reference {
                id: $ref_missing, ref_type: 'drawing', number: '999', raw_text: '도면 999',
                source_block_id: $source_id
            })
            CREATE (source)-[:REFERENCES]->(r1)
            CREATE (source)-[:REFERENCES]->(r2)

            CREATE (a1:DerivedArtifact {id: $artifact1})
            CREATE (a2:DerivedArtifact {id: $artifact2})
            CREATE (c1)-[:HAS_ARTIFACT]->(a1)
            CREATE (c2)-[:HAS_ARTIFACT]->(a2)

            CREATE (p44:Plate {
                id: $selected_44, number: '44', title: '다른 유구', referenceCorpusId: $corpus_id
            })
            CREATE (p45:Plate {
                id: $selected_45, number: '45', title: '1지점 6호 석관묘', referenceCorpusId: $corpus_id
            })
            CREATE (c1)-[:HAS_PLATE]->(p44)
            CREATE (c1)-[:HAS_PLATE]->(p45)
            CREATE (p45)-[:DEPICTS {referenceCorpusId: $corpus_id}]->(obj)

            CREATE (d44:Plate {
                id: $decoy_44, number: '44', title: 'decoy 44', referenceCorpusId: $decoy_corpus_id
            })
            CREATE (d45:Plate {
                id: $decoy_45, number: '45', title: 'decoy 45', referenceCorpusId: $decoy_corpus_id
            })
            CREATE (d999:Drawing {
                id: $decoy_drawing_999, number: '999', title: 'decoy drawing',
                referenceCorpusId: $decoy_corpus_id
            })
            CREATE (c2)-[:HAS_PLATE]->(d44)
            CREATE (c2)-[:HAS_PLATE]->(d45)
            CREATE (c2)-[:HAS_DRAWING]->(d999)
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            decoy_corpus_id=decoy_corpus_id,
            run_id=run_id,
            object_id=object_id,
            source_id=source_id,
            ref_wrong=ref_wrong,
            ref_missing=ref_missing,
            artifact1=f"{scope}artifact1",
            artifact2=f"{scope}artifact2",
            selected_44=selected_44,
            selected_45=selected_45,
            decoy_44=decoy_44,
            decoy_45=decoy_45,
            decoy_drawing_999=decoy_drawing_999,
        )

        repository = GraphReviewRepository(neo4j_driver)
        engine = GraphRuleEngine(repository)
        findings = engine.run(
            project_id=project_id,
            reference_corpus_id=corpus_id,
            analysis_run_id=run_id,
            archaeology_object_ids=[object_id],
            body_regions_by_object={
                object_id: [
                    GraphBodyRegion(
                        source_block_id=source_id,
                        text="1지점 6호 석관묘는 도판 44와 도면 999를 참조한다.",
                    )
                ]
            },
        )

        by_code = {item.rule_code: item for item in findings}
        assert by_code["VISUAL_REFERENCE_WRONG_TARGET"].canonical_target_ids == (
            selected_45,
        )
        assert by_code["VISUAL_REFERENCE_WRONG_TARGET"].proposed_text == "도판 45"
        assert by_code["VISUAL_REFERENCE_MISSING_TARGET"].canonical_target_ids == ()
        assert by_code["VISUAL_REFERENCE_MISSING_TARGET"].proposed_text is None
        assert all(decoy_corpus_id not in target for item in findings for target in item.canonical_target_ids)
        assert all(item.requires_ai is False for item in findings)

        evidence, _, _ = neo4j_driver.execute_query(
            """
            MATCH (run:AnalysisRun {id: $run_id})-[:HAS_RESOLUTION_EVIDENCE]->(e:ResolutionEvidence)
            MATCH (e)-[:FOR_CORPUS]->(c:ReferenceCorpus)
            RETURN e.referenceCorpusId AS corpus_id,
                   e.analysisRunId AS run_id,
                   e.referenceId AS reference_id,
                   e.status AS status,
                   e.targetIds AS target_ids,
                   c.id AS linked_corpus
            ORDER BY reference_id
            """,
            run_id=run_id,
        )
        assert len(evidence) == 2
        assert {row["corpus_id"] for row in evidence} == {corpus_id}
        assert {row["linked_corpus"] for row in evidence} == {corpus_id}
        assert {row["run_id"] for row in evidence} == {run_id}
        statuses = {row["reference_id"]: row["status"] for row in evidence}
        assert statuses == {ref_missing: "MISSING", ref_wrong: "RESOLVED"}
        wrong_row = next(row for row in evidence if row["reference_id"] == ref_wrong)
        assert wrong_row["target_ids"] == [selected_44]
    finally:
        cleanup(scope)
