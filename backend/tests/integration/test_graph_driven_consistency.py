"""Gate D — graph-backed discrepancy (plan §3 Gate D, §6 Test 3).

One ArchaeologyObject with two graph-backed text claims (`길이 275cm` on Page A,
`길이 2.45m` on Page B). The graph-driven consistency analysis (object evidence
bundle -> RuleEngine) must generate exactly one numeric_value candidate in
pending_review supported by Evidence from both pages. Equivalent values
(275cm vs 2.75m) must produce no numeric conflict. This is the real-DB version
of the existing bundle Gate D unit test. Scoped ids (it_<uuid8>_) are deleted
in finally.
"""
import uuid

from app.domain.canonical_models import ArchaeologyObjectData
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