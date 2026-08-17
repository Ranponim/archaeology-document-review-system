from app.domain.canonical_models import ArchaeologyObjectData
from app.domain.review_models import EvidenceData
from app.services.strict_rule_engine import StrictRuleEngine


def test_structured_type_is_authoritative_over_generated_rationale():
    engine = StrictRuleEngine()
    evidence = EvidenceData(
        kind=None,
        value={"type": "토광묘"},
        rationale="그래프 설명 문자열에는 수혈 유구 표현도 포함됨",
    )
    assert engine.extract_types_from_evidence(evidence) == ["토광묘"]


def test_generated_rationale_is_not_an_independent_type_source():
    engine = StrictRuleEngine()
    evidence = EvidenceData(kind=None, value={}, rationale="수혈유구")
    assert engine.extract_types_from_evidence(evidence) == []


def test_target_number_filters_multi_object_text_to_target_mention():
    engine = StrictRuleEngine()
    evidence = EvidenceData(
        kind=None,
        value="1호 토광묘와 2호 수혈유구를 조사하였다.",
    )
    target = ArchaeologyObjectData(
        object_id="obj2",
        number="2호",
        type="수혈유구",
        canonical_name="2호 수혈유구",
    )
    types = engine.extract_types_from_evidence(evidence, target_object=target)
    assert "수혈유구" in types
    assert "토광묘" not in types
