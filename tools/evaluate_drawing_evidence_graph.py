from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.canonical_models import EvidenceLevel  # noqa: E402
from app.domain.drawing_evidence import (  # noqa: E402
    BodyDrawingContext,
    DrawingEvidenceResolution,
    DrawingSourceObservation,
)
from app.services.drawing_evidence_graph_resolver import (  # noqa: E402
    DrawingEvidenceGraphResolver,
)
from app.services.drawing_source_observer import DrawingSourceObserver  # noqa: E402
from app.services.pdf_parser import PDFParser  # noqa: E402

_FILENAME_IDENTIFIER = re.compile(r"(?:도면|삽도)\s*(\d+(?:-\d+)?)", re.IGNORECASE)
_DATE_PREFIX = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?!\d)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only evaluation of drawing evidence graph resolution on /src",
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument(
        "--blinded",
        action="store_true",
        help="Compatibility flag; the evaluator always reports blinded and full runs separately.",
    )
    return parser


def empty_metrics() -> dict:
    return {
        "audit": {
            "adobe_used": False,
            "com_used": False,
            "extendscript_used": False,
            "source_root_read_only": True,
            "resolver_version": DrawingEvidenceGraphResolver.resolver_version,
        },
        "blinded_35": {
            "filename_used_for_scoring": False,
            "silver_label_is_ground_truth": False,
        },
        "full_56": {},
    }


def make_observation(
    *,
    source_asset_id: str,
    source_sha256: str,
    original_name: str,
    raw_text: str,
    internal_numbers: tuple[str, ...] = (),
) -> DrawingSourceObservation:
    return DrawingSourceObservation(
        source_asset_id=source_asset_id,
        source_sha256=source_sha256,
        original_name=original_name,
        raw_text=raw_text,
        internal_numbers=tuple(internal_numbers),
    )


def blind_filename(observation: DrawingSourceObservation) -> DrawingSourceObservation:
    return replace(observation, original_name="blinded.ai")


def filename_label(name: str) -> str | None:
    numbers = {match.group(1) for match in _FILENAME_IDENTIFIER.finditer(Path(name).stem)}
    return next(iter(numbers)) if len(numbers) == 1 else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_output_outside_source(source_root: Path, output: Path) -> None:
    source = source_root.resolve()
    target = output.resolve()
    if target == source or source in target.parents:
        raise ValueError(f"output must not be written inside source root: {output}")


def _date_key(path: Path) -> tuple[int, int, str]:
    match = _DATE_PREFIX.search(path.name)
    if match:
        return int(match.group(1)), int(match.group(2)), path.as_posix()
    return 0, 0, path.as_posix()


def discover_latest_body_pdf(source_root: Path) -> Path:
    candidates = [
        path
        for path in source_root.rglob("*.pdf")
        if "본문" in path.name and "목차" not in path.name
    ]
    if not candidates:
        raise FileNotFoundError("no body PDF containing '본문' was found under source root")
    return max(candidates, key=_date_key)


def _append_context(
    grouped: dict[str, dict],
    number: str,
    text: str,
    source_id: str,
    source_sha256: str | None,
) -> None:
    clean = " ".join(str(text or "").split())
    if not clean:
        return
    item = grouped.setdefault(number, {"texts": [], "ids": [], "sha": source_sha256})
    if clean not in item["texts"]:
        item["texts"].append(clean)
        item["ids"].append(source_id)


def extract_body_contexts(body_pdf: Path) -> list[BodyDrawingContext]:
    parser = PDFParser()
    pages = parser.parse_pdf(body_pdf, mode="report_body", version_id="drawing-eval-body")
    grouped: dict[str, dict] = {}
    body_sha = _sha256(body_pdf)

    for page in pages:
        blocks = sorted(page.text_blocks, key=lambda item: item.order)
        by_order = {block.order: block for block in blocks}
        for block in blocks:
            drawing_numbers = {
                str(ref.number)
                for ref in block.references
                if str(ref.ref_type) == "drawing"
            }
            if not drawing_numbers:
                continue
            neighborhood = [
                by_order[order]
                for order in range(block.order - 2, block.order + 3)
                if order in by_order
            ]
            for number in drawing_numbers:
                for neighbor in neighborhood:
                    _append_context(
                        grouped,
                        number,
                        neighbor.normalized_text or neighbor.text,
                        neighbor.block_id,
                        body_sha,
                    )

        for caption in page.captions:
            drawing_numbers = {
                str(ref.number)
                for ref in caption.references
                if str(ref.ref_type) == "drawing"
            }
            if caption.drawing_number:
                drawing_numbers.add(str(caption.drawing_number))
            for number in drawing_numbers:
                _append_context(
                    grouped,
                    number,
                    caption.raw_text,
                    caption.caption_id,
                    body_sha,
                )

    return [
        BodyDrawingContext(
            number=number,
            raw_texts=tuple(item["texts"]),
            source_node_ids=tuple(item["ids"]),
            source_sha256=item["sha"],
        )
        for number, item in sorted(grouped.items(), key=lambda pair: pair[0])
    ]


