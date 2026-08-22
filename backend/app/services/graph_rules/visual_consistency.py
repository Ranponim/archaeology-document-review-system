from __future__ import annotations

from app.graph.graph_review_repository import GraphVisualNode

from .models import GraphRuleFinding
from .reference_resolution import ResolvedReferenceFact


def _visual_type(visual: GraphVisualNode) -> str | None:
    if visual.label == "Plate":
        return "plate"
    if visual.label == "Drawing":
        return "drawing"
    return None


def _token(reference_type: str, number: str) -> str:
    return f"도면 {number}" if reference_type == "drawing" else f"도판 {number}"


def review_visual_consistency(
    *,
    corpus_id: str,
    object_id: str,
    visuals: list[GraphVisualNode],
    facts: list[ResolvedReferenceFact],
) -> list[GraphRuleFinding]:
    expected: dict[str, list[GraphVisualNode]] = {"plate": [], "drawing": []}
    for visual in visuals:
        kind = _visual_type(visual)
        if kind is not None:
            expected[kind].append(visual)
    for values in expected.values():
        values.sort(key=lambda item: (item.number, item.id))

    findings: list[GraphRuleFinding] = []
    for reference_type in ("drawing", "plate"):
        targets = expected[reference_type]
        same_type = [
            fact
            for fact in facts
            if str(fact.reference.reference_type).lower() == reference_type
        ]
        if not targets or not same_type:
            continue
        expected_ids = {item.id for item in targets}
        if any(
            str(fact.resolution.status).upper() == "RESOLVED"
            and expected_ids.intersection(fact.resolution.target_ids)
            for fact in same_type
        ):
            continue

        if len(targets) == 1 and len(same_type) == 1:
            fact = same_type[0]
            status = str(fact.resolution.status).upper()
            if status in {"RESOLVED", "MISSING"}:
                target = targets[0]
                findings.append(
                    GraphRuleFinding(
                        rule_code="VISUAL_REFERENCE_WRONG_TARGET",
                        severity="high",
                        source_block_id=fact.reference.source_block_id,
                        archaeology_object_id=object_id,
                        reference_corpus_id=corpus_id,
                        canonical_target_ids=(target.id,),
                        original_text=fact.reference.raw_text
                        or _token(reference_type, fact.reference.number),
                        proposed_text=_token(reference_type, target.number),
                        rationale=(
                            "The existing reference is unresolved or resolves to a visual "
                            "that does not DEPICT this object, while exactly one same-type "
                            "selected-corpus target is proven."
                        ),
                        evidence_ids=(fact.evidence_id,),
                        requires_ai=False,
                    )
                )
                continue

        # Multiple plausible body references or expected targets cannot be
        # repaired deterministically. L2 ambiguity already owns identity
        # ambiguity, so only emit this when the graph still has a coverage
        # conflict after resolution.
        if len(targets) > 1 or len(same_type) > 1:
            findings.append(
                GraphRuleFinding(
                    rule_code="VISUAL_REFERENCE_AMBIGUOUS",
                    severity="high",
                    source_block_id=same_type[0].reference.source_block_id,
                    archaeology_object_id=object_id,
                    reference_corpus_id=corpus_id,
                    canonical_target_ids=tuple(item.id for item in targets),
                    original_text=None,
                    proposed_text=None,
                    rationale="Multiple graph-grounded same-type targets or references prevent deterministic replacement.",
                    evidence_ids=tuple(fact.evidence_id for fact in same_type),
                    requires_ai=False,
                )
            )
    return findings
