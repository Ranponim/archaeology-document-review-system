from __future__ import annotations

from app.domain.review_round import ReviewRound
from app.graph.project_repository import ProjectRepository, ReviewRoundNotFoundError


class ReviewProjectRepository(ProjectRepository):
    """Project repository semantics for ReviewRound execution.

    ReviewRound resolution passes `stage=None` and therefore resolves exact
    version identities without a fixed stage ceiling. Legacy direct-version
    callers that still provide a stage keep strict stage-mismatch validation.
    """

    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ):
        return super().resolve_version_input(project_id, kind, stage, version_id)

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
