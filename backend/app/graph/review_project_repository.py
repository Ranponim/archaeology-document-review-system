from __future__ import annotations

from neo4j import ManagedTransaction

from app.domain.models import Document, DocumentVersion, StoredFile
from app.domain.review_round import ReviewRound
from app.graph.project_repository import ProjectRepository, ReviewRoundNotFoundError


class ReviewProjectRepository(ProjectRepository):
    """Project repository semantics for ReviewRound execution.

    A concrete DocumentVersion id is canonical graph identity. Human stage
    labels such as ``2차`` are compatibility/display metadata and never define
    revision lineage. ReviewRound.sequence and ReviewRound PRECEDES are the
    only review-order authority.
    """

    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ):
        if version_id:
            stage = None
        return super().resolve_version_input(project_id, kind, stage, version_id)

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
        """Create an ingestable DocumentVersion without stage-derived PRECEDES.

        `stage` is retained only as compatibility metadata for older clients.
        A document may be reused in any later ReviewRound, so a stage label can
        never safely imply graph lineage.
        """
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

    def create_review_round(
        self,
        project_id: str,
        body_version_id: str | None = None,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        notes: str | None = None,
    ) -> ReviewRound:
        missing = [
            label
            for label, value in (
                ("report_body", body_version_id),
                ("plate_book", plate_version_id),
                ("drawing_book", drawing_version_id),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "ReviewRound requires the complete canonical input set "
                "(report_body + plate_book + drawing_book); missing: "
                + ", ".join(missing)
            )
        return super().create_review_round(
            project_id=project_id,
            body_version_id=body_version_id,
            plate_version_id=plate_version_id,
            drawing_version_id=drawing_version_id,
            notes=notes,
        )

    def approve_review_round(self, project_id: str, round_id: str) -> ReviewRound:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->
                  (round:ReviewRound {id: $round_id})
            SET round.status = 'approved',
                round.approvedAt = coalesce(round.approvedAt, datetime())
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
