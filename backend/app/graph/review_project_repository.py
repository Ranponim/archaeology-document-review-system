from __future__ import annotations

from uuid import uuid4

from neo4j import ManagedTransaction

from app.domain.models import Document, DocumentVersion, StoredFile
from app.domain.review_round import ReviewRound
from app.graph.project_repository import (
    DocumentVersionNotFoundError,
    ProjectRepository,
    ReviewRoundNotFoundError,
)


class ReviewProjectRepository(ProjectRepository):
    """Project repository semantics for ReviewRound execution.

    New review rounds bind one body DocumentVersion and one immutable READY
    ReferenceCorpus. Historical body+plate-PDF+drawing-PDF rounds remain
    readable/executable through an explicit legacy compatibility path.
    ReviewRound PRECEDES is the only review-order authority.
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
        """Create an ingestable DocumentVersion without stage-derived PRECEDES."""
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

    @staticmethod
    def _round_from_record(record) -> ReviewRound:
        return ReviewRound(
            id=record["id"],
            project_id=record["project_id"],
            sequence=record["sequence"],
            status=record["status"],
            body_version_id=record.get("body_version_id"),
            reference_corpus_id=record.get("reference_corpus_id"),
            plate_version_id=record.get("plate_version_id"),
            drawing_version_id=record.get("drawing_version_id"),
            created_at=record.get("created_at"),
            approved_at=record.get("approved_at"),
            notes=record.get("notes"),
        )

    def _validate_body(self, project_id: str, body_version_id: str | None) -> str:
        if not body_version_id:
            raise ValueError("ReviewRound requires a report_body DocumentVersion")
        resolved = self.resolve_version_input(
            project_id=project_id,
            kind="report_body",
            stage=None,
            version_id=body_version_id,
        )
        if resolved is None:
            raise DocumentVersionNotFoundError(
                f"DocumentVersion '{body_version_id}' is not a report_body asset "
                f"owned by project '{project_id}'"
            )
        return resolved.version_id

    def _validate_ready_corpus(self, project_id: str, reference_corpus_id: str) -> None:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $reference_corpus_id})
            WHERE corpus.projectId = $project_id
            RETURN corpus.id AS id,
                   corpus.status AS status,
                   corpus.projectId AS project_id
            LIMIT 1
            """,
            project_id=project_id,
            reference_corpus_id=reference_corpus_id,
            **self._query_config,
        )
        if not records:
            raise ValueError("reference corpus does not belong to project")
        if str(records[0].get("status") or "").lower() != "ready":
            raise ValueError("ReviewRound reference corpus must be READY")

    def _create_corpus_review_round(
        self,
        project_id: str,
        body_version_id: str,
        reference_corpus_id: str,
        notes: str | None,
    ) -> ReviewRound:
        round_id = str(uuid4())
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_DOCUMENT]->
                  (body_document:Document {kind: 'report_body'})-[:HAS_VERSION]->
                  (body:DocumentVersion {id: $body_version_id})
            MATCH (project)-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $reference_corpus_id})
            WHERE corpus.projectId = $project_id AND corpus.status = 'ready'
            SET project.updatedAt = datetime()
            WITH project, body, corpus
            OPTIONAL MATCH (project)-[:HAS_REVIEW_ROUND]->(existing:ReviewRound)
            WITH project, body, corpus, coalesce(max(existing.sequence), 0) + 1 AS next_seq
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
            CREATE (round)-[:USES_BODY_VERSION]->(body)
            CREATE (round)-[:USES_REFERENCE_CORPUS]->(corpus)
            WITH project, round, body, corpus, next_seq
            OPTIONAL MATCH (project)-[:HAS_REVIEW_ROUND]->(previous:ReviewRound)
            WHERE previous.id <> round.id AND previous.sequence = next_seq - 1
            FOREACH (_ IN CASE WHEN previous IS NULL THEN [] ELSE [1] END |
                MERGE (previous)-[:PRECEDES]->(round)
            )
            RETURN round.id AS id,
                   round.projectId AS project_id,
                   round.sequence AS sequence,
                   round.status AS status,
                   round.notes AS notes,
                   round.createdAt AS created_at,
                   round.approvedAt AS approved_at,
                   body.id AS body_version_id,
                   corpus.id AS reference_corpus_id,
                   null AS plate_version_id,
                   null AS drawing_version_id
            """,
            project_id=project_id,
            round_id=round_id,
            body_version_id=body_version_id,
            reference_corpus_id=reference_corpus_id,
            notes=notes,
            **self._query_config,
        )
        if not records:
            raise ValueError("body or READY reference corpus changed before round creation")
        return self._round_from_record(records[0])

    def create_review_round(
        self,
        project_id: str,
        body_version_id: str | None = None,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        notes: str | None = None,
        reference_corpus_id: str | None = None,
    ) -> ReviewRound:
        if reference_corpus_id is not None:
            if plate_version_id is not None or drawing_version_id is not None:
                raise ValueError("mixed ReferenceCorpus and legacy visual PDF authority is not allowed")
            validated_body = self._validate_body(project_id, body_version_id)
            self._validate_ready_corpus(project_id, reference_corpus_id)
            return self._create_corpus_review_round(
                project_id,
                validated_body,
                reference_corpus_id,
                notes,
            )

        requested = (
            ("report_body", body_version_id),
            ("plate_book", plate_version_id),
            ("drawing_book", drawing_version_id),
        )
        missing = [kind for kind, version_id in requested if not version_id]
        if missing:
            raise ValueError(
                "Legacy ReviewRound requires the complete canonical input set "
                "(report_body + plate_book + drawing_book); missing: "
                + ", ".join(missing)
            )

        validated: dict[str, str] = {}
        for kind, version_id in requested:
            assert version_id is not None
            resolved = self.resolve_version_input(
                project_id=project_id,
                kind=kind,
                stage=None,
                version_id=version_id,
            )
            if resolved is None:
                raise DocumentVersionNotFoundError(
                    f"DocumentVersion '{version_id}' is not a {kind} asset "
                    f"owned by project '{project_id}'"
                )
            validated[kind] = resolved.version_id

        return super().create_review_round(
            project_id=project_id,
            body_version_id=validated["report_body"],
            plate_version_id=validated["plate_book"],
            drawing_version_id=validated["drawing_book"],
            notes=notes,
        )

    def list_review_rounds(self, project_id: str) -> list[ReviewRound]:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->(round:ReviewRound)
            OPTIONAL MATCH (round)-[:USES_BODY_VERSION]->(body:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_REFERENCE_CORPUS]->(corpus:ReferenceCorpus)
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
                   corpus.id AS reference_corpus_id,
                   plate.id AS plate_version_id,
                   drawing.id AS drawing_version_id
            ORDER BY round.sequence ASC
            """,
            project_id=project_id,
            **self._query_config,
        )
        return [self._round_from_record(record) for record in records]

    def get_review_round(self, project_id: str, round_id: str) -> ReviewRound | None:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->
                  (round:ReviewRound {id: $round_id})
            OPTIONAL MATCH (round)-[:USES_BODY_VERSION]->(body:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_REFERENCE_CORPUS]->(corpus:ReferenceCorpus)
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
                   corpus.id AS reference_corpus_id,
                   plate.id AS plate_version_id,
                   drawing.id AS drawing_version_id
            """,
            project_id=project_id,
            round_id=round_id,
            **self._query_config,
        )
        if not records:
            return None
        return self._round_from_record(records[0])

    def get_previous_review_round(
        self,
        project_id: str,
        round_id: str,
    ) -> ReviewRound | None:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->
                  (current:ReviewRound {id: $round_id})
            OPTIONAL MATCH (project)-[:HAS_REVIEW_ROUND]->
                           (previous:ReviewRound)-[:PRECEDES]->(current:ReviewRound)
            OPTIONAL MATCH (previous)-[:USES_BODY_VERSION]->(body:DocumentVersion)
            OPTIONAL MATCH (previous)-[:USES_REFERENCE_CORPUS]->(corpus:ReferenceCorpus)
            OPTIONAL MATCH (previous)-[:USES_PLATE_VERSION]->(plate:DocumentVersion)
            OPTIONAL MATCH (previous)-[:USES_DRAWING_VERSION]->(drawing:DocumentVersion)
            RETURN previous.id AS id,
                   project.id AS project_id,
                   previous.sequence AS sequence,
                   previous.status AS status,
                   previous.notes AS notes,
                   previous.createdAt AS created_at,
                   previous.approvedAt AS approved_at,
                   body.id AS body_version_id,
                   corpus.id AS reference_corpus_id,
                   plate.id AS plate_version_id,
                   drawing.id AS drawing_version_id
            """,
            project_id=project_id,
            round_id=round_id,
            **self._query_config,
        )
        if not records or records[0].get("id") is None:
            return None
        return self._round_from_record(records[0])

    def approve_review_round(self, project_id: str, round_id: str) -> ReviewRound:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REVIEW_ROUND]->
                  (round:ReviewRound {id: $round_id})
            SET project.updatedAt = datetime(),
                round.status = 'approved',
                round.approvedAt = coalesce(round.approvedAt, datetime())
            WITH round
            OPTIONAL MATCH (round)-[:USES_BODY_VERSION]->(body:DocumentVersion)
            OPTIONAL MATCH (round)-[:USES_REFERENCE_CORPUS]->(corpus:ReferenceCorpus)
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
                   corpus.id AS reference_corpus_id,
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
        return self._round_from_record(records[0])
