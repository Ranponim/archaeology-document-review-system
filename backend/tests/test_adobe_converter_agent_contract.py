from __future__ import annotations

from pathlib import Path
import sys

import pytest

from app.services.adobe_conversion_client import (
    AdobeConversionError,
    ConversionRequest,
    SubprocessAdobeConversionClient,
)


def test_default_adobe_agent_fails_closed_when_adobe_is_unavailable(tmp_path: Path):
    if sys.platform == "win32":
        pytest.skip("portable CI contract is asserted on non-Windows runners")

    source = tmp_path / "_45.indd"
    source.write_bytes(b"not-an-indesign-file")
    output = tmp_path / "output"
    output.mkdir()
    client = SubprocessAdobeConversionClient(timeout_seconds=10)

    with pytest.raises(AdobeConversionError) as error:
        client.convert(
            ConversionRequest(
                project_id="project-1",
                reference_corpus_id="corpus-1",
                source_asset_id="asset-layout",
                source_path=str(source),
                source_role="plate_layout",
                output_dir=str(output),
            )
        )

    assert error.value.code == "ADOBE_UNAVAILABLE"
    assert not list(output.glob("*.json")), "agent must not fabricate a manifest fallback"


def test_adobe_extractors_describe_dom_structure_not_filename_identity():
    repo_root = Path(__file__).resolve().parents[2]
    indesign = repo_root / "tools" / "adobe_converter" / "scripts" / "indesign_extract.jsx"
    illustrator = repo_root / "tools" / "adobe_converter" / "scripts" / "illustrator_extract.jsx"

    assert indesign.is_file()
    assert illustrator.is_file()

    indesign_text = indesign.read_text(encoding="utf-8")
    illustrator_text = illustrator.read_text(encoding="utf-8")

    for token in ("textFrames", "graphics", "linkPath", "sourceAssetId", "sourceSha256"):
        assert token in indesign_text
    for token in ("artboards", "textFrames", "placedItems", "sourceAssetId", "sourceSha256"):
        assert token in illustrator_text

    # Extractors report document structure only. Publication-number regexes belong
    # to ReferenceCanonicalizer, never the Adobe DOM extraction layer.
    assert "도판\\s*" not in indesign_text
    assert "도면\\s*" not in illustrator_text
