from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import time
from typing import Any

import evaluate_panel_provenance as base
import evaluate_panel_provenance_hybrid as hybrid

from app.services.geometric_visual_retriever import GeometricVisualRetriever
from app.services.visual_asset_matcher import VisualAssetMatcher


DEFAULT_SAMPLE_SIZE = 100
DEFAULT_GEOMETRIC_CANDIDATE_POOL = base.DEFAULT_TOP_K
DEFAULT_GEOMETRIC_MINIMUM_MARGIN = 0.08
DEFAULT_BASELINE_JSON = (
    base.REPO_ROOT / "docs" / "local_panel_provenance_acceptance_retest_12688f8.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only diagnostic spike for 100 unresolved panels. Measures current "
            "hybrid SIFT usefulness and runtime without changing production policy."
        )
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--baseline-json", type=Path, default=DEFAULT_BASELINE_JSON)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument(
        "--geometric-candidate-pool",
        type=int,
        default=DEFAULT_GEOMETRIC_CANDIDATE_POOL,
    )
    parser.add_argument(
        "--geometric-minimum-margin",
        type=float,
        default=DEFAULT_GEOMETRIC_MINIMUM_MARGIN,
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=base.REPO_ROOT / "docs" / "local_panel_provenance_hybrid_profile.json",
    )
    return parser


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _sample_evenly(rows: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    if sample_size < 1:
        raise ValueError("sample-size must be positive")
    if len(rows) <= sample_size:
        return list(rows)
    if sample_size == 1:
        return [rows[0]]
    step = (len(rows) - 1) / (sample_size - 1)
    return [rows[round(index * step)] for index in range(sample_size)]


def _mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    if args.geometric_candidate_pool < 1:
        raise ValueError("geometric-candidate-pool must be positive")
    if args.geometric_minimum_margin < 0.0:
        raise ValueError("geometric-minimum-margin cannot be negative")

    source_root = args.source_root.resolve()
    baseline_path = args.baseline_json.resolve()
    if not source_root.is_dir():
        raise NotADirectoryError(source_root)
    if not baseline_path.is_file():
        raise FileNotFoundError(baseline_path)
    base.assert_output_outside_source(source_root, args.output_json)

    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    rows = baseline_payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("baseline JSON has no rows list")

    baseline_algorithm = baseline_payload.get("algorithm")
    baseline_top_k = (
        baseline_algorithm.get("top_k") if isinstance(baseline_algorithm, dict) else None
    )
    if (
        isinstance(baseline_top_k, int)
        and not isinstance(baseline_top_k, bool)
        and args.geometric_candidate_pool > baseline_top_k
    ):
        raise ValueError(
            "geometric candidate pool exceeds candidates retained by the baseline: "
            f"baseline top_k={baseline_top_k}, requested pool={args.geometric_candidate_pool}; "
            "regenerate the baseline with a larger --top-k before profiling this pool"
        )

    unresolved = [
        row
        for row in rows
        if row.get("bbox_status") == "segmented"
        and row.get("deterministic_status") in {"BELOW_SCORE", "AMBIGUOUS_MARGIN"}
    ]
    sample = _sample_evenly(unresolved, args.sample_size)
    before = base._tree_snapshot(source_root)

    matcher = VisualAssetMatcher()
    retriever = GeometricVisualRetriever()
    candidate_paths = base.discover_candidate_images(source_root)
    candidate_by_id = {
        base._relative(source_root, path): path.resolve() for path in candidate_paths
    }

    panel_total_times: list[float] = []
    panel_extraction_times: list[float] = []
    panel_feature_times: list[float] = []
    candidate_step_times: list[float] = []
    candidate_feature_times: list[float] = []
    candidate_evidence_times: list[float] = []
    candidate_feature_cache_hit_times: list[float] = []
    candidate_feature_cache_miss_times: list[float] = []
    evidence_ranks: list[int] = []
    evidence_panel_count = 0
    accepted_panel_count = 0
    ambiguous_panel_count = 0
    unavailable_panel_count = 0
    sampled_rows: list[dict[str, Any]] = []
    cache_by_pdf: dict[str, hybrid._PdfPanelImageCache] = {}

    try:
        for row in sample:
            panel_started = time.perf_counter()
            pdf_relative = str(row["pdf"])
            cache = cache_by_pdf.get(pdf_relative)
            if cache is None:
                cache = hybrid._PdfPanelImageCache(
                    matcher,
                    (source_root / pdf_relative).resolve(),
                )
                cache_by_pdf[pdf_relative] = cache

            extraction_started = time.perf_counter()
            panel_image = cache.panel_image(
                int(row["physical_page"]),
                tuple(float(value) for value in row["bbox"]),
            )
            extraction_seconds = time.perf_counter() - extraction_started
            panel_extraction_times.append(extraction_seconds)

            record: dict[str, Any] = {
                "panel_id": row["panel_id"],
                "pdf": row["pdf"],
                "physical_page": row["physical_page"],
                "deterministic_status": row["deterministic_status"],
                "panel_image_available": panel_image is not None,
                "first_strong_evidence_rank": None,
                "strong_evidence_count": 0,
                "best_geometric_score": None,
                "geometric_margin": None,
                "accepted_by_current_margin": False,
                "panel_seconds": None,
            }
            if panel_image is None:
                unavailable_panel_count += 1
                record["panel_seconds"] = time.perf_counter() - panel_started
                panel_total_times.append(float(record["panel_seconds"]))
                sampled_rows.append(record)
                continue

            feature_started = time.perf_counter()
            panel_features = retriever._features_image(panel_image)
            panel_feature_times.append(time.perf_counter() - feature_started)
            if panel_features is None:
                record["panel_seconds"] = time.perf_counter() - panel_started
                panel_total_times.append(float(record["panel_seconds"]))
                sampled_rows.append(record)
                continue

            strong: list[tuple[int, Any]] = []
            for rank, candidate in enumerate(
                row.get("candidates", [])[: args.geometric_candidate_pool],
                start=1,
            ):
                source_asset_id = str(candidate["source_asset_id"])
                candidate_path = candidate_by_id.get(source_asset_id)
                if candidate_path is None:
                    continue

                candidate_started = time.perf_counter()
                resolved_candidate_path = candidate_path.resolve()
                feature_cache_hit = resolved_candidate_path in retriever._feature_cache
                candidate_feature_started = time.perf_counter()
                candidate_features = retriever._features_path(candidate_path)
                candidate_feature_seconds = time.perf_counter() - candidate_feature_started
                candidate_feature_times.append(candidate_feature_seconds)
                if feature_cache_hit:
                    candidate_feature_cache_hit_times.append(candidate_feature_seconds)
                else:
                    candidate_feature_cache_miss_times.append(candidate_feature_seconds)

                evidence = None
                if candidate_features is not None:
                    evidence_started = time.perf_counter()
                    evidence = retriever._evidence(
                        source_asset_id=source_asset_id,
                        panel_features=panel_features,
                        candidate_features=candidate_features,
                    )
                    candidate_evidence_times.append(time.perf_counter() - evidence_started)
                candidate_step_times.append(time.perf_counter() - candidate_started)
                if evidence is not None:
                    strong.append((rank, evidence))

            if strong:
                evidence_panel_count += 1
                first_rank = min(rank for rank, _ in strong)
                evidence_ranks.append(first_rank)
                record["first_strong_evidence_rank"] = first_rank
                record["strong_evidence_count"] = len(strong)

                ranked = sorted(
                    (evidence for _, evidence in strong),
                    key=lambda item: (
                        -item.score,
                        -item.inliers,
                        -item.inlier_ratio,
                        item.source_asset_id,
                    ),
                )
                best = ranked[0]
                margin = best.score - ranked[1].score if len(ranked) > 1 else None
                record["best_geometric_score"] = best.score
                record["geometric_margin"] = margin
                accepted = margin is None or margin >= args.geometric_minimum_margin
                record["accepted_by_current_margin"] = accepted
                if accepted:
                    accepted_panel_count += 1
                else:
                    ambiguous_panel_count += 1

            record["panel_seconds"] = time.perf_counter() - panel_started
            panel_total_times.append(float(record["panel_seconds"]))
            sampled_rows.append(record)
    finally:
        for cache in cache_by_pdf.values():
            cache.close()

    after = base._tree_snapshot(source_root)
    source_mutated = before != after
    mean_panel_seconds = _mean(panel_total_times)
    estimated_geometric_seconds = (
        mean_panel_seconds * len(unresolved) if mean_panel_seconds is not None else None
    )
    baseline_seconds = float(baseline_payload.get("elapsed_seconds") or 0.0)
    estimated_total_seconds = (
        baseline_seconds + estimated_geometric_seconds
        if estimated_geometric_seconds is not None
        else None
    )

    rank_buckets = Counter()
    for rank in evidence_ranks:
        if rank == 1:
            rank_buckets["top1"] += 1
        if rank <= 5:
            rank_buckets["top5"] += 1
        if rank <= 10:
            rank_buckets["top10"] += 1
        if rank <= 20:
            rank_buckets["top20"] += 1
        if rank <= 50:
            rank_buckets["top50"] += 1

    return {
        "measurement_head": base._head_sha(),
        "baseline_measurement_head": baseline_payload.get("measurement_head"),
        "baseline_json": str(baseline_path),
        "baseline_top_k": baseline_top_k,
        "source_root": str(source_root),
        "source_root_mutated": source_mutated,
        "unresolved_panel_count": len(unresolved),
        "sample_size": len(sample),
        "geometric_candidate_pool": args.geometric_candidate_pool,
        "geometric_minimum_margin": args.geometric_minimum_margin,
        "evidence_panel_count": evidence_panel_count,
        "accepted_panel_count": accepted_panel_count,
        "ambiguous_panel_count": ambiguous_panel_count,
        "unavailable_panel_count": unavailable_panel_count,
        "first_strong_evidence_rank_buckets": dict(rank_buckets),
        "timing": {
            "baseline_pixel_seconds": baseline_seconds,
            "panel_mean_seconds": mean_panel_seconds,
            "panel_p50_seconds": _percentile(panel_total_times, 0.50),
            "panel_p95_seconds": _percentile(panel_total_times, 0.95),
            "panel_extraction_mean_seconds": _mean(panel_extraction_times),
            "panel_feature_mean_seconds": _mean(panel_feature_times),
            "candidate_step_count": len(candidate_step_times),
            "candidate_step_mean_seconds": _mean(candidate_step_times),
            "candidate_feature_mean_seconds": _mean(candidate_feature_times),
            "candidate_evidence_mean_seconds": _mean(candidate_evidence_times),
            "candidate_feature_cache_hit_count": len(candidate_feature_cache_hit_times),
            "candidate_feature_cache_miss_count": len(candidate_feature_cache_miss_times),
            "candidate_feature_cache_hit_mean_seconds": _mean(
                candidate_feature_cache_hit_times
            ),
            "candidate_feature_cache_miss_mean_seconds": _mean(
                candidate_feature_cache_miss_times
            ),
            "estimated_geometric_full_seconds": estimated_geometric_seconds,
            "estimated_geometric_full_minutes": (
                estimated_geometric_seconds / 60.0
                if estimated_geometric_seconds is not None
                else None
            ),
            "estimated_hybrid_total_seconds": estimated_total_seconds,
            "estimated_hybrid_total_minutes": (
                estimated_total_seconds / 60.0
                if estimated_total_seconds is not None
                else None
            ),
        },
        "sampled_rows": sampled_rows,
    }


def main() -> int:
    args = build_parser().parse_args()
    payload = evaluate(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {key: value for key, value in payload.items() if key != "sampled_rows"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not payload["source_root_mutated"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
