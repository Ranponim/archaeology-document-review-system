from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

from app.services.panel_provenance_evaluation import (  # noqa: E402
    classify_revision_collisions,
    recall_at_k,
)
from app.services.plate_parser import PlateParser  # noqa: E402
from app.services.visual_asset_matcher import VisualAssetMatcher  # noqa: E402


IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg"})
DEFAULT_MINIMUM_SCORE = 0.97
DEFAULT_MINIMUM_MARGIN = 0.03
DEFAULT_TOP_K = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only local /src E2E for revision-aware plate-panel provenance. "
            "All unit/integration regression belongs in CI; this tool is only for "
            "the real local corpus acceptance gate."
        )
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--gold", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=REPO_ROOT / "docs" / "local_panel_provenance_acceptance.json")
    parser.add_argument("--output-report", type=Path, default=REPO_ROOT / "docs" / "local_panel_provenance_acceptance.md")
    parser.add_argument(
        "--plate-pdf",
        action="append",
        default=[],
        help="Optional plate PDF path relative to source root; repeat for multiple revisions.",
    )
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--minimum-score", type=float, default=DEFAULT_MINIMUM_SCORE)
    parser.add_argument("--minimum-margin", type=float, default=DEFAULT_MINIMUM_MARGIN)
    parser.add_argument(
        "--limit-panels",
        type=int,
        default=None,
        help="Debug-only cap. Omit for the required full local E2E.",
    )
    return parser


def assert_output_outside_source(source_root: Path, output: Path) -> None:
    source = source_root.resolve()
    target = output.resolve()
    if target == source or source in target.parents:
        raise ValueError(f"output must be outside source root: {output}")


def _tree_snapshot(source_root: Path) -> tuple[tuple[str, int, int], ...]:
    root = source_root.resolve()
    rows = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        stat = path.stat()
        rows.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
    return tuple(sorted(rows))


def _head_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def discover_plate_pdfs(source_root: Path, explicit: Iterable[str]) -> list[Path]:
    root = source_root.resolve()
    explicit_values = [str(value).strip() for value in explicit if str(value).strip()]
    if explicit_values:
        paths = [(root / value).resolve() for value in explicit_values]
        for path in paths:
            if root not in path.parents or not path.is_file():
                raise FileNotFoundError(f"plate PDF not found under source root: {path}")
        return sorted(paths, key=lambda path: _relative(root, path))

    paths = [
        path.resolve()
        for path in root.rglob("*.pdf")
        if "도판" in path.name and "목차" not in path.name
    ]
    if not paths:
        raise FileNotFoundError(
            "no plate PDFs containing '도판' were found; pass --plate-pdf explicitly"
        )
    return sorted(paths, key=lambda path: _relative(root, path))


def discover_candidate_images(source_root: Path) -> list[Path]:
    root = source_root.resolve()
    return sorted(
        (
            path.resolve()
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ),
        key=lambda path: _relative(root, path),
    )


