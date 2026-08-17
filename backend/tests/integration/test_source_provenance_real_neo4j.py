from app.api.project_structure_contract import ProjectStructureNodeType
from app.domain.source_assets import OriginalAssetData
from app.graph.project_structure_repository import ProjectStructureRepository
from app.graph.source_asset_repository import SourceAssetRepository


def _asset(scope: str, project_id: str, suffix: str, name: str) -> OriginalAssetData:
    return OriginalAssetData(
        id=f"{scope}asset_{suffix}",
        project_id=project_id,
        uri=f"incoming/{project_id}/{suffix}/{name}",
        sha256=f"{scope}sha_{suffix}",
        size_bytes=10,
        mime_type="image/jpeg",
        original_name=name,
        relative_path=f"도판(사진들)/Links/{name}",
        asset_kind="linked_photo",
        source_root_name="src",
        import_batch_id=f"{scope}batch",
        parse_status="stored",
        provenance_status="unlinked",
    )


def test_real_neo4j_original_asset_is_project_owned_and_manifest_only(
    neo4j_driver, scoped_prefix, cleanup
):
    scope = scoped_prefix
    project_id = f"{scope}project"
    other_project_id = f"{scope}other"
    doc_id = f"{scope}plate_doc"
    version_id = f"{scope}plate_v1"
    plate_id = f"{scope}plate45"
    panel_id = f"{scope}panel45a"
    ref_id = f"{scope}ref45"
    decoy91_id = f"{scope}asset_91"

    try:
        neo4j_driver.execute_query(
            """
            CREATE (p:Project {id: $project_id, name: '산노리', createdAt: datetime(), updatedAt: datetime()})
            CREATE (other:Project {id: $other_project_id, name: '다른 프로젝트', createdAt: datetime(), updatedAt: datetime()})
            CREATE (doc:Document {id: $doc_id, projectId: $project_id, kind: 'plate_book', title: '도판집'})
            CREATE (v:DocumentVersion {id: $version_id, originalName: '도판집.pdf', uri: 'incoming/plate.pdf', sha256: 'plate-sha', sizeBytes: 100, mimeType: 'application/pdf', stage: 'source'})
            CREATE (plate:Plate {id: $plate_id, number: '45', raw_identifier: '【도판 45】', title: '6호 석관묘', document_version_id: $version_id})
            CREATE (panel:PlatePanel {id: $panel_id, plate_id: $plate_id, panel_index: 1, caption: '조사 후'})
            CREATE (ref:Reference {id: $ref_id, ref_type: 'plate', number: '45', raw_text: '도판 45'})
            CREATE (p)-[:HAS_DOCUMENT]->(doc)
            CREATE (doc)-[:HAS_VERSION]->(v)
            CREATE (v)-[:HAS_PLATE]->(plate)
            CREATE (plate)-[:HAS_PANEL]->(panel)
            CREATE (ref)-[:RESOLVES_TO]->(plate)
            """,
            project_id=project_id,
            other_project_id=other_project_id,
            doc_id=doc_id,
            version_id=version_id,
            plate_id=plate_id,
            panel_id=panel_id,
            ref_id=ref_id,
        )

        repository = SourceAssetRepository(neo4j_driver)
        asset45 = _asset(scope, project_id, "45", "4. 조사 후_45.JPG")
        asset91 = _asset(scope, project_id, "91", "missing_91.JPG")
        repository.save_original_asset(asset45)
        repository.save_original_asset(asset91)

        ownership, _, _ = neo4j_driver.execute_query(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset)
            WHERE asset.id IN [$asset45, $asset91]
            RETURN asset.id AS id, asset.provenanceStatus AS provenance_status
            ORDER BY asset.id
            """,
            project_id=project_id,
            asset45=asset45.id,
            asset91=asset91.id,
        )
        assert {row["id"] for row in ownership} == {asset45.id, asset91.id}
        assert {row["provenance_status"] for row in ownership} == {"unlinked"}

        # A filename containing 45 or 91 creates no canonical relationship or target.
        before, _, _ = neo4j_driver.execute_query(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset)
            OPTIONAL MATCH (canonical)-[rel:DERIVED_FROM]->(asset)
            WITH collect(rel) AS rels
            OPTIONAL MATCH (missing:Plate {number: '91'})
            RETURN size([r IN rels WHERE r IS NOT NULL]) AS derived_links,
                   count(missing) AS plate91_count
            """,
            project_id=project_id,
        )
        assert before[0]["derived_links"] == 0
        assert before[0]["plate91_count"] == 0

        resolved = repository.resolve_scoped_target(
            project_id, version_id, "PlatePanel", node_id=panel_id
        )
        assert resolved == {"id": panel_id, "label": "PlatePanel"}
        assert repository.resolve_scoped_target(
            other_project_id, version_id, "PlatePanel", node_id=panel_id
        ) is None

        repository.link_derived_from(
            project_id,
            "PlatePanel",
            panel_id,
            asset45.id,
            method="manifest_mapping",
            manifest_sha256=f"{scope}manifest",
        )

        linked, _, _ = neo4j_driver.execute_query(
            """
            MATCH (panel:PlatePanel {id: $panel_id})-[rel:DERIVED_FROM]->(asset:OriginalAsset {id: $asset_id})
            RETURN rel.method AS method, rel.status AS status,
                   rel.manifestSha256 AS manifest_sha,
                   asset.provenanceStatus AS provenance_status
            """,
            panel_id=panel_id,
            asset_id=asset45.id,
        )
        assert len(linked) == 1
        assert linked[0]["method"] == "manifest_mapping"
        assert linked[0]["status"] == "declared"
        assert linked[0]["provenance_status"] == "declared"

        # Case 6 identity remains Reference -> RESOLVES_TO -> canonical Plate 45.
        case6, _, _ = neo4j_driver.execute_query(
            """
            MATCH (ref:Reference {id: $ref_id})-[:RESOLVES_TO]->(plate:Plate {id: $plate_id})
            OPTIONAL MATCH (plate)-[:DERIVED_FROM]->(asset:OriginalAsset)
            RETURN ref.number AS ref_number, plate.number AS plate_number,
                   plate.raw_identifier AS raw_identifier, count(asset) AS direct_source_assets
            """,
            ref_id=ref_id,
            plate_id=plate_id,
        )
        assert len(case6) == 1
        assert case6[0]["ref_number"] == "45"
        assert case6[0]["plate_number"] == "45"
        assert case6[0]["raw_identifier"] == "【도판 45】"
        assert case6[0]["direct_source_assets"] == 0

        structure = ProjectStructureRepository(neo4j_driver)
        kinds, kind_total = structure.list_children(
            project_id,
            ProjectStructureNodeType.source_asset_group,
            "source-assets",
            0,
            50,
        )
        assert kind_total == 1
        assert kinds[0]["id"] == "source-kind:linked_photo"

        assets, asset_total = structure.list_children(
            project_id,
            ProjectStructureNodeType.source_kind_group,
            "source-kind:linked_photo",
            0,
            50,
        )
        assert asset_total == 2
        assert {row["id"] for row in assets} == {asset45.id, asset91.id}
        assert structure.get_detail(
            other_project_id,
            ProjectStructureNodeType.original_asset,
            asset45.id,
        ) is None
    finally:
        cleanup(scope)


