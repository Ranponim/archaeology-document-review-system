from app.domain.canonical_models import (
    ArchaeologyObject,
    ArchaeologyObjectData,
    ObjectResolutionResult,
    ResolutionResult,
)
from app.domain.document_structure import CaptionData, TextBlockData
from app.services.object_resolver import (
    ExtractedMention,
    ObjectResolver,
)


def test_domain_model_and_type_aliases():
    assert ArchaeologyObject is ArchaeologyObjectData
    assert ResolutionResult is ObjectResolutionResult


def test_alias_normalization_bronze_age():
    # '1지점 청동기시대 6호 석관묘' and '1지점 청동기 6호 석관묘' must resolve to the same canonical object
    resolver = ObjectResolver()
    blocks = [
        TextBlockData(
            block_id="b1",
            text="1지점 청동기시대 6호 석관묘는 구릉 남사면에 위치한다.",
            normalized_text="1지점 청동기시대 6호 석관묘는 구릉 남사면에 위치한다.",
            order=1,
        ),
        TextBlockData(
            block_id="b2",
            text="1지점 청동기 6호 석관묘 내부에서 마제석검 1점이 출토되었다.",
            normalized_text="1지점 청동기 6호 석관묘 내부에서 마제석검 1점이 출토되었다.",
            order=2,
        ),
    ]

    results = resolver.resolve_mentions(blocks=blocks)

    # Both mentions merge into the single canonical object
    stone_cists = [r for r in results if r.object_data.type == "석관묘"]
    assert len(stone_cists) == 1
    res = stone_cists[0]
    assert res.object_data.canonical_name == "1지점 청동기시대 6호 석관묘"
    assert res.object_data.point == "1지점"
    assert res.object_data.period == "청동기시대"
    assert res.object_data.number == "6호"
    assert res.object_data.type == "석관묘"
    assert set(res.source_block_ids) == {"b1", "b2"}
    assert set(res.object_data.source_block_ids) == {"b1", "b2"}
    assert res.status == "candidate"
    assert res.confidence == 1.0


def test_multi_attribute_extraction_with_explicit_site():
    resolver = ObjectResolver()
    blocks = [
        TextBlockData(
            block_id="b_site",
            text="논산 산노리 산17-1번지 1지점 청동기시대 6호 석관묘 발굴조사 결과",
            normalized_text="논산 산노리 산17-1번지 1지점 청동기시대 6호 석관묘 발굴조사 결과",
            order=1,
        )
    ]

    results = resolver.resolve_mentions(blocks=blocks)
    assert len(results) >= 1
    res = results[0]
    assert res.object_data.site == "논산 산노리 산17-1번지"
    assert res.object_data.point == "1지점"
    assert res.object_data.period == "청동기시대"
    assert res.object_data.number == "6호"
    assert res.object_data.type == "석관묘"
    assert res.object_data.canonical_name == "1지점 청동기시대 6호 석관묘"
    assert res.source_block_ids == ["b_site"]


def test_period_synonym_normalizations():
    resolver = ObjectResolver()
    period_cases = [
        ("1지점 구석기 1호 유구", "구석기시대", "1지점 구석기시대 1호 유구"),
        ("1지점 구석기시대 1호 유구", "구석기시대", "1지점 구석기시대 1호 유구"),
        ("1지점 신석기 2호 주거지", "신석기시대", "1지점 신석기시대 2호 주거지"),
        ("1지점 신석기시대 2호 주거지", "신석기시대", "1지점 신석기시대 2호 주거지"),
        ("1지점 청동기 3호 석관묘", "청동기시대", "1지점 청동기시대 3호 석관묘"),
        ("1지점 청동기시대 3호 석관묘", "청동기시대", "1지점 청동기시대 3호 석관묘"),
        ("1지점 초기철기 4호 토광묘", "초기철기시대", "1지점 초기철기시대 4호 토광묘"),
        ("1지점 철기 4호 토광묘", "초기철기시대", "1지점 초기철기시대 4호 토광묘"),
        ("1지점 원삼국 5호 주거지", "원삼국시대", "1지점 원삼국시대 5호 주거지"),
        ("1지점 삼국 6호 고분", "삼국시대", "1지점 삼국시대 6호 고분"),
        ("1지점 백제 7호 석실묘", "백제", "1지점 백제 7호 석실묘"),
        ("1지점 통일신라 8호 수혈유구", "통일신라", "1지점 통일신라 8호 수혈유구"),
        ("1지점 고려 9호 건물지", "고려시대", "1지점 고려시대 9호 건물지"),
        ("1지점 조선 10호 토광묘", "조선시대", "1지점 조선시대 10호 토광묘"),
        ("1지점 조선시대 10호 토광묘", "조선시대", "1지점 조선시대 10호 토광묘"),
        ("1지점 시대미상 11호 수혈유구", "시대미상", "1지점 시대미상 11호 수혈유구"),
    ]

    for text, expected_period, expected_canonical in period_cases:
        block = TextBlockData(
            block_id="b_test",
            text=text,
            normalized_text=text,
            order=1,
        )
        results = resolver.resolve_mentions(blocks=[block])
        assert len(results) >= 1, f"Failed to extract for: {text}"
        res = results[0]
        assert res.object_data.period == expected_period, f"Failed period for: {text}"
        assert (
            res.object_data.canonical_name == expected_canonical
        ), f"Failed canonical name for: {text}"


