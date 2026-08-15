from uuid import uuid4

from neo4j import Driver, ManagedTransaction

from app.domain.models import DocumentVersion, Project, StoredFile


class ProjectNotFoundError(LookupError):
    pass


class ProjectRepository:
    def __init__(self, driver: Driver, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @property
    def _query_config(self) -> dict[str, str]:
        if self._database is None:
            return {}
        return {"database_": self._database}

    def create_project(self, name: str, internal_code: str | None) -> Project:
        project = Project(
            id=str(uuid4()),
            name=name,
            internal_code=internal_code,
        )
        self._driver.execute_query(
            """
            CREATE (project:Project {
                id: $id,
                name: $name,
                internalCode: $internal_code
            })
            """,
            id=project.id,
            name=project.name,
            internal_code=project.internal_code,
            **self._query_config,
        )
        return project

    def add_document_version(
        self, project_id: str, stored: StoredFile, stage: str
    ) -> DocumentVersion:
        version = DocumentVersion(
            id=str(uuid4()),
            document_id=str(uuid4()),
            analysis_run_id=str(uuid4()),
            uri=stored.uri,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type=stored.mime_type,
            original_name=stored.original_name,
            stage=stage,
        )
        session_config = (
            {"database": self._database} if self._database is not None else {}
        )
        with self._driver.session(**session_config) as session:
            created = session.execute_write(
                self._create_document_version,
                project_id,
                version,
            )
        if not created:
            raise ProjectNotFoundError(project_id)
        return version

    @staticmethod
    def _create_document_version(
        transaction: ManagedTransaction,
        project_id: str,
        version: DocumentVersion,
    ) -> bool:
        result = transaction.run(
            """
            MATCH (project:Project {id: $project_id})
            CREATE (document:Document {
                id: $document_id,
                name: $original_name
            })
            CREATE (document_version:DocumentVersion {
                id: $version_id,
                uri: $uri,
                sha256: $sha256,
                sizeBytes: $size_bytes,
                mimeType: $mime_type,
                originalName: $original_name,
                stage: $stage
            })
            CREATE (run:AnalysisRun {
                id: $analysis_run_id,
                status: 'queued',
                step: 'ingest'
            })
            CREATE (project)-[:HAS_DOCUMENT]->(document)
            CREATE (document)-[:HAS_VERSION]->(document_version)
            CREATE (run)-[:ANALYZES]->(document_version)
            RETURN document_version.id AS id
            """,
            project_id=project_id,
            document_id=version.document_id,
            version_id=version.id,
            analysis_run_id=version.analysis_run_id,
            uri=version.uri,
            sha256=version.sha256,
            size_bytes=version.size_bytes,
            mime_type=version.mime_type,
            original_name=version.original_name,
            stage=version.stage,
        )
        return result.single() is not None

    def graph_shape(self, document_version_id: str) -> dict[str, int]:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (version:DocumentVersion {id: $document_version_id})
            OPTIONAL MATCH (project:Project)-[:HAS_DOCUMENT]->
                           (document:Document)-[:HAS_VERSION]->(version)
            OPTIONAL MATCH (run:AnalysisRun)-[:ANALYZES]->(version)
            RETURN count(DISTINCT project) AS Project,
                   count(DISTINCT document) AS Document,
                   count(DISTINCT version) AS DocumentVersion,
                   count(DISTINCT run) AS AnalysisRun
            """,
            document_version_id=document_version_id,
            **self._query_config,
        )
        if not records:
            return {}
        return dict(records[0])
