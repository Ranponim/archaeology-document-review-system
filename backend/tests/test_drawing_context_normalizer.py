from app.services.drawing_context_normalizer import DrawingContextNormalizer


def test_normalizes_archaeology_context_entities_without_inventing_numeric_facts():
    normalizer = DrawingContextNormalizer()

    context = normalizer.normalize(
        "도면 14. 2지점 S1 E1 북동 토층, 4호 수혈 A-A' 단면",
        source_kind="body",
        source_node_id="caption-14",
        source_sha256="abc",
    )

    facts = {(fact.kind, fact.normalized_value) for fact in context.facts}
    assert ("point", "2") in facts
    assert ("grid", "S1E1") in facts
    assert ("direction", "북동") in facts
    assert ("drawing_type", "토층") in facts
    assert ("drawing_type", "단면") in facts
    assert ("feature", "4호:수혈") in facts
    assert ("section_label", "A-A'") in facts
    assert all(fact.source_kind == "body" for fact in context.facts)
    assert all(fact.source_node_id == "caption-14" for fact in context.facts)
    assert all(fact.source_sha256 == "abc" for fact in context.facts)


def test_normalizes_spacing_and_case_for_grid_and_tokens():
    normalizer = DrawingContextNormalizer()

    context = normalizer.normalize(
        "  제2지점   s1  e1  북동쪽   토층도  ",
        source_kind="drawing_ai",
    )

    facts = {(fact.kind, fact.normalized_value) for fact in context.facts}
    assert ("point", "2") in facts
    assert ("grid", "S1E1") in facts
    assert ("direction", "북동") in facts
    assert ("drawing_type", "토층") in facts
    assert "S1E1" in context.tokens


def test_does_not_treat_unrelated_year_or_page_numbers_as_context_entities():
    normalizer = DrawingContextNormalizer()

    context = normalizer.normalize(
        "1968년 조사보고서 115집 25페이지 참고",
        source_kind="body",
    )

    assert not [fact for fact in context.facts if fact.kind in {"point", "grid", "feature"}]
