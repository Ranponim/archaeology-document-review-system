from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.services.review_budget import (
    candidate_sampling_bucket,
    make_finding_fingerprint,
    make_run_candidate_id,
    select_development_candidates,
)


def _candidate(cid: str, category: str, *, severity: str = "high", text: str = "") -> CorrectionCandidateData:
    return CorrectionCandidateData(
        candidate_id=cid,
        rule_category=category,
        severity=severity,
        confidence=0.95,
        original_text=text,
        proposed_text=text,
    )


def test_sampling_bucket_distinguishes_plate_and_drawing_reference_candidates():
    plate = _candidate("c1", "figure_plate_table_photo_ref", text="도판 45")
    drawing = _candidate("c2", "figure_plate_table_photo_ref", text="도면 30")
    assert candidate_sampling_bucket(plate) == "visual_plate"
    assert candidate_sampling_bucket(drawing) == "visual_drawing"


def test_development_selection_is_deterministic_and_category_balanced():
    candidates = [
        *[_candidate(f"num_{i}", "numeric_value", text=f"길이 {i}cm") for i in range(12)],
        _candidate("plate_1", "figure_plate_table_photo_ref", text="도판 45"),
        _candidate("drawing_1", "figure_plate_table_photo_ref", text="도면 30"),
        _candidate("type_1", "feature_or_artifact_id", text="6호 석관묘"),
        _candidate("period_1", "direction_period_term", text="청동기시대"),
        _candidate("annotation_1", "annotation_resolution", text="주석"),
    ]

    selected_a = select_development_candidates(candidates, max_candidates=10)
    selected_b = select_development_candidates(list(reversed(candidates)), max_candidates=10)

    assert [c.candidate_id for c in selected_a] == [c.candidate_id for c in selected_b]
    assert len(selected_a) == 10
    buckets = {candidate_sampling_bucket(c) for c in selected_a}
    assert "visual_plate" in buckets
    assert "visual_drawing" in buckets
    assert "feature_or_artifact_id" in buckets
    assert "numeric_value" in buckets


def test_run_candidate_id_changes_per_run_but_fingerprint_stays_stable():
    candidate = _candidate("legacy", "numeric_value", text="210cm")
    fp1 = make_finding_fingerprint(candidate)
    fp2 = make_finding_fingerprint(candidate)
    assert fp1 == fp2

    run1_id = make_run_candidate_id("run_aaa", candidate)
    run2_id = make_run_candidate_id("run_bbb", candidate)
    assert run1_id != run2_id
    assert run1_id.startswith("cand_run_aaa_")
    assert run2_id.startswith("cand_run_bbb_")


def test_sampling_bucket_uses_evidence_when_text_is_not_visual():
    ev = EvidenceData(
        id="ev1",
        kind=None,
        value={"raw_text": "【도판 45】"},
    )
    candidate = CorrectionCandidateData(
        candidate_id="c1",
        rule_category="figure_plate_table_photo_ref",
        evidence=ev,
    )
    assert candidate_sampling_bucket(candidate) == "visual_plate"
