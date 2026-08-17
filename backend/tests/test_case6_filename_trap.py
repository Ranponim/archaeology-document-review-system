from pathlib import Path

from app.domain.canonical_models import PlateData, ReferenceData, ResolutionStatus
from app.services.asset_matcher import AssetMatcher, resolve_reference
from app.services.plate_parser import PlateIndex


def _canonical_plate_45() -> PlateData:
    return PlateData(
        plate_id="plate_45",
        number="45",
        physical_page=123,
        title="1지점 청동기시대 6호 석관묘",
        raw_identifier="【도판 45】",
        document_version_id="plate_book_v1",
        source_sha256="canonical-plate-sha",
    )


def test_case6_unrelated_links_filename_45_never_defines_plate_identity(tmp_path: Path):
    """Permanent regression for archaeologist feedback Case 6.

    The InDesign Links file name suffix `_45.JPG` is a packaging rename and has
    no publication identity. `도판 45` must resolve only through the explicit
    publication identifier `【도판 45】` in the canonical plate index.
    """
    links_dir = tmp_path / "Links"
    links_dir.mkdir()
    unrelated = links_dir / "4. 조사 후_45.JPG"
    unrelated.write_bytes(b"not-the-publication-plate")

    plate = _canonical_plate_45()
    index = PlateIndex(plates_by_number={"45": plate}, plates=[plate])
    matcher = AssetMatcher(plates_dir=links_dir, plate_index=index)
    reference = ReferenceData(ref_type="plate", number="45")

    result = matcher.resolve_reference(reference)

    assert matcher.get_index_summary()["plate_files_count"] == 1  # trap is present
    assert result.status == ResolutionStatus.RESOLVED
    assert result.target is plate
    assert result.identity_source == "plate_pdf"
    assert "【도판 45】" in result.identity_evidence
    assert unrelated.name not in result.identity_evidence
    assert unrelated.name not in result.rationale


def test_case6_filename_45_cannot_rescue_missing_explicit_plate(tmp_path: Path):
    """If `【도판 45】` is absent, `_45.JPG` must not become a fallback target."""
    links_dir = tmp_path / "Links"
    links_dir.mkdir()
    (links_dir / "4. 조사 후_45.JPG").write_bytes(b"unrelated-pit-grave-photo")

    matcher = AssetMatcher(
        plates_dir=links_dir,
        plate_index=PlateIndex(),
    )
    result = matcher.resolve_reference(ReferenceData(ref_type="plate", number="45"))

    assert result.status == ResolutionStatus.MISSING
    assert result.target is None
    assert result.identity_source == "plate_pdf"


def test_case6_module_level_resolver_has_no_filesystem_identity_path():
    """Canonical resolver accepts indexes only; filenames are not an identity input."""
    result = resolve_reference(
        ReferenceData(ref_type="plate", number="45"),
        plate_index=PlateIndex(),
    )
    assert result.status == ResolutionStatus.MISSING
    assert result.target is None
