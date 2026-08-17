from app.graph.source_asset_repository import SourceAssetRepository


class FakeDriver:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []

    def execute_query(self, query, **kwargs):
        self.queries.append((query, kwargs))
        return self.rows, None, None


def test_document_version_target_aliases_scoped_version_as_target():
    driver = FakeDriver([{"id": "version-1", "label": "DocumentVersion"}])
    repository = SourceAssetRepository(driver)

    resolved = repository.resolve_scoped_target(
        "project-1",
        "version-1",
        "DocumentVersion",
        node_id="version-1",
    )

    assert resolved == {"id": "version-1", "label": "DocumentVersion"}
    query, _ = driver.queries[0]
    assert "WITH v AS target" in query
    assert "MATCH (v)" not in query


def test_document_version_derived_from_uses_scoped_version_as_target():
    driver = FakeDriver()
    repository = SourceAssetRepository(driver)

    repository.link_derived_from(
        "project-1",
        "DocumentVersion",
        "version-1",
        "asset-1",
        method="manifest_mapping",
        manifest_sha256="manifest-sha",
    )

    query, _ = driver.queries[0]
    assert "WITH p, asset, v AS target" in query
    assert "MATCH (v)" not in query
    assert "MERGE (target)-[rel:DERIVED_FROM]->(asset)" in query
