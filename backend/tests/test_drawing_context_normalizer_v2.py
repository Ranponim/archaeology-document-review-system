from app.services.drawing_context_normalizer import DrawingContextNormalizer


def facts(context):
    return {(fact.kind, fact.normalized_value) for fact in context.facts}


def test_v2_extracts_drawing_kind_and_structured_archaeology_signature():
    context = DrawingContextNormalizer().normalize(
        "도면 44. 3지점 조선시대 2호 토광묘 평·단면도 및 출토유물 A-A'",
        source_kind="body",
        source_node_id="caption-44",
    )

    assert context.publication_kind == "drawing"
    values = facts(context)
    assert ("site_point", "3") in values
    assert ("period", "조선시대") in values
    assert ("feature_type", "토광묘") in values
    assert ("feature_number", "2") in values
    assert ("drawing_type", "평단면") in values
    assert ("content_type", "출토유물") in values
    assert ("section_label", "A-A'") in values


def test_v2_extracts_illustration_map_signature_and_contextual_year():
    context = DrawingContextNormalizer().normalize(
        "삽도 2-1. 항공지도 1968",
        source_kind="drawing_ai",
    )

    assert context.publication_kind == "illustration"
    values = facts(context)
    assert ("map_type", "항공지도") in values
    assert ("year", "1968") in values


def test_v2_does_not_promote_generic_year_without_map_context():
    context = DrawingContextNormalizer().normalize(
        "1968년 조사보고서 115집",
        source_kind="body",
    )
    assert not [fact for fact in context.facts if fact.kind == "year"]


def test_v2_preserves_legacy_point_and_feature_facts_for_v1():
    context = DrawingContextNormalizer().normalize(
        "2지점 4호 수혈",
        source_kind="body",
    )
    values = facts(context)
    assert ("point", "2") in values
    assert ("feature", "4호:수혈") in values