def test_real_neo4j_document_version_can_be_explicit_manifest_target(
    neo4j_driver, scoped_prefix, cleanup
):
    scope = scoped_prefix
    project_id = f"{scope}project"
    doc_id = f"{scope}body_doc"
    version_id = f"{scope}body_v1"
    asset = _asset(scope, project_id, "body", "body-source.jpg")

    try:
        neo4j_driver.execute_query(
            """
            CREATE (p:Project {id: $project_id, name: '산노리', createdAt: datetime(), updatedAt: datetime()})
            CREATE (doc:Document {id: $doc_id, projectId: $project_id, kind: 'report_body', title: '본문'})
            CREATE (v:DocumentVersion {id: $version_id, originalName: '본문.pdf', uri: 'incoming/body.pdf', sha256: 'body-sha', sizeBytes: 100, mimeType: 'application/pdf', stage: 'source'})
            CREATE (p)-[:HAS_DOCUMENT]->(doc)
            CREATE (doc)-[:HAS_VERSION]->(v)
            """,
            project_id=project_id,
            doc_id=doc_id,
            version_id=version_id,
        )
        repository = SourceAssetRepository(neo4j_driver)
        repository.save_original_asset(asset)

        resolved = repository.resolve_scoped_target(
            project_id,
            version_id,
            "DocumentVersion",
            node_id=version_id,
        )
        assert resolved == {"id": version_id, "label": "DocumentVersion"}
        repository.link_derived_from(
            project_id,
            "DocumentVersion",
            version_id,
            asset.id,
            method="manifest_mapping",
            manifest_sha256=f"{scope}manifest",
        )
        records, _, _ = neo4j_driver.execute_query(
            """
            MATCH (v:DocumentVersion {id: $version_id})-[rel:DERIVED_FROM]->(asset:OriginalAsset {id: $asset_id})
            RETURN rel.method AS method, asset.projectId AS project_id
            """,
            version_id=version_id,
            asset_id=asset.id,
        )
        assert len(records) == 1
        assert records[0]["method"] == "manifest_mapping"
        assert records[0]["project_id"] == project_id
    finally:
        cleanup(scope)
