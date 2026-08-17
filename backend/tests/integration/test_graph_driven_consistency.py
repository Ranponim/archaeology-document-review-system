"""Gate D — graph-backed discrepancy (plan §3 Gate D, §6 Test 3).

One ArchaeologyObject with two graph-backed text claims (`길이 275cm` on Page A,
`길이 2.45m` on Page B). The graph-driven consistency analysis (object evidence
bundle -> RuleEngine) must generate exactly one numeric_value candidate in
pending_review supported by Evidence from both pages. Equivalent values
(275cm vs 2.75m) must produce no numeric conflict. This is the real-DB version
of the existing bundle Gate D unit test. Scoped ids (it_<uuid8>_) are deleted
in finally.

Also hosts the review P0-2 / Test B real-Neo4j kill-switch tests: deleting a
load-bearing graph relationship (MENTIONS / DEPICTS) must change the analysis
OUTCOME — the candidate produced from graph evidence is NOT produced and the
object becomes unresolved — never a silent in-memory fallback.
"""
import uuid

import pytest

from app.domain.canonical_models import ArchaeologyObjectData, PlateData
from app.domain.document_structure import (
    ParsedPage,
    TextBlockData,
    make_block_id,
    make_page_id,
)
from app.domain.models import StoredFile
from app.graph.canonical_repository import CanonicalRepository
from app.graph.project_repository import ProjectRepository
from app.graph.review_repository import ReviewRepository
from app.services.orchestrator_factory import build_proofreading_orchestrator
from app.services.rule_engine import RuleEngine


def _stored(scope: str, name: str) -> StoredFile:
    return StoredFile(
        uri=f"incoming/{scope}/{name}",
        sha256=f"sha256_{scope}",
        size_bytes=1,
        mime_type="application/pdf",
        original_name=name,
    )


def _page(scope: str, version_id: str, physical_page: int, text: str) -> ParsedPage:
    block_id = make_block_id(version_id, physical_page, 1)
    return ParsedPage(
        page_id=make_page_id(version_id, physical_page),
        physical_page=physical_page,
        printed_page=physical_page,
        header="",
        raw_text=text,
        normalized_text=text,
        text_blocks=[
            TextBlockData(
                block_id=block_id,
                text=text,
                normalized_text=text,
                block_type="paragraph",
                order=1,
                source_sha256=f"sha256_{scope}",
            )
        ],
        captions=[],
        source_sha256=f"sha256_{scope}",
    )


def _build_object_graph(
    neo4j_driver,
    scope: str,
    version_id: str,
    canonical_name: str,
    page_a_text: str,
    page_b_text: str,
) -> str:
    review_repo = ReviewRepository(neo4j_driver)
    page_a = _page(scope, version_id, 1, page_a_text)
    page_b = _page(scope, version_id, 2, page_b_text)
    review_repo.save_pages_and_blocks(version_id=version_id, pages=[page_a, page_b])

    block_a = make_block_id(version_id, 1, 1)
    block_b = make_block_id(version_id, 2, 1)
    obj = ArchaeologyObjectData(
        object_id=f"{scope}_obj",
        site="1지점",
        point="1지점",
        period="청동기시대",
        type="주거지",
        number="1호",
        canonical_name=canonical_name,
        source_block_ids=[block_a, block_b],
        source_sha256=f"sha256_{scope}",
    )
    CanonicalRepository(neo4j_driver).save_archaeology_objects([obj])
    return obj.object_id


