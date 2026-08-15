import os
from ipaddress import ip_address
from urllib.parse import urlsplit

import pytest
from neo4j import GraphDatabase

from app.domain.models import StoredFile
from app.graph.project_repository import (
    AnalysisRunNotFoundError,
    ProjectNotFoundError,
    ProjectRepository,
)
from app.graph.schema import CONSTRAINTS, ensure_schema
from app.jobs.ingest import ExtractionMetadata


def _validated_test_uri() -> str:
    uri = os.environ.get("NEO4J_TEST_URI")
    if not uri:
        raise pytest.UsageError(
            "NEO4J_TEST_URI must explicitly identify an isolated Neo4j test instance"
        )
    endpoint = urlsplit(uri)
    hostname = (endpoint.hostname or "").lower().rstrip(".")
    try:
        is_loopback = ip_address(hostname).is_loopback
    except ValueError:
        is_loopback = hostname == "localhost" or hostname.endswith(".localhost")
    if hostname == "neo4j" or (is_loopback and endpoint.port in {None, 7687}):
        raise pytest.UsageError(
            "NEO4J_TEST_URI must not target the default or Compose Neo4j endpoint; "
            "use an isolated test instance"
        )
    application_uri = os.environ.get("NEO4J_URI")
    if application_uri:
        application_endpoint = urlsplit(application_uri)
        application_host = (application_endpoint.hostname or "").lower().rstrip(".")
        if (hostname, endpoint.port or 7687) == (
            application_host,
            application_endpoint.port or 7687,
        ):
            raise pytest.UsageError(
                "NEO4J_TEST_URI must not target the configured application endpoint"
            )
    return uri


def _required_test_setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise pytest.UsageError(f"{name} must be explicitly configured")
    return value


@pytest.fixture(scope="session")
def neo4j_driver():
    uri = _validated_test_uri()
    database = _required_test_setting("NEO4J_TEST_DATABASE")
    if database.lower() == "system":
        raise pytest.UsageError(
            "NEO4J_TEST_DATABASE must identify an isolated data database, not system"
        )
    user = _required_test_setting("NEO4J_TEST_USER")
    password = _required_test_setting("NEO4J_TEST_PASSWORD")
    disposable = _required_test_setting("NEO4J_TEST_DISPOSABLE")
    if disposable != "1":
        raise pytest.UsageError(
            "NEO4J_TEST_DISPOSABLE must be 1 for a disposable test instance"
        )
    driver = GraphDatabase.driver(
        uri,
        auth=(user, password),
    )
    driver.execute_query("RETURN 1 AS ready", database_=database)
    ensure_schema(driver, database=database)
    yield driver
    driver.close()


@pytest.fixture(scope="session")
def neo4j_database():
    return _required_test_setting("NEO4J_TEST_DATABASE")


def test_neo4j_fixture_fails_closed_without_explicit_test_configuration(
    monkeypatch,
):
    for name in (
        "NEO4J_TEST_URI",
        "NEO4J_TEST_DATABASE",
        "NEO4J_TEST_USER",
        "NEO4J_TEST_PASSWORD",
        "NEO4J_TEST_DISPOSABLE",
    ):
        monkeypatch.delenv(name, raising=False)

    def reject_unconfigured_connection(*args, **kwargs):
        pytest.fail("fixture attempted a Neo4j connection before validation")

    monkeypatch.setattr(GraphDatabase, "driver", reject_unconfigured_connection)

    with pytest.raises(pytest.UsageError, match="NEO4J_TEST_URI"):
        next(neo4j_driver.__wrapped__())


@pytest.mark.parametrize(
    "unsafe_uri",
    [
        "bolt://localhost:7687",
        "bolt://localhost.:7687",
        "bolt://db.localhost:7687",
        "neo4j://127.0.0.1:7687",
        "bolt://127.0.0.2:7687",
        "bolt://[::1]:7687",
        "bolt://[0:0:0:0:0:0:0:1]:7687",
        "bolt://neo4j:7687",
        "bolt://neo4j.:7687",
    ],
)
def test_neo4j_fixture_rejects_default_and_compose_endpoints(monkeypatch, unsafe_uri):
    monkeypatch.setenv("NEO4J_TEST_URI", unsafe_uri)
    monkeypatch.setenv("NEO4J_TEST_DATABASE", "neo4j")
    monkeypatch.setenv("NEO4J_TEST_USER", "neo4j")
    monkeypatch.setenv("NEO4J_TEST_PASSWORD", "test-password")
    monkeypatch.setenv("NEO4J_TEST_DISPOSABLE", "1")

    def reject_unsafe_connection(*args, **kwargs):
        pytest.fail("fixture attempted to connect to an unsafe Neo4j endpoint")

    monkeypatch.setattr(GraphDatabase, "driver", reject_unsafe_connection)

    with pytest.raises(pytest.UsageError, match="isolated"):
        next(neo4j_driver.__wrapped__())


