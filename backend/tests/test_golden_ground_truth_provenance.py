from pathlib import Path

import yaml


GOLDEN_DATASET_PATH = (
    Path(__file__).parent / "fixtures" / "golden" / "golden_dataset.yaml"
)


def _load_dataset():
    with GOLDEN_DATASET_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_unverified_cases_are_not_labeled_valid_ground_truth():
    dataset = _load_dataset()

    assert "Expert-verified" not in dataset["description"]

    cases = {case["case_id"]: case for case in dataset["benchmark_cases"]}
    assert cases["GT_CASE_006"]["ground_truth_status"] == "INVALID_GROUND_TRUTH_MAPPING"

    for case_id, case in cases.items():
        if case_id == "GT_CASE_006":
            continue
        assert case["ground_truth_status"] == "NEEDS_REVALIDATION"
        assert case.get("expert_verified") is False


def test_valid_ground_truth_requires_expert_provenance():
    dataset = _load_dataset()

    required_fields = {
        "verified_by",
        "verified_at",
        "source_pdf_sha256",
        "canonical_publication_identifier",
        "expert_note",
    }

    for case in dataset["benchmark_cases"]:
        if case["ground_truth_status"] != "VALID_GROUND_TRUTH":
            continue
        assert case.get("expert_verified") is True
        missing = [field for field in required_fields if not case.get(field)]
        assert not missing, (
            f"{case['case_id']} cannot be VALID_GROUND_TRUTH without expert provenance: "
            + ", ".join(sorted(missing))
        )
