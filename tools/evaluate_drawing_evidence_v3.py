from __future__ import annotations

import argparse
from collections import Counter
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

from app.config import CodexDrawingResolverConfig  # noqa: E402
from app.domain.drawing_evidence_v3 import (  # noqa: E402
    BodyDrawingEvidencePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
)
from app.services.codex_drawing_resolver_client import CodexDrawingResolverClient  # noqa: E402
from app.services.drawing_candidate_generator_v3 import DrawingCandidateGeneratorV3  # noqa: E402
from app.services.drawing_context_normalizer import DrawingContextNormalizer  # noqa: E402
from app.services.drawing_evidence_resolver_v3 import DrawingEvidenceResolverV3  # noqa: E402
from app.services.drawing_source_observer import DrawingSourceObserver  # noqa: E402
from app.services.drawing_visual_extractor import DrawingVisualExtractor  # noqa: E402
from app.services.pdf_parser import PDFParser  # noqa: E402

_DATE_PREFIX = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?!\d)")
_SOURCE_FAMILY_BY_KIND = {
    "publication_kind": "identity_signature",
    "site_point": "spatial_signature",
    "point": "spatial_signature",
    "grid": "spatial_signature",
    "direction": "spatial_signature",
    "period": "archaeology_signature",
    "feature_type": "archaeology_signature",
    "feature_number": "archaeology_signature",
    "feature": "archaeology_signature",
    "drawing_type": "drawing_signature",
    "section_label": "drawing_signature",
    "content_type": "drawing_signature",
    "map_type": "map_signature",
    "year": "map_signature",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gold-based local evaluation for Codex-first drawing-evidence-v3.",
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument(
        "--fake-results",
        type=Path,
        default=None,
        help="Deterministic fixture mode for CI; contains no network calls.",
    )
    parser.add_argument(
        "--live-codex",
        action="store_true",
        help="Call the configured live Codex resolver. Intended only for local /src acceptance.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N discovered AI sources; useful for live smoke tests.",
    )
    parser.add_argument("--body-pdf", type=Path, default=None)
    parser.add_argument("--render-dir", type=Path, default=None)
    return parser


def assert_output_outside_source(source_root: Path, output: Path) -> None:
    source = source_root.resolve()
    target = output.resolve()
    if target == source or source in target.parents:
        raise ValueError(f"output must be outside source root: {output}")


def _load_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("rows")
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"expected a JSON row list: {path}")
    return [dict(row) for row in payload]


def _truth(row: dict) -> tuple[str, str] | None:
    if str(row.get("verification") or "unknown").strip().lower() == "unknown":
        return None
    kind = row.get("publication_kind")
    number = row.get("number")
    if kind not in {"drawing", "illustration"} or number is None:
        return None
    return str(kind), str(number)