@pytest.mark.parametrize(
    "missing_name",
    [
        "NEO4J_TEST_DATABASE",
        "NEO4J_TEST_USER",
        "NEO4J_TEST_PASSWORD",
        "NEO4J_TEST_DISPOSABLE",
    ],
)
def test_neo4j_fixture_requires_all_isolation_settings_before_connecting(
    monkeypatch, missing_name
):
    settings = {
        "NEO4J_TEST_URI": "bolt://localhost:17687",
        "NEO4J_TEST_DATABASE": "neo4j",
        "NEO4J_TEST_USER": "neo4j",
        "NEO4J_TEST_PASSWORD": "test-password",
        "NEO4J_TEST_DISPOSABLE": "1",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing_name)

    def reject_incomplete_configuration(*args, **kwargs):
        pytest.fail("fixture attempted to connect with incomplete test configuration")

    monkeypatch.setattr(GraphDatabase, "driver", reject_incomplete_configuration)

    with pytest.raises(pytest.UsageError, match=missing_name):
        next(neo4j_driver.__wrapped__())


def test_neo4j_fixture_requires_disposable_instance_acknowledgement(monkeypatch):
    monkeypatch.setenv("NEO4J_TEST_URI", "bolt://localhost:17687")
    monkeypatch.setenv("NEO4J_TEST_DATABASE", "neo4j")
    monkeypatch.setenv("NEO4J_TEST_USER", "neo4j")
    monkeypatch.setenv("NEO4J_TEST_PASSWORD", "test-password")
    monkeypatch.setenv("NEO4J_TEST_DISPOSABLE", "false")

    def reject_non_disposable_connection(*args, **kwargs):
        pytest.fail("fixture attempted to connect to a non-disposable Neo4j instance")

    monkeypatch.setattr(GraphDatabase, "driver", reject_non_disposable_connection)

    with pytest.raises(pytest.UsageError, match="NEO4J_TEST_DISPOSABLE"):
        next(neo4j_driver.__wrapped__())


def test_neo4j_fixture_rejects_the_system_database(monkeypatch):
    monkeypatch.setenv("NEO4J_TEST_URI", "bolt://localhost:17687")
    monkeypatch.setenv("NEO4J_TEST_DATABASE", "system")
    monkeypatch.setenv("NEO4J_TEST_USER", "neo4j")
    monkeypatch.setenv("NEO4J_TEST_PASSWORD", "test-password")
    monkeypatch.setenv("NEO4J_TEST_DISPOSABLE", "1")

    def reject_system_database_connection(*args, **kwargs):
        pytest.fail("fixture attempted to connect to Neo4j's system database")

    monkeypatch.setattr(GraphDatabase, "driver", reject_system_database_connection)

    with pytest.raises(pytest.UsageError, match="NEO4J_TEST_DATABASE"):
        next(neo4j_driver.__wrapped__())


