from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any

import pymupdf
from PIL import Image, ImageOps

import evaluate_panel_provenance as base

from app.services.geometric_visual_retriever import (
    DEFAULT_CANDIDATE_MAX_EDGE,
    DEFAULT_SIFT_NFEATURES,
    GeometricVisualRetriever,
)
from app.services.visual_asset_matcher import VisualAssetMatcher


DEFAULT_GEOMETRIC_CANDIDATE_POOL = 50
DEFAULT_GEOMETRIC_MINIMUM_MARGIN = 0.08
DEFAULT_GEOMETRIC_CANDIDATE_MAX_EDGE = DEFAULT_CANDIDATE_MAX_EDGE
DEFAULT_GEOMETRIC_SIFT_NFEATURES = DEFAULT_SIFT_NFEATURES


def build_parser() -> argparse.ArgumentParser:
    parser = base.build_parser()
    parser.description = (
        "Read-only local /src hybrid panel provenance E2E. Tier 0 keeps the "
        "existing pixel verifier; unresolved segmented panels use a bounded "
        "pixel shortlist followed by SIFT/RANSAC geometric verification."
    )
    parser.add_argument(
        "--geometric-candidate-pool",
        type=int,
        default=DEFAULT_GEOMETRIC_CANDIDATE_POOL,
        help="Pixel shortlist size passed to SIFT/RANSAC for unresolved panels.",
    )
    parser.add_argument(
        "--geometric-minimum-margin",
        type=float,
        default=DEFAULT_GEOMETRIC_MINIMUM_MARGIN,
        help="Required SIFT/RANSAC score separation from a second eligible candidate.",
    )
    parser.add_argument(
        "--geometric-candidate-max-edge",
        type=int,
        default=DEFAULT_GEOMETRIC_CANDIDATE_MAX_EDGE,
        help="Maximum candidate-image edge used for SIFT feature extraction.",
    )
    parser.add_argument(
        "--geometric-sift-nfeatures",
        type=int,
        default=DEFAULT_GEOMETRIC_SIFT_NFEATURES,
        help="Maximum retained SIFT features per candidate image.",
    )
    parser.set_defaults(
        output_json=base.REPO_ROOT / "docs" / "local_panel_provenance_hybrid_latest.json",
        output_report=base.REPO_ROOT / "docs" / "local_panel_provenance_hybrid_latest.md",
    )
    return parser


class _PdfPanelImageCache:
    def __init__(self, matcher: VisualAssetMatcher, pdf_path: Path) -> None:
        self.matcher = matcher
        self.doc = pymupdf.open(str(pdf_path))
        self._page_occurrences: dict[int, tuple[tuple[Any, int], ...]] = {}
        self._xref_images: dict[int, Image.Image | None] = {}

    def close(self) -> None:
        self.doc.close()

    def _occurrences(self, physical_page: int) -> tuple[tuple[Any, int], ...]:
        cached = self._page_occurrences.get(physical_page)
        if cached is not None:
            return cached
        page = self.doc[physical_page - 1]
        rows: list[tuple[Any, int]] = []
        for image_info in page.get_images(full=True):
            xref = int(image_info[0])
            for rect in page.get_image_rects(xref):
                rows.append((rect, xref))
        value = tuple(rows)
        self._page_occurrences[physical_page] = value
        return value

    def _xref_image(self, xref: int) -> Image.Image | None:
        if xref in self._xref_images:
            image = self._xref_images[xref]
            return image.copy() if image is not None else None

        image = None
        extracted = self.doc.extract_image(xref)
        data = extracted.get("image")
        if data:
            try:
                with Image.open(BytesIO(data)) as opened:
                    opened.load()
                    image = ImageOps.exif_transpose(opened).convert("RGB").copy()
            except (OSError, ValueError):
                image = None
        self._xref_images[xref] = image
        return image.copy() if image is not None else None

    def panel_image(
        self,
        physical_page: int,
        bbox: tuple[float, float, float, float],
    ) -> Image.Image | None:
        if physical_page < 1 or physical_page > len(self.doc):
            return None
        page = self.doc[physical_page - 1]
        target = self.matcher._target_rect(page, bbox)
        matches: list[tuple[float, int]] = []
        for rect, xref in self._occurrences(physical_page):
            score = self.matcher._rect_similarity(rect, target)
            if score >= 0.90:
                matches.append((score, xref))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        best_score = matches[0][0]
        best_xrefs = {xref for score, xref in matches if abs(score - best_score) < 1e-6}
        if len(best_xrefs) != 1:
            return None
        return self._xref_image(next(iter(best_xrefs)))


