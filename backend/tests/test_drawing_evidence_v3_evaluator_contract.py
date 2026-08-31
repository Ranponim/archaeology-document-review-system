from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_tool(name: str):
    path = Path(__file__).resolve().parents[2] / "tools" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gold_template_starts_all_truth_as_unknown_and_never_uses_filename(tmp_path):
    module = _load_tool("build_drawing_gold_template.py")
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "도면52. 2지점.ai").write_bytes(b"%PDF-test")
    (source_root / "삽도3.ai").write_bytes(b"%PDF-test")

    rows = module.build_gold_rows(source_root)

    assert [row["source"] for row in rows] == ["도면52. 2지점.ai", "삽도3.ai"]
    assert all(row["publication_kind"] is None for row in rows)
    assert all(row["number"] is None for row in rows)
    assert all(row["verification"] == "unknown" for row in rows)


def test_gold_template_rejects_output_inside_source_root(tmp_path):
    module = _load_tool("build_drawing_gold_template.py")
    source_root = tmp_path / "src"
    source_root.mkdir()
    with __import__("pytest").raises(ValueError, match="outside source root"):
        module.write_gold_template(source_root, source_root / "gold.json")


def test_evaluator_unknown_gold_rows_are_excluded_from_accuracy_and_precision():
    module = _load_tool("evaluate_drawing_evidence_v3.py")
    gold = [
        {"source": "a.ai", "publication_kind": "drawing", "number": "52", "verification": "human"},
        {"source": "b.ai", "publication_kind": None, "number": None, "verification": "unknown"},
        {"source": "c.ai", "publication_kind": "drawing", "number": "54", "verification": "human"},
    ]
    evaluations = [
        {
            "source": "a.ai",
            "candidate_identities": [["drawing", "52"], ["drawing", "53"]],
            "codex_identity": ["drawing", "52"],
            "status": "AUTO_VERIFIED",
            "invalid_response": False,
        },
        {
            "source": "b.ai",
            "candidate_identities": [["drawing", "999"]],
            "codex_identity": ["drawing", "999"],
            "status": "AUTO_VERIFIED",
            "invalid_response": False,
        },
        {
            "source": "c.ai",
            "candidate_identities": [["drawing", "54"]],
            "codex_identity": ["drawing", "53"],
            "status": "REVIEW_REQUIRED",
            "invalid_response": False,
        },
    ]

    metrics = module.compute_metrics(gold, evaluations)

    assert metrics["gold_known"] == 2
    assert metrics["recall_at_10"] == 1.0
    assert metrics["codex_top1_accuracy"] == 0.5
    assert metrics["auto_coverage"] == 0.5
    assert metrics["auto_precision"] == 1.0
    assert metrics["review_rate"] == 0.5


def test_evaluator_reports_required_safety_counters():
    module = _load_tool("evaluate_drawing_evidence_v3.py")
    metrics = module.compute_metrics([], [])
    assert metrics["hard_contradiction_promoted_count"] == 0
    assert metrics["filename_only_promoted_count"] == 0
    assert metrics["kind_collision_count"] == 0
    assert metrics["api_unsafe_promotion_count"] == 0
    assert metrics["invalid_response_count"] == 0


def test_evaluator_cli_defaults_to_fake_mode_and_rejects_output_inside_source(tmp_path):
    module = _load_tool("evaluate_drawing_evidence_v3.py")
    parser = module.build_parser()
    args = parser.parse_args([
        "--source-root", str(tmp_path / "src"),
        "--gold", "gold.json",
        "--output-json", "metrics.json",
        "--output-report", "report.md",
    ])
    assert args.live_codex is False

    source_root = tmp_path / "src"
    source_root.mkdir()
    with __import__("pytest").raises(ValueError, match="outside source root"):
        module.assert_output_outside_source(source_root, source_root / "metrics.json")


def test_fake_evaluator_is_deterministic_and_never_needs_network(tmp_path):
    module = _load_tool("evaluate_drawing_evidence_v3.py")
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps([
        {"source": "a.ai", "publication_kind": "drawing", "number": "52", "verification": "human"}
    ]), encoding="utf-8")
    fake_path = tmp_path / "fake.json"
    fake_path.write_text(json.dumps([
        {
            "source": "a.ai",
            "candidate_identities": [["drawing", "52"]],
            "codex_identity": ["drawing", "52"],
            "status": "AUTO_VERIFIED",
            "invalid_response": False
        }
    ]), encoding="utf-8")

    first = module.evaluate_from_fixture(gold_path, fake_path)
    second = module.evaluate_from_fixture(gold_path, fake_path)
    assert first == second
    assert first["recall_at_10"] == 1.0
    assert first["auto_precision"] == 1.0
