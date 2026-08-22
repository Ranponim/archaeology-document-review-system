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


def _body() -> EvidenceData:
    return EvidenceData(
        id="ev-body",
        kind="text_claim",
        source_sha256="body-sha",
        document_version_id="body-v1",
        page_id="body-v1-p1",
        region_id="b1",
        value="6호 석관묘를 설명한다.",
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


def test_strict_rule_engine_composes_reverse_coverage_after_bundle_rules() -> None:
    coverage_candidate = _coverage_candidate()
    coverage = StubCoverageService([coverage_candidate])
    engine = StrictRuleEngine(visual_reference_coverage_service=coverage)
    obj = ArchaeologyObjectData(
        object_id="obj-6",
        site="산노리",
        point="1지점",
        type="석관묘",
        number="6호",
        canonical_name="1지점 6호 석관묘",
    )
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
