"""Gate E — real review traceability (plan §3 Gate E, §6 Test 4).

Persist a candidate + evidence + decisions via the real repositories and assert
the full traversal exists in the real DB:

    Candidate -[:ABOUT]-> Object
    Candidate -[:SUPPORTED_BY]-> Evidence -[:EXTRACTED_FROM]-> Page
    Evidence -[:FROM_VERSION]-> DocumentVersion
    Candidate -[:HAS_DECISION]-> ReviewDecision  (append-only: two decisions)

Candidate generation status stays pending_review and decision values are in the
4-value set (accepted|rejected|modified|deferred). Scoped ids (it_<uuid8>_) are
deleted in finally.
"""
import time
import uuid

from app.domain.canonical_models import ArchaeologyObjectData, PlateData, ReferenceData
from app.domain.document_structure import (
    ParsedPage,
    TextBlockData,
    make_block_id,
    make_page_id,
    make_reference_id,
)
from app.domain.models import StoredFile
from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.graph.canonical_repository import CanonicalRepository
from app.graph.project_repository import ProjectRepository
from app.graph.review_repository import ReviewRepository

DECISION_VALUES = {"accepted", "rejected", "modified", "deferred"}


def _stored(scope: str, name: str) -> StoredFile:
    return StoredFile(
        uri=f"incoming/{scope}/{name}",
        sha256=f"sha256_{scope}",
        size_bytes=1,
        mime_type="application/pdf",
        original_name=name,
    )


