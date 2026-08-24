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
from app.services.drawing_evidence_graph_resolver_v2 import (  # noqa: E402
    DrawingEvidenceGraphResolverV2,
)
from app.services.drawing_source_observer import DrawingSourceObserver  # noqa: E402
from app.services.pdf_parser import PDFParser  # noqa: E402

_FILENAME_IDENTIFIER = re.compile(r"(도면|삽도)\s*(\d+(?:-\d+)?)", re.IGNORECASE)
_DATE_PREFIX = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?!\d)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only evaluation of drawing evidence graph resolution on /src",
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--resolver-version",
        choices=("v1", "v2"),
        default="v1",
        help="Resolver to evaluate. Production remains v1 until local v2 acceptance passes.",
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument(
        "--blinded",
        action="store_true",
        help="Compatibility flag; the evaluator always reports blinded and full runs separately.",
    )
    return parser


def resolver_for_version(version: str):
    normalized = str(version or "v1").strip().lower()
    if normalized == "v1":
        return DrawingEvidenceGraphResolver()
    if normalized == "v2":
        return DrawingEvidenceGraphResolverV2()
    raise ValueError(f"Unsupported resolver version: {version}")


def empty_metrics(resolver_version: str = "v1") -> dict:
    resolver = resolver_for_version(resolver_version)
    return {
        "audit": {
            "adobe_used": False,
            "com_used": False,
            "extendscript_used": False,
            "source_root_read_only": True,
            "resolver_version": resolver.resolver_version,
        },
        "blinded_35": {
            "filename_used_for_scoring": False,
            "silver_label_is_ground_truth": False,
        },
        "full_56": {
            "kind_collision_count": 0,
            "hard_contradiction_promoted_count": 0,
            "filename_only_verified_count": 0,
        },
    }


def make_observation(
    *,
    source_asset_id: str,
    source_sha256: str,
    original_name: str,
    raw_text: str,
    internal_numbers: tuple[str, ...] = (),
    source_path: str = "",
    publication_kind: str | None = None,
) -> DrawingSourceObservation:
    return DrawingSourceObservation(
        source_asset_id=source_asset_id,
        source_sha256=source_sha256,
        original_name=original_name,
        raw_text=raw_text,
        internal_numbers=tuple(internal_numbers),
        source_path=source_path,
        publication_kind=publication_kind,
    )


def blind_filename(observation: DrawingSourceObservation) -> DrawingSourceObservation:
    # Keep content/path evidence intact. V2 path scoring only consumes semantic
    # path facts (for example `3지점`) and never the hidden publication number.
    return replace(observation, original_name="blinded.ai")


def publication_kind_from_text(text: str) -> str | None:
    value = str(text or "")
    if re.search(r"삽도\s*\d", value):
        return "illustration"
    if re.search(r"도면\s*\d", value):
        return "drawing"
    return None


def filename_identity(name: str) -> tuple[str, str] | None:
    identities = {
        ("illustration" if match.group(1) == "삽도" else "drawing", match.group(2))
        for match in _FILENAME_IDENTIFIER.finditer(Path(name).stem)
    }
    return next(iter(identities)) if len(identities) == 1 else None


def filename_label(name: str) -> str | None:
    identity = filename_identity(name)
    return identity[1] if identity is not None else None


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


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").split())


def _append_legacy_context(
    grouped: dict[str, dict],
    number: str,
    text: str,
    source_id: str,
    source_sha256: str | None,
) -> None:
    clean = _clean_text(text)
    if not clean:
        return
    item = grouped.setdefault(number, {"texts": [], "ids": [], "sha": source_sha256})
    if clean not in item["texts"]:
        item["texts"].append(clean)
        item["ids"].append(source_id)


def _append_v2_mention(
    grouped: dict[tuple[str, str], dict],
    *,
    publication_kind: str,
    number: str,
    text_parts: list[str],
    mention_id: str,
    source_sha256: str,
) -> None:
    cleaned = [_clean_text(text) for text in text_parts if _clean_text(text)]
    mention_text = "\n".join(dict.fromkeys(cleaned))
    if not mention_text:
        return
    key = (publication_kind, str(number))
    item = grouped.setdefault(key, {"texts": [], "ids": [], "sha": source_sha256})
    if mention_id not in item["ids"]:
        item["texts"].append(mention_text)
        item["ids"].append(mention_id)


