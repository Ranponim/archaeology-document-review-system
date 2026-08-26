from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.drawing_evidence_v3 import (
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Resolution,
    DrawingV3SourceResult,
)
from app.graph.drawing_evidence_repository_v3 import DrawingEvidenceRepositoryV3
from app.main import create_app


class ProjectLookupRepository:
    def __init__(self, project_id: str):
        self.project_id = project_id

    def get_project(self, project_id: str):
        if project_id != self.project_id:
            raise KeyError(project_id)
        return {"id": project_id, "name": "integration"}


def candidate(candidate_id: str, number: str, score: float) -> DrawingCandidatePacket:
    return DrawingCandidatePacket(
        candidate_id=candidate_id,
        publication_kind="drawing",
        number=number,
        raw_texts=(f"도면 {number}. 2지점 토광묘",),
        facts=(),
        visual_regions=(),
        local_score=score,
        evidence=(),
        hard_contradiction=False,
        strong_contradiction_ids=(),
    )


def test_human_choose_preserves_codex_and_persists_review_provenance(
    neo4j_driver,
    scoped_prefix,
    cleanup,
):
    scope = scoped_prefix
    project_id = f"{scope}project"
    corpus_id = f"{scope}corpus"
    source_id = f"{scope}source"
    candidate_52 = f"{scope}candidate-52"
    candidate_53 = f"{scope}candidate-53"
    run_id = f"{scope}run"

    neo4j_driver.execute_query(
        """
        CREATE (p:Project {id: $project_id, name: 'drawing-review-e2e'})
        CREATE (c:ReferenceCorpus {id: $corpus_id, projectId: $project_id, status: 'ready'})
        CREATE (a:OriginalAsset {
            id: $source_id,
            projectId: $project_id,
            originalName: 'source.ai',
            sha256: 'sha-source'
        })
        CREATE (p)-[:HAS_REFERENCE_CORPUS]->(c)
        CREATE (c)-[:USES_SOURCE]->(a)
        """,
        project_id=project_id,
        corpus_id=corpus_id,
        source_id=source_id,
    )

    repository = DrawingEvidenceRepositoryV3(neo4j_driver)
    c52 = candidate(candidate_52, "52", 18.0)
    c53 = candidate(candidate_53, "53", 17.0)
    source = DrawingSourceEvidencePacket(
        source_asset_id=source_id,
        source_sha256="sha-source",
        original_name="source.ai",
        source_path="drawings/source.ai",
        raw_text="2지점 1호 토광묘 평단면",
        publication_kind=None,
        internal_numbers=(),
        facts=(),
        visual_regions=(),
        evidence=(),
    )
    resolution = DrawingV3Resolution(
        source_results=(
            DrawingV3SourceResult(
                source_asset_id=source_id,
                status="REVIEW_REQUIRED",
                candidates=(c52, c53),
                decision=CodexDrawingDecision(
                    run_id=run_id,
                    model="gpt-5.3-codex",
                    verdict="match",
                    candidate_id=candidate_52,
                    confidence=0.98,
                    cited_support_ids=(),
                    cited_contradiction_ids=(),
                    reason_codes=("review_required",),
                    summary="도면 52가 가장 유력하지만 사람 확인이 필요합니다.",
                ),
                selected_candidate_id=candidate_52,
                diagnostics={"resolver_version": "drawing-evidence-v3"},
            ),
        ),
        diagnostics={"resolver_version": "drawing-evidence-v3"},
    )
    repository.save_v3_resolution(
        project_id,
        corpus_id,
        resolution,
        auto_promote=False,
        sources=(source,),
    )

    app = create_app(project_repository=ProjectLookupRepository(project_id))
    app.state.drawing_evidence_repository = repository

    try:
        with TestClient(app) as client:
            queue = client.get(f"/api/v1/projects/{project_id}/drawing-reviews")
            assert queue.status_code == 200
            rows = queue.json()
            assert len(rows) == 1
            assert rows[0]["source_asset_id"] == source_id
            assert rows[0]["codex_candidate_id"] == candidate_52
            assert [item["candidate_id"] for item in rows[0]["candidates"]] == [
                candidate_52,
                candidate_53,
            ]

            resolved = client.post(
                f"/api/v1/projects/{project_id}/drawing-reviews/{source_id}/resolve",
                json={
                    "action": "choose",
                    "candidate_id": candidate_53,
                    "reviewer": "integration-human",
                },
            )
            assert resolved.status_code == 200
            assert resolved.json() == {
                "source_asset_id": source_id,
                "action": "choose",
                "candidate_id": candidate_53,
                "final_status": "HUMAN_VERIFIED",
            }

            after = client.get(f"/api/v1/projects/{project_id}/drawing-reviews")
            assert after.status_code == 200
            assert after.json() == []

        records, _, _ = neo4j_driver.execute_query(
            """
            MATCH (asset:OriginalAsset {id: $source_id})-[:HAS_CODEX_DECISION]->(decision:CodexDecision)
            OPTIONAL MATCH (asset)-[:HAS_HUMAN_RESOLUTION]->(human:HumanDrawingResolution)-[:REVIEWS]->(decision)
            OPTIONAL MATCH (human)-[:SELECTED]->(selected:DrawingCandidate)
            OPTIONAL MATCH (human)-[:REJECTED]->(rejected:DrawingCandidate)
            OPTIONAL MATCH (selected)-[:TARGETS]->(drawing:Drawing)
            RETURN decision.finalStatus AS codex_status,
                   decision.candidateId AS codex_candidate_id,
                   decision.runId AS codex_run_id,
                   decision.model AS codex_model,
                   count(DISTINCT human) AS human_count,
                   head(collect(DISTINCT human.action)) AS human_action,
                   head(collect(DISTINCT human.reviewer)) AS reviewer,
                   head(collect(DISTINCT selected.id)) AS selected_id,
                   [id IN collect(DISTINCT rejected.id) WHERE id IS NOT NULL] AS rejected_ids,
                   count(DISTINCT drawing) AS drawing_count,
                   head(collect(DISTINCT drawing.evidenceMethod)) AS evidence_method,
                   head(collect(DISTINCT drawing.number)) AS drawing_number
            """,
            source_id=source_id,
        )
        assert len(records) == 1
        row = records[0]
        assert row["codex_status"] == "REVIEW_REQUIRED"
        assert row["codex_candidate_id"] == candidate_52
        assert row["codex_run_id"] == run_id
        assert row["codex_model"] == "gpt-5.3-codex"
        assert row["human_count"] == 1
        assert row["human_action"] == "choose"
        assert row["reviewer"] == "integration-human"
        assert row["selected_id"] == candidate_53
        assert row["rejected_ids"] == [candidate_52]
        assert row["drawing_count"] == 1
        assert row["evidence_method"] == "human-verified-v3"
        assert row["drawing_number"] == "53"
    finally:
        cleanup(scope)
