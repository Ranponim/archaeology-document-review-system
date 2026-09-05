from app.domain.canonical_models import EvidenceLevel
from app.domain.drawing_evidence import BodyDrawingContext, DrawingSourceObservation
from app.services.drawing_evidence_graph_resolver import DrawingEvidenceGraphResolver


def body(number: str, text: str) -> BodyDrawingContext:
    return BodyDrawingContext(
        number=number,
        raw_texts=(text,),
        source_node_ids=(f"caption-{number}",),
    )


def source(source_id: str, name: str, text: str = "", internal_numbers=()) -> DrawingSourceObservation:
    return DrawingSourceObservation(
        source_asset_id=source_id,
        source_sha256=f"sha-{source_id}",
        original_name=name,
        raw_text=text,
        internal_numbers=tuple(internal_numbers),
    )


def candidate_for(result, source_id: str, number: str):
    return next(
        item
        for item in result.candidates
        if item.source_asset_id == source_id and item.candidate_number == number
    )


def test_explicit_internal_identifier_remains_direct_and_locked():
    resolver = DrawingEvidenceGraphResolver()
    result = resolver.resolve_observations(
        corpus_id="c1",
        observations=[source("ai1", "도면99.ai", "2지점 S1 E1 북동 토층", ("14",))],
        body_contexts=[body("14", "도면 14 2지점 S1 E1 북동 토층")],
    )

    assert len(result.canonical_drawings) == 1
    drawing = result.canonical_drawings[0]
    assert drawing.number == "14"
    assert drawing.source_asset_id == "ai1"
    assert drawing.evidence_level == EvidenceLevel.DIRECT
    assert candidate_for(result, "ai1", "14").evidence_level == EvidenceLevel.DIRECT


def test_filename_only_candidate_stays_heuristic_and_is_not_canonical():
    resolver = DrawingEvidenceGraphResolver()
    result = resolver.resolve_observations(
        corpus_id="c1",
        observations=[source("ai1", "도면14.ai")],
        body_contexts=[body("14", "도면 14")],
    )

    candidate = candidate_for(result, "ai1", "14")
    assert candidate.evidence_level == EvidenceLevel.HEURISTIC
    assert result.canonical_drawings == ()


def test_filename_plus_independent_body_and_semantic_evidence_promotes_verified():
    resolver = DrawingEvidenceGraphResolver()
    result = resolver.resolve_observations(
        corpus_id="c1",
        observations=[source("ai1", "도면14. 2지점 S1E1 북동 토층.ai", "2지점 S1 E1 북동 토층 A-A' 단면")],
        body_contexts=[
            body("14", "도면 14. 2지점 S1 E1 북동 토층 A-A' 단면"),
            body("15", "도면 15. 3지점 N1 W1 남서 평면"),
        ],
    )

    candidate = candidate_for(result, "ai1", "14")
    assert candidate.evidence_level == EvidenceLevel.DERIVED_VERIFIED
    assert set(candidate.evidence_families) >= {"identity", "body_context", "semantic_content"}
    assert candidate.margin >= resolver.minimum_margin
    assert [drawing.number for drawing in result.canonical_drawings] == ["14"]
    assert result.canonical_drawings[0].evidence_level == EvidenceLevel.DERIVED_VERIFIED


def test_point_or_grid_contradiction_blocks_filename_promotion():
    resolver = DrawingEvidenceGraphResolver()
    result = resolver.resolve_observations(
        corpus_id="c1",
        observations=[source("ai1", "도면14.ai", "2지점 S1 E1 북동 토층")],
        body_contexts=[body("14", "도면 14. 3지점 S2 E2 북동 토층")],
    )

    candidate = candidate_for(result, "ai1", "14")
    assert candidate.has_hard_contradiction is True
    assert candidate.evidence_level != EvidenceLevel.DERIVED_VERIFIED
    assert result.canonical_drawings == ()


def test_near_tie_content_candidates_remain_ambiguous():
    resolver = DrawingEvidenceGraphResolver()
    result = resolver.resolve_observations(
        corpus_id="c1",
        observations=[source("ai1", "unknown.ai", "북동 토층 단면")],
        body_contexts=[
            body("14", "도면 14 북동 토층 단면"),
            body("15", "도면 15 북동 토층 단면"),
        ],
    )

    assert "ai1" in result.ambiguous_source_ids
    assert result.canonical_drawings == ()


def test_global_assignment_allows_at_most_one_ai_per_canonical_drawing():
    resolver = DrawingEvidenceGraphResolver()
    result = resolver.resolve_observations(
        corpus_id="c1",
        observations=[
            source("strong", "도면14.ai", "2지점 S1 E1 북동 토층 A-A' 단면"),
            source("weak", "도면14.ai", "2지점 S1 E1 북동 토층"),
        ],
        body_contexts=[body("14", "도면 14 2지점 S1 E1 북동 토층 A-A' 단면")],
    )

    assert len([drawing for drawing in result.canonical_drawings if drawing.number == "14"]) == 1
    assert result.canonical_drawings[0].source_asset_id == "strong"
    assert "weak" in result.ambiguous_source_ids or "weak" in result.unresolved_source_ids


def test_blinded_mode_does_not_use_filename_number_as_evidence():
    resolver = DrawingEvidenceGraphResolver()
    result = resolver.resolve_observations(
        corpus_id="c1",
        observations=[source("ai1", "도면14.ai", "3지점 N1 W1 남서 평면")],
        body_contexts=[
            body("14", "도면 14 2지점 S1 E1 북동 토층"),
            body("27", "도면 27 3지점 N1 W1 남서 평면"),
        ],
        include_filename_evidence=False,
    )

    numbers = {candidate.candidate_number for candidate in result.candidates if candidate.source_asset_id == "ai1"}
    assert "27" in numbers
    assert "14" not in numbers