def discover_ai_files(source_root: Path) -> list[Path]:
    return sorted(
        (path for path in source_root.rglob("*") if path.is_file() and path.suffix.lower() == ".ai"),
        key=lambda path: path.as_posix(),
    )


def observe_ai_files(source_root: Path) -> tuple[list[DrawingSourceObservation], dict[str, str]]:
    observer = DrawingSourceObserver()
    observations: list[DrawingSourceObservation] = []
    paths: dict[str, str] = {}
    for index, path in enumerate(discover_ai_files(source_root), start=1):
        relative = path.relative_to(source_root).as_posix()
        source_id = f"eval-ai:{index:03d}:{hashlib.sha256(relative.encode('utf-8')).hexdigest()[:12]}"
        sha = _sha256(path)
        asset = SimpleNamespace(id=source_id, sha256=sha, original_name=path.name)
        observation = observer.observe(asset, path)
        observations.append(observation)
        paths[source_id] = relative
    return observations, paths


def _rankings(result: DrawingEvidenceResolution) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for candidate in result.candidates:
        grouped.setdefault(candidate.source_asset_id, []).append(candidate)
    for source_id in grouped:
        grouped[source_id].sort(key=lambda item: (-item.score, item.candidate_number))
    return grouped


def _blinded_metrics(
    observations: list[DrawingSourceObservation],
    result: DrawingEvidenceResolution,
    paths: dict[str, str],
) -> dict:
    labeled = [item for item in observations if filename_label(item.original_name) is not None]
    rankings = _rankings(result)
    top1 = 0
    top3 = 0
    disagreements = []
    no_candidate = []
    for item in labeled:
        hidden = filename_label(item.original_name)
        ranked = rankings.get(item.source_asset_id, [])
        predicted = [candidate.candidate_number for candidate in ranked]
        if predicted and predicted[0] == hidden:
            top1 += 1
        elif predicted:
            disagreements.append(
                {
                    "source": paths.get(item.source_asset_id, item.original_name),
                    "hidden_filename_label": hidden,
                    "top1": predicted[0],
                    "top1_score": ranked[0].score,
                }
            )
        else:
            no_candidate.append(paths.get(item.source_asset_id, item.original_name))
        if hidden in predicted[:3]:
            top3 += 1

    labeled_ids = {item.source_asset_id for item in labeled}
    verified = [
        drawing
        for drawing in result.canonical_drawings
        if drawing.source_asset_id in labeled_ids
    ]
    return {
        "filename_used_for_scoring": False,
        "silver_label_is_ground_truth": False,
        "labeled_files": len(labeled),
        "top1_agreement": top1,
        "top1_rate_percent": round(100.0 * top1 / len(labeled), 4) if labeled else 0.0,
        "top3_agreement": top3,
        "top3_rate_percent": round(100.0 * top3 / len(labeled), 4) if labeled else 0.0,
        "unique_verified": len(verified),
        "ambiguous": len(set(result.ambiguous_source_ids) & labeled_ids),
        "unresolved": len(set(result.unresolved_source_ids) & labeled_ids),
        "disagreements": disagreements,
        "no_candidate": no_candidate,
    }


def _full_metrics(
    observations: list[DrawingSourceObservation],
    result: DrawingEvidenceResolution,
    paths: dict[str, str],
) -> dict:
    canonical_by_source = {
        drawing.source_asset_id: drawing
        for drawing in result.canonical_drawings
        if drawing.source_asset_id
    }
    evidence_by_candidate: dict[str, list] = {}
    for item in result.evidence:
        evidence_by_candidate.setdefault(item.candidate_id, []).append(item)
    candidates_by_source = _rankings(result)

    status = {"direct": 0, "derived_verified": 0, "heuristic_only": 0, "ambiguous": 0, "unresolved": 0}
    rows = []
    ambiguous_ids = set(result.ambiguous_source_ids)
    unresolved_ids = set(result.unresolved_source_ids)
    for observation in observations:
        source_id = observation.source_asset_id
        drawing = canonical_by_source.get(source_id)
        if drawing is not None:
            level = drawing.evidence_level.value if isinstance(drawing.evidence_level, EvidenceLevel) else str(drawing.evidence_level)
            key = "direct" if level == EvidenceLevel.DIRECT.value else "derived_verified"
            status[key] += 1
            rows.append({"source": paths.get(source_id, observation.original_name), "status": key, "number": drawing.number})
            continue
        if source_id in ambiguous_ids:
            status["ambiguous"] += 1
            rows.append({"source": paths.get(source_id, observation.original_name), "status": "ambiguous"})
            continue
        ranked = candidates_by_source.get(source_id, [])
        has_filename_evidence = any(
            evidence.method == "filename_identifier"
            for candidate in ranked
            for evidence in evidence_by_candidate.get(candidate.candidate_id, [])
        )
        if has_filename_evidence:
            status["heuristic_only"] += 1
            rows.append({"source": paths.get(source_id, observation.original_name), "status": "heuristic_only"})
        else:
            status["unresolved"] += 1
            rows.append({"source": paths.get(source_id, observation.original_name), "status": "unresolved"})

    return {
        "files": len(observations),
        **status,
        "resolver_diagnostics": result.diagnostics,
        "rows": rows,
        "known_false_verified_reviewed": 0,
    }


