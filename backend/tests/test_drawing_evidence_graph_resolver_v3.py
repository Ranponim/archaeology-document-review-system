from dataclasses import replace

import pytest

from app.domain.drawing_evidence_v3 import (
    BodyDrawingEvidencePacket,
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
)
from app.services.codex_drawing_resolver_client import CodexDrawingDecisionError
from app.services.drawing_evidence_resolver_v3 import DrawingEvidenceResolverV3


def evidence(eid: str, family: str, *, weak: bool = False) -> DrawingV3Evidence:
    return DrawingV3Evidence(
        id=eid,
        family=family,
        method="test",
        value=eid,
        weak=weak,
    )


def source(asset_id: str = "asset-1", *, internal_numbers=()) -> DrawingSourceEvidencePacket:
    return DrawingSourceEvidencePacket(
        source_asset_id=asset_id,
        source_sha256=f"sha-{asset_id}",
        original_name=f"{asset_id}.ai",
        source_path=f"site/{asset_id}.ai",
        raw_text="2지점 1호 토광묘",
        publication_kind="drawing",
        internal_numbers=tuple(internal_numbers),
        facts=(),
        visual_regions=(),
        evidence=(evidence(f"ev:{asset_id}:source", "source_signature"),),
    )


def candidate(
    source_asset_id: str = "asset-1",
    *,
    number: str = "52",
    hard: bool = False,
    weak_only: bool = False,
) -> DrawingCandidatePacket:
    support = (
        evidence(
            f"ev:{source_asset_id}:{number}:site",
            "spatial_signature",
            weak=weak_only,
        ),
        evidence(
            f"ev:{source_asset_id}:{number}:feature",
            "archaeology_signature",
            weak=weak_only,
        ),
    )
    return DrawingCandidatePacket(
        candidate_id=f"candidate:{source_asset_id}:drawing:{number}",
        publication_kind="drawing",
        number=number,
        raw_texts=(f"도면 {number}. 2지점 1호 토광묘",),
        facts=(),
        visual_regions=(),
        local_score=18.0,
        evidence=support,
        hard_contradiction=hard,
        strong_contradiction_ids=(),
    )


def decision(
    row: DrawingCandidatePacket | None,
    *,
    verdict: str = "match",
    confidence: float = 0.99,
    support_ids: tuple[str, ...] | None = None,
    contradiction_ids: tuple[str, ...] = (),
) -> CodexDrawingDecision:
    if row is not None and support_ids is None:
        support_ids = tuple(item.id for item in row.evidence)
    return CodexDrawingDecision(
        run_id="run-1",
        model="gpt-5.3-codex",
        verdict=verdict,
        candidate_id=row.candidate_id if verdict == "match" and row else None,
        confidence=confidence,
        cited_support_ids=support_ids or (),
        cited_contradiction_ids=contradiction_ids,
        reason_codes=("test",),
        summary="test decision",
    )


class FakeGenerator:
    def __init__(self, initial, expanded=None):
        self.initial = tuple(initial)
        self.expanded = tuple(expanded if expanded is not None else initial)
        self.generate_calls = []
        self.expand_calls = []

    def generate(self, source, bodies, limit=10):
        self.generate_calls.append((source.source_asset_id, limit))
        return tuple(
            replace(row, candidate_id=row.candidate_id.replace("asset-1", source.source_asset_id))
            if row.candidate_id.startswith("candidate:asset-1:") and source.source_asset_id != "asset-1"
            else row
            for row in self.initial
        )

    def expand(self, source, bodies, existing_candidate_ids, limit=20):
        self.expand_calls.append((source.source_asset_id, limit, set(existing_candidate_ids)))
        return tuple(
            replace(row, candidate_id=row.candidate_id.replace("asset-1", source.source_asset_id))
            if row.candidate_id.startswith("candidate:asset-1:") and source.source_asset_id != "asset-1"
            else row
            for row in self.expanded
        )


class FakeClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def resolve(self, source, candidates):
        self.calls.append((source.source_asset_id, tuple(row.candidate_id for row in candidates)))
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        if callable(output):
            return output(source, candidates)
        return output


