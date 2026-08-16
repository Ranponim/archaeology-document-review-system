from pathlib import Path
import pytest
import yaml

from app.domain.canonical_models import (
    DrawingData,
    PlateData,
    ReferenceData,
    ResolutionStatus,
)
from app.services.asset_matcher import AssetMatcher, ResolutionResult, resolve_reference
from app.services.plate_parser import PlateIndex, PlateParser


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "golden" / "case6.yaml"
PLATE_45_PDF = Path(__file__).parent / "fixtures" / "golden" / "plate_45_fixture.pdf"


@pytest.fixture
def case6_spec() -> dict:
    assert FIXTURE_PATH.is_file(), f"Fixture file not found: {FIXTURE_PATH}"
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_case6_golden_fixture_structure(case6_spec):
    assert case6_spec["case_id"] == "GT_CASE_006"
    assert case6_spec["reference"]["type"] == "plate"
    assert case6_spec["reference"]["number"] == "45"
    assert case6_spec["plate_explicit_identifier"] == "【도판 45】"
    assert case6_spec["plate_title"] == "1지점 청동기시대 6호 석관묘"
    assert case6_spec["forbidden_link_filename"] == "4. 조사 후_45.JPG"
    assert len(case6_spec["ambiguous_filenames"]) >= 2
    assert len(case6_spec["missing_reference"]["decoy_filenames"]) >= 1


def test_case6_reference_resolves_canonically_and_never_picks_forbidden_filename(
    tmp_path, case6_spec
):
    # Setup on-disk decoy directory containing the forbidden link filename and decoys
    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()
    forbidden_name = case6_spec["forbidden_link_filename"]
    (plates_dir / forbidden_name).write_bytes(b"decoy forbidden photo bytes")
    for decoy in case6_spec["ambiguous_filenames"]:
        (plates_dir / decoy).write_bytes(b"decoy photo bytes")

    # Canonical PlateIndex containing explicit Plate 45
    plate_45 = PlateData(
        plate_id="plate_45",
        number=case6_spec["reference"]["number"],
        physical_page=case6_spec["physical_page"],
        title=case6_spec["plate_title"],
        raw_identifier=case6_spec["plate_explicit_identifier"],
        source_sha256="canonical_plate_hash_45",
        source_kind="plate_pdf",
    )
    plate_index = PlateIndex(
        plates_by_number={"45": plate_45},
        plates=[plate_45],
    )

    matcher = AssetMatcher(
        drawings_dir=tmp_path / "drawings",
        plates_dir=plates_dir,
        plate_index=plate_index,
    )

    ref = ReferenceData(
        ref_type=case6_spec["reference"]["type"],
        number=case6_spec["reference"]["number"],
        raw_text="도판 : 45ㆍ46",
    )

    # 1. Resolve reference via matcher instance
    result = matcher.resolve_reference(ref)

    assert isinstance(result, ResolutionResult)
    assert result.status == ResolutionStatus.RESOLVED
    assert result.status == "resolved"
    assert result.target is not None
    assert isinstance(result.target, PlateData)
    assert result.target.number == "45"
    assert result.target.title == "1지점 청동기시대 6호 석관묘"
    assert result.target.physical_page == 47
    assert result.target.raw_identifier == "【도판 45】"
    assert result.target.source_kind == "plate_pdf"

    # Strict invariant: forbidden filename must NEVER be present in target or evidence
    assert forbidden_name not in str(result.target)
    assert forbidden_name not in result.identity_evidence
    for evidence in result.identity_evidence:
        assert forbidden_name not in evidence

    # 2. Resolve reference via standalone / class method
    result_standalone = resolve_reference(ref, plate_index=plate_index)
    assert result_standalone.status == ResolutionStatus.RESOLVED
    assert result_standalone.target == plate_45
    assert forbidden_name not in result_standalone.identity_evidence


def test_case6_missing_reference_resolves_to_missing_even_with_decoy_files_on_disk(
    tmp_path, case6_spec
):
    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()

    missing_spec = case6_spec["missing_reference"]
    missing_num = missing_spec["number"]

    # Write decoy files with the missing number to disk
    for decoy in missing_spec["decoy_filenames"]:
        (plates_dir / decoy).write_bytes(b"decoy bytes")

    plate_index = PlateIndex(
        plates_by_number={},
        plates=[],
    )

    matcher = AssetMatcher(
        drawings_dir=tmp_path / "drawings",
        plates_dir=plates_dir,
        plate_index=plate_index,
    )

    ref = ReferenceData(
        ref_type="plate",
        number=missing_num,
        raw_text=f"도판 : {missing_num}",
    )

    result = matcher.resolve_reference(ref)

    # Invariant: Must resolve to MISSING or UNRESOLVED with target None
    assert result.status in (ResolutionStatus.MISSING, ResolutionStatus.UNRESOLVED)
    assert result.target is None
    assert len(result.identity_evidence) == 0


def test_case6_ambiguous_and_trap_filenames_do_not_corrupt_canonical_resolution(
    tmp_path, case6_spec
):
    plates_dir = tmp_path / "plates"
    plates_dir.mkdir()

    # Place multiple ambiguous/trap files matching pattern *45*.JPG
    for filename in case6_spec["ambiguous_filenames"]:
        (plates_dir / filename).write_bytes(b"ambiguous trap content")

    plate_45 = PlateData(
        plate_id="plate_45",
        number="45",
        physical_page=47,
        title="1지점 청동기시대 6호 석관묘",
        raw_identifier="【도판 45】",
    )
    plate_index = PlateIndex(
        plates_by_number={"45": plate_45},
        plates=[plate_45],
    )

    matcher = AssetMatcher(
        drawings_dir=tmp_path / "drawings",
        plates_dir=plates_dir,
        plate_index=plate_index,
    )

    ref = ReferenceData(ref_type="plate", number="45")
    result = matcher.resolve_reference(ref)

    assert result.status == ResolutionStatus.RESOLVED
    assert result.target == plate_45
    assert result.target.title == "1지점 청동기시대 6호 석관묘"


def test_case6_resolution_with_real_golden_pdf():
    if not PLATE_45_PDF.is_file():
        pytest.skip(f"Golden PDF fixture not found: {PLATE_45_PDF}")

    parser = PlateParser()
    plate_index = parser.parse(PLATE_45_PDF)

    assert "45" in plate_index
    plate_45 = plate_index.get_plate("45")
    assert plate_45 is not None
    assert plate_45.number == "45"
    assert plate_45.physical_page == 47
    assert plate_45.title == "1지점 청동기시대 6호 석관묘"

    ref = ReferenceData(ref_type="plate", number="45")
    result = resolve_reference(ref, plate_index=plate_index)

    assert result.status == ResolutionStatus.RESOLVED
    assert result.target is not None
    assert result.target.number == "45"
    assert result.target.physical_page == 47
    assert result.target.title == "1지점 청동기시대 6호 석관묘"
    assert "4. 조사 후_45.JPG" not in result.identity_evidence
