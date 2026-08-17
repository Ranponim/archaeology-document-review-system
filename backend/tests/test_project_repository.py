import os
from ipaddress import ip_address
from urllib.parse import urlsplit

import pytest
from neo4j import GraphDatabase

from app.domain.models import Document, DocumentVersion, StoredFile
from app.graph.project_repository import (
    AnalysisRunNotFoundError,
    ProjectNotFoundError,
    ProjectRepository,
)
from app.graph.schema import CONSTRAINTS, INDEXES, ensure_schema
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

    assert driver.query_count == len(CONSTRAINTS) + len(INDEXES)


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


def test_multiple_version_uploads_belong_to_same_parent_document_with_precedes_chain(
    neo4j_driver, neo4j_database
):
    repo = ProjectRepository(neo4j_driver, database=neo4j_database)
    project = repo.create_project("산노리", "NONSAN-001")

    f1 = StoredFile("incoming/p/h1/1.pdf", "1" * 64, 100, "application/pdf", "1차.pdf")
    f2 = StoredFile("incoming/p/h2/2.pdf", "2" * 64, 200, "application/pdf", "2차.pdf")
    f3 = StoredFile("incoming/p/h3/3.pdf", "3" * 64, 300, "application/pdf", "3차.pdf")
    f4 = StoredFile("incoming/p/h4/4.pdf", "4" * 64, 400, "application/pdf", "final.pdf")

    v1 = repo.add_document_version(project.id, f1, stage="1차", kind="report_body", title="본문")
    v2 = repo.add_document_version(project.id, f2, stage="2차", kind="report_body", title="본문")
    v3 = repo.add_document_version(project.id, f3, stage="3차", kind="report_body", title="본문")
    v4 = repo.add_document_version(project.id, f4, stage="final", kind="report_body", title="본문")

    # All 4 versions share the same parent Document node
    assert v1.document_id == v2.document_id == v3.document_id == v4.document_id

    # Verify get_project_documents
    documents = repo.get_project_documents(project.id)
    assert len(documents) == 1
    assert documents[0].id == v1.document_id
    assert documents[0].kind == "report_body"
    assert documents[0].title == "본문"

    # Verify get_document_versions returns all 4 versions in order
    versions = repo.get_document_versions(documents[0].id)
    assert len(versions) == 4
    assert [v.stage for v in versions] == ["1차", "2차", "3차", "final"]
    assert [v.id for v in versions] == [v1.id, v2.id, v3.id, v4.id]

    # Verify sequential PRECEDES chain in Neo4j graph
    records, _, _ = neo4j_driver.execute_query(
        """
        MATCH (v1:DocumentVersion {id: $v1_id})-[:PRECEDES]->
              (v2:DocumentVersion {id: $v2_id})-[:PRECEDES]->
              (v3:DocumentVersion {id: $v3_id})-[:PRECEDES]->
              (v4:DocumentVersion {id: $v4_id})
        RETURN count(*) AS chain_count
        """,
        v1_id=v1.id,
        v2_id=v2.id,
        v3_id=v3.id,
        v4_id=v4.id,
        database_=neo4j_database,
    )
    assert records[0]["chain_count"] == 1


def test_different_document_kinds_create_separate_document_nodes_under_same_project(
    neo4j_driver, neo4j_database
):
    repo = ProjectRepository(neo4j_driver, database=neo4j_database)
    project = repo.create_project("산노리", "NONSAN-001")

    f_body = StoredFile("incoming/p/hb/b.pdf", "b" * 64, 100, "application/pdf", "본문.pdf")
    f_plate = StoredFile("incoming/p/hp/p.pdf", "p" * 64, 200, "application/pdf", "도판.pdf")
    f_draw = StoredFile("incoming/p/hd/d.pdf", "d" * 64, 300, "application/pdf", "도면.pdf")
    f_plate_2 = StoredFile("incoming/p/hp2/p2.pdf", "e" * 64, 250, "application/pdf", "도판2.pdf")

    v_body = repo.add_document_version(project.id, f_body, stage="1차", kind="report_body")
    v_plate1 = repo.add_document_version(project.id, f_plate, stage="1차", kind="plate_book")
    v_draw = repo.add_document_version(project.id, f_draw, stage="1차", kind="drawing_book")

    assert len({v_body.document_id, v_plate1.document_id, v_draw.document_id}) == 3

    docs = repo.get_project_documents(project.id)
    assert len(docs) == 3
    doc_kinds = {d.kind for d in docs}
    assert doc_kinds == {"report_body", "plate_book", "drawing_book"}

    v_plate2 = repo.add_document_version(project.id, f_plate_2, stage="2차", kind="plate_book")
    assert v_plate2.document_id == v_plate1.document_id

    plate_versions = repo.get_document_versions(v_plate1.document_id)
    assert len(plate_versions) == 2
    assert [v.stage for v in plate_versions] == ["1차", "2차"]