@pytest.mark.parametrize(
    ("verdict", "confidence", "hard", "expected"),
    [
        ("match", 0.99, False, "AUTO_VERIFIED"),
        ("match", 0.70, False, "REVIEW_REQUIRED"),
        ("match", 0.99, True, "REVIEW_REQUIRED"),
        ("ambiguous", 0.80, False, "REVIEW_REQUIRED"),
        ("none", 0.20, False, "UNRESOLVED"),
    ],
)
def test_v3_final_state_matrix(verdict, confidence, hard, expected):
    row = candidate(hard=hard)
    final = decision(row if verdict == "match" else None, verdict=verdict, confidence=confidence)
    generator = FakeGenerator([row])
    client = FakeClient([final, final] if verdict in {"ambiguous", "none"} else [final])
    resolver = DrawingEvidenceResolverV3(
        generator,
        client,
        auto_confidence=0.95,
        max_candidates=10,
        max_expansions=1,
    )

    result = resolver.resolve_observations("corpus-1", [source()], [])

    assert result.source_results[0].status == expected
    assert len(client.calls) >= 1


def test_explicit_internal_identifier_still_calls_codex():
    row = candidate(number="52")
    client = FakeClient([decision(row)])
    resolver = DrawingEvidenceResolverV3(FakeGenerator([row]), client)

    result = resolver.resolve_observations(
        "corpus-1", [source(internal_numbers=("52",))], []
    )

    assert result.source_results[0].status == "AUTO_VERIFIED"
    assert len(client.calls) == 1


def test_ambiguous_first_pass_expands_once_to_top20_and_uses_second_decision():
    first = candidate(number="51")
    second = candidate(number="52")
    generator = FakeGenerator([first], [first, second])

    def second_decision(source, rows):
        selected = next(row for row in rows if row.number == "52")
        return decision(selected)

    client = FakeClient(
        [
            decision(None, verdict="ambiguous", confidence=0.5),
            second_decision,
        ]
    )
    resolver = DrawingEvidenceResolverV3(generator, client, max_expansions=1)

    result = resolver.resolve_observations("corpus-1", [source()], [])

    assert result.source_results[0].status == "AUTO_VERIFIED"
    assert result.source_results[0].selected_candidate_id.endswith(":52")
    assert len(generator.expand_calls) == 1
    assert generator.expand_calls[0][1] == 20
    assert len(client.calls) == 2


def test_repeated_typed_client_error_fails_closed_to_review_after_one_expansion():
    row = candidate()
    generator = FakeGenerator([row], [row])
    client = FakeClient(
        [
            CodexDrawingDecisionError("bad response"),
            CodexDrawingDecisionError("still bad"),
        ]
    )
    resolver = DrawingEvidenceResolverV3(generator, client, max_expansions=1)

    result = resolver.resolve_observations("corpus-1", [source()], [])

    item = result.source_results[0]
    assert item.status == "REVIEW_REQUIRED"
    assert item.decision is None
    assert len(client.calls) == 2
    assert len(generator.expand_calls) == 1


def test_auto_requires_two_cited_families_and_at_least_one_nonweak_support():
    row = candidate(weak_only=True)
    one_family = decision(row, support_ids=(row.evidence[0].id,))
    all_weak = decision(row)

    first = DrawingEvidenceResolverV3(FakeGenerator([row]), FakeClient([one_family]))
    second = DrawingEvidenceResolverV3(FakeGenerator([row]), FakeClient([all_weak]))

    assert first.resolve_observations("c", [source()], []).source_results[0].status == "REVIEW_REQUIRED"
    assert second.resolve_observations("c", [source()], []).source_results[0].status == "REVIEW_REQUIRED"


def test_cited_contradiction_blocks_auto_promotion():
    row = candidate()
    final = decision(row, contradiction_ids=(row.evidence[0].id,))
    resolver = DrawingEvidenceResolverV3(FakeGenerator([row]), FakeClient([final]))

    result = resolver.resolve_observations("c", [source()], [])

    assert result.source_results[0].status == "REVIEW_REQUIRED"


def test_duplicate_target_assignment_keeps_stronger_source_and_routes_loser_to_review():
    row = candidate(number="52")

    def matching(source_packet, rows):
        selected = rows[0]
        return decision(
            selected,
            confidence=0.98 if source_packet.source_asset_id == "asset-1" else 0.99,
        )

    generator = FakeGenerator([row])
    client = FakeClient([matching, matching])
    resolver = DrawingEvidenceResolverV3(generator, client)

    result = resolver.resolve_observations(
        "c",
        [
            source("asset-1", internal_numbers=("52",)),
            source("asset-2"),
        ],
        [],
    )

    by_source = {item.source_asset_id: item for item in result.source_results}
    assert by_source["asset-1"].status == "AUTO_VERIFIED"
    assert by_source["asset-2"].status == "REVIEW_REQUIRED"
    assert by_source["asset-2"].diagnostics["assignment_conflict"] is True
