from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_evaluator():
    path = Path(__file__).resolve().parents[2] / "tools" / "evaluate_drawing_evidence_graph.py"
    spec = importlib.util.spec_from_file_location("drawing_evidence_evaluator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evaluator_cli_requires_source_root_and_outputs():
    module = _load_evaluator()
    parser = module.build_parser()
    args = parser.parse_args([
        "--source-root", "/src",
        "--output-json", "metrics.json",
        "--output-report", "report.md",
    ])
    assert args.source_root == Path("/src")
    assert args.output_json == Path("metrics.json")
    assert args.output_report == Path("report.md")


def test_filename_label_is_hidden_from_blinded_observation():
    module = _load_evaluator()
    observation = module.make_observation(
        source_asset_id="ai-14",
        source_sha256="sha",
        original_name="도면14. 2지점.ai",
        raw_text="2지점 S1 E1 북동 토층",
        internal_numbers=(),
    )
    blinded = module.blind_filename(observation)
    assert blinded.original_name == "blinded.ai"
    assert blinded.raw_text == observation.raw_text
    assert blinded.internal_numbers == observation.internal_numbers
    assert module.filename_label(observation.original_name) == "14"


def test_report_schema_separates_blinded_and_full_metrics():
    module = _load_evaluator()
    payload = module.empty_metrics()
    assert set(payload) >= {"audit", "blinded_35", "full_56"}
    assert payload["audit"]["adobe_used"] is False
    assert payload["blinded_35"]["filename_used_for_scoring"] is False
