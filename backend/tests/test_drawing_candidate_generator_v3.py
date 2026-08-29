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


def test_strong_period_contradiction_marks_candidate_hard():
    generator = DrawingCandidateGeneratorV3()
    source = source_packet("조선시대 평단면")

    rows = generator.generate(source, [body("35", "고려시대 평단면")])

    assert len(rows) == 1
    assert rows[0].strong_contradiction_ids
    assert rows[0].hard_contradiction is True


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


def test_sparse_ai_text_uses_semantic_filename_only_to_retrieve_correct_target():
    generator = DrawingCandidateGeneratorV3()
    filename = "【도면  】1지점 고려시대 1호 석곽묘 평·입단면도 및 출토유물.ai"
    source = source_packet(
        "",
        original_name=filename,
        source_path=f"본문 도면/1지점/{filename}",
    )
    distractors = [
        body(str(number), "1지점 고려시대 1호 옹관묘 평·입단면도 및 출토유물")
        for number in range(21, 31)
    ]
    correct = body("35", "1지점 고려시대 1호 석곽묘 평·입단면도 및 출토유물")

    rows = generator.generate(source, [*distractors, correct], limit=10)

    assert any(row.number == "35" for row in rows)
    correct_row = next(row for row in rows if row.number == "35")
    filename_semantic = [
        evidence
        for evidence in correct_row.evidence
        if evidence.method.startswith("filename_semantic_")
    ]
    assert filename_semantic
    assert all(evidence.weak for evidence in filename_semantic)


def test_filename_exact_feature_number_conflict_keeps_candidate_but_vetoes_auto():
    generator = DrawingCandidateGeneratorV3()
    filename = "5지점 조선시대 4호 토광묘 평·단면도 및 출토유물.ai"
    source = source_packet(
        "",
        original_name=filename,
        source_path=f"본문 도면/5지점/{filename}",
    )

    rows = generator.generate(
        source,
        [
            body("119", "5지점 조선시대 3호 토광묘 평·단면도 및 출토유물"),
            body("120", "5지점 조선시대 4호 토광묘 평·단면도 및 출토유물"),
        ],
    )

    wrong = next(row for row in rows if row.number == "119")
    correct = next(row for row in rows if row.number == "120")

    # Filename semantics remain retrieval hints: the conflicting candidate stays
    # available to Luna/review, but an explicit same-type feature-number clash
    # must prevent unattended AUTO promotion.
    assert wrong.hard_contradiction is True
    assert any(
        evidence.method == "strong_contradiction_filename_feature_pair"
        and not evidence.supports
        for evidence in wrong.evidence
    )
    assert correct.hard_contradiction is False


def test_explicit_feature_pairs_do_not_invent_cross_type_number_matches():
    generator = DrawingCandidateGeneratorV3()
    source = source_packet("3호 토광묘와 4호 석곽묘 평단면")

    rows = generator.generate(
        source,
        [body("70", "3호 토광묘와 4호 토광묘 평단면")],
    )

    assert len(rows) == 1
    feature_pair_values = {
        evidence.value
        for evidence in rows[0].evidence
        if evidence.method == "exact_feature_pair"
    }
    assert feature_pair_values == {"토광묘:3"}


def test_neighboring_context_cannot_create_hard_feature_match_for_anchor():
    generator = DrawingCandidateGeneratorV3()
    source = source_packet("4호 석곽묘 평단면")

    rows = generator.generate(
        source,
        [body("70", "도면 70. 3호 토광묘 평단면\n4호 석곽묘 평단면")],
    )

    assert rows == ()


def test_multiple_source_feature_pairs_are_context_and_do_not_hard_filter_target():
    generator = DrawingCandidateGeneratorV3()
    source = source_packet(
        "2지점 조선시대 25호 토광묘 및 26호 토광묘 평·단면도 및 출토유물",
        original_name="도면 54.ai",
        source_path="본문 도면/2지점/도면 54.ai",
    )

    rows = generator.generate(
        source,
        [
            body("54", "2지점 조선시대 2호 토광묘 평·단면도 및 출토유물"),
        ],
    )

    assert rows
    assert rows[0].number == "54"


def test_semantic_filename_map_type_retrieves_confirmed_map_before_contextual_labels():
    generator = DrawingCandidateGeneratorV3()
    source = source_packet(
        "1지점",
        original_name="도면17. 1지점-유구현황도(15-22)800.ai",
        source_path="환경 도면/도면17. 1지점-유구현황도(15-22)800.ai",
    )
    distractors = [
        body(
            str(number),
            "1지점 조선시대 1호 토광묘 평·단면도",
        )
        for number in range(1, 13)
    ]
    target = body("23", "1지점 유구현황도(S=1/800)")

    rows = generator.generate(source, [*distractors, target], limit=10)

    assert any((row.publication_kind, row.number) == ("drawing", "23") for row in rows)
    target = next(row for row in rows if row.number == "23")
    map_evidence = [
        evidence
        for evidence in target.evidence
        if evidence.method == "filename_semantic_exact_map_type"
    ]
    assert map_evidence
    assert all(evidence.weak for evidence in map_evidence)


def test_illustration_panel_filename_uses_parent_identity_for_retrieval():
    generator = DrawingCandidateGeneratorV3()
    source = source_packet(
        "",
        publication_kind=None,
        original_name="삽도2-1. 항공지도-1968(15-10).ai",
        source_path="환경 도면/삽도2-1. 항공지도-1968(15-10).ai",
    )
    bodies = [
        body(str(number), f"도면 {number}. 일반 도면")
        for number in range(1, 21)
    ]
    bodies.append(
        body(
            "2",
            "삽도 2. 조사 지역 일대 연도별 항공사진",
            publication_kind="illustration",
        )
    )

    rows = generator.generate(source, bodies, limit=10)

    assert rows
    assert (rows[0].publication_kind, rows[0].number) == ("illustration", "2")
    identity_evidence = [
        evidence for evidence in rows[0].evidence if evidence.method == "filename_identity"
    ]
    assert identity_evidence
    assert all(evidence.weak for evidence in identity_evidence)
