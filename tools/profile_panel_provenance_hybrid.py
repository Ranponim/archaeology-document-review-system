from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import time
from typing import Any

import cv2
import evaluate_panel_provenance as base
import evaluate_panel_provenance_hybrid as hybrid
import numpy as np
from PIL import Image, ImageOps

from app.services.geometric_visual_retriever import (
    GeometricVisualEvidence,
    GeometricVisualRetriever,
)
from app.services.visual_asset_matcher import VisualAssetMatcher


DEFAULT_SAMPLE_SIZE = 100
DEFAULT_GEOMETRIC_CANDIDATE_POOL = base.DEFAULT_TOP_K
DEFAULT_GEOMETRIC_MINIMUM_MARGIN = 0.08
DEFAULT_BASELINE_JSON = (
    base.REPO_ROOT / "docs" / "local_panel_provenance_acceptance_retest_12688f8.json"
)
DEFAULT_SAMPLE_REFERENCE_JSON = (
    base.REPO_ROOT / "docs" / "local_panel_provenance_hybrid_profile_pool5.json"
)

_PIXEL_HISTOGRAM_LABELS = (
    "<=0.5MP",
    "0.5-1MP",
    "1-2MP",
    "2-4MP",
    "4-8MP",
    ">8MP",
)
_DESCRIPTOR_HISTOGRAM_LABELS = (
    "0",
    "1-250",
    "251-500",
    "501-1000",
    "1001-2000",
    ">2000",
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


def _distribution(values: list[float | int]) -> dict[str, Any]:
    numeric = [float(value) for value in values]
    return {
        "count": len(numeric),
        "mean": _mean(numeric),
        "p50": _percentile(numeric, 0.50),
        "p95": _percentile(numeric, 0.95),
        "max": max(numeric) if numeric else None,
    }


def _timing_distribution(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "total_seconds": float(sum(values)),
        "mean_seconds": _mean(values),
        "p50_seconds": _percentile(values, 0.50),
        "p95_seconds": _percentile(values, 0.95),
    }


def _pixel_bucket(pixel_count: int) -> str:
    megapixels = pixel_count / 1_000_000.0
    if megapixels <= 0.5:
        return "<=0.5MP"
    if megapixels <= 1.0:
        return "0.5-1MP"
    if megapixels <= 2.0:
        return "1-2MP"
    if megapixels <= 4.0:
        return "2-4MP"
    if megapixels <= 8.0:
        return "4-8MP"
    return ">8MP"


def _descriptor_bucket(descriptor_count: int) -> str:
    if descriptor_count == 0:
        return "0"
    if descriptor_count <= 250:
        return "1-250"
    if descriptor_count <= 500:
        return "251-500"
    if descriptor_count <= 1000:
        return "501-1000"
    if descriptor_count <= 2000:
        return "1001-2000"
    return ">2000"


def _histogram(values: list[int], bucket, labels: tuple[str, ...]) -> dict[str, int]:
    result = {label: 0 for label in labels}
    for value in values:
        result[bucket(value)] += 1
    return result


def _reuse_bucket(evaluation_count: int) -> str:
    if evaluation_count == 1:
        return "1"
    if evaluation_count == 2:
        return "2"
    if evaluation_count <= 5:
        return "3-5"
    if evaluation_count <= 10:
        return "6-10"
    return ">10"


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    x_mean = statistics.mean(xs)
    y_mean = statistics.mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_variance = sum((x - x_mean) ** 2 for x in xs)
    y_variance = sum((y - y_mean) ** 2 for y in ys)
    denominator = (x_variance * y_variance) ** 0.5
    return numerator / denominator if denominator else None


def _safe_candidate_id(source_asset_id: str) -> str:
    digest = hashlib.sha256(source_asset_id.encode("utf-8")).hexdigest()
    return f"candidate-{digest[:16]}"


class _ProfiledGeometricVisualRetriever(GeometricVisualRetriever):
    """Profiler-only mirror of retriever internals with stage timers.

    The method bodies intentionally preserve the production retriever's
    image/feature/evidence sequence. This class is used only by this tool;
    production services are not instrumented or changed.
    """

    def __init__(self) -> None:
        super().__init__()
        self._active_feature_record: dict[str, Any] | None = None
        self._active_evidence_record: dict[str, Any] | None = None
        self._candidate_image_metadata: dict[Path, dict[str, int]] = {}

    def profile_panel_features(
        self,
        image: Image.Image,
    ) -> tuple[tuple[tuple[cv2.KeyPoint, ...], np.ndarray] | None, dict[str, Any]]:
        record: dict[str, Any] = {
            "keypoint_count": 0,
            "descriptor_count": 0,
            "descriptor_shape": None,
            "grayscale_or_preprocess_seconds": 0.0,
            "sift_detect_compute_seconds": 0.0,
            "feature_total_seconds": 0.0,
        }
        self._active_feature_record = record
        started = time.perf_counter()
        try:
            features = self._features_image(image)
        finally:
            record["feature_total_seconds"] = time.perf_counter() - started
            self._active_feature_record = None
        return features, record

    def profile_candidate_features(
        self,
        path: Path,
        record: dict[str, Any],
    ) -> tuple[tuple[tuple[cv2.KeyPoint, ...], np.ndarray] | None, dict[str, Any]]:
        self._active_feature_record = record
        try:
            features = self._features_path(path)
        finally:
            self._active_feature_record = None
        return features, record

    @staticmethod
    def _apply_feature_metadata(
        record: dict[str, Any],
        features: tuple[tuple[cv2.KeyPoint, ...], np.ndarray] | None,
    ) -> None:
        if features is None:
            return
        keypoints, descriptors = features
        record["keypoint_count"] = len(keypoints)
        record["descriptor_count"] = int(len(descriptors))
        record["descriptor_shape"] = list(descriptors.shape)

    def _features_image(
        self,
        image: Image.Image,
    ) -> tuple[tuple[cv2.KeyPoint, ...], np.ndarray] | None:
        record = self._active_feature_record
        preprocess_started = time.perf_counter()
        grayscale = self._grayscale(image)
        preprocess_seconds = time.perf_counter() - preprocess_started
        sift_started = time.perf_counter()
        keypoints, descriptors = self._sift.detectAndCompute(grayscale, None)
        sift_seconds = time.perf_counter() - sift_started

        if record is not None:
            record["grayscale_or_preprocess_seconds"] = preprocess_seconds
            record["sift_detect_compute_seconds"] = sift_seconds
            record["keypoint_count"] = len(keypoints)
            record["descriptor_count"] = (
                int(len(descriptors)) if descriptors is not None else 0
            )
            record["descriptor_shape"] = (
                list(descriptors.shape) if descriptors is not None else None
            )

        if descriptors is None or len(keypoints) < 4:
            return None
        return tuple(keypoints), descriptors

    def _features_path(
        self,
        path: Path,
    ) -> tuple[tuple[cv2.KeyPoint, ...], np.ndarray] | None:
        resolved = path.resolve()
        record = self._active_feature_record
        lookup_started = time.perf_counter()
        cache_hit = resolved in self._feature_cache
        lookup_seconds = time.perf_counter() - lookup_started
        if record is not None:
            record["feature_cache_hit"] = cache_hit
            record["feature_cache_lookup_seconds"] = lookup_seconds

        if cache_hit:
            if record is not None:
                record.update(self._candidate_image_metadata.get(resolved, {}))
                self._apply_feature_metadata(record, self._feature_cache[resolved])
            return self._feature_cache[resolved]

        features = None
        decode_started = time.perf_counter()
        try:
            with Image.open(resolved) as image:
                image.load()
                decode_seconds = time.perf_counter() - decode_started
                if record is not None:
                    record["image_decode_seconds"] = decode_seconds
                    width, height = image.size
                    record["width"] = int(width)
                    record["height"] = int(height)
                    record["pixel_count"] = int(width * height)
                    self._candidate_image_metadata[resolved] = {
                        "width": int(width),
                        "height": int(height),
                        "pixel_count": int(width * height),
                    }
                features = self._features_image(image)
        except (OSError, ValueError):
            features = None
        if record is not None:
            record.setdefault(
                "image_decode_seconds",
                time.perf_counter() - decode_started,
            )
        self._feature_cache[resolved] = features
        return features

    def _evidence(
        self,
        *,
        source_asset_id: str,
        panel_features: tuple[tuple[cv2.KeyPoint, ...], np.ndarray],
        candidate_features: tuple[tuple[cv2.KeyPoint, ...], np.ndarray],
    ) -> GeometricVisualEvidence | None:
        timing = (
            self._active_evidence_record["evidence_timing"]
            if self._active_evidence_record is not None
            else {
                "bf_knn_match_seconds": 0.0,
                "lowe_ratio_filter_seconds": 0.0,
                "homography_ransac_seconds": 0.0,
                "other_score_evidence_seconds": 0.0,
                "total_seconds": 0.0,
            }
        )
        evidence_started = time.perf_counter()
        try:
            panel_keypoints, panel_descriptors = panel_features
            candidate_keypoints, candidate_descriptors = candidate_features
            if len(panel_descriptors) < 2 or len(candidate_descriptors) < 2:
                return None

            match_started = time.perf_counter()
            pairs = self._matcher.knnMatch(candidate_descriptors, panel_descriptors, k=2)
            timing["bf_knn_match_seconds"] = time.perf_counter() - match_started

            ratio_started = time.perf_counter()
            good_matches = [
                first
                for pair in pairs
                if len(pair) == 2
                for first, second in [pair]
                if first.distance < self._lowe_ratio * second.distance
            ]
            timing["lowe_ratio_filter_seconds"] = time.perf_counter() - ratio_started
            if len(good_matches) < max(4, self._minimum_inliers):
                return None

            source_points = np.float32(
                [candidate_keypoints[match.queryIdx].pt for match in good_matches]
            ).reshape(-1, 1, 2)
            panel_points = np.float32(
                [panel_keypoints[match.trainIdx].pt for match in good_matches]
            ).reshape(-1, 1, 2)
            ransac_started = time.perf_counter()
            homography, mask = cv2.findHomography(
                source_points,
                panel_points,
                cv2.RANSAC,
                self._ransac_reprojection_threshold,
            )
            timing["homography_ransac_seconds"] = time.perf_counter() - ransac_started
            if homography is None or mask is None or not np.isfinite(homography).all():
                return None

            inliers = int(mask.ravel().sum())
            inlier_ratio = inliers / len(good_matches)
            if inliers < self._minimum_inliers or inlier_ratio < self._minimum_inlier_ratio:
                return None

            support = min(1.0, inliers / 24.0)
            score = min(1.0, max(0.0, 0.65 * inlier_ratio + 0.35 * support))
            return GeometricVisualEvidence(
                source_asset_id=source_asset_id,
                score=score,
                good_matches=len(good_matches),
                inliers=inliers,
                inlier_ratio=inlier_ratio,
            )
        finally:
            total_seconds = time.perf_counter() - evidence_started
            timing["total_seconds"] = total_seconds
            measured = (
                timing["bf_knn_match_seconds"]
                + timing["lowe_ratio_filter_seconds"]
                + timing["homography_ransac_seconds"]
            )
            timing["other_score_evidence_seconds"] = max(0.0, total_seconds - measured)


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
    retriever = _ProfiledGeometricVisualRetriever()
    candidate_paths = base.discover_candidate_images(source_root)
    candidate_by_id = {
        base._relative(source_root, path): path.resolve() for path in candidate_paths
    }
    candidate_file_sizes: dict[Path, int | None] = {}
    for candidate_path in candidate_by_id.values():
        try:
            candidate_file_sizes[candidate_path] = candidate_path.stat().st_size
        except OSError:
            candidate_file_sizes[candidate_path] = None

    panel_total_times: list[float] = []
    panel_extraction_times: list[float] = []
    panel_feature_times: list[float] = []
    candidate_step_times: list[float] = []
    candidate_feature_times: list[float] = []
    candidate_evidence_times: list[float] = []
    candidate_feature_cache_hit_times: list[float] = []
    candidate_feature_cache_miss_times: list[float] = []
    candidate_image_records: list[dict[str, Any]] = []
    candidate_feature_records: list[dict[str, Any]] = []
    panel_feature_records: list[dict[str, Any]] = []
    candidate_evaluations: list[dict[str, Any]] = []
    candidate_reuse_counts: Counter[str] = Counter()
    candidate_feature_decode_times: list[float] = []
    candidate_feature_preprocess_times: list[float] = []
    candidate_feature_sift_times: list[float] = []
    candidate_feature_lookup_times: list[float] = []
    candidate_evidence_total_times: list[float] = []
    candidate_bf_match_times: list[float] = []
    candidate_lowe_times: list[float] = []
    candidate_ransac_times: list[float] = []
    candidate_other_evidence_times: list[float] = []
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
            panel_features, panel_feature_record = retriever.profile_panel_features(
                panel_image
            )
            panel_feature_times.append(time.perf_counter() - feature_started)
            panel_feature_records.append(panel_feature_record)
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
                source_asset_hash = _safe_candidate_id(source_asset_id)
                candidate_reuse_counts[source_asset_id] += 1
                candidate_profile: dict[str, Any] = {
                    "candidate_id": source_asset_hash,
                    "width": None,
                    "height": None,
                    "pixel_count": None,
                    "file_size_bytes": candidate_file_sizes.get(resolved_candidate_path),
                    "feature_cache_hit": None,
                    "keypoint_count": 0,
                    "descriptor_count": 0,
                    "descriptor_shape": None,
                    "image_decode_seconds": 0.0,
                    "grayscale_or_preprocess_seconds": 0.0,
                    "sift_detect_compute_seconds": 0.0,
                    "feature_cache_lookup_seconds": 0.0,
                    "candidate_feature_seconds": 0.0,
                    "evidence_timing": {
                        "bf_knn_match_seconds": 0.0,
                        "lowe_ratio_filter_seconds": 0.0,
                        "homography_ransac_seconds": 0.0,
                        "other_score_evidence_seconds": 0.0,
                        "total_seconds": 0.0,
                    },
                    "evidence_present": False,
                }
                candidate_feature_started = time.perf_counter()
                candidate_features, candidate_profile = retriever.profile_candidate_features(
                    candidate_path,
                    candidate_profile,
                )
                candidate_feature_seconds = time.perf_counter() - candidate_feature_started
                candidate_profile["candidate_feature_seconds"] = candidate_feature_seconds
                candidate_feature_times.append(candidate_feature_seconds)
                if candidate_profile["feature_cache_hit"]:
                    candidate_feature_cache_hit_times.append(candidate_feature_seconds)
                else:
                    candidate_feature_cache_miss_times.append(candidate_feature_seconds)
                candidate_image_records.append(candidate_profile)
                candidate_feature_records.append(candidate_profile)
                candidate_feature_decode_times.append(
                    float(candidate_profile["image_decode_seconds"])
                )
                candidate_feature_preprocess_times.append(
                    float(candidate_profile["grayscale_or_preprocess_seconds"])
                )
                candidate_feature_sift_times.append(
                    float(candidate_profile["sift_detect_compute_seconds"])
                )
                candidate_feature_lookup_times.append(
                    float(candidate_profile["feature_cache_lookup_seconds"])
                )

                evidence = None
                if candidate_features is not None:
                    evidence_started = time.perf_counter()
                    retriever._active_evidence_record = candidate_profile
                    try:
                        evidence = retriever._evidence(
                            source_asset_id=source_asset_id,
                            panel_features=panel_features,
                            candidate_features=candidate_features,
                        )
                    finally:
                        retriever._active_evidence_record = None
                    candidate_evidence_seconds = time.perf_counter() - evidence_started
                    candidate_evidence_times.append(candidate_evidence_seconds)
                    candidate_evidence_total_times.append(
                        float(candidate_profile["evidence_timing"]["total_seconds"])
                    )
                    candidate_bf_match_times.append(
                        float(
                            candidate_profile["evidence_timing"][
                                "bf_knn_match_seconds"
                            ]
                        )
                    )
                    candidate_lowe_times.append(
                        float(
                            candidate_profile["evidence_timing"][
                                "lowe_ratio_filter_seconds"
                            ]
                        )
                    )
                    candidate_ransac_times.append(
                        float(
                            candidate_profile["evidence_timing"][
                                "homography_ransac_seconds"
                            ]
                        )
                    )
                    candidate_other_evidence_times.append(
                        float(
                            candidate_profile["evidence_timing"][
                                "other_score_evidence_seconds"
                            ]
                        )
                    )
                    candidate_profile["evidence_present"] = evidence is not None
                candidate_step_times.append(time.perf_counter() - candidate_started)
                candidate_profile["candidate_step_seconds"] = candidate_step_times[-1]
                if evidence is not None:
                    candidate_profile["score"] = evidence.score
                    candidate_profile["inliers"] = evidence.inliers
                    candidate_profile["inlier_ratio"] = evidence.inlier_ratio
                if evidence is not None:
                    strong.append((rank, evidence))
                candidate_evaluations.append(candidate_profile)

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

    candidate_pixel_counts = [
        int(record["pixel_count"])
        for record in candidate_image_records
        if record.get("pixel_count") is not None
    ]
    candidate_widths = [
        int(record["width"])
        for record in candidate_image_records
        if record.get("width") is not None
    ]
    candidate_heights = [
        int(record["height"])
        for record in candidate_image_records
        if record.get("height") is not None
    ]
    candidate_file_sizes_values = [
        int(record["file_size_bytes"])
        for record in candidate_image_records
        if record.get("file_size_bytes") is not None
    ]
    candidate_descriptor_counts = [
        int(record.get("descriptor_count") or 0) for record in candidate_feature_records
    ]
    panel_descriptor_counts = [
        int(record.get("descriptor_count") or 0) for record in panel_feature_records
    ]

    candidate_descriptor_shapes = Counter(
        "x".join(str(value) for value in record["descriptor_shape"])
        for record in candidate_feature_records
        if record.get("descriptor_shape") is not None
    )
    panel_descriptor_shapes = Counter(
        "x".join(str(value) for value in record["descriptor_shape"])
        for record in panel_feature_records
        if record.get("descriptor_shape") is not None
    )
    candidate_reuse_histogram = Counter(
        _reuse_bucket(count) for count in candidate_reuse_counts.values()
    )
    total_candidate_evaluations = len(candidate_evaluations)
    unique_candidate_source_count = len(candidate_reuse_counts)
    repeated_candidate_evaluations = (
        total_candidate_evaluations - unique_candidate_source_count
    )
    top_reused_candidates = [
        {
            "candidate_id": _safe_candidate_id(source_asset_id),
            "evaluation_count": count,
        }
        for source_asset_id, count in sorted(
            candidate_reuse_counts.items(),
            key=lambda item: (-item[1], _safe_candidate_id(item[0])),
        )[:10]
    ]

    sample_panel_ids = [str(row["panel_id"]) for row in sample]
    sample_reference = {
        "path": str(DEFAULT_SAMPLE_REFERENCE_JSON.resolve()),
        "available": DEFAULT_SAMPLE_REFERENCE_JSON.is_file(),
        "sampled_panel_ids_match": None,
    }
    if sample_panel_ids and DEFAULT_SAMPLE_REFERENCE_JSON.is_file():
        reference_payload = json.loads(
            DEFAULT_SAMPLE_REFERENCE_JSON.read_text(encoding="utf-8")
        )
        reference_ids = [
            str(row["panel_id"])
            for row in reference_payload.get("sampled_rows", [])
            if isinstance(row, dict) and "panel_id" in row
        ]
        sample_reference["sampled_panel_ids_match"] = reference_ids == sample_panel_ids

    pixel_sift_pairs = [
        (float(record["pixel_count"]), float(record["sift_detect_compute_seconds"]))
        for record in candidate_evaluations
        if record.get("pixel_count") is not None
    ]
    descriptor_match_pairs = [
        (
            float(record.get("descriptor_count") or 0),
            float(record["evidence_timing"]["bf_knn_match_seconds"]),
        )
        for record in candidate_evaluations
    ]
    pixel_sift_x, pixel_sift_y = zip(*pixel_sift_pairs) if pixel_sift_pairs else ((), ())
    descriptor_match_x, descriptor_match_y = (
        zip(*descriptor_match_pairs) if descriptor_match_pairs else ((), ())
    )

    candidate_image_stats = {
        "evaluation_count": len(candidate_image_records),
        "decoded_evaluation_count": len(candidate_pixel_counts),
        "width": _distribution(candidate_widths),
        "height": _distribution(candidate_heights),
        "pixel_count": _distribution(candidate_pixel_counts),
        "file_size_bytes": _distribution(candidate_file_sizes_values),
        "pixel_count_histogram": _histogram(
            candidate_pixel_counts,
            _pixel_bucket,
            _PIXEL_HISTOGRAM_LABELS,
        ),
    }
    candidate_feature_stats = {
        "evaluation_count": len(candidate_feature_records),
        "keypoint_count": _distribution(
            [int(record.get("keypoint_count") or 0) for record in candidate_feature_records]
        ),
        "descriptor_count": _distribution(candidate_descriptor_counts),
        "descriptor_shape_counts": dict(candidate_descriptor_shapes),
        "descriptor_count_histogram": _histogram(
            candidate_descriptor_counts,
            _descriptor_bucket,
            _DESCRIPTOR_HISTOGRAM_LABELS,
        ),
    }
    panel_feature_stats = {
        "evaluation_count": len(panel_feature_records),
        "keypoint_count": _distribution(
            [int(record.get("keypoint_count") or 0) for record in panel_feature_records]
        ),
        "descriptor_count": _distribution(panel_descriptor_counts),
        "descriptor_shape_counts": dict(panel_descriptor_shapes),
    }
    candidate_reuse = {
        "total_candidate_evaluations": total_candidate_evaluations,
        "unique_candidate_source_count": unique_candidate_source_count,
        "repeated_candidate_evaluations": repeated_candidate_evaluations,
        "candidate_reuse_ratio": (
            repeated_candidate_evaluations / total_candidate_evaluations
            if total_candidate_evaluations
            else 0.0
        ),
        "evaluation_count_histogram": {
            label: candidate_reuse_histogram.get(label, 0)
            for label in ("1", "2", "3-5", "6-10", ">10")
        },
        "top_reused_candidates": top_reused_candidates,
    }

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
        "sampled_panel_ids": sample_panel_ids,
        "sample_reference": sample_reference,
        "candidate_image_stats": candidate_image_stats,
        "candidate_feature_stats": candidate_feature_stats,
        "panel_feature_stats": panel_feature_stats,
        "candidate_reuse": candidate_reuse,
        "correlations": {
            "method": "pearson",
            "pixel_count_vs_sift_detect_compute": _pearson(
                list(pixel_sift_x), list(pixel_sift_y)
            ),
            "descriptor_count_vs_bf_knn_match": _pearson(
                list(descriptor_match_x), list(descriptor_match_y)
            ),
        },
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
            "candidate_feature_cache_hit_timing": _timing_distribution(
                candidate_feature_cache_hit_times
            ),
            "candidate_feature_cache_miss_timing": _timing_distribution(
                candidate_feature_cache_miss_times
            ),
            "candidate_feature_decomposition": {
                "image_decode": _timing_distribution(candidate_feature_decode_times),
                "grayscale_or_preprocess": _timing_distribution(
                    candidate_feature_preprocess_times
                ),
                "sift_detect_compute": _timing_distribution(candidate_feature_sift_times),
                "feature_cache_lookup": _timing_distribution(
                    candidate_feature_lookup_times
                ),
            },
            "candidate_evidence_decomposition": {
                "bf_knn_match": _timing_distribution(candidate_bf_match_times),
                "lowe_ratio_filter": _timing_distribution(candidate_lowe_times),
                "homography_ransac": _timing_distribution(candidate_ransac_times),
                "other_score_evidence": _timing_distribution(
                    candidate_other_evidence_times
                ),
                "total": _timing_distribution(candidate_evidence_total_times),
            },
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
        "candidate_evaluations": candidate_evaluations,
    }


def main() -> int:
    args = build_parser().parse_args()
    payload = evaluate(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {
        key: value
        for key, value in payload.items()
        if key not in {"sampled_rows", "candidate_evaluations", "sampled_panel_ids"}
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not payload["source_root_mutated"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
