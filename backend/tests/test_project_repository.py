import os

import pytest
from neo4j import GraphDatabase

from app.domain.models import StoredFile
from app.graph.project_repository import ProjectNotFoundError, ProjectRepository
from app.graph.schema import ensure_schema


@pytest.fixture(scope="session")
def neo4j_driver():
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_TEST_USER", "neo4j"),
            os.environ.get("NEO4J_TEST_PASSWORD", "test-password"),
        ),
    )
    driver.verify_connectivity()
    ensure_schema(driver)
    yield driver
    driver.close()


@pytest.fixture
def stored_pdf():
    return StoredFile(
        uri="incoming/00000000-0000-0000-0000-000000000001/hash/report.pdf",
        sha256="a" * 64,
        size_bytes=4,
        mime_type="application/pdf",
        original_name="report.pdf",
    )


def test_document_version_links_project_document_file_and_analysis_run(
    neo4j_driver, stored_pdf
):
    repo = ProjectRepository(neo4j_driver)
    project = repo.create_project("산노리", "NONSAN-001")

    version = repo.add_document_version(project.id, stored_pdf, "source")

    assert repo.graph_shape(version.id) == {
        "Project": 1,
        "Document": 1,
        "DocumentVersion": 1,
        "AnalysisRun": 1,
    }
    assert version.analysis_run_id

    records, _, _ = neo4j_driver.execute_query(
        """
        MATCH (project:Project)-[:HAS_DOCUMENT]->(document:Document)
              -[:HAS_VERSION]->(version:DocumentVersion {id: $version_id})
        MATCH (run:AnalysisRun)-[:ANALYZES]->(version)
        RETURN project.name AS project_name,
               project.internalCode AS internal_code,
               document.name AS document_name,
               version.uri AS uri,
               version.sha256 AS sha256,
               version.sizeBytes AS size_bytes,
               version.mimeType AS mime_type,
               version.originalName AS original_name,
               version.stage AS stage,
               run.id AS analysis_run_id,
               run.status AS status,
               run.step AS step
        """,
        version_id=version.id,
    )
    assert dict(records[0]) == {
        "project_name": "산노리",
        "internal_code": "NONSAN-001",
        "document_name": "report.pdf",
        "uri": stored_pdf.uri,
        "sha256": stored_pdf.sha256,
        "size_bytes": stored_pdf.size_bytes,
        "mime_type": stored_pdf.mime_type,
        "original_name": stored_pdf.original_name,
        "stage": "source",
        "analysis_run_id": version.analysis_run_id,
        "status": "queued",
        "step": "ingest",
    }


def test_ensure_schema_creates_required_unique_constraints_and_hash_index(
    neo4j_driver,
):
    constraints, _, _ = neo4j_driver.execute_query(
        """
        SHOW CONSTRAINTS YIELD labelsOrTypes, properties, type
        WHERE type = 'UNIQUENESS'
        RETURN labelsOrTypes[0] AS label, properties
        """
    )
    observed_constraints = {
        (record["label"], tuple(record["properties"])) for record in constraints
    }
    assert {
        ("Project", ("id",)),
        ("Document", ("id",)),
        ("DocumentVersion", ("id",)),
        ("AnalysisRun", ("id",)),
    } <= observed_constraints

    indexes, _, _ = neo4j_driver.execute_query(
        """
        SHOW INDEXES YIELD labelsOrTypes, properties
        WHERE labelsOrTypes = ['DocumentVersion'] AND properties = ['sha256']
        RETURN count(*) AS count
        """
    )
    assert indexes[0]["count"] == 1


def test_missing_project_does_not_leave_partial_document_nodes(
    neo4j_driver, stored_pdf
):
    repo = ProjectRepository(neo4j_driver)
    before, _, _ = neo4j_driver.execute_query("MATCH (node) RETURN count(node) AS count")

    with pytest.raises(ProjectNotFoundError):
        repo.add_document_version(
            "00000000-0000-0000-0000-000000000099", stored_pdf, "source"
        )

    after, _, _ = neo4j_driver.execute_query("MATCH (node) RETURN count(node) AS count")
    assert after[0]["count"] == before[0]["count"]