def test_create_document_with_version_returns_document_and_version(
    neo4j_driver, neo4j_database, stored_pdf
):
    repo = ProjectRepository(neo4j_driver, database=neo4j_database)
    project = repo.create_project("산노리", None)

    doc, ver = repo.create_document_with_version(
        project.id,
        stored_pdf,
        stage="1차",
        kind="report_body",
        title="보고서 본문",
    )
    assert isinstance(doc, Document)
    assert isinstance(ver, DocumentVersion)
    assert doc.id == ver.document_id
    assert doc.project_id == project.id
    assert doc.kind == "report_body"
    assert doc.title == "보고서 본문"
    assert ver.stage == "1차"


class FakeNeo4jRecord:
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key: str):
        return self._data[key]

    def get(self, key: str, default=None):
        return self._data.get(key, default)


class FakeNeo4jDriver:
    def __init__(self, records_to_return=None):
        self.queries: list[dict] = []
        self.records_to_return = [
            FakeNeo4jRecord(r) for r in (records_to_return or [])
        ]

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        return self.records_to_return, None, None


def test_get_project_surfaces_proofreading_runs_via_has_run():
    """P0-5: get_project must surface a proofreading run reachable only through
    (Project)-[:HAS_RUN]->(AnalysisRun) alongside ingest runs reachable through
    ANALYZES, so frontend polling observes queued/running/completed/failed."""
    record = {
        "project": {"id": "p1", "name": "산노리", "internalCode": None},
        "documents": [
            {"id": "doc_1", "projectId": "p1", "kind": "report_body", "title": "본문"},
        ],
        "documentVersions": [
            {
                "id": "ver_body_1",
                "documentId": "doc_1",
                "uri": "incoming/p1/body.pdf",
                "sha256": "a" * 64,
                "sizeBytes": 100,
                "mimeType": "application/pdf",
                "originalName": "body.pdf",
                "stage": "1차",
                "createdAt": "2026-08-17T00:00:00Z",
            },
        ],
        "analysisRuns": [
            {
                "id": "run_ingest",
                "status": "completed",
                "step": "ingest",
                "errorCode": None,
                "retryable": False,
                "documentVersionId": "ver_body_1",
                "progressStage": None,
                "progressMessage": None,
                "currentPage": None,
                "totalPages": None,
            },
        ],
        "proofreadingRuns": [
            {
                "id": "run_proof",
                "status": "running",
                "step": "analysis",
                "errorCode": None,
                "retryable": False,
                "documentVersionId": "ver_body_1",
                "progressStage": "도판 패널 렌더링",
                "progressMessage": "도판 1/10쪽",
                "currentPage": 1,
                "totalPages": 10,
            },
        ],
    }
    driver = FakeNeo4jDriver(records_to_return=[record])
    repo = ProjectRepository(driver)

    snapshot = repo.get_project("p1")

    assert "HAS_RUN" in driver.queries[0]["query"]
    run_ids = [r["id"] for r in snapshot["analysis_runs"]]
    assert "run_ingest" in run_ids
    assert "run_proof" in run_ids
    proof = next(r for r in snapshot["analysis_runs"] if r["id"] == "run_proof")
    assert proof["status"] == "running"
    assert proof["document_version_id"] == "ver_body_1"
    assert proof["progress_stage"] == "도판 패널 렌더링"
    assert proof["progress_message"] == "도판 1/10쪽"
    assert proof["current_page"] == 1
    assert proof["total_pages"] == 10


