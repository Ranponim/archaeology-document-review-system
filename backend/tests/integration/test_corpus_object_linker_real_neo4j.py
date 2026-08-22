from __future__ import annotations

from app.domain.canonical_models import ArchaeologyObjectData
from app.graph.corpus_object_repository import CorpusObjectGraphRepository
from app.services.corpus_object_linker import CorpusObjectLinker


def test_real_neo4j_depicts_link_is_project_and_corpus_scoped(
    neo4j_driver, scoped_prefix, cleanup
):
    scope = scoped_prefix
    project_id = f"{scope}project"
    corpus_id = f"{scope}corpus1"
    other_corpus_id = f"{scope}corpus2"
    plate_id = f"{scope}plate45"
    decoy_id = f"{scope}decoy45"
    object_id = f"{scope}obj6"

    try:
        neo4j_driver.execute_query(
            """
            CREATE (p:Project {id: $project_id})
            CREATE (c1:ReferenceCorpus {id: $corpus_id, projectId: $project_id, status: 'ready', revision: 1})
            CREATE (c2:ReferenceCorpus {id: $other_corpus_id, projectId: $project_id, status: 'ready', revision: 2})
            CREATE (plate:Plate {id: $plate_id, number: '45', title: '1지점 6호 석관묘', referenceCorpusId: $corpus_id})
            CREATE (decoy:Plate {id: $decoy_id, number: '45', title: '1지점 6호 석관묘', referenceCorpusId: $other_corpus_id})
            CREATE (obj:ArchaeologyObject {
                id: $object_id,
                projectId: $project_id,
                canonical_name: '1지점 6호 석관묘',
                point: '1지점',
                number: '6호',
                type: '석관묘'
            })
            CREATE (p)-[:HAS_REFERENCE_CORPUS]->(c1)
            CREATE (p)-[:HAS_REFERENCE_CORPUS]->(c2)
            CREATE (c1)-[:HAS_PLATE]->(plate)
            CREATE (c2)-[:HAS_PLATE]->(decoy)
            CREATE (p)-[:HAS_OBJECT]->(obj)
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            other_corpus_id=other_corpus_id,
            plate_id=plate_id,
            decoy_id=decoy_id,
            object_id=object_id,
        )

        repository = CorpusObjectGraphRepository(neo4j_driver)
        linker = CorpusObjectLinker(repository)
        result = linker.link(
            project_id,
            corpus_id,
            [
                ArchaeologyObjectData(
                    object_id=object_id,
                    site="산노리",
                    point="1지점",
                    number="6호",
                    type="석관묘",
                    canonical_name="1지점 6호 석관묘",
                    project_id=project_id,
                )
            ],
        )

        assert len(result.created) == 1
        links, _, _ = neo4j_driver.execute_query(
            """
            MATCH (plate:Plate {id: $plate_id})-[rel:DEPICTS]->(obj:ArchaeologyObject {id: $object_id})
            RETURN rel.method AS method, rel.referenceCorpusId AS corpus_id
            """,
            plate_id=plate_id,
            object_id=object_id,
        )
        assert len(links) == 1
        assert links[0]["method"] == "strong_identifier"
        assert links[0]["corpus_id"] == corpus_id

        decoys, _, _ = neo4j_driver.execute_query(
            """
            MATCH (decoy:Plate {id: $decoy_id})-[rel:DEPICTS]->(:ArchaeologyObject)
            RETURN count(rel) AS count
            """,
            decoy_id=decoy_id,
        )
        assert decoys[0]["count"] == 0
    finally:
        cleanup(scope)