def extract_body_contexts(
    body_pdf: Path,
    *,
    resolver_version: str = "v1",
) -> list[BodyDrawingContext]:
    parser = PDFParser()
    pages = parser.parse_pdf(body_pdf, mode="report_body", version_id="drawing-eval-body")
    body_sha = _sha256(body_pdf)

    if resolver_version == "v1":
        grouped: dict[str, dict] = {}
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
                        _append_legacy_context(
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
                    _append_legacy_context(
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

    if resolver_version != "v2":
        raise ValueError(f"Unsupported resolver version: {resolver_version}")

    grouped_v2: dict[tuple[str, str], dict] = {}
    for page in pages:
        blocks = sorted(page.text_blocks, key=lambda item: item.order)
        by_order = {block.order: block for block in blocks}
        for block in blocks:
            drawing_refs = [ref for ref in block.references if str(ref.ref_type) == "drawing"]
            if not drawing_refs:
                continue
            neighborhood = [
                by_order[order]
                for order in range(block.order - 2, block.order + 3)
                if order in by_order
            ]
            local_parts = [block.normalized_text or block.text]
            local_parts.extend(
                neighbor.normalized_text or neighbor.text
                for neighbor in neighborhood
                if neighbor.block_id != block.block_id
            )
            for ref in drawing_refs:
                kind = (
                    getattr(ref, "publication_kind", None)
                    or publication_kind_from_text(ref.raw_text or "")
                    or publication_kind_from_text(block.normalized_text or block.text)
                    or "drawing"
                )
                _append_v2_mention(
                    grouped_v2,
                    publication_kind=kind,
                    number=str(ref.number),
                    text_parts=local_parts,
                    mention_id=block.block_id,
                    source_sha256=body_sha,
                )

        for caption in page.captions:
            refs = [ref for ref in caption.references if str(ref.ref_type) == "drawing"]
            if not refs and caption.drawing_number:
                refs = [SimpleNamespace(
                    number=str(caption.drawing_number),
                    raw_text=caption.raw_text,
                    publication_kind=publication_kind_from_text(caption.raw_text),
                )]
            for ref in refs:
                kind = (
                    getattr(ref, "publication_kind", None)
                    or publication_kind_from_text(getattr(ref, "raw_text", "") or "")
                    or publication_kind_from_text(caption.raw_text)
                    or "drawing"
                )
                _append_v2_mention(
                    grouped_v2,
                    publication_kind=kind,
                    number=str(ref.number),
                    text_parts=[caption.raw_text],
                    mention_id=caption.caption_id,
                    source_sha256=body_sha,
                )

    return [
        BodyDrawingContext(
            number=number,
            raw_texts=tuple(item["texts"]),
            source_node_ids=tuple(item["ids"]),
            source_sha256=item["sha"],
            publication_kind=kind,
            mention_context_ids=tuple(item["ids"]),
        )
        for (kind, number), item in sorted(grouped_v2.items())
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
        observed = observer.observe(asset, path)
        # Only internal text may make publication kind explicit. Filename/path
        # remain weak evidence channels and must not become hard authority.
        observation = replace(
            observed,
            source_path=relative,
            publication_kind=publication_kind_from_text(observed.raw_text),
        )
        observations.append(observation)
        paths[source_id] = relative
    return observations, paths


def _rankings(result: DrawingEvidenceResolution) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for candidate in result.candidates:
        grouped.setdefault(candidate.source_asset_id, []).append(candidate)
    for source_id in grouped:
        grouped[source_id].sort(
            key=lambda item: (-item.score, item.publication_kind, item.candidate_number)
        )
    return grouped


def _blinded_metrics(
    observations: list[DrawingSourceObservation],
    result: DrawingEvidenceResolution,
    paths: dict[str, str],
    *,
    resolver_version: str,
) -> dict:
    labeled = [item for item in observations if filename_identity(item.original_name) is not None]
    rankings = _rankings(result)
    top1 = 0
    top3 = 0
    disagreements = []
    no_candidate = []
    for item in labeled:
        hidden_identity = filename_identity(item.original_name)
        assert hidden_identity is not None
        hidden_kind, hidden_number = hidden_identity
        ranked = rankings.get(item.source_asset_id, [])
        if resolver_version == "v2":
            predicted = [(candidate.publication_kind, candidate.candidate_number) for candidate in ranked]
            hidden = (hidden_kind, hidden_number)
        else:
            predicted = [candidate.candidate_number for candidate in ranked]
            hidden = hidden_number
        if predicted and predicted[0] == hidden:
            top1 += 1
        elif predicted:
            first = ranked[0]
            disagreements.append(
                {
                    "source": paths.get(item.source_asset_id, item.original_name),
                    "hidden_filename_kind": hidden_kind,
                    "hidden_filename_label": hidden_number,
                    "top1_kind": first.publication_kind,
                    "top1": first.candidate_number,
                    "top1_score": first.score,
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
        "identity_includes_publication_kind": resolver_version == "v2",
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

    status = {
        "direct": 0,
        "derived_verified": 0,
        "heuristic_only": 0,
        "ambiguous": 0,
        "unresolved": 0,
    }
    rows = []
    ambiguous_ids = set(result.ambiguous_source_ids)
    for observation in observations:
        source_id = observation.source_asset_id
        drawing = canonical_by_source.get(source_id)
        if drawing is not None:
            level = (
                drawing.evidence_level.value
                if isinstance(drawing.evidence_level, EvidenceLevel)
                else str(drawing.evidence_level)
            )
            key = "direct" if level == EvidenceLevel.DIRECT.value else "derived_verified"
            status[key] += 1
            rows.append(
                {
                    "source": paths.get(source_id, observation.original_name),
                    "status": key,
                    "publication_kind": getattr(drawing, "publication_kind", "drawing"),
                    "number": drawing.number,
                }
            )
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

    diagnostics = dict(result.diagnostics or {})
    return {
        "files": len(observations),
        **status,
        "kind_collision_count": int(diagnostics.get("kindCollisionCount", 0)),
        "hard_contradiction_promoted_count": int(
            diagnostics.get("hardContradictionPromotedCount", 0)
        ),
        "filename_only_verified_count": int(
            diagnostics.get("filenameOnlyVerifiedCount", 0)
        ),
        "canonical_drawing_count": len(result.canonical_drawings),
        "resolver_diagnostics": diagnostics,
        "rows": rows,
        "known_false_verified_reviewed": 0,
    }


def evaluate(source_root: Path, *, resolver_version: str = "v1") -> dict:
    source_root = source_root.resolve()
    body_pdf = discover_latest_body_pdf(source_root)
    body_contexts = extract_body_contexts(body_pdf, resolver_version=resolver_version)
    observations, paths = observe_ai_files(source_root)
    resolver = resolver_for_version(resolver_version)

    labeled_observations = [
        item for item in observations if filename_identity(item.original_name) is not None
    ]
    blinded_result = resolver.resolve_observations(
        corpus_id=f"local-drawing-evidence-{resolver_version}-blinded",
        observations=[blind_filename(item) for item in labeled_observations],
        body_contexts=body_contexts,
        include_filename_evidence=False,
    )
    full_result = resolver.resolve_observations(
        corpus_id=f"local-drawing-evidence-{resolver_version}-full",
        observations=observations,
        body_contexts=body_contexts,
        include_filename_evidence=True,
    )

    metrics = empty_metrics(resolver_version)
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
    metrics["blinded_35"] = _blinded_metrics(
        labeled_observations,
        blinded_result,
        paths,
        resolver_version=resolver_version,
    )
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
            f"- Resolver: **{audit.get('resolver_version', '')}**",
            f"- Source root: `{audit.get('source_root', '')}`",
            f"- Body PDF: `{audit.get('body_pdf', '')}`",
            "- Adobe/COM/ExtendScript used: **no**",
            f"- AI files: **{audit.get('ai_files', 0)}**",
            f"- Filename-labeled AI: **{audit.get('filename_labeled_ai', 0)}**",
            "",
            "## Blinded filename evaluation",
            "",
            f"- Filename used for scoring: **{str(blinded.get('filename_used_for_scoring', False)).lower()}**",
            f"- Kind included in identity comparison: **{str(blinded.get('identity_includes_publication_kind', False)).lower()}**",
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
            f"- Kind collision: **{full.get('kind_collision_count', 0)}**",
            f"- Hard contradiction promoted: **{full.get('hard_contradiction_promoted_count', 0)}**",
            f"- Filename-only verified: **{full.get('filename_only_verified_count', 0)}**",
            "",
            "## Safety contract",
            "",
            "- Filename/path/sequence evidence cannot independently verify a candidate.",
            "- Explicit kind/site/grid/feature-pair hard contradictions cannot be promoted.",
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

    metrics = evaluate(source_root, resolver_version=args.resolver_version)
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