def test_isolated_mention_without_point_and_period_marked_semantic_review():
    resolver = ObjectResolver()
    blocks = [
        TextBlockData(
            block_id="b_iso",
            text="2호 토광묘 바닥면은 정지되어 있었다.",
            normalized_text="2호 토광묘 바닥면은 정지되어 있었다.",
            order=1,
        )
    ]

    results = resolver.resolve_mentions(blocks=blocks)
    assert len(results) == 1
    res = results[0]
    assert res.object_data.number == "2호"
    assert res.object_data.type == "토광묘"
    assert res.object_data.point == ""
    assert res.object_data.period == ""
    assert res.object_data.canonical_name == "2호 토광묘"
    # Ambiguity safety rule: isolated mention without point/period must be marked semantic_review
    assert res.status == "semantic_review"
    assert res.confidence <= 0.7
    assert res.source_block_ids == ["b_iso"]


def test_ambiguity_safety_prevents_unsafe_merging_in_multi_period_point_document():
    resolver = ObjectResolver()
    blocks = [
        TextBlockData(
            block_id="b1",
            text="2지점 조선시대 2호 토광묘는 양호하게 잔존한다.",
            normalized_text="2지점 조선시대 2호 토광묘는 양호하게 잔존한다.",
            order=1,
        ),
        TextBlockData(
            block_id="b2",
            text="2지점 시대미상 2호 토광묘 내부를 조사하였다.",
            normalized_text="2지점 시대미상 2호 토광묘 내부를 조사하였다.",
            order=2,
        ),
        TextBlockData(
            block_id="b3",
            text="2호 토광묘의 바닥면에서 목탄 흔적이 확인된다.",
            normalized_text="2호 토광묘의 바닥면에서 목탄 흔적이 확인된다.",
            order=3,
        ),
    ]

    results = resolver.resolve_mentions(blocks=blocks)

    # Must produce 3 results, not falsely merging b3 into b1 or b2
    canonical_names = [r.object_data.canonical_name for r in results]
    assert "2지점 조선시대 2호 토광묘" in canonical_names
    assert "2지점 시대미상 2호 토광묘" in canonical_names
    assert "2호 토광묘" in canonical_names

    res_b1 = next(
        r for r in results if r.object_data.canonical_name == "2지점 조선시대 2호 토광묘"
    )
    res_b2 = next(
        r for r in results if r.object_data.canonical_name == "2지점 시대미상 2호 토광묘"
    )
    res_b3 = next(r for r in results if r.object_data.canonical_name == "2호 토광묘")

    assert res_b1.source_block_ids == ["b1"]
    assert res_b1.status == "candidate"
    assert res_b1.confidence == 1.0

    assert res_b2.source_block_ids == ["b2"]
    assert res_b2.status == "candidate"
    assert res_b2.confidence == 1.0

    # b3 is ambiguous between the two 2호 토광묘 entities
    assert res_b3.source_block_ids == ["b3"]
    assert res_b3.status == "semantic_review"
    assert res_b3.confidence <= 0.7


def test_captions_and_blocks_co_resolution():
    resolver = ObjectResolver()
    blocks = [
        TextBlockData(
            block_id="p12_b1",
            text="1지점 청동기 6호 석관묘 내부 구조",
            normalized_text="1지점 청동기 6호 석관묘 내부 구조",
            order=1,
            source_sha256="sha_p12",
        )
    ]
    captions = [
        CaptionData(
            caption_id="p12_c1",
            raw_text="【도판 15】 1지점 청동기시대 6호 석관묘 전경",
            plate_number="15",
            source_sha256="sha_p12",
        )
    ]

    results = resolver.resolve_mentions(blocks=blocks, captions=captions)

    stone_cists = [
        r
        for r in results
        if r.object_data.canonical_name == "1지점 청동기시대 6호 석관묘"
    ]
    assert len(stone_cists) == 1
    res = stone_cists[0]
    assert set(res.source_block_ids) == {"p12_b1", "p12_c1"}
    assert set(res.object_data.source_block_ids) == {"p12_b1", "p12_c1"}
    assert res.object_data.source_sha256 == "sha_p12"
    assert res.status == "candidate"


