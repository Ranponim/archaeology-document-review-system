from app.domain.drawing_evidence_v3 import (
    BodyDrawingEvidencePacket,
    DrawingSourceEvidencePacket,
)
from app.services.drawing_candidate_generator_v3 import DrawingCandidateGeneratorV3


def source_packet(
    text: str,
    *,
    publication_kind: str | None = "drawing",
    original_name: str = "mystery.ai",
    source_path: str = "site/source/mystery.ai",
) -> DrawingSourceEvidencePacket:
    return DrawingSourceEvidencePacket(
        source_asset_id="asset-1",
        source_sha256="source-sha",
        original_name=original_name,
        source_path=source_path,
        raw_text=text,
        publication_kind=publication_kind,
        internal_numbers=(),
        facts=(),
        visual_regions=(),
        evidence=(),
    )


def body(
    number: str,
    text: str,
    *,
    publication_kind: str = "drawing",
    mention: str | None = None,
) -> BodyDrawingEvidencePacket:
    mention_id = mention or f"caption-{publication_kind}-{number}"
    return BodyDrawingEvidencePacket(
        publication_kind=publication_kind,
        number=number,
        raw_texts=(text,),
        source_node_ids=(mention_id,),
        source_sha256="body-sha",
        document_version_id="version-1",
        physical_page=1,
        source_bbox=None,
        visual_regions=(),
    )


def test_feature_pair_contradiction_is_removed_but_missing_feature_is_kept():
    generator = DrawingCandidateGeneratorV3()
    source = source_packet("2지점 조선시대 1호 토광묘 평단면")

    rows = generator.generate(
        source,
        [
            body("51", "2지점 조선시대 2호 토광묘 평단면"),
            body("52", "2지점 조선시대 1호 토광묘 평단면"),
            body("53", "2지점 평단면"),
        ],
    )

    assert "51" not in [row.number for row in rows]
    assert rows[0].number == "52"
    assert "53" in [row.number for row in rows]


def test_explicit_publication_kind_and_site_contradictions_are_hard_filters():
    generator = DrawingCandidateGeneratorV3()
    source = source_packet("도면 7. 2지점 S1 E1 유구현황도")

    rows = generator.generate(
        source,
        [
            body("7", "삽도 7. 2지점 S1 E1 유구현황도", publication_kind="illustration"),
            body("8", "도면 8. 3지점 S1 E1 유구현황도"),
            body("9", "도면 9. 2지점 S1 E1 유구현황도"),
        ],
    )

    assert [row.number for row in rows] == ["9"]


def test_top10_keeps_best_semantic_target_and_top20_is_duplicate_free_superset():
    generator = DrawingCandidateGeneratorV3()
    source = source_packet("2지점 조선시대 1호 토광묘 평단면 A-A'")
    bodies = [body(str(index), f"2지점 도면 {index} 일반 현황도") for index in range(1, 26)]
    bodies[17] = body("18", "2지점 조선시대 1호 토광묘 평단면 A-A'")

    top10 = generator.generate(source, bodies, limit=10)
    top20 = generator.expand(
        source,
        bodies,
        existing_candidate_ids={row.candidate_id for row in top10},
        limit=20,
    )

    top10_ids = {row.candidate_id for row in top10}
    top20_ids = [row.candidate_id for row in top20]
    assert any(row.number == "18" for row in top10)
    assert top10_ids <= set(top20_ids)
    assert len(top20_ids) == len(set(top20_ids))
    assert len(top20_ids) <= 20


def test_filename_and_sequence_signals_are_marked_weak():
    generator = DrawingCandidateGeneratorV3()
    source = source_packet(
        "조선시대 평단면",
        original_name="도면 52.ai",
        source_path="2지점/도면 52.ai",
    )

    rows = generator.generate(
        source,
        [
            body("51", "조선시대 평단면"),
            body("52", "조선시대 평단면"),
        ],
    )

    filename_evidence = [
        evidence
        for row in rows
        for evidence in row.evidence
        if evidence.method in {"filename_identity", "sequence_neighbor", "path_site_point"}
    ]
    assert filename_evidence
    assert all(evidence.weak for evidence in filename_evidence)