def _load_gold(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("rows")
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError("gold must be a CSV or a JSON row list")
    return [dict(row) for row in payload]


def _candidate_matrix(
    matcher: VisualAssetMatcher,
    source_root: Path,
    candidate_paths: list[Path],
):
    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover - local environment contract
        raise RuntimeError(
            "local panel E2E requires numpy for vectorized 2,750 x 1,032 scoring; "
            "install it in the local evaluation environment"
        ) from error

    asset_ids: list[str] = []
    valid_paths: list[Path] = []
    view_rows: list[Any] = []
    owner_rows: list[int] = []
    invalid: list[str] = []

    for path in candidate_paths:
        asset_id = _relative(source_root, path)
        try:
            fingerprints = matcher._candidate_fingerprints_path(path)
        except (OSError, ValueError):
            invalid.append(asset_id)
            continue
        if not fingerprints:
            invalid.append(asset_id)
            continue
        owner_index = len(asset_ids)
        asset_ids.append(asset_id)
        valid_paths.append(path)
        for fingerprint in fingerprints:
            view_rows.append(np.frombuffer(fingerprint, dtype=np.uint8))
            owner_rows.append(owner_index)

    if not view_rows:
        raise RuntimeError("no decodable JPG candidates were found")

    matrix = np.stack(view_rows).astype(np.int16, copy=False)
    owners = np.asarray(owner_rows, dtype=np.int32)
    return asset_ids, valid_paths, matrix, owners, invalid


def _score_panel(panel_fingerprint: bytes, matrix, owners, asset_ids: list[str], top_k: int):
    import numpy as np

    panel = np.frombuffer(panel_fingerprint, dtype=np.uint8).astype(np.int16)
    errors = np.abs(matrix - panel).sum(axis=1, dtype=np.int64)
    view_scores = 1.0 - errors / (255.0 * panel.size)
    asset_scores = np.full(len(asset_ids), -np.inf, dtype=np.float64)
    np.maximum.at(asset_scores, owners, view_scores)

    available = min(top_k, len(asset_ids))
    if available == 0:
        return []
    if available == len(asset_ids):
        indices = np.arange(len(asset_ids))
    else:
        indices = np.argpartition(-asset_scores, available - 1)[:available]
    ordered = sorted(indices.tolist(), key=lambda index: (-float(asset_scores[index]), asset_ids[index]))
    return [
        {"source_asset_id": asset_ids[index], "score": round(float(asset_scores[index]), 9)}
        for index in ordered
    ]


class _PdfPanelFingerprintCache:
    def __init__(self, matcher: VisualAssetMatcher, pdf_path: Path) -> None:
        self.matcher = matcher
        self.doc = pymupdf.open(str(pdf_path))
        self._page_occurrences: dict[int, tuple[tuple[Any, int], ...]] = {}
        self._xref_fingerprints: dict[int, bytes | None] = {}

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

    def _xref_fingerprint(self, xref: int) -> bytes | None:
        if xref in self._xref_fingerprints:
            return self._xref_fingerprints[xref]
        fingerprint = None
        extracted = self.doc.extract_image(xref)
        data = extracted.get("image")
        if data:
            try:
                with Image.open(BytesIO(data)) as image:
                    image.load()
                    fingerprint = self.matcher._fingerprint_image(image)
            except (OSError, ValueError):
                fingerprint = None
        self._xref_fingerprints[xref] = fingerprint
        return fingerprint

    def panel_fingerprint(
        self,
        physical_page: int,
        bbox: tuple[float, float, float, float],
    ) -> bytes | None:
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
        return self._xref_fingerprint(next(iter(best_xrefs)))


def _deterministic_status(
    ranked: list[dict[str, Any]],
    minimum_score: float,
    minimum_margin: float,
) -> tuple[str, float | None, float | None, str | None]:
    if not ranked:
        return "NO_CANDIDATE", None, None, None
    best = float(ranked[0]["score"])
    second = float(ranked[1]["score"]) if len(ranked) > 1 else None
    margin = best - second if second is not None else None
    best_source = str(ranked[0]["source_asset_id"])
    if best < minimum_score:
        return "BELOW_SCORE", best, margin, best_source
    if margin is not None and margin < minimum_margin:
        return "AMBIGUOUS_MARGIN", best, margin, best_source
    return "VERIFIED", best, margin, best_source


def _apply_revision_uniqueness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    verified = [
        {
            "panel_id": row["panel_id"],
            "uniqueness_scope_id": row["uniqueness_scope_id"],
            "source_asset_id": row["best_source_asset_id"],
        }
        for row in rows
        if row["deterministic_status"] == "VERIFIED" and row.get("best_source_asset_id")
    ]
    metrics = classify_revision_collisions(verified)

    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in verified:
        groups[(item["uniqueness_scope_id"], item["source_asset_id"])].append(item["panel_id"])
    collision_keys = {key for key, panel_ids in groups.items() if len(panel_ids) > 1}

    for row in rows:
        if row["deterministic_status"] != "VERIFIED":
            row["final_status"] = "UNRESOLVED"
            row["verified_source_asset_id"] = None
            continue
        key = (row["uniqueness_scope_id"], row["best_source_asset_id"])
        if key in collision_keys:
            row["final_status"] = "UNRESOLVED_COLLISION"
            row["verified_source_asset_id"] = None
        else:
            row["final_status"] = "DERIVED_VERIFIED"
            row["verified_source_asset_id"] = row["best_source_asset_id"]
    return metrics


def _gold_metrics(rows: list[dict[str, Any]], gold_path: Path | None) -> dict[str, Any] | None:
    if gold_path is None:
        return None
    gold_rows = _load_gold(gold_path)
    evaluation_by_id = {str(row["panel_id"]): row for row in rows}
    recall_rows = []
    labelled = 0
    missing = 0
    for gold in gold_rows:
        panel_id = str(gold.get("panel_id") or "").strip()
        if not panel_id:
            continue
        evaluation = evaluation_by_id.get(panel_id)
        if evaluation is None:
            missing += 1
            continue
        correct = str(gold.get("correct_source_asset_id") or "").strip() or None
        if correct is not None:
            labelled += 1
        recall_rows.append(
            {
                "panel_id": panel_id,
                "correct_source_asset_id": correct,
                "ranked_source_asset_ids": [
                    candidate["source_asset_id"] for candidate in evaluation["candidates"]
                ],
            }
        )
    metrics = recall_at_k(recall_rows, ks=(1, 3, 5))
    return {
        **metrics,
        "gold_row_count": len(gold_rows),
        "gold_labelled_count": labelled,
        "gold_missing_panel_count": missing,
    }


def _markdown(payload: dict[str, Any]) -> str:
    corpus = payload["corpus"]
    results = payload["results"]
    safety = payload["safety"]
    collision = results["revision_collision_metrics"]
    gold = payload.get("gold_metrics")
    lines = [
        "# Local Panel Provenance Acceptance",
        "",
        f"- Measurement HEAD: `{payload.get('measurement_head') or 'unknown'}`",
        f"- Source root: `{payload['source_root']}` (read-only: `{payload['source_root_read_only']}`)",
        f"- Plate PDFs: **{corpus['plate_pdfs']}**",
        f"- JPG candidates: **{corpus['jpg_candidates']}** (decodable: {corpus['decodable_jpg_candidates']})",
        f"- Panels: **{corpus['total_panels']}** total / **{corpus['segmented_panels']}** segmented",
        "",
        "## Deterministic results",
        "",
        f"- Local VERIFIED before batch uniqueness: **{results['local_verified_count']}**",
        f"- Final DERIVED_VERIFIED: **{results['unique_verified_count']}**",
        f"- Coverage over segmented: **{results['coverage_over_segmented']:.4%}**",
        f"- Within-revision collision groups: **{collision['within_revision_collision_group_count']}**",
        f"- Within-revision collision panels: **{collision['within_revision_collision_panel_count']}**",
        f"- Cross-revision reused JPG sources: **{collision['cross_revision_reuse_source_count']}**",
        "",
        "## Retrieval / gold",
        "",
    ]
    if gold is None:
        lines.append("- No human gold supplied; Recall@K is intentionally not claimed.")
    else:
        lines.extend(
            [
                f"- Gold labelled: **{gold['gold_labelled_count']}**",
                f"- Recall@1: **{gold['recall_at_1']:.4%}**",
                f"- Recall@3: **{gold['recall_at_3']:.4%}**",
                f"- Recall@5: **{gold['recall_at_5']:.4%}**",
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
            f"- threshold bypass: **{safety['threshold_bypass_count']}**",
            f"- within-revision collision promotion: **{safety['within_revision_collision_promotion_count']}**",
            f"- source root mutated: **{safety['source_root_mutated']}**",
            f"- Safety pass: **{safety['safety_pass']}**",
            "",
            "> VLM auto-promotion is disabled. AI-supported decisions require separate gold-set precision validation.",
            "",
        ]
    )
    return "\n".join(lines)


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    source_root = args.source_root.resolve()
    if not source_root.is_dir():
        raise NotADirectoryError(source_root)
    if args.top_k < 1:
        raise ValueError("top-k must be positive")
    if args.limit_panels is not None and args.limit_panels <= 0:
        raise ValueError("limit-panels must be positive")
    assert_output_outside_source(source_root, args.output_json)
    assert_output_outside_source(source_root, args.output_report)
    if args.gold is not None and not args.gold.is_file():
        raise FileNotFoundError(args.gold)

    before = _tree_snapshot(source_root)
    started = time.perf_counter()
    matcher = VisualAssetMatcher(
        minimum_score=args.minimum_score,
        minimum_margin=args.minimum_margin,
    )
    plate_pdfs = discover_plate_pdfs(source_root, args.plate_pdf)
    candidate_paths = discover_candidate_images(source_root)
    asset_ids, valid_paths, matrix, owners, invalid_candidates = _candidate_matrix(
        matcher, source_root, candidate_paths
    )

    parser = PlateParser()
    rows: list[dict[str, Any]] = []
    parse_counts = []
    stop = False

    for pdf_path in plate_pdfs:
        parse_started = time.perf_counter()
        parsed = parser.parse(pdf_path)
        pdf_relative = _relative(source_root, pdf_path)
        scope_id = f"plate-pdf:{pdf_relative}"
        cache = _PdfPanelFingerprintCache(matcher, pdf_path)
        pdf_panel_count = 0
        pdf_segmented = 0
        pdf_insufficient = 0
        try:
            for plate in parsed.plates:
                for panel in plate.panels:
                    if args.limit_panels is not None and len(rows) >= args.limit_panels:
                        stop = True
                        break
                    pdf_panel_count += 1
                    panel_id = f"panel:{scope_id}:{plate.number}:{panel.panel_index}"
                    base = {
                        "panel_id": panel_id,
                        "uniqueness_scope_id": scope_id,
                        "pdf": pdf_relative,
                        "plate_number": str(plate.number),
                        "physical_page": int(panel.physical_page or plate.physical_page),
                        "panel_index": int(panel.panel_index),
                        "bbox_status": panel.bbox_status,
                        "bbox": list(panel.bbox) if panel.bbox is not None else None,
                        "caption": panel.caption,
                    }
                    if panel.bbox is None or panel.bbox_status != "segmented":
                        pdf_insufficient += 1
                        rows.append(
                            {
                                **base,
                                "deterministic_status": "INSUFFICIENT_PANEL",
                                "best_score": None,
                                "margin": None,
                                "best_source_asset_id": None,
                                "candidates": [],
                            }
                        )
                        continue

                    pdf_segmented += 1
                    fingerprint = cache.panel_fingerprint(
                        int(panel.physical_page or plate.physical_page),
                        tuple(float(value) for value in panel.bbox),
                    )
                    if fingerprint is None:
                        rows.append(
                            {
                                **base,
                                "deterministic_status": "INSUFFICIENT_PANEL",
                                "best_score": None,
                                "margin": None,
                                "best_source_asset_id": None,
                                "candidates": [],
                            }
                        )
                        continue
                    ranked = _score_panel(fingerprint, matrix, owners, asset_ids, args.top_k)
                    status, best_score, margin, best_source = _deterministic_status(
                        ranked, args.minimum_score, args.minimum_margin
                    )
                    rows.append(
                        {
                            **base,
                            "deterministic_status": status,
                            "best_score": best_score,
                            "margin": round(margin, 9) if margin is not None else None,
                            "best_source_asset_id": best_source,
                            "candidates": ranked,
                        }
                    )
                if stop:
                    break
        finally:
            cache.close()

        parse_counts.append(
            {
                "pdf": pdf_relative,
                "plates": len(parsed.plates),
                "panels": pdf_panel_count,
                "segmented": pdf_segmented,
                "insufficient": pdf_insufficient,
                "seconds": round(time.perf_counter() - parse_started, 3),
            }
        )
        if stop:
            break

    collision_metrics = _apply_revision_uniqueness(rows)
    after = _tree_snapshot(source_root)
    source_mutated = before != after

    status_counts = Counter(str(row["deterministic_status"]) for row in rows)
    final_counts = Counter(str(row["final_status"]) for row in rows)
    segmented_count = sum(row["bbox_status"] == "segmented" for row in rows)
    verified_count = final_counts["DERIVED_VERIFIED"]

    threshold_bypass = sum(
        1
        for row in rows
        if row["final_status"] == "DERIVED_VERIFIED"
        and (
            row["best_score"] is None
            or float(row["best_score"]) < args.minimum_score
            or (
                row["margin"] is not None
                and float(row["margin"]) < args.minimum_margin
            )
        )
    )
    collision_promotions = 0
    collision_groups: dict[tuple[str, str], int] = Counter(
        (row["uniqueness_scope_id"], row["best_source_asset_id"])
        for row in rows
        if row["deterministic_status"] == "VERIFIED" and row.get("best_source_asset_id")
    )
    for row in rows:
        if row["final_status"] != "DERIVED_VERIFIED":
            continue
        if collision_groups[(row["uniqueness_scope_id"], row["best_source_asset_id"])] > 1:
            collision_promotions += 1

    safety = {
        "filename_only_promotion_count": 0,
        "path_only_promotion_count": 0,
        "caption_only_promotion_count": 0,
        "threshold_bypass_count": threshold_bypass,
        "within_revision_collision_promotion_count": collision_promotions,
        "source_root_mutated": source_mutated,
    }
    safety["safety_pass"] = (
        not source_mutated
        and threshold_bypass == 0
        and collision_promotions == 0
    )

    payload = {
        "measurement_head": _head_sha(),
        "measurement_time": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "source_root_read_only": not source_mutated,
        "algorithm": {
            "matcher": "VisualAssetMatcher",
            "minimum_score": args.minimum_score,
            "minimum_margin": args.minimum_margin,
            "top_k": args.top_k,
            "candidate_fingerprint_cache": True,
            "pdf_page_image_cache": True,
            "vectorized_scoring_only_in_runner": True,
            "production_policy_changed": False,
            "vlm_auto_promotion_enabled": False,
        },
        "corpus": {
            "plate_pdfs": len(plate_pdfs),
            "jpg_candidates": len(candidate_paths),
            "decodable_jpg_candidates": len(valid_paths),
            "undecodable_jpg_candidates": len(invalid_candidates),
            "total_panels": len(rows),
            "segmented_panels": segmented_count,
            "parse_counts": parse_counts,
        },
        "results": {
            "deterministic_status_counts": dict(sorted(status_counts.items())),
            "final_status_counts": dict(sorted(final_counts.items())),
            "local_verified_count": status_counts["VERIFIED"],
            "unique_verified_count": verified_count,
            "coverage_over_total": verified_count / len(rows) if rows else 0.0,
            "coverage_over_segmented": verified_count / segmented_count if segmented_count else 0.0,
            "revision_collision_metrics": collision_metrics,
        },
        "gold_metrics": _gold_metrics(rows, args.gold),
        "safety": safety,
        "invalid_candidate_files": invalid_candidates,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "rows": rows,
    }
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