def _identity(value) -> tuple[str, str] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    kind, number = value
    if kind not in {"drawing", "illustration"} or number is None:
        return None
    return str(kind), str(number)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def compute_metrics(gold_rows: list[dict], evaluations: list[dict]) -> dict:
    gold_by_source = {
        str(row.get("source") or ""): _truth(row)
        for row in gold_rows
        if str(row.get("source") or "")
    }
    evaluation_by_source = {
        str(row.get("source") or ""): row
        for row in evaluations
        if str(row.get("source") or "")
    }
    known = {
        source: truth
        for source, truth in gold_by_source.items()
        if truth is not None
    }

    recall_hits = {5: 0, 10: 0, 20: 0}
    codex_correct = 0
    auto_known = 0
    auto_correct = 0
    review_known = 0
    unresolved_known = 0
    ambiguous_count = 0
    none_count = 0

    for source, truth in known.items():
        row = evaluation_by_source.get(source, {})
        ranked = [
            identity
            for value in (row.get("candidate_identities") or [])
            if (identity := _identity(value)) is not None
        ]
        for k in recall_hits:
            if truth in ranked[:k]:
                recall_hits[k] += 1

        codex_identity = _identity(row.get("codex_identity"))
        if codex_identity == truth:
            codex_correct += 1

        status = str(row.get("status") or "")
        if status == "AUTO_VERIFIED":
            auto_known += 1
            if codex_identity == truth:
                auto_correct += 1
        elif status == "REVIEW_REQUIRED":
            review_known += 1
        elif status == "UNRESOLVED":
            unresolved_known += 1

    for row in evaluations:
        verdict = str(row.get("codex_verdict") or "")
        if verdict == "ambiguous":
            ambiguous_count += 1
        elif verdict == "none":
            none_count += 1

    invalid_response_count = sum(bool(row.get("invalid_response")) for row in evaluations)
    hard_promoted = sum(bool(row.get("hard_contradiction_promoted")) for row in evaluations)
    filename_only = sum(bool(row.get("filename_only_promoted")) for row in evaluations)
    kind_collision = sum(bool(row.get("kind_collision")) for row in evaluations)
    api_unsafe = sum(bool(row.get("api_unsafe_promotion")) for row in evaluations)

    known_count = len(known)
    return {
        "gold_rows": len(gold_rows),
        "gold_known": known_count,
        "gold_unknown": len(gold_rows) - known_count,
        "evaluated_sources": len(evaluations),
        "recall_at_5": _ratio(recall_hits[5], known_count),
        "recall_at_10": _ratio(recall_hits[10], known_count),
        "recall_at_20": _ratio(recall_hits[20], known_count),
        "codex_top1_accuracy": _ratio(codex_correct, known_count),
        "auto_coverage": _ratio(auto_known, known_count),
        "auto_precision": _ratio(auto_correct, auto_known),
        "review_rate": _ratio(review_known, known_count),
        "unresolved_rate": _ratio(unresolved_known, known_count),
        "ambiguous_count": ambiguous_count,
        "none_count": none_count,
        "invalid_response_count": invalid_response_count,
        "hard_contradiction_promoted_count": hard_promoted,
        "filename_only_promoted_count": filename_only,
        "kind_collision_count": kind_collision,
        "api_unsafe_promotion_count": api_unsafe,
        "safety_pass": all(
            value == 0
            for value in (
                invalid_response_count,
                hard_promoted,
                filename_only,
                kind_collision,
                api_unsafe,
            )
        ),
    }