def _geometry_key(row: dict[str, Any]) -> tuple[str, int, tuple[float, ...]] | None:
    bbox = row.get("bbox")
    if not bbox:
        return None
    return (
        str(row["uniqueness_scope_id"]),
        int(row["physical_page"]),
        tuple(round(float(value), 9) for value in bbox),
    )


def _hybrid_gold_metrics(
    rows: list[dict[str, Any]],
    gold_path: Path | None,
) -> dict[str, Any] | None:
    if gold_path is None:
        return None
    gold_rows = base._load_gold(gold_path)
    by_panel = {str(row["panel_id"]): row for row in rows}
    recall_rows = []
    labelled = 0
    missing = 0
    for gold in gold_rows:
        panel_id = str(gold.get("panel_id") or "").strip()
        if not panel_id:
            continue
        evaluation = by_panel.get(panel_id)
        if evaluation is None:
            missing += 1
            continue
        correct = str(gold.get("correct_source_asset_id") or "").strip() or None
        if correct is not None:
            labelled += 1

        ranked = [candidate["source_asset_id"] for candidate in evaluation["candidates"]]
        geometric_source = evaluation.get("geometric_source_asset_id")
        if geometric_source:
            ranked = [geometric_source] + [item for item in ranked if item != geometric_source]
        recall_rows.append(
            {
                "panel_id": panel_id,
                "correct_source_asset_id": correct,
                "ranked_source_asset_ids": ranked,
            }
        )
    metrics = base.recall_at_k(recall_rows, ks=(1, 3, 5))
    return {
        **metrics,
        "gold_row_count": len(gold_rows),
        "gold_labelled_count": labelled,
        "gold_missing_panel_count": missing,
    }


def _apply_hybrid_uniqueness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    geometries_by_source: dict[tuple[str, str], set[tuple[str, int, tuple[float, ...]]]] = defaultdict(set)
    rows_by_geometry: Counter[tuple[str, int, tuple[float, ...]]] = Counter()
    source_scopes: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        geometry = _geometry_key(row)
        if geometry is not None and row.get("bbox_status") == "segmented":
            rows_by_geometry[geometry] += 1
        source = row.get("local_source_asset_id")
        if not source or geometry is None:
            continue
        scope = str(row["uniqueness_scope_id"])
        geometries_by_source[(scope, str(source))].add(geometry)
        source_scopes[str(source)].add(scope)

    collision_keys = {
        key for key, geometries in geometries_by_source.items() if len(geometries) > 1
    }
    collision_rows = 0
    collision_geometries: set[tuple[str, int, tuple[float, ...]]] = set()
    verified_geometries: set[tuple[str, int, tuple[float, ...]]] = set()

    for row in rows:
        source = row.get("local_source_asset_id")
        geometry = _geometry_key(row)
        if not source or geometry is None:
            row["final_status"] = "UNRESOLVED"
            row["verified_source_asset_id"] = None
            continue
        key = (str(row["uniqueness_scope_id"]), str(source))
        if key in collision_keys:
            row["final_status"] = "UNRESOLVED_COLLISION"
            row["verified_source_asset_id"] = None
            collision_rows += 1
            collision_geometries.add(geometry)
        else:
            row["final_status"] = "DERIVED_VERIFIED"
            row["verified_source_asset_id"] = source
            verified_geometries.add(geometry)

    return {
        "within_revision_collision_group_count": len(collision_keys),
        "within_revision_collision_panel_count": collision_rows,
        "within_revision_collision_geometry_count": len(collision_geometries),
        "cross_revision_reuse_source_count": sum(
            1 for scopes in source_scopes.values() if len(scopes) > 1
        ),
        "duplicate_geometry_alias_count": sum(max(0, count - 1) for count in rows_by_geometry.values()),
        "segmented_geometry_count": len(rows_by_geometry),
        "verified_geometry_count": len(verified_geometries),
    }


