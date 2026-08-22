from __future__ import annotations

from app.graph.graph_review_repository import GraphVisualNode

from .models import GraphBodyRegion, GraphRuleFinding


def review_semantic_escalation(
    *,
    corpus_id: str,
    object_id: str,
    visuals: list[GraphVisualNode],
    body_regions: list[GraphBodyRegion],
) -> list[GraphRuleFinding]:
    if not visuals:
        return []
    target_ids = tuple(sorted({visual.id for visual in visuals}))
    findings: list[GraphRuleFinding] = []
    for region in body_regions:
        topics = tuple(sorted({topic.strip().lower() for topic in region.semantic_topics if topic.strip()}))
        if not topics:
            continue
        findings.append(
            GraphRuleFinding(
                rule_code="SEMANTIC_REVIEW_REQUIRED",
                severity="medium",
                source_block_id=region.source_block_id,
                archaeology_object_id=object_id,
                reference_corpus_id=corpus_id,
                canonical_target_ids=target_ids,
                original_text=region.text,
                proposed_text=None,
                rationale=(
                    "Graph identity is resolved, but semantic topic(s) "
                    + ", ".join(topics)
                    + " require visual/contextual interpretation rather than deterministic identity selection."
                ),
                evidence_ids=target_ids,
                requires_ai=True,
            )
        )
    return findings