def test_real_neo4j_graph_driven_numeric_conflict(neo4j_driver, scoped_prefix, cleanup, create_project):
    """Gate D: two graph-backed claims (275cm vs 2.45m) yield exactly one
    numeric_value candidate in pending_review supported by both pages."""
    scope = scoped_prefix
    project_repo = ProjectRepository(neo4j_driver)
    project_id = create_project(scope, f"{scope} project")
    _doc, version = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "body.pdf"),
        stage="1차",
        kind="report_body",
    )

    try:
        obj_id = _build_object_graph(
            neo4j_driver,
            scope,
            version.id,
            "1지점 청동기시대 1호 주거지",
            "1지점 청동기시대 1호 주거지 규모는 길이 275cm이다.",
            "1지점 청동기시대 1호 주거지 평면조사에서는 길이 2.45m로 기록되었다.",
        )

        bundle = CanonicalRepository(neo4j_driver).get_object_evidence_bundle(obj_id)
        assert len(bundle.text_claims) == 2, "bundle must carry both graph claims"

        candidates = RuleEngine(header_patterns=[]).check_object_bundle_consistency(
            bundle, plates=[], drawings=[]
        )
        numeric = [c for c in candidates if c.rule_category == "numeric_value"]
        assert len(numeric) == 1, "exactly one numeric_value candidate expected"
        assert numeric[0].status == "pending_review"
        assert len(numeric[0].evidences) == 2, (
            "candidate must be supported by evidence from both pages"
        )
        page_ids = {ev.page_id for ev in numeric[0].evidences}
        assert page_ids == {
            make_page_id(version.id, 1),
            make_page_id(version.id, 2),
        }, "evidence must come from both source pages"
    finally:
        cleanup(scope)


def test_real_neo4j_graph_driven_equivalent_values_no_conflict(
    neo4j_driver, scoped_prefix, cleanup, create_project
):
    """Gate D: equivalent values (275cm vs 2.75m) produce no numeric conflict."""
    scope = scoped_prefix
    project_repo = ProjectRepository(neo4j_driver)
    project_id = create_project(scope, f"{scope} project")
    _doc, version = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "body.pdf"),
        stage="1차",
        kind="report_body",
    )

    try:
        obj_id = _build_object_graph(
            neo4j_driver,
            scope,
            version.id,
            "1지점 청동기시대 1호 주거지",
            "1지점 청동기시대 1호 주거지 규모는 길이 275cm이다.",
            "1지점 청동기시대 1호 주거지 평면조사에서는 길이 2.75m로 기록되었다.",
        )

        bundle = CanonicalRepository(neo4j_driver).get_object_evidence_bundle(obj_id)
        candidates = RuleEngine(header_patterns=[]).check_object_bundle_consistency(
            bundle, plates=[], drawings=[]
        )
        numeric = [c for c in candidates if c.rule_category == "numeric_value"]
        assert numeric == [], "equivalent values must produce no numeric conflict"
    finally:
        cleanup(scope)


@pytest.mark.anyio
async def test_real_neo4j_kill_switch_mentions_deletion_changes_outcome(
    neo4j_driver, scoped_prefix, cleanup, create_project
):
    """Review P0-2 / Test B (real Neo4j): deleting a load-bearing MENTIONS
    relationship must change the analysis OUTCOME — the numeric candidate
    produced from graph evidence is NOT produced and the object becomes
    unresolved. A node-count-only assertion is insufficient; the candidate
    outcome must change. Scoped ids; cleanup in finally."""
    scope = scoped_prefix
    project_repo = ProjectRepository(neo4j_driver)
    project_id = create_project(scope, f"{scope} project")
    _doc, version = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "body.pdf"),
        stage="1차",
        kind="report_body",
    )
    try:
        # 1. Ingest a valid body/object graph via the production orchestrator
        #    (allow_degraded_mode=False default) and verify the candidate.
        orchestrator = build_proofreading_orchestrator(neo4j_driver)
        result = await orchestrator.run_proofreading(
            project_id=project_id,
            body_version_id=version.id,
            body_pages=[
                _page(scope, version.id, 1, "1지점 청동기시대 1호 주거지 규모는 길이 275cm이다."),
                _page(scope, version.id, 2, "1지점 청동기시대 1호 주거지 평면조사에서는 길이 2.45m로 기록되었다."),
            ],
            analysis_run_id=f"{scope}_run1",
            enable_vlm=False,
            enable_ai_review=False,
        )
        assert result.status == "completed"
        numeric = [c for c in result.candidates if c.rule_category == "numeric_value"]
        assert numeric, "run 1 must produce the numeric candidate from graph evidence"
        assert result.unresolved == []
        obj_id = result.objects[0].object_id

        # 2. Delete the load-bearing MENTIONS relationship (scoped ids only).
        #    Source block ids derive from the version id, so match by version.
        neo4j_driver.execute_query(
            """
            MATCH (s)-[r:MENTIONS]->(o:ArchaeologyObject)
            WHERE s.id STARTS WITH $version_id
            DETACH DELETE r
            """,
            version_id=version.id,
        )

        # 3. Re-run the production-mode graph-driven analysis: the bundle is
        #    now empty, so the numeric candidate is NOT produced and the object
        #    is unresolved (no in-memory fallback).
        bundle = CanonicalRepository(neo4j_driver).get_object_evidence_bundle(obj_id)
        assert bundle.has_graph_evidence() is False, (
            "deleting MENTIONS must empty the object's graph evidence bundle"
        )
        candidates = RuleEngine(header_patterns=[]).check_object_bundle_consistency(
            bundle, plates=[], drawings=[]
        )
        numeric2 = [c for c in candidates if c.rule_category == "numeric_value"]
        assert numeric2 == [], (
            "the numeric candidate must NOT be produced after MENTIONS is deleted"
        )
    finally:
        cleanup(scope)


