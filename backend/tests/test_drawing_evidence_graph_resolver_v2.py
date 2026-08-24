from app.domain.canonical_models import EvidenceLevel
from app.domain.drawing_evidence import BodyDrawingContext, DrawingSourceObservation
from app.services.drawing_evidence_graph_resolver_v2 import DrawingEvidenceGraphResolverV2


def body(number, text, *, kind="drawing", ids=("m1",)):
    return BodyDrawingContext(
        number=str(number),
        raw_texts=(text,) if isinstance(text, str) else tuple(text),
        source_node_ids=ids,
        mention_context_ids=ids,
        publication_kind=kind,
    )


def obs(source_id, name, text="", *, internal=(), kind=None, path=""):
    return DrawingSourceObservation(
        source_asset_id=source_id,
        source_sha256=f"sha-{source_id}",
        original_name=name,
        raw_text=text,
        internal_numbers=tuple(internal),
        publication_kind=kind,
        source_path=path,
    )


def test_v2_separates_drawing_and_illustration_identity_spaces():
    resolver = DrawingEvidenceGraphResolverV2()
    result = resolver.resolve_observations(
        corpus_id="c1",
        observations=[
            obs("d3", "도면3.ai", "도면 3", internal=("3",), kind="drawing"),
            obs("i3", "삽도3.ai", "삽도 3", internal=("3",), kind="illustration"),
        ],
        body_contexts=[
            body("3", "도면 3. 2지점 현황도", kind="drawing", ids=("dm3",)),
            body("3", "삽도 3. 2지점 그리드", kind="illustration", ids=("im3",)),
        ],
    )

    assert {(d.publication_kind, d.number) for d in result.canonical_drawings} == {
        ("drawing", "3"),
        ("illustration", "3"),
    }
    assert result.diagnostics["kindCollisionCount"] == 0


def test_v2_uses_consensus_not_unconditional_union_for_structured_match():
    resolver = DrawingEvidenceGraphResolverV2()
    result = resolver.resolve_observations(
        corpus_id="c1",
        observations=[obs("a44", "도면44.ai", "3지점 조선시대 2호 토광묘 평단면도 출토유물")],
        body_contexts=[
            body(
                "44",
                (
                    "도면 44. 3지점 조선시대 2호 토광묘 평단면도",
                    "3지점 조선시대 2호 토광묘 출토유물",
                    "인접 문단 1지점 청동기시대 수혈",
                ),
                ids=("m44a", "m44b", "neighbor"),
            )
        ],
        include_filename_evidence=False,
    )

    assert [(d.number, d.evidence_level) for d in result.canonical_drawings] == [
        ("44", EvidenceLevel.DERIVED_VERIFIED)
    ]
    consensus = [
        fact for fact in result.context_facts
        if fact.consensus_status == "consensus" and fact.normalized_value in {"3", "조선시대", "토광묘", "2"}
    ]
    assert consensus
    assert not [
        fact for fact in result.context_facts
        if fact.consensus_status == "consensus" and fact.normalized_value in {"1", "청동기시대", "수혈"}
    ]


def test_v2_rejects_feature_number_pair_hard_contradiction():
    result = DrawingEvidenceGraphResolverV2().resolve_observations(
        corpus_id="c1",
        observations=[obs("a", "도면44.ai", "3지점 조선시대 1호 토광묘 평단면도")],
        body_contexts=[body("44", "도면 44. 3지점 조선시대 2호 토광묘 평단면도")],
        include_filename_evidence=False,
    )
    assert not result.canonical_drawings
    assert any(candidate.has_hard_contradiction for candidate in result.candidates)
    assert result.diagnostics["hardContradictionPromotedCount"] == 0


def test_v2_period_mismatch_is_strong_contradiction_and_not_promoted():
    result = DrawingEvidenceGraphResolverV2().resolve_observations(
        corpus_id="c1",
        observations=[obs("a", "도면44.ai", "3지점 고려시대 2호 토광묘 평단면도")],
        body_contexts=[body("44", "도면 44. 3지점 조선시대 2호 토광묘 평단면도")],
        include_filename_evidence=False,
    )
    assert not result.canonical_drawings
    assert any(candidate.has_strong_contradiction for candidate in result.candidates)


def test_v2_filename_and_path_are_tie_breakers_only_and_cannot_promote():
    result = DrawingEvidenceGraphResolverV2().resolve_observations(
        corpus_id="c1",
        observations=[obs("a", "도면44.ai", "", path="본문 도면/3지점/도면44.ai")],
        body_contexts=[body("44", "도면 44. 3지점 조선시대 2호 토광묘 평단면도")],
    )
    assert not result.canonical_drawings
    assert result.diagnostics["filenameOnlyVerifiedCount"] == 0


def test_v2_filename_kind_does_not_create_hard_kind_contradiction():
    result = DrawingEvidenceGraphResolverV2().resolve_observations(
        corpus_id="c1",
        observations=[
            obs(
                "a",
                "삽도44.ai",
                "3지점 조선시대 2호 토광묘 평단면도 출토유물",
            )
        ],
        body_contexts=[
            body("44", "도면 44. 3지점 조선시대 2호 토광묘 평단면도 출토유물")
        ],
        include_filename_evidence=True,
    )

    drawing_candidate = next(
        candidate
        for candidate in result.candidates
        if candidate.publication_kind == "drawing" and candidate.candidate_number == "44"
    )
    assert drawing_candidate.has_hard_contradiction is False


def test_v2_global_assignment_allows_same_number_in_different_kinds():
    result = DrawingEvidenceGraphResolverV2().resolve_observations(
        corpus_id="c1",
        observations=[
            obs("d", "도면7.ai", "도면 7", internal=("7",), kind="drawing"),
            obs("i", "삽도7.ai", "삽도 7", internal=("7",), kind="illustration"),
        ],
        body_contexts=[
            body("7", "도면 7. 유구현황도", kind="drawing", ids=("d7",)),
            body("7", "삽도 7. 위치도", kind="illustration", ids=("i7",)),
        ],
    )
    assert len(result.canonical_drawings) == 2
    assert len({drawing.drawing_id for drawing in result.canonical_drawings}) == 2
