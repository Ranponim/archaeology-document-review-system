"""Shared fixtures for the real-Neo4j integration suite.

The whole module is skipped when NEO4J_PASSWORD is unset or the connection
fails, so the suite is portable (CI without a Neo4j instance skips cleanly).
Every test gets a scoped id prefix (it_<uuid8>_) and a cleanup helper that
DETACH DELETEs only nodes whose id starts with that prefix — the shared local
database may contain other projects' data and is never touched outside the
scoped ids.
"""
import os
import uuid

import pytest
from neo4j import GraphDatabase


def _build_driver():
    uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        return None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return driver
    except Exception:
        return None


@pytest.fixture(scope="module")
def neo4j_driver():
    """Real Neo4j driver; skips the whole module when unavailable."""
    driver = _build_driver()
    if driver is None:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")
    yield driver
    driver.close()


@pytest.fixture(autouse=True)
def _asset_cache_dir(tmp_path, monkeypatch):
    """Point ASSET_CACHE_DIR at a writable temp dir so factory-built
    orchestrators (VLMReviewService -> AssetHashCache) never touch /data."""
    monkeypatch.setenv("ASSET_CACHE_DIR", str(tmp_path / "asset_cache"))


@pytest.fixture
def scoped_prefix():
    """Per-test scoped id prefix: it_<uuid8>_."""
    return f"it_{uuid.uuid4().hex[:8]}_"


@pytest.fixture
def create_project(neo4j_driver):
    """Create a Project node with a scoped id so cleanup can delete its whole
    subtree (ProjectRepository.create_document_with_version emits random-uuid
    DocumentVersion/AnalysisRun nodes that a scope-only match would miss)."""

    def _create(scope: str, name: str) -> str:
        project_id = f"{scope}project"
        neo4j_driver.execute_query(
            "CREATE (p:Project {id: $id, name: $name})",
            id=project_id,
            name=name,
        )
        return project_id

    return _create


@pytest.fixture
def cleanup(neo4j_driver):
    """Return a helper that deletes every node under a scoped prefix, including
    the scoped project's whole subtree (random-uuid DocumentVersion/AnalysisRun
    nodes reachable from the project)."""

    def _cleanup(scope: str) -> None:
        neo4j_driver.execute_query(
            """
            MATCH (p:Project) WHERE p.id CONTAINS $scope
            OPTIONAL MATCH (p)-[*1..10]-(n)
            WITH p, collect(DISTINCT n) AS nodes
            DETACH DELETE p
            FOREACH (n IN [x IN nodes WHERE x IS NOT NULL] | DETACH DELETE n)
            """,
            scope=scope,
        )
        neo4j_driver.execute_query(
            "MATCH (n) WHERE n.id CONTAINS $scope DETACH DELETE n",
            scope=scope,
        )

    return _cleanup