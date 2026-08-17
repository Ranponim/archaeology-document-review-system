"""Test A — browser-selected versions are the actual worker inputs (Phase P0-A).

Upload body/plate/drawing 3차 versions, create an AnalysisRun with the three
selected version ids, and verify in Neo4j that the run ANALYZES the body 3차,
USES_PLATE the plate 3차, USES_DRAWING the drawing 3차, AND that the canonical
Plate/Drawing indexes reconstructed from those versions contain the persisted
plates/drawings. Scoped ids (it_<uuid8>_) are deleted in finally.
"""
from app.domain.canonical_models import DrawingData, PlateData
from app.domain.models import StoredFile
from app.graph.canonical_repository import CanonicalRepository
from app.graph.project_repository import ProjectRepository
from app.graph.review_repository import ReviewRepository


def _stored(scope: str, name: str) -> StoredFile:
    return StoredFile(
        uri=f"incoming/{scope}/{name}",
        sha256=f"sha256_{scope}_{name}",
        size_bytes=1,
        mime_type="application/pdf",
        original_name=name,
    )


def test_real_neo4j_run_uses_selected_versions_and_reconstructs_indexes(
    neo4j_driver, scoped_prefix, cleanup, create_project
):
    """Test A: the run graph links the selected body/plate/drawing 3차 versions
    and the canonical Plate/Drawing indexes come from those versions."""
    scope = scoped_prefix
    project_repo = ProjectRepository(neo4j_driver)
    canonical_repo = CanonicalRepository(neo4j_driver)
    review_repo = ReviewRepository(neo4j_driver)
    project_id = create_project(scope, f"{scope} project")

    _doc, body = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "body-3차.pdf"),
        stage="3차",
        kind="report_body",
    )
    _doc, plate = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "plate-3차.pdf"),
        stage="3차",
        kind="plate_book",
    )
    _doc, drawing = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "drawing-3차.pdf"),
        stage="3차",
        kind="drawing_book",
    )

    plate_data = PlateData(
        plate_id=f"{plate.id}_plate_45",
        number="45",
        physical_page=47,
        title="1지점 청동기시대 6호 석관묘",
        document_version_id=plate.id,
        raw_identifier="【도판 45】",
    )
    drawing_data = DrawingData(
        drawing_id=f"{drawing.id}_drawing_16",
        number="16",
        physical_page=18,
        title="1지점 6호 석관묘 실측도",
        document_version_id=drawing.id,
        raw_identifier="【도면 16】",
    )
    canonical_repo.save_plates([plate_data])
    canonical_repo.save_drawings([drawing_data])

    run_id = f"{scope}_run"
    try:
        review_repo.create_analysis_run(
            project_id=project_id,
            run_id=run_id,
            body_version_id=body.id,
            plate_version_id=plate.id,
            drawing_version_id=drawing.id,
            version_stage="3차",
        )

        recs, _, _ = neo4j_driver.execute_query(
            """
            MATCH (run:AnalysisRun {id: $run_id})
            OPTIONAL MATCH (run)-[:ANALYZES]->(b:DocumentVersion)
            OPTIONAL MATCH (run)-[:USES_PLATE]->(p:DocumentVersion)
            OPTIONAL MATCH (run)-[:USES_DRAWING]->(d:DocumentVersion)
            RETURN b.id AS body_id, p.id AS plate_id, d.id AS drawing_id
            """,
            run_id=run_id,
        )
        assert recs[0]["body_id"] == body.id, "run must ANALYZES the body 3차"
        assert recs[0]["plate_id"] == plate.id, "run must USES_PLATE the plate 3차"
        assert recs[0]["drawing_id"] == drawing.id, "run must USES_DRAWING the drawing 3차"

        plate_index = canonical_repo.get_plate_index_for_version(plate.id)
        assert len(plate_index) == 1, "plate index must come from the selected plate version"
        assert plate_index.get_plate("45").plate_id == plate_data.plate_id

        drawing_index = canonical_repo.get_drawing_index_for_version(drawing.id)
        assert len(drawing_index) == 1, "drawing index must come from the selected drawing version"
        assert drawing_index.get_drawing("16").drawing_id == drawing_data.drawing_id
    finally:
        cleanup(scope)