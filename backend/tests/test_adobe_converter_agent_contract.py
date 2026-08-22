from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT = REPO_ROOT / "tools" / "adobe_converter" / "agent.py"
INDESIGN_JSX = REPO_ROOT / "tools" / "adobe_converter" / "scripts" / "indesign_extract.jsx"
ILLUSTRATOR_JSX = REPO_ROOT / "tools" / "adobe_converter" / "scripts" / "illustrator_extract.jsx"


def test_standalone_agent_and_structural_extractors_exist() -> None:
    assert AGENT.is_file()
    assert INDESIGN_JSX.is_file()
    assert ILLUSTRATOR_JSX.is_file()


def test_non_windows_agent_fails_closed_as_adobe_unavailable(tmp_path: Path) -> None:
    if sys.platform == "win32":
        return

    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(
        json.dumps(
            {
                "project_id": "p1",
                "reference_corpus_id": "c1",
                "source_asset_id": "a1",
                "source_path": str(tmp_path / "plates.indd"),
                "source_role": "plate_layout",
                "output_dir": str(tmp_path / "out"),
                "manifest_schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(AGENT), "--request", str(request_path), "--result", str(result_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["errorCode"] == "ADOBE_UNAVAILABLE"


def test_jsx_extractors_are_dom_fact_collectors_not_identity_rules() -> None:
    indesign = INDESIGN_JSX.read_text(encoding="utf-8")
    illustrator = ILLUSTRATOR_JSX.read_text(encoding="utf-8")

    assert "textFrames" in indesign
    assert "links" in indesign
    assert "textFrames" in illustrator
    assert "artboards" in illustrator
    assert "DUPLICATE_CANONICAL_IDENTIFIER" not in indesign + illustrator
    assert "AMBIGUOUS_IDENTIFIER" not in indesign + illustrator