def test_get_project_deduplicates_runs_reachable_by_both_paths():
    """P0-5: a proofreading run with both HAS_RUN and ANALYZES edges appears
    exactly once in the project run list."""
    record = {
        "project": {"id": "p1", "name": "산노리", "internalCode": None},
        "documents": [
            {"id": "doc_1", "projectId": "p1", "kind": "report_body", "title": "본문"},
        ],
        "documentVersions": [
            {
                "id": "ver_body_1",
                "documentId": "doc_1",
                "uri": "incoming/p1/body.pdf",
                "sha256": "a" * 64,
                "sizeBytes": 100,
                "mimeType": "application/pdf",
                "originalName": "body.pdf",
                "stage": "1차",
                "createdAt": "2026-08-17T00:00:00Z",
            },
        ],
        "analysisRuns": [
            {
                "id": "run_proof",
                "status": "queued",
                "step": "queued",
                "errorCode": None,
                "retryable": False,
                "documentVersionId": "ver_body_1",
                "progressStage": None,
                "progressMessage": None,
                "currentPage": None,
                "totalPages": None,
            },
        ],
        "proofreadingRuns": [
            {
                "id": "run_proof",
                "status": "queued",
                "step": "queued",
                "errorCode": None,
                "retryable": False,
                "documentVersionId": "ver_body_1",
                "progressStage": None,
                "progressMessage": None,
                "currentPage": None,
                "totalPages": None,
            },
        ],
    }
    driver = FakeNeo4jDriver(records_to_return=[record])
    repo = ProjectRepository(driver)

    snapshot = repo.get_project("p1")

    run_ids = [r["id"] for r in snapshot["analysis_runs"]]
    assert run_ids.count("run_proof") == 1


def test_create_document_with_version_orders_precedes_by_stage_rank():
    """7.2: the upload-time PRECEDES edge must follow semantic stage rank
    (1차<2차<3차<final), never upload chronology — a 3차 upload must not
    PRECEDES a later 1차 upload."""
    driver = _FakeSessionDriver(
        {"document_id": "doc_1", "kind": "report_body", "title": "본문", "version_id": "ver_1"}
    )
    repo = ProjectRepository(driver)
    stored = StoredFile(
        uri="incoming/p1/hash/body.pdf",
        sha256="a" * 64,
        size_bytes=100,
        mime_type="application/pdf",
        original_name="body.pdf",
    )

    repo.create_document_with_version(
        "p1", stored, stage="3차", kind="report_body", title="본문"
    )

    tx = driver.sessions[0]._tx
    assert len(tx.queries) == 1
    cypher = tx.queries[0]["query"]
    params = tx.queries[0]["params"]
    assert "prev.stage = $prev_stage" in cypher
    assert "next.stage = $next_stage" in cypher
    assert params["prev_stage"] == "2차"
    assert params["next_stage"] == "final"
    assert params["stage"] == "3차"


def test_create_document_with_version_first_stage_has_no_precedes_edges():
    """7.2: uploading 1차 first creates no PRECEDES edge (no earlier stage)."""
    driver = _FakeSessionDriver(
        {"document_id": "doc_1", "kind": "report_body", "title": "본문", "version_id": "ver_1"}
    )
    repo = ProjectRepository(driver)
    stored = StoredFile(
        uri="incoming/p1/hash/body.pdf",
        sha256="a" * 64,
        size_bytes=100,
        mime_type="application/pdf",
        original_name="body.pdf",
    )

    repo.create_document_with_version(
        "p1", stored, stage="1차", kind="report_body", title="본문"
    )

    params = driver.sessions[0]._tx.queries[0]["params"]
    assert params["prev_stage"] is None
    assert params["next_stage"] == "2차"


class _FakeSessionDriver:
    def __init__(self, record: dict):
        self.sessions: list[_FakeSession] = []
        self._record = record

    def session(self, **kwargs):
        session = _FakeSession(self._record)
        self.sessions.append(session)
        return session


class _FakeSession:
    def __init__(self, record: dict):
        self._tx = _FakeTransaction(record)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute_write(self, callback, *args):
        return callback(self._tx, *args)


class _FakeTransaction:
    def __init__(self, record: dict):
        self.queries: list[dict] = []
        self._record = record

    def run(self, query: str, **params):
        self.queries.append({"query": query, "params": params})
        return _FakeResult(self._record)


class _FakeResult:
    def __init__(self, record: dict):
        self._record = record

    def single(self):
        return FakeNeo4jRecord(self._record)

