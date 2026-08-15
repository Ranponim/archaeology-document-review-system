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

    def get_project(self, project_id: str) -> dict:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})
            OPTIONAL MATCH (project)-[:HAS_DOCUMENT]->(document:Document)
                           -[:HAS_VERSION]->(version:DocumentVersion)
            OPTIONAL MATCH (run:AnalysisRun)-[:ANALYZES]->(version)
            RETURN project,
                   collect(DISTINCT {
                       id: version.id,
                       documentId: document.id,
                       analysisRunId: run.id,
                       uri: version.uri,
                       sha256: version.sha256,
                       sizeBytes: version.sizeBytes,
                       mimeType: version.mimeType,
                       originalName: version.originalName,
                       stage: version.stage
                   }) AS documentVersions,
                   collect(DISTINCT {
                       id: run.id,
                       status: run.status,
                       step: run.step,
                       errorCode: run.errorCode,
                       retryable: coalesce(run.retryable, false),
                       documentVersionId: version.id
                   }) AS analysisRuns
            """,
            project_id=project_id,
            **self._query_config,
        )
        if not records:
            raise ProjectNotFoundError(project_id)

        record = records[0]
        project_node = record["project"]
        project = Project(
            id=project_node["id"],
            name=project_node["name"],
            internal_code=project_node.get("internalCode"),
        )
        versions = [
            DocumentVersion(
                id=value["id"],
                document_id=value["documentId"],
                analysis_run_id=value["analysisRunId"],
                uri=value["uri"],
                sha256=value["sha256"],
                size_bytes=value["sizeBytes"],
                mime_type=value["mimeType"],
                original_name=value["originalName"],
                stage=value["stage"],
            )
            for value in record["documentVersions"]
            if value["id"] is not None
        ]
        runs = [
            {
                "id": value["id"],
                "status": value["status"],
                "step": value["step"],
                "document_version_id": value["documentVersionId"],
                "error_code": value.get("errorCode"),
                "retryable": value.get("retryable", False),
            }
            for value in record["analysisRuns"]
            if value["id"] is not None
        ]
        return {
            "project": project,
            "document_versions": versions,
            "analysis_runs": runs,
        }

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

    def claim_ingest(self, analysis_run_id: str):
        from app.jobs.ingest import IngestContext

        records, _, _ = self._driver.execute_query(
            """
            MATCH (run:AnalysisRun {id: $analysis_run_id})-[:ANALYZES]->
                  (version:DocumentVersion)
            WHERE run.step = 'ingest'
              AND (run.status = 'queued'
                   OR (run.status = 'failed' AND run.retryable = true))
            SET run.status = 'running',
                run.startedAt = datetime(),
                run.completedAt = null,
                run.attemptCount = coalesce(run.attemptCount, 0) + 1,
                run.errorCode = null,
                run.retryable = false
            RETURN run.id AS analysisRunId,
                   version.id AS documentVersionId,
                   version.uri AS uri,
                   version.sha256 AS sha256,
                   version.mimeType AS mimeType
            """,
            analysis_run_id=analysis_run_id,
            **self._query_config,
        )
        if not records:
            return None
        record = records[0]
        return IngestContext(
            analysis_run_id=record["analysisRunId"],
            document_version_id=record["documentVersionId"],
            uri=record["uri"],
            sha256=record["sha256"],
            mime_type=record["mimeType"],
        )

    def analysis_status(self, analysis_run_id: str) -> str:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (run:AnalysisRun {id: $analysis_run_id})
            RETURN run.status AS status
            """,
            analysis_run_id=analysis_run_id,
            **self._query_config,
        )
        if not records:
            raise LookupError(analysis_run_id)
        return records[0]["status"]

    def find_cached_extraction(self, sha256: str, excluding_version_id: str):
        from app.jobs.ingest import CachedExtraction, ExtractionMetadata

        records, _, _ = self._driver.execute_query(
            """
            MATCH (run:AnalysisRun {status: 'completed'})-[:ANALYZES]->
                  (version:DocumentVersion {sha256: $sha256})
            WHERE version.id <> $excluding_version_id
              AND version.ingestMimeType IS NOT NULL
            RETURN version.id AS documentVersionId,
                   version.ingestMimeType AS mimeType,
                   version.pageCount AS pageCount,
                   version.textExtractable AS textExtractable
            ORDER BY run.completedAt DESC
            LIMIT 1
            """,
            sha256=sha256,
            excluding_version_id=excluding_version_id,
            **self._query_config,
        )
        if not records:
            return None
        record = records[0]
        return CachedExtraction(
            document_version_id=record["documentVersionId"],
            metadata=ExtractionMetadata(
                mime_type=record["mimeType"],
                page_count=record["pageCount"],
                text_extractable=record["textExtractable"],
            ),
        )

    def complete_ingest(
        self,
        analysis_run_id: str,
        metadata,
        reused_from_version_id: str | None,
    ) -> bool:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (run:AnalysisRun {id: $analysis_run_id})-[:ANALYZES]->
                  (version:DocumentVersion)
            WHERE run.status = 'running'
            SET run.status = 'completed',
                run.completedAt = datetime(),
                run.errorCode = null,
                run.retryable = false,
                version.ingestMimeType = $mime_type,
                version.pageCount = $page_count,
                version.textExtractable = $text_extractable,
                version.reusedFromVersionId = $reused_from_version_id
            RETURN run.id AS id
            """,
            analysis_run_id=analysis_run_id,
            mime_type=metadata.mime_type,
            page_count=metadata.page_count,
            text_extractable=metadata.text_extractable,
            reused_from_version_id=reused_from_version_id,
            **self._query_config,
        )
        return bool(records)

    def fail_ingest(self, analysis_run_id: str, code: str, retryable: bool) -> bool:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (run:AnalysisRun {id: $analysis_run_id})
            WHERE run.status IN ['queued', 'running']
            SET run.status = 'failed',
                run.completedAt = datetime(),
                run.errorCode = $code,
                run.retryable = $retryable
            RETURN run.id AS id
            """,
            analysis_run_id=analysis_run_id,
            code=code,
            retryable=retryable,
            **self._query_config,
        )
        return bool(records)

    def cancel_analysis_run(self, analysis_run_id: str) -> bool:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (run:AnalysisRun {id: $analysis_run_id})
            WHERE run.status IN ['queued', 'running']
            SET run.status = 'cancelled', run.completedAt = datetime()
            RETURN run.id AS id
            """,
            analysis_run_id=analysis_run_id,
            **self._query_config,
        )
        return bool(records)
