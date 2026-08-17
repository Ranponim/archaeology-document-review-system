from uuid import uuid4

from neo4j import Driver, ManagedTransaction

from app.domain.models import (
    Document,
    DocumentVersion,
    Project,
    StoredFile,
    VersionInput,
)
from app.domain.review_round import ReviewRound


class ProjectNotFoundError(LookupError):
    pass


class AnalysisRunNotFoundError(LookupError):
    pass


class DocumentVersionNotFoundError(LookupError):
    pass


class ReviewRoundNotFoundError(LookupError):
    pass



_STAGE_RANK = {"1차": 0, "2차": 1, "3차": 2, "final": 3}


def _adjacent_stages(stage: str) -> tuple[str | None, str | None]:
    """Return (previous_stage, next_stage) by semantic rank (1차<2차<3차<final).
    Unknown stages have no lineage neighbors so they never create PRECEDES."""
    rank = _STAGE_RANK.get(stage)
    if rank is None:
        return None, None
    prev_stage = next((s for s, r in _STAGE_RANK.items() if r == rank - 1), None)
    next_stage = next((s for s, r in _STAGE_RANK.items() if r == rank + 1), None)
    return prev_stage, next_stage



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
        project_id = str(uuid4())
        result = self._driver.execute_query(
            """
            CREATE (project:Project {
                id: $id, name: $name, internalCode: $internal_code,
                createdAt: datetime(), updatedAt: datetime()
            })
            RETURN toString(project.createdAt) AS createdAt,
                   toString(project.updatedAt) AS updatedAt
            """,
            id=project_id, name=name, internal_code=internal_code, **self._query_config,
        )
        records = getattr(result, "records", None)
        if records is None and isinstance(result, tuple) and result:
            records = result[0]
        record = records[0] if records else None
        return Project(
            id=project_id, name=name, internal_code=internal_code,
            created_at=(record.get("createdAt") if record is not None else None),
            updated_at=(record.get("updatedAt") if record is not None else None),
        )

    def list_projects(self) -> list[Project]:
        result = self._driver.execute_query(
            """
            MATCH (project:Project)
            RETURN project.id AS id, project.name AS name, project.internalCode AS internalCode,
                   toString(project.createdAt) AS createdAt, toString(project.updatedAt) AS updatedAt
            ORDER BY CASE WHEN project.createdAt IS NULL THEN 1 ELSE 0 END ASC,
                     project.createdAt DESC, project.name ASC, project.id ASC
            """,
            **self._query_config,
        )
        return [
            Project(
                id=record["id"],
                name=record["name"],
                internal_code=record["internalCode"],
                created_at=record.get("createdAt"), updated_at=record.get("updatedAt"),
            )
            for record in result.records
        ]

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

    def get_document_version_by_id(self, version_id: str) -> DocumentVersion | None:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (version:DocumentVersion {id: $version_id})
            OPTIONAL MATCH (document:Document)-[:HAS_VERSION]->(version)
            OPTIONAL MATCH (run:AnalysisRun)-[:ANALYZES]->(version)
            RETURN version.id AS id,
                   coalesce(document.id, '') AS document_id,
                   coalesce(run.id, '') AS analysis_run_id,
                   version.uri AS uri,
                   version.sha256 AS sha256,
                   version.sizeBytes AS size_bytes,
                   version.mimeType AS mime_type,
                   version.originalName AS original_name,
                   version.stage AS stage
            """,
            version_id=version_id,
            **self._query_config,
        )
        if not records:
            return None
        record = records[0]
        return DocumentVersion(
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

    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ) -> VersionInput | None:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_DOCUMENT]->(document:Document)-[:HAS_VERSION]->(version:DocumentVersion)
            WHERE coalesce(document.kind, 'report_body') = $kind
              AND ($stage IS NULL OR version.stage = $stage)
              AND ($version_id IS NULL OR version.id = $version_id)
            RETURN version.id AS version_id,
                   document.id AS document_id,
                   project.id AS project_id,
                   coalesce(document.kind, 'report_body') AS kind,
                   version.stage AS stage,
                   version.uri AS uri,
                   version.sha256 AS sha256,
                   coalesce(version.mimeType, 'application/pdf') AS mime_type
            ORDER BY version.createdAt DESC, version.id DESC
            LIMIT 1
            """,
            project_id=project_id,
            kind=kind,
            stage=stage,
            version_id=version_id,
            **self._query_config,
        )
        if not records:
            return None
        record = records[0]
        return VersionInput(
            version_id=record["version_id"],
            document_id=record["document_id"],
            project_id=record["project_id"],
            kind=record["kind"],
            stage=record["stage"],
            uri=record["uri"],
            sha256=record["sha256"],
            mime_type=record["mime_type"],
        )

    def get_project(self, project_id: str) -> dict:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})
            OPTIONAL MATCH (project)-[:HAS_DOCUMENT]->(document:Document)
            OPTIONAL MATCH (document)-[:HAS_VERSION]->(version:DocumentVersion)
            OPTIONAL MATCH (run:AnalysisRun)-[:ANALYZES]->(version)
            OPTIONAL MATCH (project)-[:HAS_RUN]->(prun:AnalysisRun)
            OPTIONAL MATCH (prun)-[:ANALYZES]->(prun_version:DocumentVersion)
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
                       documentVersionId: version.id,
                       progressStage: run.progressStage,
                       progressMessage: run.progressMessage,
                       currentPage: run.currentPage,
                       totalPages: run.totalPages
                   }) AS analysisRuns,
                   collect(DISTINCT {
                       id: prun.id,
                       status: prun.status,
                       step: prun.step,
                       errorCode: prun.errorCode,
                       retryable: coalesce(prun.retryable, false),
                       documentVersionId: prun_version.id,
                       progressStage: prun.progressStage,
                       progressMessage: prun.progressMessage,
                       currentPage: prun.currentPage,
                       totalPages: prun.totalPages
                   }) AS proofreadingRuns
            """,
            project_id=project_id,
            **self._query_config,
        )
        if not records:
            raise ProjectNotFoundError(project_id)

        record = records[0]
        project_node = record["project"]
        project = Project(
            id=project_node["id"], name=project_node["name"], internal_code=project_node.get("internalCode"),
            created_at=(str(project_node.get("createdAt")) if project_node.get("createdAt") is not None else None),
            updated_at=(str(project_node.get("updatedAt")) if project_node.get("updatedAt") is not None else None),
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
                analysis_run_id=value.get("analysisRunId") or "",
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
                "progress_stage": value.get("progressStage"),
                "progress_message": value.get("progressMessage"),
                "current_page": value.get("currentPage"),
                "total_pages": value.get("totalPages"),
            }
            for value in record["analysisRuns"]
            if value["id"] is not None
        ]
        proofreading_runs = [
            {
                "id": value["id"],
                "status": value["status"],
                "step": value["step"],
                "document_version_id": value["documentVersionId"],
                "error_code": value.get("errorCode"),
                "retryable": value.get("retryable", False),
                "progress_stage": value.get("progressStage"),
                "progress_message": value.get("progressMessage"),
                "current_page": value.get("currentPage"),
                "total_pages": value.get("totalPages"),
            }
            for value in record.get("proofreadingRuns", [])
            if value["id"] is not None
        ]
        seen_run_ids: set[str] = set()
        merged_runs = []
        for run in runs + proofreading_runs:
            if run["id"] in seen_run_ids:
                continue
            seen_run_ids.add(run["id"])
            merged_runs.append(run)
        return {
            "project": project,
            "documents": documents,
            "document_versions": versions,
            "analysis_runs": merged_runs,
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
        prev_stage, next_stage = _adjacent_stages(stage)
        result = transaction.run(
            """
            MATCH (project:Project {id: $project_id})
            SET project.updatedAt = datetime()
            MERGE (document:Document {projectId: $project_id, kind: $kind})
            ON CREATE SET document.id = $doc_id,
                          document.title = $title,
                          document.name = $title,
                          document.createdAt = datetime()
            MERGE (project)-[:HAS_DOCUMENT]->(document)
            WITH project, document
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
            WITH document, document_version
            OPTIONAL MATCH (prev:DocumentVersion)<-[:HAS_VERSION]-(document)
            WHERE prev.stage = $prev_stage
            FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
                MERGE (prev)-[:PRECEDES]->(document_version)
            )
            WITH document, document_version
            OPTIONAL MATCH (next:DocumentVersion)<-[:HAS_VERSION]-(document)
            WHERE next.stage = $next_stage
            FOREACH (_ IN CASE WHEN next IS NOT NULL THEN [1] ELSE [] END |
                MERGE (document_version)-[:PRECEDES]->(next)
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
            prev_stage=prev_stage,
            next_stage=next_stage,
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
            OPTIONAL MATCH (project:Project)-[:HAS_DOCUMENT]->
                           (document:Document)-[:HAS_VERSION]->(version)
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
                   version.mimeType AS mimeType,
                   coalesce(document.kind, 'report_body') AS kind,
                   project.id AS projectId
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
            kind=record["kind"],
            project_id=record["projectId"],
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

    def update_run_progress(
        self,
        analysis_run_id: str,
        progress_stage: str,
        progress_message: str,
        current_page: int | None = None,
        total_pages: int | None = None,
    ) -> None:
        self._driver.execute_query(
            """
            MATCH (run:AnalysisRun {id: $analysis_run_id})
            SET run.progressStage = $progress_stage,
                run.progressMessage = $progress_message,
                run.currentPage = $current_page,
                run.totalPages = $total_pages,
                run.updatedAt = datetime()
            """,
            analysis_run_id=analysis_run_id,
            progress_stage=progress_stage,
            progress_message=progress_message,
            current_page=current_page,
            total_pages=total_pages,
            **self._query_config,
        )

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

    def create_review_round(
        self,
        project_id: str,
        body_version_id: str | None = None,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        notes: str | None = None,
    ) -> ReviewRound:
        round_id = str(uuid4())
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})
            SET project.updatedAt = datetime()
            WITH project
            OPTIONAL MATCH (project)-[:HAS_REVIEW_ROUND]->(existing:ReviewRound)
            WITH project, coalesce(max(existing.sequence), 0) + 1 AS next_seq
            CREATE (round:ReviewRound {
                id: $round_id,
                projectId: $project_id,
                sequence: next_seq,
                status: 'reviewing',
                notes: $notes,
                createdAt: datetime(),
                approvedAt: null
            })
            CREATE (project)-[:HAS_REVIEW_ROUND]->(round)
            WITH project, round, next_seq
            OPTIONAL MATCH (project)-[:HAS_REVIEW_ROUND]->(prev:ReviewRound {sequence: next_seq - 1})
            FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
                MERGE (prev)-[:PRECEDES]->(round)
            )
            WITH round
            OPTIONAL MATCH (body:DocumentVersion {id: $body_version_id})
            FOREACH (_ IN CASE WHEN body IS NOT NULL THEN [1] ELSE [] END |
                MERGE (round)-[:USES_BODY_VERSION]->(body)
            )
            WITH round
            OPTIONAL MATCH (plate:DocumentVersion {id: $plate_version_id})
            FOREACH (_ IN CASE WHEN plate IS NOT NULL THEN [1] ELSE [] END |
                MERGE (round)-[:USES_PLATE_VERSION]->(plate)
            )
            WITH round
            OPTIONAL MATCH (drawing:DocumentVersion {id: $drawing_version_id})
            FOREACH (_ IN CASE WHEN drawing IS NOT NULL THEN [1] ELSE [] END |
                MERGE (round)-[:USES_DRAWING_VERSION]->(drawing)
            )
            RETURN round.id AS id,
                   round.projectId AS project_id,
                   round.sequence AS sequence,
                   round.status AS status,
                   round.notes AS notes,
                   round.createdAt AS created_at,
                   round.approvedAt AS approved_at,
                   $body_version_id AS body_version_id,
                   $plate_version_id AS plate_version_id,
                   $drawing_version_id AS drawing_version_id
            """,
            project_id=project_id,
            round_id=round_id,
            body_version_id=body_version_id,
            plate_version_id=plate_version_id,
            drawing_version_id=drawing_version_id,
            notes=notes,
            **self._query_config,
        )
        if not records:
            raise ProjectNotFoundError(project_id)
        record = records[0]
        return ReviewRound(
            id=record["id"],
            project_id=record["project_id"],
            sequence=record["sequence"],
            status=record["status"],
            body_version_id=record.get("body_version_id"),
            plate_version_id=record.get("plate_version_id"),
            drawing_version_id=record.get("drawing_version_id"),
            created_at=record.get("created_at"),
            approved_at=record.get("approved_at"),
            notes=record.get("notes"),
        )

    def list_review_rounds(self, project_id: str) -> list[ReviewRound]:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->(round:ReviewRound)
            OPTIONAL MATCH (round)-[:USES_BODY_VERSION]->(body:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_PLATE_VERSION]->(plate:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_DRAWING_VERSION]->(drawing:DocumentVersion)
            RETURN round.id AS id,
                   round.projectId AS project_id,
                   round.sequence AS sequence,
                   round.status AS status,
                   round.notes AS notes,
                   round.createdAt AS created_at,
                   round.approvedAt AS approved_at,
                   body.id AS body_version_id,
                   plate.id AS plate_version_id,
                   drawing.id AS drawing_version_id
            ORDER BY round.sequence ASC
            """,
            project_id=project_id,
            **self._query_config,
        )
        return [
            ReviewRound(
                id=record["id"],
                project_id=record["project_id"],
                sequence=record["sequence"],
                status=record["status"],
                body_version_id=record.get("body_version_id"),
                plate_version_id=record.get("plate_version_id"),
                drawing_version_id=record.get("drawing_version_id"),
                created_at=record.get("created_at"),
                approved_at=record.get("approved_at"),
                notes=record.get("notes"),
            )
            for record in records
        ]

    def get_review_round(
        self, project_id: str, round_id: str
    ) -> ReviewRound | None:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->(round:ReviewRound {id: $round_id})
            OPTIONAL MATCH (round)-[:USES_BODY_VERSION]->(body:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_PLATE_VERSION]->(plate:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_DRAWING_VERSION]->(drawing:DocumentVersion)
            RETURN round.id AS id,
                   round.projectId AS project_id,
                   round.sequence AS sequence,
                   round.status AS status,
                   round.notes AS notes,
                   round.createdAt AS created_at,
                   round.approvedAt AS approved_at,
                   body.id AS body_version_id,
                   plate.id AS plate_version_id,
                   drawing.id AS drawing_version_id
            """,
            project_id=project_id,
            round_id=round_id,
            **self._query_config,
        )
        if not records:
            return None
        record = records[0]
        return ReviewRound(
            id=record["id"],
            project_id=record["project_id"],
            sequence=record["sequence"],
            status=record["status"],
            body_version_id=record.get("body_version_id"),
            plate_version_id=record.get("plate_version_id"),
            drawing_version_id=record.get("drawing_version_id"),
            created_at=record.get("created_at"),
            approved_at=record.get("approved_at"),
            notes=record.get("notes"),
        )

    def approve_review_round(
        self, project_id: str, round_id: str
    ) -> ReviewRound:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->(round:ReviewRound {id: $round_id})
            SET project.updatedAt = datetime(),
                round.status = 'approved',
                round.approvedAt = datetime()
            WITH round
            OPTIONAL MATCH (round)-[:USES_BODY_VERSION]->(body:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_PLATE_VERSION]->(plate:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_DRAWING_VERSION]->(drawing:DocumentVersion)
            RETURN round.id AS id,
                   round.projectId AS project_id,
                   round.sequence AS sequence,
                   round.status AS status,
                   round.notes AS notes,
                   round.createdAt AS created_at,
                   round.approvedAt AS approved_at,
                   body.id AS body_version_id,
                   plate.id AS plate_version_id,
                   drawing.id AS drawing_version_id
            """,
            project_id=project_id,
            round_id=round_id,
            **self._query_config,
        )
        if not records:
            raise ReviewRoundNotFoundError(
                f"Review round {round_id} not found in project {project_id}"
            )
        record = records[0]
        return ReviewRound(
            id=record["id"],
            project_id=record["project_id"],
            sequence=record["sequence"],
            status=record["status"],
            body_version_id=record.get("body_version_id"),
            plate_version_id=record.get("plate_version_id"),
            drawing_version_id=record.get("drawing_version_id"),
            created_at=record.get("created_at"),
            approved_at=record.get("approved_at"),
            notes=record.get("notes"),
        )

