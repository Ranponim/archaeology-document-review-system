from __future__ import annotations

from .corpus_integrity import enforce_corpus_integrity
from .models import GraphBodyRegion, GraphRuleFinding
from .reference_resolution import resolve_object_references
from .semantic_escalation import review_semantic_escalation
from .visual_consistency import review_visual_consistency
from .visual_coverage import review_visual_coverage


class GraphRuleEngine:
    """Four-layer deterministic graph review for ReferenceCorpus rounds.

    L1 validates corpus integrity and may stop the run. L2 resolves body
    references inside the selected corpus and persists scoped evidence. L3
    performs deterministic bidirectional coverage/consistency. L4 only marks
    semantic questions that may optionally be escalated; it never chooses graph
    identity.
    """

    def __init__(self, repository) -> None:
        self.repository = repository

    def run(
        self,
        *,
        project_id: str,
        reference_corpus_id: str,
        analysis_run_id: str,
        archaeology_object_ids: list[str],
        body_regions_by_object: dict[str, list[GraphBodyRegion]] | None = None,
    ) -> list[GraphRuleFinding]:
        enforce_corpus_integrity(
            self.repository,
            project_id,
            reference_corpus_id,
        )
        body_regions_by_object = body_regions_by_object or {}
        findings: list[GraphRuleFinding] = []
        for object_id in sorted(set(archaeology_object_ids)):
            references = self.repository.references_for_object(project_id, object_id)
            visuals = self.repository.visuals_for_object(
                project_id,
                reference_corpus_id,
                object_id,
            )
            facts, resolution_findings = resolve_object_references(
                self.repository,
                project_id=project_id,
                corpus_id=reference_corpus_id,
                analysis_run_id=analysis_run_id,
                object_id=object_id,
                references=references,
            )
            findings.extend(resolution_findings)
            findings.extend(
                review_visual_consistency(
                    corpus_id=reference_corpus_id,
                    object_id=object_id,
                    visuals=visuals,
                    facts=facts,
                )
            )
            body_regions = list(body_regions_by_object.get(object_id, []))
            findings.extend(
                review_visual_coverage(
                    corpus_id=reference_corpus_id,
                    object_id=object_id,
                    visuals=visuals,
                    references=references,
                    body_regions=body_regions,
                )
            )
            findings.extend(
                review_semantic_escalation(
                    corpus_id=reference_corpus_id,
                    object_id=object_id,
                    visuals=visuals,
                    body_regions=body_regions,
                )
            )

        return sorted(
            findings,
            key=lambda item: (
                item.archaeology_object_id or "",
                item.rule_code,
                item.source_block_id or "",
                item.canonical_target_ids,
                item.original_text or "",
            ),
        )