def test_real_neo4j_review_traceability_graph(neo4j_driver, scoped_prefix, cleanup, create_project):
    """Gate E: the full candidate -> object -> evidence -> page -> version ->
    decision traversal exists in the real DB with pending_review generation
    status and 4-value decisions."""
    scope = scoped_prefix
    project_repo = ProjectRepository(neo4j_driver)
    project_id = create_project(scope, f"{scope} project")
    _doc, version = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "body.pdf"),
        stage="1차",
        kind="report_body",
    )

    review_repo = ReviewRepository(neo4j_driver)
    canonical_repo = CanonicalRepository(neo4j_driver)

    page_id = make_page_id(version.id, 1)
    block_id = make_block_id(version.id, 1, 1)
    text = "1지점 청동기시대 1호 주거지 규모는 길이 275cm이다."
    page = ParsedPage(
        page_id=page_id,
        physical_page=1,
        printed_page=1,
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
    review_repo.save_pages_and_blocks(version_id=version.id, pages=[page])

    obj = ArchaeologyObjectData(
        object_id=f"{scope}_obj",
        site="1지점",
        point="1지점",
        period="청동기시대",
        type="주거지",
        number="1호",
        canonical_name="1지점 청동기시대 1호 주거지",
        source_block_ids=[block_id],
        source_sha256=f"sha256_{scope}",
    )
    canonical_repo.save_archaeology_objects([obj])

    cand_id = f"{scope}_cand"
    ev_id = f"{scope}_ev"
    run_id = f"{scope}_run"
    candidate = CorrectionCandidateData(
        candidate_id=cand_id,
        rule_category="numeric_value",
        change_type="modified",
        status="pending_review",
        original_text="길이 275cm",
        proposed_text="길이 2.45m",
        evidence=EvidenceData(
            id=ev_id,
            kind="text_claim",
            source_sha256=f"sha256_{scope}",
            document_version_id=version.id,
            page_id=page_id,
            region_id=block_id,
            value="길이 275cm",
            confidence=1.0,
        ),
        archaeology_object_id=obj.object_id,
        analysis_run_id=run_id,
    )

    dec1 = f"{scope}_dec1"
    dec2 = f"{scope}_dec2"
    try:
        review_repo.save_candidates(
            project_id=project_id,
            candidates=[candidate],
            analysis_run_id=run_id,
        )
        review_repo.save_review_decision(
            decision_id=dec1,
            candidate_id=cand_id,
            decision_status="accepted",
            reviewer="expert_1",
            note="1차 수용",
        )
        time.sleep(0.05)
        review_repo.save_review_decision(
            decision_id=dec2,
            candidate_id=cand_id,
            decision_status="deferred",
            reviewer="expert_2",
            note="보류",
        )

        recs, _, _ = neo4j_driver.execute_query(
            """
            MATCH (cand:CorrectionCandidate {id: $cand_id})
            MATCH (cand)-[:ABOUT]->(obj:ArchaeologyObject)
            MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
            MATCH (ev)-[:EXTRACTED_FROM]->(page:Page)
            MATCH (ev)-[:FROM_VERSION]->(version:DocumentVersion)
            MATCH (cand)-[:HAS_DECISION]->(dec:ReviewDecision)
            RETURN cand.status AS status, obj.id AS obj_id, ev.id AS ev_id,
                   page.id AS page_id, version.id AS version_id,
                   collect(DISTINCT dec.decision_status) AS decisions
            """,
            cand_id=cand_id,
        )
        assert len(recs) == 1, "full traceability traversal must exist"
        row = recs[0]
        assert row["status"] == "pending_review"
        assert row["obj_id"] == obj.object_id
        assert row["ev_id"] == ev_id
        assert row["page_id"] == page_id
        assert row["version_id"] == version.id
        assert set(row["decisions"]) == {"accepted", "deferred"}
        assert set(row["decisions"]) <= DECISION_VALUES

        cand = review_repo.get_candidate(cand_id)
        assert cand is not None
        assert cand["status"] == "pending_review"
        assert {d["id"] for d in cand["decisions"]} == {dec1, dec2}
        assert cand["latest_decision"]["id"] == dec2
        assert cand["latest_decision"]["decision_status"] == "deferred"
    finally:
        cleanup(scope)


def test_real_neo4j_canonical_identity_path_in_traceability(
    neo4j_driver, cleanup, create_project
):
    scope = f"cip_test_{uuid.uuid4().hex[:8]}_"
    project_repo = ProjectRepository(neo4j_driver)
    project_id = create_project(scope, f"{scope} project")
    _doc, version = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "body.pdf"),
        stage="1차",
        kind="report_body",
    )

    review_repo = ReviewRepository(neo4j_driver)
    canonical_repo = CanonicalRepository(neo4j_driver)

    page_id = make_page_id(version.id, 54)
    block_id = make_block_id(version.id, 54, 1)
    text = "1지점 청동기시대 6호 석관묘는 도판 45를 참조한다."
    page = ParsedPage(
        page_id=page_id,
        physical_page=54,
        printed_page=50,
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
    review_repo.save_pages_and_blocks(version_id=version.id, pages=[page])

    obj = ArchaeologyObjectData(
        object_id=f"{scope}_obj",
        site="1지점",
        point="1지점",
        period="청동기시대",
        type="석관묘",
        number="6호",
        canonical_name="1지점 청동기시대 6호 석관묘",
        source_block_ids=[block_id],
        source_sha256=f"sha256_{scope}",
    )
    canonical_repo.save_archaeology_objects([obj])

    ref = ReferenceData(
        ref_type="plate",
        number="45",
        source_block_id=block_id,
        raw_text="도판 45",
        source_sha256=f"sha256_{scope}",
        physical_page=54,
    )
    canonical_repo.save_references([ref])
    ref_id = make_reference_id(block_id, "plate", "45")

    plate = PlateData(
        plate_id=f"{scope}_plate45",
        number="45",
        physical_page=45,
        title="1지점 청동기시대 6호 석관묘",
        source_sha256=f"sha256_{scope}",
        document_version_id=version.id,
        raw_identifier="【도판 45】",
    )
    canonical_repo.save_plates([plate])
    canonical_repo.link_reference_to_target(ref_id, "Plate", plate.plate_id)
    canonical_repo.link_visual_assets_to_objects(plates=[plate], objects=[obj])

    cand_id = f"{scope}_cand"
    run_id = f"{scope}_run"
    candidate = CorrectionCandidateData(
        candidate_id=cand_id,
        rule_category="figure_plate_table_photo_ref",
        change_type="modified",
        status="pending_review",
        original_text="도판 : ",
        proposed_text="도판 : 45",
        evidence=EvidenceData(
            id=f"{scope}_ev",
            kind="reference",
            source_sha256=f"sha256_{scope}",
            document_version_id=version.id,
            page_id=page_id,
            region_id=block_id,
            value="도판 : 45",
            confidence=1.0,
        ),
        archaeology_object_id=obj.object_id,
        analysis_run_id=run_id,
    )

    try:
        review_repo.save_candidates(
            project_id=project_id,
            candidates=[candidate],
            analysis_run_id=run_id,
        )

        trace = review_repo.get_candidate_traceability(cand_id)
        assert trace["candidate"]["id"] == cand_id
        assert trace["archaeology_object"]["id"] == obj.object_id

        canonical_path = trace["canonical_path"]
        edges = [(e["edge"], e["from"], e["to"]) for e in canonical_path]
        assert ("REFERENCES", block_id, ref_id) in edges
        assert ("RESOLVES_TO", ref_id, plate.plate_id) in edges
        assert ("DEPICTS", plate.plate_id, obj.object_id) in edges

        by_edge = {e["edge"]: e for e in canonical_path}
        assert by_edge["RESOLVES_TO"]["target"]["raw_identifier"] == "【도판 45】"
        assert by_edge["DEPICTS"]["target"]["canonical_name"] == "1지점 청동기시대 6호 석관묘"
    finally:
        cleanup(scope)