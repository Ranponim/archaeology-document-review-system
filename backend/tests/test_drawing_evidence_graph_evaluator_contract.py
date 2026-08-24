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
    assert args.resolver_version == "v1"


def test_evaluator_cli_can_select_v2_explicitly():
    module = _load_evaluator()
    parser = module.build_parser()
    args = parser.parse_args([
        "--source-root", "/src",
        "--resolver-version", "v2",
        "--output-json", "metrics.json",
        "--output-report", "report.md",
    ])
    assert args.resolver_version == "v2"


def test_filename_label_is_hidden_from_blinded_observation():
    module = _load_evaluator()
    observation = module.make_observation(
        source_asset_id="ai-14",
        source_sha256="sha",
        original_name="도면14. 2지점.ai",
        raw_text="2지점 S1 E1 북동 토층",
        internal_numbers=(),
        source_path="본문 도면/2지점/도면14.ai",
    )
    blinded = module.blind_filename(observation)
    assert blinded.original_name == "blinded.ai"
    assert blinded.raw_text == observation.raw_text
    assert blinded.internal_numbers == observation.internal_numbers
    assert blinded.source_path == observation.source_path
    assert module.filename_label(observation.original_name) == "14"


def test_v2_body_reference_kind_is_losslessly_classified():
    module = _load_evaluator()
    assert module.publication_kind_from_text("도면 3. 유구현황도") == "drawing"
    assert module.publication_kind_from_text("삽도 3. 그리드") == "illustration"


def test_report_schema_separates_blinded_and_full_metrics():
    module = _load_evaluator()
    payload = module.empty_metrics("v2")
    assert set(payload) >= {"audit", "blinded_35", "full_56"}
    assert payload["audit"]["adobe_used"] is False
    assert payload["audit"]["resolver_version"] == "drawing-evidence-v2"
    assert payload["blinded_35"]["filename_used_for_scoring"] is False
    assert payload["full_56"]["kind_collision_count"] == 0
    assert payload["full_56"]["hard_contradiction_promoted_count"] == 0
    assert payload["full_56"]["filename_only_verified_count"] == 0