def test_neo4j_fixture_rejects_the_configured_application_endpoint(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://database.internal:7687")
    monkeypatch.setenv("NEO4J_TEST_URI", "neo4j://database.internal:7687")
    monkeypatch.setenv("NEO4J_TEST_DATABASE", "neo4j")
    monkeypatch.setenv("NEO4J_TEST_USER", "neo4j")
    monkeypatch.setenv("NEO4J_TEST_PASSWORD", "test-password")
    monkeypatch.setenv("NEO4J_TEST_DISPOSABLE", "1")

    def reject_application_database_connection(*args, **kwargs):
        pytest.fail("fixture attempted to connect to the application Neo4j endpoint")

    monkeypatch.setattr(GraphDatabase, "driver", reject_application_database_connection)

    with pytest.raises(pytest.UsageError, match="application"):
        next(neo4j_driver.__wrapped__())


def test_ensure_schema_targets_the_explicit_test_database():
    class DatabaseGuardDriver:
        def __init__(self):
            self.query_count = 0

        def execute_query(self, query, **kwargs):
            if kwargs.get("database_") != "isolated_test":
                raise AssertionError("schema query escaped the explicit test database")
            self.query_count += 1

    driver = DatabaseGuardDriver()

    ensure_schema(driver, database="isolated_test")

    assert driver.query_count == len(CONSTRAINTS) + 2


def test_project_repository_targets_the_explicit_test_database(stored_pdf):
    class DatabaseGuardSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute_write(self, callback, *args):
            return True

    class DatabaseGuardDriver:
        def execute_query(self, query, **kwargs):
            if kwargs.get("database_") != "isolated_test":
                raise AssertionError(
                    "repository query escaped the explicit test database"
                )
            return [], None, None

        def session(self, **kwargs):
            if kwargs.get("database") != "isolated_test":
                raise AssertionError(
                    "repository session escaped the explicit test database"
                )
            return DatabaseGuardSession()

    repo = ProjectRepository(DatabaseGuardDriver(), database="isolated_test")

    project = repo.create_project("산노리", None)
    version = repo.add_document_version(project.id, stored_pdf, "source")

    assert project.name == "산노리"
    assert version.analysis_run_id


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
    neo4j_driver, neo4j_database, stored_pdf
):
    repo = ProjectRepository(neo4j_driver, database=neo4j_database)
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
        database_=neo4j_database,
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
    neo4j_driver, neo4j_database
):
    constraints, _, _ = neo4j_driver.execute_query(
        """
        SHOW CONSTRAINTS YIELD labelsOrTypes, properties, type
        WHERE type = 'UNIQUENESS'
        RETURN labelsOrTypes[0] AS label, properties
        """,
        database_=neo4j_database,
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
        """,
        database_=neo4j_database,
    )
    assert indexes[0]["count"] == 1


def test_missing_project_does_not_leave_partial_document_nodes(
    neo4j_driver, neo4j_database, stored_pdf
):
    repo = ProjectRepository(neo4j_driver, database=neo4j_database)
    before, _, _ = neo4j_driver.execute_query(
        "MATCH (node) RETURN count(node) AS count",
        database_=neo4j_database,
    )

    with pytest.raises(ProjectNotFoundError):
        repo.add_document_version(
            "00000000-0000-0000-0000-000000000099", stored_pdf, "source"
        )

    after, _, _ = neo4j_driver.execute_query(
        "MATCH (node) RETURN count(node) AS count",
        database_=neo4j_database,
    )
    assert after[0]["count"] == before[0]["count"]


def test_retrying_failed_ingest_clears_its_terminal_timestamp(
    neo4j_driver, neo4j_database, stored_pdf
):
    repo = ProjectRepository(neo4j_driver, database=neo4j_database)
    project = repo.create_project("task5-retry", None)
    version = repo.add_document_version(project.id, stored_pdf, "source")

    assert repo.claim_ingest(version.analysis_run_id) is not None
    assert repo.fail_ingest(version.analysis_run_id, "api_error", True)
    assert repo.claim_ingest(version.analysis_run_id) is not None

    records, _, _ = neo4j_driver.execute_query(
        """
        MATCH (run:AnalysisRun {id: $analysis_run_id})
        RETURN run.status AS status,
               run.completedAt AS completedAt,
               run.attemptCount AS attemptCount
        """,
        analysis_run_id=version.analysis_run_id,
        database_=neo4j_database,
    )
    assert dict(records[0]) == {
        "status": "running",
        "completedAt": None,
        "attemptCount": 2,
    }
    assert repo.complete_ingest(
        version.analysis_run_id,
        ExtractionMetadata("application/pdf", 1, False),
        None,
    )


def test_prepare_retry_is_project_scoped_and_idempotently_queues_the_same_run(
    neo4j_driver, neo4j_database, stored_pdf
):
    repo = ProjectRepository(neo4j_driver, database=neo4j_database)
    project = repo.create_project("task5-recovery", None)
    other_project = repo.create_project("task5-other", None)
    version = repo.add_document_version(project.id, stored_pdf, "source")
    assert repo.fail_ingest(version.analysis_run_id, "api_error", True)

    with pytest.raises(AnalysisRunNotFoundError):
        repo.prepare_ingest_retry(other_project.id, version.analysis_run_id)

    first = repo.prepare_ingest_retry(project.id, version.analysis_run_id)
    second = repo.prepare_ingest_retry(project.id, version.analysis_run_id)

    assert first == "queued"
    assert second == "queued"
    records, _, _ = neo4j_driver.execute_query(
        """
        MATCH (run:AnalysisRun {id: $analysis_run_id})
        RETURN run.status AS status,
               run.errorCode AS errorCode,
               run.retryable AS retryable,
               run.completedAt AS completedAt
        """,
        analysis_run_id=version.analysis_run_id,
        database_=neo4j_database,
    )
    assert dict(records[0]) == {
        "status": "queued",
        "errorCode": None,
        "retryable": False,
        "completedAt": None,
    }
