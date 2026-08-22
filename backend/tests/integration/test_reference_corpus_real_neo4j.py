from __future__ import annotations

import pytest

from app.domain.canonical_models import DrawingData, PlateData, PlatePanelData
from app.domain.reference_corpus import (
    DerivedArtifactData,
    ReferenceCorpusStatus,
    compute_build_identity,
)
from app.domain.source_assets import OriginalAssetData
from app.graph.reference_corpus_repository import ReferenceCorpusRepository
from app.graph.source_asset_repository import SourceAssetRepository


def _asset(scope: str, project_id: str, suffix: str, name: str, kind: str) -> OriginalAssetData:
    mime = "image/jpeg" if kind == "linked_photo" else "application/octet-stream"
    return OriginalAssetData(
        id=f"{scope}asset_{suffix}",
        project_id=project_id,
        uri=f"incoming/{project_id}/{name}",
        sha256=f"{scope}sha_{suffix}",
        size_bytes=100,
        mime_type=mime,
        original_name=name,
        relative_path=name,
        asset_kind=kind,
        source_root_name="reference-corpus",
        import_batch_id=f"{scope}batch",
        parse_status="stored",
        provenance_status="unlinked",
    )


def test_real_neo4j_reference_corpus_is_project_scoped_and_ready_is_immutable(
    neo4j_driver, scoped_prefix, cleanup
):
    scope = scoped_prefix
    project_id = f"{scope}project"
    other_project_id = f"{scope}other_project"
    corpus_id = f"{scope}corpus"
    source_repo = SourceAssetRepository(neo4j_driver)
    repository = ReferenceCorpusRepository(neo4j_driver)

    layout = _asset(scope, project_id, "layout", "plates.indd", "indesign")
    photo = _asset(scope, project_id, "photo", "4. 조사 후_45.JPG", "linked_photo")
    drawing_source = _asset(scope, project_id, "drawing", "도면30.ai", "illustrator")
    foreign = _asset(scope, other_project_id, "foreign", "foreign.jpg", "linked_photo")

    try:
        neo4j_driver.execute_query(
            """
            CREATE (:Project {id: $project_id, name: '산노리'})
            CREATE (:Project {id: $other_project_id, name: '다른 프로젝트'})
            """,
            project_id=project_id,
            other_project_id=other_project_id,
        )
        for asset in (layout, photo, drawing_source, foreign):
            source_repo.save_original_asset(asset)

        corpus = repository.create_staging(project_id, corpus_id=corpus_id, revision=1)
        assert corpus.id == corpus_id
        assert corpus.project_id == project_id
        assert corpus.revision == 1
        assert corpus.status == ReferenceCorpusStatus.STAGING

        repository.attach_source(project_id, corpus_id, layout.id, "plate_layout")
        repository.attach_source(project_id, corpus_id, photo.id, "plate_link")
        repository.attach_source(project_id, corpus_id, drawing_source.id, "drawing_source")
        sources = repository.list_sources(project_id, corpus_id)
        assert {(item["id"], item["role"]) for item in sources} == {
            (layout.id, "plate_layout"),
            (photo.id, "plate_link"),
            (drawing_source.id, "drawing_source"),
        }

        with pytest.raises(ValueError, match="project"):
            repository.attach_source(project_id, corpus_id, foreign.id, "plate_link")

        identity = compute_build_identity("source-set", "adobe-1", "manifest-1", "canon-1")
        repository.transition_status(
            project_id,
            corpus_id,
            ReferenceCorpusStatus.CONVERTING,
            source_set_hash="source-set",
            converter_version="adobe-1",
            manifest_schema_version="manifest-1",
            canonicalizer_version="canon-1",
            build_identity=identity,
        )
        repository.save_artifact(
            project_id,
            corpus_id,
            DerivedArtifactData(
                id=f"{scope}manifest",
                reference_corpus_id=corpus_id,
                artifact_type="manifest",
                uri="artifacts/manifest.json",
                sha256=f"{scope}manifest-sha",
                mime_type="application/json",
                source_asset_id=layout.id,
                converter_version="adobe-1",
            ),
        )
        repository.transition_status(project_id, corpus_id, ReferenceCorpusStatus.VALIDATING)
        repository.transition_status(project_id, corpus_id, ReferenceCorpusStatus.CANONICALIZING)

        plate = PlateData(
            plate_id=f"plate:{corpus_id}:45",
            number="45",
            physical_page=1,
            title="6호 석관묘",
            raw_identifier="【도판 45】",
            source_kind="indesign_source",
            source_sha256=layout.sha256,
            reference_corpus_id=corpus_id,
            panels=[
                PlatePanelData(
                    panel_id=f"plate-panel:{corpus_id}:45:1",
                    plate_id=f"plate:{corpus_id}:45",
                    panel_index=1,
                    caption="조사 후",
                    source_sha256=photo.sha256,
                    source_asset_id=photo.id,
                )
            ],
        )
        drawing = DrawingData(
            drawing_id=f"drawing:{corpus_id}:30",
            number="30",
            physical_page=1,
            title="6호 석관묘",
            raw_identifier="【도면 30】",
            source_kind="illustrator_source",
            source_sha256=drawing_source.sha256,
            reference_corpus_id=corpus_id,
        )
        repository.save_canonical_visuals(
            project_id,
            corpus_id,
            plates=[plate],
            drawings=[drawing],
        )

        with pytest.raises(ValueError, match="corpus"):
            repository.save_canonical_visuals(
                project_id,
                corpus_id,
                plates=[
                    PlateData(
                        plate_id="plate:foreign:99",
                        number="99",
                        physical_page=1,
                        reference_corpus_id="foreign-corpus",
                    )
                ],
                drawings=[],
            )

        repository.transition_status(project_id, corpus_id, ReferenceCorpusStatus.GRAPH_VALIDATING)
        assert repository.validate_ready_graph(project_id, corpus_id) is True
        ready = repository.transition_status(project_id, corpus_id, ReferenceCorpusStatus.READY)
        assert ready.status == ReferenceCorpusStatus.READY
        assert repository.find_ready_by_build_identity(project_id, identity).id == corpus_id
        assert repository.get(project_id, corpus_id).id == corpus_id
        assert [item.id for item in repository.list_for_project(project_id)] == [corpus_id]

        graph, _, _ = neo4j_driver.execute_query(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->(c:ReferenceCorpus {id: $corpus_id})
            MATCH (c)-[:HAS_PLATE]->(plate:Plate {number: '45'})-[:HAS_PANEL]->(panel:PlatePanel)
            MATCH (panel)-[:DERIVED_FROM]->(photo:OriginalAsset {id: $photo_id})
            MATCH (c)-[:HAS_DRAWING]->(drawing:Drawing {number: '30'})
            OPTIONAL MATCH (:DocumentVersion)-[:HAS_PLATE|HAS_DRAWING]->(legacy_visual)
            WHERE legacy_visual.id IN [plate.id, drawing.id]
            RETURN plate.referenceCorpusId AS plate_corpus,
                   drawing.referenceCorpusId AS drawing_corpus,
                   panel.sourceAssetId AS panel_source,
                   count(legacy_visual) AS legacy_owner_count
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            photo_id=photo.id,
        )
        assert len(graph) == 1
        assert graph[0]["plate_corpus"] == corpus_id
        assert graph[0]["drawing_corpus"] == corpus_id
        assert graph[0]["panel_source"] == photo.id
        assert graph[0]["legacy_owner_count"] == 0

        with pytest.raises(ValueError, match="immutable"):
            repository.attach_source(project_id, corpus_id, photo.id, "plate_link")
        with pytest.raises(ValueError, match="immutable"):
            repository.save_artifact(
                project_id,
                corpus_id,
                DerivedArtifactData(
                    id=f"{scope}late_artifact",
                    reference_corpus_id=corpus_id,
                    artifact_type="png",
                    uri="late.png",
                    sha256="late",
                    mime_type="image/png",
                ),
            )
        with pytest.raises(ValueError, match="immutable"):
            repository.save_canonical_visuals(project_id, corpus_id, plates=[plate], drawings=[drawing])
        with pytest.raises(ValueError, match="immutable"):
            repository.transition_status(project_id, corpus_id, ReferenceCorpusStatus.FAILED)
    finally:
        cleanup(scope)
