from __future__ import annotations

import re

from app.graph.graph_review_repository import GraphObjectReference, GraphVisualNode

from .models import GraphBodyRegion, GraphRuleFinding


_BLANK_BOTH_RE = re.compile(
    r"\(\s*도면\s*:\s*(?P<drawing>[^,\)]*)\s*,\s*도판\s*:\s*(?P<plate>[^\)]*)\s*\)"
)


def _visual_type(visual: GraphVisualNode) -> str | None:
    if visual.label == "Plate":
        return "plate"
    if visual.label == "Drawing":
        return "drawing"
    return None


def _token(reference_type: str, number: str) -> str:
    return f"도면 {number}" if reference_type == "drawing" else f"도판 {number}"


def _suffix(targets: list[tuple[str, GraphVisualNode]]) -> str:
    ordered = sorted(targets, key=lambda item: (0 if item[0] == "drawing" else 1, item[1].number))
    return "(" + ", ".join(_token(kind, visual.number) for kind, visual in ordered) + ")"


def review_visual_coverage(
    *,
    corpus_id: str,
    object_id: str,
    visuals: list[GraphVisualNode],
    references: list[GraphObjectReference],
    body_regions: list[GraphBodyRegion],
) -> list[GraphRuleFinding]:
    expected: dict[str, list[GraphVisualNode]] = {"drawing": [], "plate": []}
    for visual in visuals:
        kind = _visual_type(visual)
        if kind is not None:
            expected[kind].append(visual)
    for values in expected.values():
        values.sort(key=lambda item: (item.number, item.id))

    referenced_types = {
        str(reference.reference_type).lower()
        for reference in references
        if str(reference.reference_type).lower() in {"plate", "drawing"}
    }
    missing_types = [
        kind for kind in ("drawing", "plate") if expected[kind] and kind not in referenced_types
    ]
    if not missing_types:
        return []

    findings: list[GraphRuleFinding] = []
    unique_targets: list[tuple[str, GraphVisualNode]] = []
    for kind in missing_types:
        if len(expected[kind]) == 1:
            unique_targets.append((kind, expected[kind][0]))
        else:
            findings.append(
                GraphRuleFinding(
                    rule_code="VISUAL_REFERENCE_AMBIGUOUS",
                    severity="high",
                    source_block_id=body_regions[0].source_block_id if body_regions else None,
                    archaeology_object_id=object_id,
                    reference_corpus_id=corpus_id,
                    canonical_target_ids=tuple(item.id for item in expected[kind]),
                    original_text=None,
                    proposed_text=None,
                    rationale="Multiple same-type selected-corpus visuals DEPICT this object; no reference number can be chosen automatically.",
                    evidence_ids=tuple(item.id for item in expected[kind]),
                    requires_ai=False,
                )
            )
    if not unique_targets:
        return findings

    blank_matches: list[tuple[GraphBodyRegion, re.Match[str]]] = []
    for region in body_regions:
        match = _BLANK_BOTH_RE.search(region.text or "")
        if match and (not match.group("drawing").strip() or not match.group("plate").strip()):
            blank_matches.append((region, match))

    target_ids = tuple(visual.id for _, visual in unique_targets)
    if len(blank_matches) > 1:
        findings.append(
            GraphRuleFinding(
                rule_code="VISUAL_REFERENCE_LOCATION_AMBIGUOUS",
                severity="high",
                source_block_id=None,
                archaeology_object_id=object_id,
                reference_corpus_id=corpus_id,
                canonical_target_ids=target_ids,
                original_text=None,
                proposed_text=None,
                rationale="Multiple explicit blank reference locations exist; insertion location requires human review.",
                evidence_ids=target_ids,
                requires_ai=False,
            )
        )
        return findings

    if len(blank_matches) == 1:
        region, match = blank_matches[0]
        drawing_value = match.group("drawing").strip()
        plate_value = match.group("plate").strip()
        for kind, visual in unique_targets:
            if kind == "drawing" and not drawing_value:
                drawing_value = visual.number
            elif kind == "plate" and not plate_value:
                plate_value = visual.number
        findings.append(
            GraphRuleFinding(
                rule_code="VISUAL_REFERENCE_BLANK_FILL",
                severity="high",
                source_block_id=region.source_block_id,
                archaeology_object_id=object_id,
                reference_corpus_id=corpus_id,
                canonical_target_ids=target_ids,
                original_text=match.group(0),
                proposed_text=f"(도면: {drawing_value}, 도판: {plate_value})",
                rationale="The explicit blank placeholder has uniquely proven selected-corpus target(s).",
                evidence_ids=target_ids,
                requires_ai=False,
            )
        )
        return findings

    if len(body_regions) != 1:
        findings.append(
            GraphRuleFinding(
                rule_code="VISUAL_REFERENCE_LOCATION_AMBIGUOUS",
                severity="high",
                source_block_id=None,
                archaeology_object_id=object_id,
                reference_corpus_id=corpus_id,
                canonical_target_ids=target_ids,
                original_text=None,
                proposed_text=None,
                rationale="The visual target is unique but the body insertion location is not unique.",
                evidence_ids=target_ids,
                requires_ai=False,
            )
        )
        return findings

    region = body_regions[0]
    findings.append(
        GraphRuleFinding(
            rule_code="VISUAL_REFERENCE_MISSING",
            severity="high",
            source_block_id=region.source_block_id,
            archaeology_object_id=object_id,
            reference_corpus_id=corpus_id,
            canonical_target_ids=target_ids,
            original_text=region.text,
            proposed_text=_suffix(unique_targets),
            rationale="Selected-corpus visual target(s) DEPICT this object but the body has no same-type reference.",
            evidence_ids=target_ids,
            requires_ai=False,
        )
    )
    return findings