def _markdown(payload: dict[str, Any]) -> str:
    corpus = payload["corpus"]
    results = payload["results"]
    safety = payload["safety"]
    collision = results["revision_collision_metrics"]
    gold = payload.get("gold_metrics")
    method_counts = results["local_match_method_counts"]
    lines = [
        "# Local Hybrid Panel Provenance Acceptance",
        "",
        f"- Measurement HEAD: `{payload.get('measurement_head') or 'unknown'}`",
        f"- Source root: `{payload['source_root']}` (read-only: `{payload['source_root_read_only']}`)",
        f"- Plate PDFs: **{corpus['plate_pdfs']}**",
        f"- JPG candidates: **{corpus['jpg_candidates']}** (decodable: {corpus['decodable_jpg_candidates']})",
        f"- Panels: **{corpus['total_panels']}** total / **{corpus['segmented_panels']}** segmented",
        "",
        "## Hybrid retrieval",
        "",
        f"- Tier-0 pixel local matches: **{method_counts.get('pixel_thumbnail_similarity', 0)}**",
        f"- Tier-1 SIFT/RANSAC local matches: **{method_counts.get('sift_ransac', 0)}**",
        f"- Final DERIVED_VERIFIED panel rows: **{results['unique_verified_count']}**",
        f"- Final verified physical geometries: **{collision['verified_geometry_count']}**",
        f"- Coverage over segmented rows: **{results['coverage_over_segmented']:.4%}**",
        f"- Coverage over segmented geometries: **{results['coverage_over_segmented_geometries']:.4%}**",
        f"- Geometric attempts: **{results['geometric_attempted_count']}**",
        f"- Geometric strong-evidence rows before uniqueness: **{results['geometric_local_verified_count']}**",
        "",
        "## Collision / parser aliases",
        "",
        f"- Within-revision collision groups: **{collision['within_revision_collision_group_count']}**",
        f"- Collision panel rows: **{collision['within_revision_collision_panel_count']}**",
        f"- Collision physical geometries: **{collision['within_revision_collision_geometry_count']}**",
        f"- Duplicate geometry aliases: **{collision['duplicate_geometry_alias_count']}**",
        f"- Cross-revision reused JPG sources: **{collision['cross_revision_reuse_source_count']}**",
        "",
        "## Gold",
        "",
    ]
    if gold is None:
        lines.append("- No human gold supplied; Recall@K is intentionally not claimed.")
    else:
        lines.extend(
            [
                f"- Gold labelled: **{gold['gold_labelled_count']}**",
                f"- Hybrid Recall@1: **{gold['recall_at_1']:.4%}**",
                f"- Hybrid Recall@3: **{gold['recall_at_3']:.4%}**",
                f"- Hybrid Recall@5: **{gold['recall_at_5']:.4%}**",
            ]
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- filename-only promotion: **{safety['filename_only_promotion_count']}**",
            f"- path-only promotion: **{safety['path_only_promotion_count']}**",
            f"- caption-only promotion: **{safety['caption_only_promotion_count']}**",
            f"- pixel threshold bypass: **{safety['pixel_threshold_bypass_count']}**",
            f"- geometric gate bypass: **{safety['geometric_gate_bypass_count']}**",
            f"- within-revision collision promotion: **{safety['within_revision_collision_promotion_count']}**",
            f"- source root mutated: **{safety['source_root_mutated']}**",
            f"- Safety pass: **{safety['safety_pass']}**",
            "",
            "> VLM auto-promotion is disabled. Geometric matches use image-content evidence only.",
            "",
        ]
    )
    return "\n".join(lines)


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    if args.geometric_candidate_pool < 1:
        raise ValueError("geometric-candidate-pool must be positive")
    if args.geometric_minimum_margin < 0.0:
        raise ValueError("geometric-minimum-margin cannot be negative")
    if args.geometric_candidate_max_edge < 1:
        raise ValueError("geometric-candidate-max-edge must be positive")
    if args.geometric_sift_nfeatures < 1:
        raise ValueError("geometric-sift-nfeatures must be positive")

    source_root = args.source_root.resolve()
    before = base._tree_snapshot(source_root)
    started = time.perf_counter()

    base_args = argparse.Namespace(**vars(args))
    base_args.top_k = max(args.top_k, args.geometric_candidate_pool)
    payload = base.evaluate(base_args)
    baseline_results = payload["results"]
    rows = payload["rows"]

    matcher = VisualAssetMatcher(
        minimum_score=args.minimum_score,
        minimum_margin=args.minimum_margin,
        geometric_candidate_pool=args.geometric_candidate_pool,
        geometric_minimum_margin=args.geometric_minimum_margin,
    )
    retriever = GeometricVisualRetriever(
        candidate_max_edge=args.geometric_candidate_max_edge,
        sift_nfeatures=args.geometric_sift_nfeatures,
    )
    candidate_paths = base.discover_candidate_images(source_root)
    candidate_by_id = {
        base._relative(source_root, path): path.resolve() for path in candidate_paths
    }

    for row in rows:
        row["baseline_final_status"] = row.get("final_status")
        row["baseline_verified_source_asset_id"] = row.get("verified_source_asset_id")
        row["local_match_method"] = None
        row["local_source_asset_id"] = None
        row["geometric_score"] = None
        row["geometric_margin"] = None
        row["geometric_good_matches"] = None
        row["geometric_inliers"] = None
        row["geometric_inlier_ratio"] = None
        if row.get("deterministic_status") == "VERIFIED" and row.get("best_source_asset_id"):
            row["local_match_method"] = "pixel_thumbnail_similarity"
            row["local_source_asset_id"] = row["best_source_asset_id"]

    unresolved_by_pdf: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if (
            row.get("bbox_status") == "segmented"
            and row.get("deterministic_status") in {"BELOW_SCORE", "AMBIGUOUS_MARGIN"}
        ):
            unresolved_by_pdf[str(row["pdf"])].append(row)

    geometric_attempted = 0
    geometric_verified = 0
    geometric_ambiguous = 0
    geometric_no_evidence = 0

    for pdf_relative, pdf_rows in unresolved_by_pdf.items():
        pdf_path = (source_root / pdf_relative).resolve()
        cache = _PdfPanelImageCache(matcher, pdf_path)
        try:
            for row in pdf_rows:
                bbox = row.get("bbox")
                if not bbox:
                    continue
                panel_image = cache.panel_image(
                    int(row["physical_page"]),
                    tuple(float(value) for value in bbox),
                )
                if panel_image is None:
                    continue

                shortlist = []
                for candidate in row.get("candidates", [])[: args.geometric_candidate_pool]:
                    source_asset_id = str(candidate["source_asset_id"])
                    candidate_path = candidate_by_id.get(source_asset_id)
                    if candidate_path is None:
                        continue
                    shortlist.append((SimpleNamespace(id=source_asset_id), candidate_path))
                if not shortlist:
                    continue

                geometric_attempted += 1
                ranked = retriever.rank(
                    panel_image=panel_image,
                    candidates=shortlist,
                    top_k=2,
                )
                if not ranked:
                    geometric_no_evidence += 1
                    continue

                best = ranked[0]
                margin = best.score - ranked[1].score if len(ranked) > 1 else None
                row["geometric_score"] = round(best.score, 9)
                row["geometric_margin"] = round(margin, 9) if margin is not None else None
                row["geometric_good_matches"] = best.good_matches
                row["geometric_inliers"] = best.inliers
                row["geometric_inlier_ratio"] = round(best.inlier_ratio, 9)
                row["geometric_source_asset_id"] = best.source_asset_id

                if margin is not None and margin < args.geometric_minimum_margin:
                    geometric_ambiguous += 1
                    continue

                row["local_match_method"] = "sift_ransac"
                row["local_source_asset_id"] = best.source_asset_id
                geometric_verified += 1
        finally:
            cache.close()

    collision_metrics = _apply_hybrid_uniqueness(rows)
    after = base._tree_snapshot(source_root)
    source_mutated = before != after

    final_counts = Counter(str(row["final_status"]) for row in rows)
    method_counts = Counter(
        str(row["local_match_method"])
        for row in rows
        if row.get("local_match_method")
    )
    segmented_count = sum(row.get("bbox_status") == "segmented" for row in rows)
    verified_count = final_counts["DERIVED_VERIFIED"]
    segmented_geometry_count = collision_metrics["segmented_geometry_count"]
    verified_geometry_count = collision_metrics["verified_geometry_count"]

    pixel_threshold_bypass = sum(
        1
        for row in rows
        if row.get("final_status") == "DERIVED_VERIFIED"
        and row.get("local_match_method") == "pixel_thumbnail_similarity"
        and (
            row.get("best_score") is None
            or float(row["best_score"]) < args.minimum_score
            or (
                row.get("margin") is not None
                and float(row["margin"]) < args.minimum_margin
            )
        )
    )
    geometric_gate_bypass = sum(
        1
        for row in rows
        if row.get("final_status") == "DERIVED_VERIFIED"
        and row.get("local_match_method") == "sift_ransac"
        and (
            row.get("geometric_inliers") is None
            or int(row["geometric_inliers"]) < retriever.minimum_inliers
            or row.get("geometric_inlier_ratio") is None
            or float(row["geometric_inlier_ratio"]) < retriever.minimum_inlier_ratio
            or (
                row.get("geometric_margin") is not None
                and float(row["geometric_margin"]) < args.geometric_minimum_margin
            )
        )
    )

    collision_promotions = 0
    geometries_by_source: dict[tuple[str, str], set[tuple[str, int, tuple[float, ...]]]] = defaultdict(set)
    for row in rows:
        source = row.get("local_source_asset_id")
        geometry = _geometry_key(row)
        if source and geometry is not None:
            geometries_by_source[(str(row["uniqueness_scope_id"]), str(source))].add(geometry)
    for row in rows:
        if row.get("final_status") != "DERIVED_VERIFIED":
            continue
        source = row.get("local_source_asset_id")
        if not source:
            continue
        if len(geometries_by_source[(str(row["uniqueness_scope_id"]), str(source))]) > 1:
            collision_promotions += 1

    safety = {
        "filename_only_promotion_count": 0,
        "path_only_promotion_count": 0,
        "caption_only_promotion_count": 0,
        "pixel_threshold_bypass_count": pixel_threshold_bypass,
        "geometric_gate_bypass_count": geometric_gate_bypass,
        "within_revision_collision_promotion_count": collision_promotions,
        "source_root_mutated": source_mutated,
    }
    safety["safety_pass"] = (
        not source_mutated
        and pixel_threshold_bypass == 0
        and geometric_gate_bypass == 0
        and collision_promotions == 0
    )

    payload["measurement_time"] = datetime.now(timezone.utc).isoformat()
    payload["source_root_read_only"] = not source_mutated
    payload["algorithm"] = {
        "tier_0": "pixel_thumbnail_similarity",
        "minimum_score": args.minimum_score,
        "minimum_margin": args.minimum_margin,
        "tier_1": "sift_ransac",
        "geometric_candidate_pool": args.geometric_candidate_pool,
        "geometric_minimum_margin": args.geometric_minimum_margin,
        "geometric_candidate_max_edge": args.geometric_candidate_max_edge,
        "geometric_sift_nfeatures": args.geometric_sift_nfeatures,
        "minimum_geometric_inliers": retriever.minimum_inliers,
        "minimum_geometric_inlier_ratio": retriever.minimum_inlier_ratio,
        "filename_path_caption_verification": False,
        "vlm_auto_promotion_enabled": False,
    }
    payload["baseline_pixel_results"] = baseline_results
    payload["results"] = {
        "final_status_counts": dict(sorted(final_counts.items())),
        "local_match_method_counts": dict(sorted(method_counts.items())),
        "geometric_attempted_count": geometric_attempted,
        "geometric_local_verified_count": geometric_verified,
        "geometric_ambiguous_count": geometric_ambiguous,
        "geometric_no_evidence_count": geometric_no_evidence,
        "unique_verified_count": verified_count,
        "coverage_over_total": verified_count / len(rows) if rows else 0.0,
        "coverage_over_segmented": verified_count / segmented_count if segmented_count else 0.0,
        "coverage_over_segmented_geometries": (
            verified_geometry_count / segmented_geometry_count
            if segmented_geometry_count
            else 0.0
        ),
        "revision_collision_metrics": collision_metrics,
    }
    payload["gold_metrics"] = _hybrid_gold_metrics(rows, args.gold)
    payload["safety"] = safety
    payload["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return payload


def main() -> int:
    args = build_parser().parse_args()
    payload = evaluate(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_report.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["results"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["safety"], ensure_ascii=False, indent=2))
    if payload["gold_metrics"] is not None:
        print(json.dumps(payload["gold_metrics"], ensure_ascii=False, indent=2))
    return 0 if payload["safety"]["safety_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