def evaluate_from_fixture(gold_path: Path, fixture_path: Path) -> dict:
    return compute_metrics(_load_rows(gold_path), _load_rows(fixture_path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def discover_ai_files(source_root: Path) -> list[Path]:
    root = source_root.resolve()
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".ai"),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def discover_limited_ai_files(source_root: Path, *, limit: int | None) -> list[Path]:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    paths = discover_ai_files(source_root)
    return paths if limit is None else paths[:limit]


def _publication_kind(text: str) -> str | None:
    value = str(text or "")
    if re.search(r"삽도\s*\d", value):
        return "illustration"
    if re.search(r"도면\s*\d", value):
        return "drawing"
    return None


def _source_evidence(source_asset_id: str, facts) -> tuple[DrawingV3Evidence, ...]:
    rows = []
    seen = set()
    for fact in facts:
        family = _SOURCE_FAMILY_BY_KIND.get(fact.kind)
        if family is None:
            continue
        key = (fact.kind, fact.normalized_value, family)
        if key in seen:
            continue
        seen.add(key)
        payload = "\0".join((source_asset_id, fact.kind, fact.normalized_value)).encode(
            "utf-8"
        )
        rows.append(
            DrawingV3Evidence(
                id="drawing-v3-source-evidence:"
                + hashlib.sha256(payload).hexdigest()[:32],
                family=family,
                method=f"source_{fact.kind}",
                value=fact.normalized_value,
                supports=True,
                weak=False,
            )
        )
    return tuple(rows)


def build_body_packets(body_pdf: Path, render_dir: Path) -> list[BodyDrawingEvidencePacket]:
    parser = PDFParser()
    pages = parser.parse_pdf(body_pdf, mode="report_body", version_id="local-v3-body")
    body_sha = _sha256(body_pdf)
    extractor = DrawingVisualExtractor()
    packets: list[BodyDrawingEvidencePacket] = []

    def add_packet(*, kind: str, number: str, text: str, source_id: str, page: int, bbox):
        visual_regions = ()
        if bbox is not None:
            try:
                region = extractor.crop_body_region(
                    body_pdf,
                    render_dir,
                    f"body:{source_id}",
                    page,
                    tuple(float(value) for value in bbox),
                    body_sha,
                )
                visual_regions = (region,)
            except (OSError, RuntimeError, ValueError):
                visual_regions = ()
        packets.append(
            BodyDrawingEvidencePacket(
                publication_kind=kind,
                number=str(number),
                raw_texts=(text,),
                source_node_ids=(source_id,),
                source_sha256=body_sha,
                document_version_id="local-v3-body",
                physical_page=page,
                source_bbox=(tuple(float(value) for value in bbox) if bbox is not None else None),
                visual_regions=visual_regions,
            )
        )

    for page in pages:
        blocks = sorted(page.text_blocks, key=lambda item: item.order)
        by_order = {block.order: block for block in blocks}
        for block in blocks:
            refs = [ref for ref in block.references if str(ref.ref_type) == "drawing"]
            if not refs:
                continue
            context = [block.normalized_text or block.text]
            context.extend(
                by_order[order].normalized_text or by_order[order].text
                for order in range(block.order - 2, block.order + 3)
                if order in by_order and order != block.order
            )
            text = "\n".join(dict.fromkeys(part for part in context if str(part).strip()))
            for ref in refs:
                kind = (
                    getattr(ref, "publication_kind", None)
                    or _publication_kind(getattr(ref, "raw_text", ""))
                    or _publication_kind(block.normalized_text or block.text)
                    or "drawing"
                )
                add_packet(
                    kind=kind,
                    number=str(ref.number),
                    text=text,
                    source_id=block.block_id,
                    page=page.physical_page,
                    bbox=block.bbox,
                )

        for caption in page.captions:
            refs = [ref for ref in caption.references if str(ref.ref_type) == "drawing"]
            if not refs and caption.drawing_number:
                refs = [
                    SimpleNamespace(
                        number=str(caption.drawing_number),
                        raw_text=caption.raw_text,
                        publication_kind=_publication_kind(caption.raw_text),
                    )
                ]
            for ref in refs:
                kind = (
                    getattr(ref, "publication_kind", None)
                    or _publication_kind(getattr(ref, "raw_text", ""))
                    or _publication_kind(caption.raw_text)
                    or "drawing"
                )
                add_packet(
                    kind=kind,
                    number=str(ref.number),
                    text=caption.raw_text,
                    source_id=caption.caption_id,
                    page=page.physical_page,
                    bbox=caption.bbox,
                )
    return packets


def build_source_packets(
    source_root: Path,
    render_dir: Path,
    *,
    limit: int | None = None,
) -> list[DrawingSourceEvidencePacket]:
    observer = DrawingSourceObserver()
    normalizer = DrawingContextNormalizer()
    extractor = DrawingVisualExtractor()
    packets = []
    root = source_root.resolve()
    for index, path in enumerate(
        discover_limited_ai_files(root, limit=limit),
        start=1,
    ):
        relative = path.relative_to(root).as_posix()
        source_id = f"local-v3-ai:{index:03d}:{hashlib.sha256(relative.encode('utf-8')).hexdigest()[:12]}"
        sha = _sha256(path)
        asset = SimpleNamespace(id=source_id, sha256=sha, original_name=path.name)
        observed = observer.observe(asset, path)
        normalized = normalizer.normalize(
            observed.raw_text,
            source_kind="drawing_ai",
            source_node_id=source_id,
            source_sha256=sha,
        )
        try:
            visual = (extractor.render_source(path, render_dir, source_id, sha),)
        except (OSError, RuntimeError, ValueError):
            visual = ()
        packets.append(
            DrawingSourceEvidencePacket(
                source_asset_id=source_id,
                source_sha256=sha,
                original_name=path.name,
                source_path=relative,
                raw_text=observed.raw_text,
                publication_kind=normalized.publication_kind,
                internal_numbers=tuple(observed.internal_numbers),
                facts=tuple(normalized.facts),
                visual_regions=visual,
                evidence=_source_evidence(source_id, normalized.facts),
            )
        )
    return packets


def resolution_rows(source_root: Path, sources, resolution) -> list[dict]:
    root = source_root.resolve()
    source_by_id = {source.source_asset_id: source for source in sources}
    rows = []
    auto_target_counts = Counter()
    for result in resolution.source_results:
        source = source_by_id[result.source_asset_id]
        candidate_by_id = {candidate.candidate_id: candidate for candidate in result.candidates}
        selected = candidate_by_id.get(result.selected_candidate_id) if result.selected_candidate_id else None
        decision = result.decision
        codex_identity = (
            [selected.publication_kind, selected.number]
            if selected is not None and decision is not None and decision.verdict == "match"
            else None
        )
        candidate_identities = [
            [candidate.publication_kind, candidate.number]
            for candidate in result.candidates
        ]
        evidence_by_id = {item.id: item for item in source.evidence}
        for candidate in result.candidates:
            evidence_by_id.update({item.id: item for item in candidate.evidence})
        cited = [
            evidence_by_id[evidence_id]
            for evidence_id in (decision.cited_support_ids if decision else ())
            if evidence_id in evidence_by_id
        ]
        weak_only = bool(cited) and all(item.weak for item in cited)
        hard_promoted = bool(
            result.status == "AUTO_VERIFIED" and selected is not None and selected.hard_contradiction
        )
        api_unsafe = bool(
            result.status == "AUTO_VERIFIED"
            and (
                decision is None
                or decision.verdict != "match"
                or selected is None
                or decision.candidate_id != result.selected_candidate_id
            )
        )
        target_key = None
        if result.status == "AUTO_VERIFIED" and selected is not None:
            target_key = (selected.publication_kind, selected.number)
            auto_target_counts[target_key] += 1
        rows.append(
            {
                "source": source.source_path,
                "candidate_identities": candidate_identities,
                "codex_identity": codex_identity,
                "codex_verdict": decision.verdict if decision else None,
                "status": result.status,
                "invalid_response": bool(result.diagnostics.get("codex_error")),
                "hard_contradiction_promoted": hard_promoted,
                "filename_only_promoted": bool(result.status == "AUTO_VERIFIED" and weak_only),
                "kind_collision": False,
                "api_unsafe_promotion": api_unsafe,
                "selected_target": list(target_key) if target_key else None,
                "codex_confidence": decision.confidence if decision else None,
                "codex_summary": decision.summary if decision else None,
            }
        )
    duplicate_targets = {key for key, count in auto_target_counts.items() if count > 1}
    if duplicate_targets:
        for row in rows:
            target = _identity(row.get("selected_target"))
            if target in duplicate_targets:
                row["kind_collision"] = True
    return rows


def _print_codex_progress(message: str) -> None:
    print(f"[codex-sdk] {message}", flush=True)


def evaluate_live(
    source_root: Path,
    gold_path: Path,
    *,
    body_pdf: Path | None,
    render_dir: Path,
    source_limit: int | None = None,
) -> tuple[dict, list[dict]]:
    root = source_root.resolve()
    body = body_pdf.resolve() if body_pdf else discover_latest_body_pdf(root)
    if root not in body.parents and body != root:
        # Explicit body PDF may live outside /src, but normal local acceptance
        # discovers it inside /src. Either way, evaluator never writes to it.
        pass
    assert_output_outside_source(root, render_dir)
    render_dir.mkdir(parents=True, exist_ok=True)

    bodies = build_body_packets(body, render_dir / "body")
    sources = build_source_packets(root, render_dir / "source", limit=source_limit)
    config = CodexDrawingResolverConfig.from_env()
    print(
        f"[acceptance] sources={len(sources)} model={config.model} "
        f"effort={config.reasoning_effort} "
        f"timeout={config.turn_timeout_seconds:g}s",
        flush=True,
    )
    generator = DrawingCandidateGeneratorV3(DrawingContextNormalizer())
    client = CodexDrawingResolverClient(
        config,
        progress_callback=_print_codex_progress,
    )
    resolver = DrawingEvidenceResolverV3(
        generator,
        client,
        auto_confidence=config.auto_confidence,
        max_candidates=config.max_candidates,
        max_expansions=config.max_expansions,
    )
    resolution = resolver.resolve_observations(
        "local-drawing-evidence-v3",
        sources,
        bodies,
        body_pdf_path=str(body),
        render_dir=str(render_dir),
    )
    rows = resolution_rows(root, sources, resolution)
    metrics = compute_metrics(_load_rows(gold_path), rows)
    metrics["audit"] = {
        "measurement_time_utc": datetime.now(timezone.utc).isoformat(),
        "resolver_version": "drawing-evidence-v3",
        "source_root": str(root),
        "body_pdf": str(body),
        "source_root_read_only": True,
        "live_codex": True,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "turn_timeout_seconds": config.turn_timeout_seconds,
        "source_limit": source_limit,
        "ai_files": len(sources),
        "body_packets": len(bodies),
    }
    return metrics, rows


def render_report(metrics: dict) -> str:
    audit = metrics.get("audit") or {}
    pct = lambda value: f"{100.0 * float(value or 0):.2f}%"
    lines = [
        "# Drawing evidence v3 local evaluation",
        "",
        f"- Resolver: **{audit.get('resolver_version', 'drawing-evidence-v3')}**",
        f"- Live Codex: **{str(audit.get('live_codex', False)).lower()}**",
        f"- Gold known: **{metrics.get('gold_known', 0)}**",
        f"- Gold unknown: **{metrics.get('gold_unknown', 0)}**",
        "",
        "## Retrieval and decision quality",
        "",
        f"- Recall@5: **{pct(metrics.get('recall_at_5'))}**",
        f"- Recall@10: **{pct(metrics.get('recall_at_10'))}**",
        f"- Recall@20: **{pct(metrics.get('recall_at_20'))}**",
        f"- Codex Top-1 accuracy: **{pct(metrics.get('codex_top1_accuracy'))}**",
        f"- Auto coverage: **{pct(metrics.get('auto_coverage'))}**",
        f"- Auto precision: **{pct(metrics.get('auto_precision'))}**",
        f"- Review rate: **{pct(metrics.get('review_rate'))}**",
        f"- Unresolved rate: **{pct(metrics.get('unresolved_rate'))}**",
        "",
        "## Safety",
        "",
        f"- Invalid response: **{metrics.get('invalid_response_count', 0)}**",
        f"- Hard contradiction promoted: **{metrics.get('hard_contradiction_promoted_count', 0)}**",
        f"- Filename-only promoted: **{metrics.get('filename_only_promoted_count', 0)}**",
        f"- Kind/assignment collision: **{metrics.get('kind_collision_count', 0)}**",
        f"- API unsafe promotion: **{metrics.get('api_unsafe_promotion_count', 0)}**",
        "",
        "## Acceptance gates",
        "",
        "- Recall@10 >= 99%",
        "- Auto coverage 75-85%",
        "- Auto precision >= 99%",
        "- Review <= 25%",
        "- All safety counters = 0",
        "",
        "> Unknown gold rows are excluded from accuracy, coverage, and precision denominators.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = build_parser().parse_args()
    root = args.source_root.resolve()
    assert_output_outside_source(root, args.output_json)
    assert_output_outside_source(root, args.output_report)
    if args.live_codex and args.fake_results is not None:
        raise ValueError("choose either --live-codex or --fake-results, not both")

    if args.live_codex:
        render_dir = args.render_dir or args.output_json.parent / "drawing-v3-render-cache"
        metrics, rows = evaluate_live(
            root,
            args.gold,
            body_pdf=args.body_pdf,
            render_dir=render_dir,
            source_limit=args.limit,
        )
        metrics["rows"] = rows
    else:
        if args.fake_results is None:
            raise ValueError("--fake-results is required unless --live-codex is set")
        metrics = evaluate_from_fixture(args.gold, args.fake_results)
        metrics["audit"] = {
            "measurement_time_utc": datetime.now(timezone.utc).isoformat(),
            "resolver_version": "drawing-evidence-v3",
            "source_root": str(root),
            "source_root_read_only": True,
            "live_codex": False,
        }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_report.write_text(render_report(metrics), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
