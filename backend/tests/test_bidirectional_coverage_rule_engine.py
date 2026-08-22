from app.domain.canonical_models import ArchaeologyObjectData
from app.domain.evidence_bundle import ObjectEvidenceBundle
from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.services.strict_rule_engine import StrictRuleEngine


class StubCoverageService:
    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.calls = []

    def review_object(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.candidates)


def _body(text: str = "6호 석관묘를 설명한다.") -> EvidenceData:
    return EvidenceData(
        id="ev-body",
        kind="text_claim",
        source_sha256="body-sha",
        document_version_id="body-v1",
        page_id="body-v1-p1",
        region_id="b1",
        value=text,
        analysis_run_id="run-1",
        rule_name="mention_claim",
    )


def _coverage_candidate() -> CorrectionCandidateData:
    body = _body()
    return CorrectionCandidateData(
        candidate_id="cand-coverage",
        rule_category="figure_plate_table_photo_ref",
        change_type="added",
        status="pending_review",
        original_text=body.value,
        proposed_text="(도판 45)",
        evidence=body,
        evidence_list=[body],
        archaeology_object_id="obj-6",
        analysis_run_id="run-1",
    )


def _object() -> ArchaeologyObjectData:
    return ArchaeologyObjectData(
        object_id="obj-6",
        site="산노리",
        point="1지점",
        type="석관묘",
        number="6호",
        canonical_name="1지점 6호 석관묘",
    )


def test_strict_rule_engine_composes_reverse_coverage_after_bundle_rules() -> None:
    coverage_candidate = _coverage_candidate()
    coverage = StubCoverageService([coverage_candidate])
    engine = StrictRuleEngine(visual_reference_coverage_service=coverage)
    obj = _object()
    bundle = ObjectEvidenceBundle(
        object_id=obj.object_id,
        canonical_name=obj.canonical_name,
        text_claims=[_body()],
    )

    candidates = engine.check_object_bundle_consistency(
        bundle=bundle,
        archaeology_object=obj,
    )

    assert coverage_candidate in candidates
    assert len(coverage.calls) == 1
    assert coverage.calls[0]["bundle"] is bundle
    assert coverage.calls[0]["archaeology_object"] is obj
    assert coverage.calls[0]["analysis_run_id"] == "run-1"


def test_precise_blank_fill_supersedes_generic_blank_candidate() -> None:
    body = _body("6호 석관묘 (도면: , 도판: )")
    plate = EvidenceData(
        id="ev-plate-45",
        kind="plate_caption",
        source_sha256="plate-sha",
        document_version_id="plate-v1",
        page_id="plate-v1-p45",
        region_id="plate-45",
        value={
            "label": "Plate",
            "plate_number": "45",
            "title": "6호 석관묘 조사 후 전경",
            "raw_identifier": "【도판 45】",
        },
        analysis_run_id="run-1",
        rule_name="plate_caption_evidence",
    )
    engine = StrictRuleEngine()
    bundle = ObjectEvidenceBundle(
        object_id="obj-6",
        canonical_name="1지점 6호 석관묘",
        text_claims=[body],
        plate_claims=[plate],
    )

    candidates = engine.check_object_bundle_consistency(
        bundle=bundle,
        archaeology_object=_object(),
    )

    precise = [
        candidate
        for candidate in candidates
        if candidate.evidence is not None
        and candidate.evidence.rule_name == "visual_reference_blank_fill"
    ]
    assert len(precise) == 1
    assert precise[0].proposed_text == "(도면: , 도판: 45)"
    assert not any(
        candidate.proposed_text is None
        and candidate.original_text == "(도면: , 도판: )"
        and not (
            candidate.evidence is not None
            and candidate.evidence.rule_name == "visual_reference_ambiguous"
        )
        for candidate in candidates
    )
