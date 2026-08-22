from __future__ import annotations

from dataclasses import dataclass

from app.graph.graph_review_repository import GraphObjectReference, GraphReferenceResolution

from .models import GraphRuleFinding


@dataclass(frozen=True, slots=True)
class ResolvedReferenceFact:
    reference: GraphObjectReference
    resolution: GraphReferenceResolution
    evidence_id: str


def resolve_object_references(
    repository,
    *,
    project_id: str,
    corpus_id: str,
    analysis_run_id: str,
    object_id: str,
    references: list[GraphObjectReference],
) -> tuple[list[ResolvedReferenceFact], list[GraphRuleFinding]]:
    facts: list[ResolvedReferenceFact] = []
    findings: list[GraphRuleFinding] = []
    for reference in sorted(references, key=lambda item: (item.reference_type, item.number, item.id)):
        resolution = repository.resolve_reference(
            project_id,
            corpus_id,
            reference.reference_type,
            reference.number,
        )
        evidence_id = repository.save_resolution_evidence(
            project_id,
            corpus_id,
            analysis_run_id,
            reference.id,
            resolution,
        )
        fact = ResolvedReferenceFact(reference, resolution, evidence_id)
        facts.append(fact)

        status = str(resolution.status).upper()
        if status == "RESOLVED":
            continue
        if status == "MISSING":
            rule_code = "VISUAL_REFERENCE_MISSING_TARGET"
            rationale = "The body reference has no target in the selected ReferenceCorpus."
        elif status == "INVALID":
            rule_code = "VISUAL_REFERENCE_INVALID"
            rationale = "The body reference type or number is invalid for deterministic graph resolution."
        elif status == "AMBIGUOUS":
            rule_code = "VISUAL_REFERENCE_AMBIGUOUS"
            rationale = "Multiple selected-corpus targets match this body reference; identity remains unresolved for human review."
        else:
            rule_code = "VISUAL_REFERENCE_INVALID"
            rationale = f"Unsupported graph resolution status: {status}."
        findings.append(
            GraphRuleFinding(
                rule_code=rule_code,
                severity="high",
                source_block_id=reference.source_block_id,
                archaeology_object_id=object_id,
                reference_corpus_id=corpus_id,
                canonical_target_ids=tuple(resolution.target_ids),
                original_text=reference.raw_text,
                proposed_text=None,
                rationale=rationale,
                evidence_ids=(evidence_id,),
                requires_ai=False,
            )
        )
    return facts, findings
