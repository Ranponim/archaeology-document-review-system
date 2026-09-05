from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import re

import networkx as nx

from app.domain.canonical_models import DrawingData, EvidenceLevel
from app.domain.drawing_evidence import (
    BodyDrawingContext,
    ContextFact,
    DrawingCandidateEvidence,
    DrawingCandidateResult,
    DrawingEvidenceResolution,
    DrawingSourceObservation,
    NormalizedDrawingContext,
)
from app.services.drawing_context_normalizer import DrawingContextNormalizer


_FILENAME_IDENTIFIER = re.compile(r"(?:도면|삽도)\s*(\d+(?:-\d+)?)", re.IGNORECASE)
_GENERIC_TOKENS = {"도면", "삽도", "도", "제"}
_SEMANTIC_WEIGHTS = {
    "point": 0.18,
    "grid": 0.22,
    "direction": 0.08,
    "drawing_type": 0.10,
    "feature": 0.16,
    "section_label": 0.12,
}
_HARD_CONTRADICTION_KINDS = {"point", "grid"}


class DrawingEvidenceGraphResolver:
    resolver_version = "drawing-evidence-v1"
    minimum_score = 0.72
    minimum_margin = 0.12
    maximum_content_candidates = 5

    def __init__(self, normalizer: DrawingContextNormalizer | None = None) -> None:
        self._normalizer = normalizer or DrawingContextNormalizer()

    @staticmethod
    def _filename_number(name: str) -> str | None:
        matches = list(_FILENAME_IDENTIFIER.finditer(Path(name).stem))
        numbers = {match.group(1) for match in matches}
        if len(numbers) != 1:
            return None
        return next(iter(numbers))

    @staticmethod
    def _candidate_id(corpus_id: str, source_asset_id: str, number: str) -> str:
        return f"drawing-candidate:{corpus_id}:{source_asset_id}:{number}"

    @staticmethod
    def _evidence_id(
        candidate_id: str,
        family: str,
        method: str,
        value: str,
        source_node_id: str | None,
    ) -> str:
        payload = "\0".join(
            (candidate_id, family, method, value, source_node_id or "")
        ).encode("utf-8")
        return "resolution-evidence:" + hashlib.sha256(payload).hexdigest()[:32]

    @staticmethod
    def _facts_by_kind(context: NormalizedDrawingContext) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for fact in context.facts:
            result.setdefault(fact.kind, set()).add(fact.normalized_value)
        return result

    @staticmethod
    def _lexical_tokens(context: NormalizedDrawingContext) -> set[str]:
        return {
            token
            for token in context.tokens
            if token not in _GENERIC_TOKENS and not token.isdigit()
        }

    def _normalize_body(self, context: BodyDrawingContext) -> tuple[NormalizedDrawingContext, ...]:
        normalized = []
        for index, text in enumerate(context.raw_texts):
            source_node_id = (
                context.source_node_ids[index]
                if index < len(context.source_node_ids)
                else None
            )
            normalized.append(
                self._normalizer.normalize(
                    text,
                    source_kind="body",
                    source_node_id=source_node_id,
                    source_sha256=context.source_sha256,
                )
            )
        return tuple(normalized)

    def _merge_contexts(self, contexts: tuple[NormalizedDrawingContext, ...]) -> NormalizedDrawingContext:
        raw_text = "\n".join(context.raw_text for context in contexts)
        tokens = tuple(sorted({token for context in contexts for token in context.tokens}))
        facts: dict[tuple[str, str, str | None], ContextFact] = {}
        for context in contexts:
            for fact in context.facts:
                facts[(fact.kind, fact.normalized_value, fact.source_node_id)] = fact
        return NormalizedDrawingContext(raw_text=raw_text, tokens=tokens, facts=tuple(facts.values()))

    def _evidence(
        self,
        *,
        candidate_id: str,
        family: str,
        method: str,
        value: str,
        normalized_value: str,
        score: float,
        source_node_id: str | None,
        source_sha256: str | None,
        supports: bool = True,
    ) -> DrawingCandidateEvidence:
        return DrawingCandidateEvidence(
            id=self._evidence_id(candidate_id, family, method, value, source_node_id),
            candidate_id=candidate_id,
            family=family,
            method=method,
            value=value,
            normalized_value=normalized_value,
            score=score,
            supports=supports,
            source_node_id=source_node_id,
            source_sha256=source_sha256,
        )

    def _score_candidate(
        self,
        *,
        corpus_id: str,
        observation: DrawingSourceObservation,
        ai_context: NormalizedDrawingContext,
        body: BodyDrawingContext,
        body_context: NormalizedDrawingContext,
        filename_number: str | None,
    ) -> tuple[DrawingCandidateResult, tuple[DrawingCandidateEvidence, ...]]:
        number = body.number
        candidate_id = self._candidate_id(corpus_id, observation.source_asset_id, number)
        evidence: list[DrawingCandidateEvidence] = []
        score = 0.0

        if filename_number == number:
            evidence.append(
                self._evidence(
                    candidate_id=candidate_id,
                    family="identity",
                    method="filename_identifier",
                    value=observation.original_name,
                    normalized_value=number,
                    score=0.35,
                    source_node_id=observation.source_asset_id,
                    source_sha256=observation.source_sha256,
                )
            )
            score += 0.35

        ai_facts = self._facts_by_kind(ai_context)
        body_facts = self._facts_by_kind(body_context)
        hard_contradiction = False
        for kind in _HARD_CONTRADICTION_KINDS:
            left = ai_facts.get(kind, set())
            right = body_facts.get(kind, set())
            if left and right and left.isdisjoint(right):
                hard_contradiction = True
                evidence.append(
                    self._evidence(
                        candidate_id=candidate_id,
                        family="semantic_content",
                        method=f"contradicting_{kind}",
                        value=f"AI={sorted(left)} BODY={sorted(right)}",
                        normalized_value=kind,
                        score=-1.0,
                        source_node_id=(body.source_node_ids[0] if body.source_node_ids else None),
                        source_sha256=body.source_sha256,
                        supports=False,
                    )
                )

        for kind, weight in _SEMANTIC_WEIGHTS.items():
            shared = ai_facts.get(kind, set()) & body_facts.get(kind, set())
            for value in sorted(shared):
                evidence.append(
                    self._evidence(
                        candidate_id=candidate_id,
                        family="semantic_content",
                        method=f"exact_{kind}",
                        value=value,
                        normalized_value=value,
                        score=weight,
                        source_node_id=(body.source_node_ids[0] if body.source_node_ids else None),
                        source_sha256=body.source_sha256,
                    )
                )
                score += weight

        ai_tokens = self._lexical_tokens(ai_context)
        body_tokens = self._lexical_tokens(body_context)
        union = ai_tokens | body_tokens
        shared_tokens = ai_tokens & body_tokens
        if union and shared_tokens:
            jaccard = len(shared_tokens) / len(union)
            lexical_score = round(0.22 * jaccard, 6)
            evidence.append(
                self._evidence(
                    candidate_id=candidate_id,
                    family="body_context",
                    method="normalized_token_overlap",
                    value=" ".join(sorted(shared_tokens)),
                    normalized_value=f"{jaccard:.6f}",
                    score=lexical_score,
                    source_node_id=(body.source_node_ids[0] if body.source_node_ids else None),
                    source_sha256=body.source_sha256,
                )
            )
            score += lexical_score

        families = tuple(sorted({item.family for item in evidence if item.supports and item.score > 0}))
        return (
            DrawingCandidateResult(
                candidate_id=candidate_id,
                reference_corpus_id=corpus_id,
                source_asset_id=observation.source_asset_id,
                source_sha256=observation.source_sha256,
                candidate_number=number,
                score=round(score, 6),
                evidence_families=families,
                evidence_ids=tuple(item.id for item in evidence),
                has_hard_contradiction=hard_contradiction,
            ),
            tuple(evidence),
        )

    @staticmethod
    def _canonical_drawing(
        corpus_id: str,
        observation: DrawingSourceObservation,
        number: str,
        level: EvidenceLevel,
        method: str,
        title: str = "",
    ) -> DrawingData:
        return DrawingData(
            drawing_id=f"drawing:{corpus_id}:{number}",
            number=number,
            physical_page=1,
            title=title,
            source_sha256=observation.source_sha256,
            document_version_id=None,
            source_kind="drawing_ai",
            reference_corpus_id=corpus_id,
            source_asset_id=observation.source_asset_id,
            evidence_level=level,
            evidence_method=method,
        )

    def resolve_observations(
        self,
        *,
        corpus_id: str,
        observations: list[DrawingSourceObservation],
        body_contexts: list[BodyDrawingContext],
        include_filename_evidence: bool = True,
    ) -> DrawingEvidenceResolution:
        body_by_number = {str(item.number): item for item in body_contexts}
        normalized_body = {
            number: self._merge_contexts(self._normalize_body(context))
            for number, context in body_by_number.items()
        }

        all_candidates: list[DrawingCandidateResult] = []
        all_evidence: list[DrawingCandidateEvidence] = []
        all_facts: list[ContextFact] = [
            fact for context in normalized_body.values() for fact in context.facts
        ]
        direct_claims: dict[str, list[tuple[DrawingSourceObservation, DrawingCandidateResult]]] = {}
        observation_by_source = {item.source_asset_id: item for item in observations}
        body_title_by_number = {
            number: (context.raw_texts[0] if context.raw_texts else "")
            for number, context in body_by_number.items()
        }
        sources_with_direct: set[str] = set()

        for observation in observations:
            ai_context = self._normalizer.normalize(
                observation.raw_text,
                source_kind="drawing_ai",
                source_node_id=observation.source_asset_id,
                source_sha256=observation.source_sha256,
            )
            all_facts.extend(ai_context.facts)

            internal_numbers = tuple(sorted(set(observation.internal_numbers)))
            if len(internal_numbers) == 1:
                number = internal_numbers[0]
                candidate_id = self._candidate_id(corpus_id, observation.source_asset_id, number)
                direct_evidence = self._evidence(
                    candidate_id=candidate_id,
                    family="identity",
                    method="pdf_internal_identifier",
                    value=f"도면 {number}",
                    normalized_value=number,
                    score=1.0,
                    source_node_id=observation.source_asset_id,
                    source_sha256=observation.source_sha256,
                )
                candidate = DrawingCandidateResult(
                    candidate_id=candidate_id,
                    reference_corpus_id=corpus_id,
                    source_asset_id=observation.source_asset_id,
                    source_sha256=observation.source_sha256,
                    candidate_number=number,
                    status="verified",
                    evidence_level=EvidenceLevel.DIRECT,
                    score=1.0,
                    runner_up_score=0.0,
                    margin=1.0,
                    evidence_families=("identity",),
                    evidence_ids=(direct_evidence.id,),
                )
                all_candidates.append(candidate)
                all_evidence.append(direct_evidence)
                direct_claims.setdefault(number, []).append((observation, candidate))
                sources_with_direct.add(observation.source_asset_id)
                continue

            if len(internal_numbers) > 1:
                for number in internal_numbers:
                    candidate_id = self._candidate_id(corpus_id, observation.source_asset_id, number)
                    all_candidates.append(
                        DrawingCandidateResult(
                            candidate_id=candidate_id,
                            reference_corpus_id=corpus_id,
                            source_asset_id=observation.source_asset_id,
                            source_sha256=observation.source_sha256,
                            candidate_number=number,
                            status="ambiguous",
                            evidence_level=EvidenceLevel.HEURISTIC,
                            score=1.0,
                            evidence_families=("identity",),
                        )
                    )
                continue

            filename_number = (
                self._filename_number(observation.original_name)
                if include_filename_evidence
                else None
            )
            scored: list[tuple[DrawingCandidateResult, tuple[DrawingCandidateEvidence, ...]]] = []
            for number, body_context in body_by_number.items():
                candidate, evidence = self._score_candidate(
                    corpus_id=corpus_id,
                    observation=observation,
                    ai_context=ai_context,
                    body=body_context,
                    body_context=normalized_body[number],
                    filename_number=filename_number,
                )
                if filename_number == number:
                    scored.append((candidate, evidence))
                elif candidate.score > 0 and not candidate.has_hard_contradiction:
                    scored.append((candidate, evidence))

            if filename_number and filename_number not in body_by_number:
                candidate_id = self._candidate_id(corpus_id, observation.source_asset_id, filename_number)
                evidence = self._evidence(
                    candidate_id=candidate_id,
                    family="identity",
                    method="filename_identifier",
                    value=observation.original_name,
                    normalized_value=filename_number,
                    score=0.35,
                    source_node_id=observation.source_asset_id,
                    source_sha256=observation.source_sha256,
                )
                scored.append(
                    (
                        DrawingCandidateResult(
                            candidate_id=candidate_id,
                            reference_corpus_id=corpus_id,
                            source_asset_id=observation.source_asset_id,
                            source_sha256=observation.source_sha256,
                            candidate_number=filename_number,
                            score=0.35,
                            evidence_families=("identity",),
                            evidence_ids=(evidence.id,),
                        ),
                        (evidence,),
                    )
                )

            scored.sort(key=lambda item: (-item[0].score, item[0].candidate_number))
            kept = scored[: self.maximum_content_candidates]
            scores = [item[0].score for item in kept]
            for index, (candidate, evidence) in enumerate(kept):
                runner_up = max((score for j, score in enumerate(scores) if j != index), default=0.0)
                updated = replace(
                    candidate,
                    runner_up_score=round(runner_up, 6),
                    margin=round(candidate.score - runner_up, 6),
                )
                all_candidates.append(updated)
                all_evidence.extend(evidence)

        canonical_drawings: list[DrawingData] = []
        ambiguous_sources: set[str] = set()
        unresolved_sources: set[str] = set()
        locked_numbers: set[str] = set()
        locked_sources: set[str] = set()

        for number, claims in direct_claims.items():
            if len(claims) != 1:
                ambiguous_sources.update(observation.source_asset_id for observation, _ in claims)
                continue
            observation, _candidate = claims[0]
            canonical_drawings.append(
                self._canonical_drawing(
                    corpus_id,
                    observation,
                    number,
                    EvidenceLevel.DIRECT,
                    "pdf_internal_identifier",
                    body_title_by_number.get(number, ""),
                )
            )
            locked_numbers.add(number)
            locked_sources.add(observation.source_asset_id)

        candidates_by_source: dict[str, list[DrawingCandidateResult]] = {}
        for candidate in all_candidates:
            if candidate.source_asset_id in sources_with_direct:
                continue
            candidates_by_source.setdefault(candidate.source_asset_id, []).append(candidate)

        locally_eligible: list[DrawingCandidateResult] = []
        for source_id, candidates in candidates_by_source.items():
            ordered = sorted(candidates, key=lambda item: (-item.score, item.candidate_number))
            if not ordered:
                unresolved_sources.add(source_id)
                continue
            top = ordered[0]
            second_score = ordered[1].score if len(ordered) > 1 else 0.0
            if len(ordered) > 1 and top.score > 0.20 and top.score - second_score < self.minimum_margin:
                ambiguous_sources.add(source_id)
                continue
            required_family = bool({"body_context", "semantic_content"} & set(top.evidence_families))
            if (
                top.has_hard_contradiction
                or top.score < self.minimum_score
                or top.margin < self.minimum_margin
                or len(set(top.evidence_families)) < 2
                or not required_family
                or top.candidate_number in locked_numbers
            ):
                if top.candidate_number in locked_numbers and top.score >= self.minimum_score:
                    ambiguous_sources.add(source_id)
                else:
                    unresolved_sources.add(source_id)
                continue
            locally_eligible.append(top)

        graph = nx.Graph()
        eligible_by_pair: dict[tuple[str, str], DrawingCandidateResult] = {}
        for candidate in locally_eligible:
            source_node = f"source:{candidate.source_asset_id}"
            drawing_node = f"drawing:{candidate.candidate_number}"
            graph.add_node(source_node, bipartite=0)
            graph.add_node(drawing_node, bipartite=1)
            graph.add_edge(source_node, drawing_node, weight=candidate.score)
            eligible_by_pair[(candidate.source_asset_id, candidate.candidate_number)] = candidate

        matched_pairs: set[tuple[str, str]] = set()
        for left, right in nx.algorithms.matching.max_weight_matching(graph, weight="weight"):
            source_node, drawing_node = (left, right) if left.startswith("source:") else (right, left)
            source_id = source_node.removeprefix("source:")
            number = drawing_node.removeprefix("drawing:")
            matched_pairs.add((source_id, number))

        promoted_candidate_ids: set[str] = set()
        for source_id, number in sorted(matched_pairs):
            candidate = eligible_by_pair[(source_id, number)]
            observation = observation_by_source[source_id]
            canonical_drawings.append(
                self._canonical_drawing(
                    corpus_id,
                    observation,
                    number,
                    EvidenceLevel.DERIVED_VERIFIED,
                    self.resolver_version,
                    body_title_by_number.get(number, ""),
                )
            )
            promoted_candidate_ids.add(candidate.candidate_id)

        eligible_ids = {candidate.candidate_id for candidate in locally_eligible}
        final_candidates: list[DrawingCandidateResult] = []
        for candidate in all_candidates:
            if candidate.evidence_level == EvidenceLevel.DIRECT:
                if candidate.source_asset_id in ambiguous_sources:
                    final_candidates.append(replace(candidate, status="ambiguous"))
                else:
                    final_candidates.append(candidate)
                continue
            if candidate.candidate_id in promoted_candidate_ids:
                final_candidates.append(
                    replace(candidate, status="verified", evidence_level=EvidenceLevel.DERIVED_VERIFIED)
                )
            elif candidate.candidate_id in eligible_ids:
                ambiguous_sources.add(candidate.source_asset_id)
                final_candidates.append(replace(candidate, status="ambiguous"))
            else:
                final_candidates.append(candidate)

        canonical_source_ids = {drawing.source_asset_id for drawing in canonical_drawings}
        for observation in observations:
            source_id = observation.source_asset_id
            if source_id in locked_sources:
                continue
            if source_id not in canonical_source_ids and source_id not in ambiguous_sources:
                unresolved_sources.add(source_id)

        counts = {level.value: 0 for level in EvidenceLevel}
        for candidate in final_candidates:
            counts[candidate.evidence_level.value] += 1

        return DrawingEvidenceResolution(
            canonical_drawings=tuple(sorted(canonical_drawings, key=lambda item: item.number)),
            candidates=tuple(sorted(final_candidates, key=lambda item: (item.source_asset_id, item.candidate_number))),
            evidence=tuple(all_evidence),
            context_facts=tuple(all_facts),
            unresolved_source_ids=tuple(sorted(unresolved_sources - ambiguous_sources)),
            ambiguous_source_ids=tuple(sorted(ambiguous_sources)),
            diagnostics={
                "resolverVersion": self.resolver_version,
                "evidenceCounts": counts,
                "canonicalDrawingCount": len(canonical_drawings),
                "ambiguousSourceCount": len(ambiguous_sources),
                "unresolvedSourceCount": len(unresolved_sources - ambiguous_sources),
            },
        )