def evaluate(source_root: Path) -> dict:
    source_root = source_root.resolve()
    body_pdf = discover_latest_body_pdf(source_root)
    body_contexts = extract_body_contexts(body_pdf)
    observations, paths = observe_ai_files(source_root)
    resolver = DrawingEvidenceGraphResolver()

    labeled_observations = [
        item for item in observations if filename_label(item.original_name) is not None
    ]
    blinded_result = resolver.resolve_observations(
        corpus_id="local-drawing-evidence-blinded",
        observations=[blind_filename(item) for item in labeled_observations],
        body_contexts=body_contexts,
        include_filename_evidence=False,
    )
    full_result = resolver.resolve_observations(
        corpus_id="local-drawing-evidence-full",
        observations=observations,
        body_contexts=body_contexts,
        include_filename_evidence=True,
    )

    metrics = empty_metrics()
    metrics["audit"].update(
        {
            "measurement_time_utc": datetime.now(timezone.utc).isoformat(),
            "source_root": str(source_root),
            "body_pdf": body_pdf.relative_to(source_root).as_posix(),
            "body_context_count": len(body_contexts),
            "ai_files": len(observations),
            "filename_labeled_ai": len(labeled_observations),
        }
    )
    metrics["blinded_35"] = _blinded_metrics(labeled_observations, blinded_result, paths)
    metrics["full_56"] = _full_metrics(observations, full_result, paths)
    return metrics


def render_report(metrics: dict) -> str:
    audit = metrics["audit"]
    blinded = metrics["blinded_35"]
    full = metrics["full_56"]
    return "\n".join(
        [
            "# Local drawing evidence graph revalidation",
            "",
            f"- Source root: `{audit.get('source_root', '')}`",
            f"- Body PDF: `{audit.get('body_pdf', '')}`",
            f"- Adobe/COM/ExtendScript used: **no**",
            f"- AI files: **{audit.get('ai_files', 0)}**",
            f"- Filename-labeled AI: **{audit.get('filename_labeled_ai', 0)}**",
            "",
            "## Blinded filename evaluation",
            "",
            f"- Filename used for scoring: **{str(blinded.get('filename_used_for_scoring', False)).lower()}**",
            f"- Top-1 agreement: **{blinded.get('top1_agreement', 0)}/{blinded.get('labeled_files', 0)} ({blinded.get('top1_rate_percent', 0)}%)**",
            f"- Top-3 agreement: **{blinded.get('top3_agreement', 0)}/{blinded.get('labeled_files', 0)} ({blinded.get('top3_rate_percent', 0)}%)**",
            f"- Unique verified: **{blinded.get('unique_verified', 0)}**",
            f"- Ambiguous: **{blinded.get('ambiguous', 0)}**",
            f"- Unresolved: **{blinded.get('unresolved', 0)}**",
            "",
            "> Filename labels are silver labels only; disagreements are review cases, not automatic resolver errors.",
            "",
            "## Full AI resolution",
            "",
            f"- Direct: **{full.get('direct', 0)}**",
            f"- Derived verified: **{full.get('derived_verified', 0)}**",
            f"- Heuristic-only: **{full.get('heuristic_only', 0)}**",
            f"- Ambiguous: **{full.get('ambiguous', 0)}**",
            f"- Unresolved: **{full.get('unresolved', 0)}**",
            "",
            "## Safety contract",
            "",
            "- Filename-only candidates are not verified.",
            "- Hard point/grid contradictions are rejected.",
            "- Near ties remain ambiguous.",
            "- `/src` is read-only and outputs must be outside it.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_root = args.source_root.resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"source root does not exist: {source_root}")
    _assert_output_outside_source(source_root, args.output_json)
    _assert_output_outside_source(source_root, args.output_report)

    metrics = evaluate(source_root)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_report.write_text(render_report(metrics), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