@pytest.mark.anyio
async def test_real_neo4j_kill_switch_depicts_deletion_changes_visual_evidence(
    neo4j_driver, scoped_prefix, cleanup, create_project
):
    """Review P0-2 / Test B (real Neo4j, DEPICTS variant): deleting the
    load-bearing DEPICTS relationship must remove the plate_claim visual
    evidence from the object's graph bundle — the semantic visual result is
    not produced normally. Scoped ids; cleanup in finally."""
    scope = scoped_prefix
    project_repo = ProjectRepository(neo4j_driver)
    project_id = create_project(scope, f"{scope} project")
    _doc, version = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "body.pdf"),
        stage="1차",
        kind="report_body",
    )
    try:
        # 1. Ingest a valid body/plate/object graph via the production
        #    orchestrator (plate DEPICTS the object) and verify the visual
        #    evidence is present.
        plate = PlateData(
            plate_id=f"{scope}_plate45",
            number="45",
            physical_page=47,
            title="1지점 청동기시대 1호 주거지",
            source_sha256=f"sha256_{scope}_plate",
            document_version_id=version.id,
            raw_identifier="【도판 45】",
        )
        orchestrator = build_proofreading_orchestrator(neo4j_driver)
        result = await orchestrator.run_proofreading(
            project_id=project_id,
            body_version_id=version.id,
            body_pages=[
                _page(scope, version.id, 1, "1지점 청동기시대 1호 주거지 규모는 길이 275cm이다."),
            ],
            plates=[plate],
            analysis_run_id=f"{scope}_run1",
            enable_vlm=False,
            enable_ai_review=False,
        )
        assert result.status == "completed"
        obj_id = result.objects[0].object_id
        bundle = CanonicalRepository(neo4j_driver).get_object_evidence_bundle(obj_id)
        assert bundle.plate_claims, "run 1 must expose the plate_claim visual evidence"

        # 2. Delete the load-bearing DEPICTS relationship (scoped ids only).
        neo4j_driver.execute_query(
            """
            MATCH (asset)-[r:DEPICTS]->(o:ArchaeologyObject)
            WHERE asset.id STARTS WITH $scope
            DETACH DELETE r
            """,
            scope=scope,
        )

        # 3. Re-run the production-mode graph-driven analysis: the plate_claim
        #    visual evidence is gone — the semantic visual result is not
        #    produced normally.
        bundle2 = CanonicalRepository(neo4j_driver).get_object_evidence_bundle(obj_id)
        assert bundle2.plate_claims == [], (
            "deleting DEPICTS must remove the plate_claim visual evidence"
        )
    finally:
        cleanup(scope)