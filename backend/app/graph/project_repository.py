from uuid import uuid4

from neo4j import Driver, ManagedTransaction

from app.domain.models import Document, DocumentVersion, Project, StoredFile


class ProjectNotFoundError(LookupError):
    pass


class AnalysisRunNotFoundError(LookupError):
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
        self,
        project_id: str,
        stored: StoredFile,
        stage: str = "source",
        kind: str = "report_body",
        title: str | None = None,
    ) -> DocumentVersion:
        _doc, version = self.create_document_with_version(
            project_id=project_id,
            stored=stored,
            stage=stage,
            kind=kind,
            title=title,
        )
        return version

    def create_document_with_version(
        self,
        project_id: str,
        stored: StoredFile,
        stage: str = "source",
        kind: str = "report_body",
        title: str | None = None,
    ) -> tuple[Document, DocumentVersion]:
        doc_id = str(uuid4())
        ver_id = str(uuid4())
        analysis_run_id = str(uuid4())
        doc_title = title if title is not None else stored.original_name

        session_config = (
            {"database": self._database} if self._database is not None else {}
        )
        with self._driver.session(**session_config) as session:
            created = session.execute_write(
                self._create_document_and_version,
                project_id,
                doc_id,
                ver_id,
                analysis_run_id,
                stored,
                stage,
                kind,
                doc_title,
            )
        if not created:
            raise ProjectNotFoundError(project_id)
        if isinstance(created, dict):
            return created["document"], created["version"]
        return (
            Document(id=doc_id, project_id=project_id, kind=kind, title=doc_title),
            DocumentVersion(
                id=ver_id,
                document_id=doc_id,
                analysis_run_id=analysis_run_id,
                uri=stored.uri,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                mime_type=stored.mime_type,
                original_name=stored.original_name,
                stage=stage,
            ),
        )

    def get_project_documents(self, project_id: str) -> list[Document]:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_DOCUMENT]->(document:Document)
            RETURN document.id AS id,
                   project.id AS project_id,
                   coalesce(document.kind, 'report_body') AS kind,
                   coalesce(document.title, document.name, '') AS title
            ORDER BY document.createdAt ASC, document.id ASC
            """,
            project_id=project_id,
            **self._query_config,
        )
        return [
            Document(
                id=record["id"],
                project_id=record["project_id"],
                kind=record["kind"],
                title=record["title"],
            )
            for record in records
        ]

    def get_document_versions(self, document_id: str) -> list[DocumentVersion]:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (document:Document {id: $document_id})-[:HAS_VERSION]->(version:DocumentVersion)
            OPTIONAL MATCH (run:AnalysisRun)-[:ANALYZES]->(version)
            RETURN version.id AS id,
                   document.id AS document_id,
                   coalesce(run.id, '') AS analysis_run_id,
                   version.uri AS uri,
                   version.sha256 AS sha256,
                   version.sizeBytes AS size_bytes,
                   version.mimeType AS mime_type,
                   version.originalName AS original_name,
                   version.stage AS stage
            ORDER BY version.createdAt ASC, version.id ASC
            """,
            document_id=document_id,
            **self._query_config,
        )
        return [
            DocumentVersion(
                id=record["id"],
                document_id=record["document_id"],
                analysis_run_id=record["analysis_run_id"],
                uri=record["uri"],
                sha256=record["sha256"],
                size_bytes=record["size_bytes"],
                mime_type=record["mime_type"],
                original_name=record["original_name"],
                stage=record["stage"],
            )
            for record in records
        ]

    def get_project(self, project_id: str) -> dict:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})
            OPTIONAL MATCH (project)-[:HAS_DOCUMENT]->(document:Document)
            OPTIONAL MATCH (document)-[:HAS_VERSION]->(version:DocumentVersion)
            OPTIONAL MATCH (run:AnalysisRun)-[:ANALYZES]->(version)
            RETURN project,
                   collect(DISTINCT {
                       id: document.id,
                       projectId: project.id,
                       kind: coalesce(document.kind, 'report_body'),
                       title: coalesce(document.title, document.name, '')
                   }) AS documents,
                   collect(DISTINCT {
                       id: version.id,
                       documentId: document.id,
                       analysisRunId: run.id,
                       uri: version.uri,
                       sha256: version.sha256,
                       sizeBytes: version.sizeBytes,
                       mimeType: version.mimeType,
                       originalName: version.originalName,
                       stage: version.stage,
                       createdAt: version.createdAt
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
        documents = [
            Document(
                id=value["id"],
                project_id=value["projectId"],
                kind=value["kind"],
                title=value["title"],
            )
            for value in record.get("documents", [])
            if value.get("id") is not None
        ]
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
            for value in sorted(
                (v for v in record["documentVersions"] if v["id"] is not None),
                key=lambda x: str(x.get("createdAt") or x["id"]),
            )
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
            "documents": documents,
            "document_versions": versions,
            "analysis_runs": runs,
        }

    @staticmethod
    def _create_document_and_version(
        transaction: ManagedTransaction,
        project_id: str,
        doc_id: str,
        ver_id: str,
        analysis_run_id: str,
        stored: StoredFile,
        stage: str,
        kind: str,
        title: str,
    ) -> dict | None:
        result = transaction.run(
            """
            MATCH (project:Project {id: $project_id})
            MERGE (document:Document {projectId: $project_id, kind: $kind})
            ON CREATE SET document.id = $doc_id,
                          document.title = $title,
                          document.name = $title,
                          document.createdAt = datetime()
            MERGE (project)-[:HAS_DOCUMENT]->(document)
            WITH project, document
            OPTIONAL MATCH (document)-[:HAS_VERSION]->(prev:DocumentVersion)
            WHERE NOT (prev)-[:PRECEDES]->(:DocumentVersion)
            WITH project, document, prev
            ORDER BY prev.createdAt DESC
            LIMIT 1
            CREATE (document_version:DocumentVersion {
                id: $ver_id,
                uri: $uri,
                sha256: $sha256,
                sizeBytes: $size_bytes,
                mimeType: $mime_type,
                originalName: $original_name,
                stage: $stage,
                createdAt: datetime()
            })
            CREATE (run:AnalysisRun {
                id: $analysis_run_id,
                status: 'queued',
                step: 'ingest',
                createdAt: datetime()
            })
            CREATE (document)-[:HAS_VERSION]->(document_version)
            CREATE (run)-[:ANALYZES]->(document_version)
            FOREACH (_ IN CASE WHEN prev IS NOT NULL AND prev <> document_version THEN [1] ELSE [] END |
                CREATE (prev)-[:PRECEDES]->(document_version)
            )
            RETURN document.id AS document_id,
                   document.kind AS kind,
                   coalesce(document.title, document.name, '') AS title,
                   document_version.id AS version_id
            """,
            project_id=project_id,
            doc_id=doc_id,
            ver_id=ver_id,
            analysis_run_id=analysis_run_id,
            uri=stored.uri,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type=stored.mime_type,
            original_name=stored.original_name,
            stage=stage,
            kind=kind,
            title=title,
        )
        record = result.single()
        if record is None:
            return None
        return {
            "document": Document(
                id=record["document_id"],
                project_id=project_id,
                kind=record["kind"],
                title=record["title"],
            ),
            "version": DocumentVersion(
                id=record["version_id"],
                document_id=record["document_id"],
                analysis_run_id=analysis_run_id,
                uri=stored.uri,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                mime_type=stored.mime_type,
                original_name=stored.original_name,
                stage=stage,
            ),
        }

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

    def prepare_ingest_retry(self, project_id: str, analysis_run_id: str) -> str:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_DOCUMENT]->
                  (:Document)-[:HAS_VERSION]->(version:DocumentVersion)<-
                  [:ANALYZES]-(run:AnalysisRun {id: $analysis_run_id})
            WHERE run.step = 'ingest'
              AND run.status = 'failed'
              AND run.retryable = true
            SET run.status = 'queued',
                run.queuedAt = datetime(),
                run.startedAt = null,
                run.completedAt = null,
                run.errorCode = null,
                run.retryable = false
            RETURN run.status AS status
            """,
            project_id=project_id,
            analysis_run_id=analysis_run_id,
            **self._query_config,
        )
        if records:
            return records[0]["status"]

        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_DOCUMENT]->
                  (:Document)-[:HAS_VERSION]->(:DocumentVersion)<-
                  [:ANALYZES]-(run:AnalysisRun {id: $analysis_run_id})
            WHERE run.step = 'ingest'
            RETURN run.status AS status
            """,
            project_id=project_id,
            analysis_run_id=analysis_run_id,
            **self._query_config,
        )
        if not records:
            raise AnalysisRunNotFoundError(analysis_run_id)
        return records[0]["status"]