def test_empty_and_noise_blocks_return_empty_list():
    resolver = ObjectResolver()
    blocks = [
        TextBlockData(
            block_id="b_noise1",
            text="조사 대상 지역은 완만한 구릉 지형을 형성하고 있다.",
            normalized_text="조사 대상 지역은 완만한 구릉 지형을 형성하고 있다.",
            order=1,
        ),
        TextBlockData(
            block_id="b_noise2",
            text="2 | 백제문화유산연구원",
            normalized_text="2 | 백제문화유산연구원",
            order=2,
        ),
    ]

    results = resolver.resolve_mentions(blocks=blocks, captions=[])
    assert results == []


def test_multiple_mentions_in_single_block():
    resolver = ObjectResolver()
    blocks = [
        TextBlockData(
            block_id="b_multi",
            text="1지점 청동기시대 1호 주거지와 1지점 청동기시대 2호 주거지가 인접하여 분포한다.",
            normalized_text="1지점 청동기시대 1호 주거지와 1지점 청동기시대 2호 주거지가 인접하여 분포한다.",
            order=1,
        )
    ]

    results = resolver.resolve_mentions(blocks=blocks)
    names = [r.object_data.canonical_name for r in results]
    assert "1지점 청동기시대 1호 주거지" in names
    assert "1지점 청동기시대 2호 주거지" in names
    assert len(results) == 2
    for r in results:
        assert r.source_block_ids == ["b_multi"]


def test_point_and_number_variations():
    resolver = ObjectResolver()
    text = "1 지점 제6호 석관묘 및 2구역 35번 토광묘 조사"
    block = TextBlockData(
        block_id="b_var",
        text=text,
        normalized_text=text,
        order=1,
    )
    results = resolver.resolve_mentions(blocks=[block])
    names = [r.object_data.canonical_name for r in results]
    assert "1지점 6호 석관묘" in names
    assert "2구역 35번 토광묘" in names


def test_deterministic_object_ids():
    resolver = ObjectResolver()
    block = TextBlockData(
        block_id="b1",
        text="1지점 청동기시대 6호 석관묘",
        normalized_text="1지점 청동기시대 6호 석관묘",
        order=1,
    )
    res1 = resolver.resolve_mentions(blocks=[block], project_id="proj_1", site="논산")
    res2 = resolver.resolve_mentions(blocks=[block], project_id="proj_1", site="논산")

    assert res1[0].object_data.object_id == res2[0].object_data.object_id
    assert res1[0].object_data.object_id.startswith("obj_")


def test_artifact_types_extraction():
    resolver = ObjectResolver()
    types_text = "1지점 1호 찍개, 1지점 2호 긁개, 1지점 3호 홈날, 1지점 4호 공이"
    block = TextBlockData(
        block_id="b_art",
        text=types_text,
        normalized_text=types_text,
        order=1,
    )
    results = resolver.resolve_mentions(blocks=[block])
    types_found = {r.object_data.type for r in results}
    assert {"찍개", "긁개", "홈날", "공이"}.issubset(types_found)


def test_reverse_token_ordering_normalizes_to_same_canonical_name():
    resolver = ObjectResolver()
    # '청동기시대 1지점 6호 석관묘' vs '1지점 청동기시대 6호 석관묘'
    b1 = TextBlockData(
        block_id="b_ord1",
        text="청동기시대 1지점 6호 석관묘",
        normalized_text="청동기시대 1지점 6호 석관묘",
        order=1,
    )
    b2 = TextBlockData(
        block_id="b_ord2",
        text="1지점 청동기시대 6호 석관묘",
        normalized_text="1지점 청동기시대 6호 석관묘",
        order=2,
    )
    results = resolver.resolve_mentions(blocks=[b1, b2])
    assert len(results) == 1
    assert results[0].object_data.canonical_name == "1지점 청동기시대 6호 석관묘"
    assert set(results[0].source_block_ids) == {"b_ord1", "b_ord2"}


def test_normalization_helper_functions():
    assert ObjectResolver.normalize_period("청동기") == "청동기시대"
    assert ObjectResolver.normalize_period("조선") == "조선시대"
    assert ObjectResolver.normalize_point("1  지점") == "1지점"
    assert ObjectResolver.normalize_number("제 6 호") == "6호"
    assert ObjectResolver.normalize_number("No. 12") == "12호"
    assert ObjectResolver.normalize_type(" 석관묘 ") == "석관묘"
    assert (
        ObjectResolver.build_canonical_name("1지점", "청동기시대", "6호", "석관묘")
        == "1지점 청동기시대 6호 석관묘"
    )
