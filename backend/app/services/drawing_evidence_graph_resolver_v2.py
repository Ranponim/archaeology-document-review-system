from __future__ import annotations

from collections import Counter
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


_FILENAME_IDENTIFIER = re.compile(r"(도면|삽도)\s*(\d+(?:-\d+)?)", re.IGNORECASE)
_SEMANTIC_WEIGHTS = {
    "site_point": 0.24,
    "grid": 0.28,
    "period": 0.18,
    "feature_type": 0.22,
    "feature_number": 0.18,
    "drawing_type": 0.14,
    "direction": 0.08,
    "section_label": 0.12,
    "content_type": 0.10,
    "map_type": 0.22,
    "year": 0.22,
}
_FAMILY_BY_KIND = {
    "site_point": "spatial_signature",
    "grid": "spatial_signature",
    "direction": "spatial_signature",
    "period": "archaeology_signature",
    "feature_type": "archaeology_signature",
    "feature_number": "archaeology_signature",
    "drawing_type": "drawing_signature",
    "section_label": "drawing_signature",
    "content_type": "drawing_signature",
    "map_type": "map_signature",
    "year": "map_signature",
}
_PROMOTION_FAMILIES = {
    "spatial_signature",
    "archaeology_signature",
    "drawing_signature",
    "map_signature",
}
_STRONG_CONTRADICTIONS = {"period", "map_type", "year"}
_GENERIC_TOKENS = {"도면", "삽도", "도", "제", "및"}


class DrawingEvidenceGraphResolverV2:
    resolver_version = "drawing-evidence-v2"
    minimum_score = 0.70
    minimum_margin = 0.10
    maximum_content_candidates = 5

    def __init__(self, normalizer: DrawingContextNormalizer | None = None) -> None:
        self._normalizer = normalizer or DrawingContextNormalizer()

    @staticmethod
    def _kind_from_label(label: str) -> str:
        return "illustration" if label == "삽도" else "drawing"

    def _filename_identity(self, name: str) -> tuple[str | None, str | None]:
        matches = list(_FILENAME_IDENTIFIER.finditer(Path(name).stem))
        identities = {(self._kind_from_label(m.group(1)), m.group(2)) for m in matches}
        if len(identities) != 1:
            return None, None
        return next(iter(identities))

    def _observation_kind(self, observation: DrawingSourceObservation) -> str | None:
        if observation.publication_kind in {"drawing", "illustration"}:
            return observation.publication_kind
        context = self._normalizer.normalize(
            observation.raw_text,
            source_kind="drawing_ai",
            source_node_id=observation.source_asset_id,
            source_sha256=observation.source_sha256,
        )
        if context.publication_kind:
            return context.publication_kind
        filename_kind, _ = self._filename_identity(observation.original_name)
        return filename_kind

    @staticmethod
    def _candidate_id(corpus_id: str, source_id: str, kind: str, number: str) -> str:
        return f"drawing-candidate:{corpus_id}:{source_id}:{kind}:{number}"

    @staticmethod
    def _evidence_id(candidate_id: str, method: str, value: str, source_node_id: str | None) -> str:
        payload = "\0".join((candidate_id, method, value, source_node_id or "")).encode("utf-8")
        return "resolution-evidence:" + hashlib.sha256(payload).hexdigest()[:32]

    @staticmethod
    def _by_kind(context: NormalizedDrawingContext) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for fact in context.facts:
            if fact.kind in _SEMANTIC_WEIGHTS:
                result.setdefault(fact.kind, set()).add(fact.normalized_value)
        return result

    @staticmethod
    def _lexical_tokens(context: NormalizedDrawingContext) -> set[str]:
        return {
            token for token in context.tokens
            if token not in _GENERIC_TOKENS and not token.isdigit() and len(token) > 1
        }

    def _mention_contexts(self, body: BodyDrawingContext) -> tuple[NormalizedDrawingContext, ...]:
        contexts = []
        for index, text in enumerate(body.raw_texts):
            mention_id = (
                body.mention_context_ids[index]
                if index < len(body.mention_context_ids)
                else body.source_node_ids[index]
                if index < len(body.source_node_ids)
                else f"{body.publication_kind}:{body.number}:mention:{index + 1}"
            )
            contexts.append(
                self._normalizer.normalize(
                    text,
                    source_kind="body",
                    source_node_id=mention_id,
                    source_sha256=body.source_sha256,
                )
            )
        return tuple(contexts)

    @staticmethod
    def _annotate_consensus(
        contexts: tuple[NormalizedDrawingContext, ...],
        publication_kind: str,
    ) -> tuple[tuple[NormalizedDrawingContext, ...], tuple[ContextFact, ...]]:
        occurrence: Counter[tuple[str, str]] = Counter()
        values_by_kind: dict[str, set[str]] = {}
        for context in contexts:
            seen = set()
            for fact in context.facts:
                if fact.kind not in _SEMANTIC_WEIGHTS:
                    continue
                key = (fact.kind, fact.normalized_value)
                seen.add(key)
                values_by_kind.setdefault(fact.kind, set()).add(fact.normalized_value)
            occurrence.update(seen)

        annotated_contexts = []
        all_facts: list[ContextFact] = []
        for context in contexts:
            annotated = []
            for fact in context.facts:
                key = (fact.kind, fact.normalized_value)
                if fact.kind not in _SEMANTIC_WEIGHTS:
                    status = fact.consensus_status
                elif occurrence[key] >= 2:
                    status = "consensus"
                elif len(values_by_kind.get(fact.kind, set())) > 1:
                    status = "conflict"
                else:
                    status = "mention_local"
                updated = replace(
                    fact,
                    publication_kind=publication_kind,
                    consensus_status=status,
                    mention_context_id=fact.source_node_id,
                )
                annotated.append(updated)
                all_facts.append(updated)
            annotated_contexts.append(replace(context, facts=tuple(annotated), publication_kind=publication_kind))
        return tuple(annotated_contexts), tuple(all_facts)

    @staticmethod
    def _feature_pairs(facts: dict[str, set[str]]) -> set[tuple[str, str]]:
        types = facts.get("feature_type", set())
        numbers = facts.get("feature_number", set())
        return {(kind, number) for kind in types for number in numbers}

    def _evidence(
        self,
        candidate_id: str,
        *,
        family: str,
        method: str,
        value: str,
        score: float,
        source_node_id: str | None,
        source_sha256: str | None,
        publication_kind: str,
        supports: bool = True,
        consensus_status: str = "mention_local",
        tie_breaker_class: str = "semantic",
    ) -> DrawingCandidateEvidence:
        return DrawingCandidateEvidence(
            id=self._evidence_id(candidate_id, method, value, source_node_id),
            candidate_id=candidate_id,
            family=family,
            method=method,
            value=value,
            normalized_value=value,
            score=score,
            supports=supports,
            source_node_id=source_node_id,
            source_sha256=source_sha256,
            publication_kind=publication_kind,
            mention_context_id=source_node_id,
            consensus_status=consensus_status,
            tie_breaker_class=tie_breaker_class,
        )

    def _score_mention(
        self,
        *,
        candidate_id: str,
        ai: NormalizedDrawingContext,
        mention: NormalizedDrawingContext,
        body: BodyDrawingContext,
        publication_kind: str,
    ) -> tuple[float, list[DrawingCandidateEvidence], bool, bool, set[str]]:
        ai_facts = self._by_kind(ai)
        body_facts = self._by_kind(mention)
        evidence: list[DrawingCandidateEvidence] = []
        families: set[str] = set()
        hard = False
        strong = False
        score = 0.0
        source_id = mention.facts[0].source_node_id if mention.facts else None

        for kind in ("site_point", "grid"):
            left, right = ai_facts.get(kind, set()), body_facts.get(kind, set())
            if left and right and left.isdisjoint(right):
                hard = True
                evidence.append(self._evidence(
                    candidate_id,
                    family=_FAMILY_BY_KIND[kind],
                    method=f"contradicting_{kind}",
                    value=f"AI={sorted(left)} BODY={sorted(right)}",
                    score=-1.0,
                    source_node_id=source_id,
                    source_sha256=body.source_sha256,
                    publication_kind=publication_kind,
                    supports=False,
                ))

        ai_pairs, body_pairs = self._feature_pairs(ai_facts), self._feature_pairs(body_facts)
        if ai_pairs and body_pairs and ai_pairs.isdisjoint(body_pairs):
            hard = True
            evidence.append(self._evidence(
                candidate_id,
                family="archaeology_signature",
                method="contradicting_feature_pair",
                value=f"AI={sorted(ai_pairs)} BODY={sorted(body_pairs)}",
                score=-1.0,
                source_node_id=source_id,
                source_sha256=body.source_sha256,
                publication_kind=publication_kind,
                supports=False,
            ))

        for kind in _STRONG_CONTRADICTIONS:
            left, right = ai_facts.get(kind, set()), body_facts.get(kind, set())
            if left and right and left.isdisjoint(right):
                strong = True
                evidence.append(self._evidence(
                    candidate_id,
                    family=_FAMILY_BY_KIND[kind],
                    method=f"strong_contradiction_{kind}",
                    value=f"AI={sorted(left)} BODY={sorted(right)}",
                    score=-0.45,
                    source_node_id=source_id,
                    source_sha256=body.source_sha256,
                    publication_kind=publication_kind,
                    supports=False,
                ))
                score -= 0.45

        for kind, weight in _SEMANTIC_WEIGHTS.items():
            shared = ai_facts.get(kind, set()) & body_facts.get(kind, set())
            family = _FAMILY_BY_KIND[kind]
            for value in sorted(shared):
                consensus = any(
                    fact.kind == kind
                    and fact.normalized_value == value
                    and fact.consensus_status == "consensus"
                    for fact in mention.facts
                )
                contribution = weight * (1.20 if consensus else 1.0)
                score += contribution
                families.add(family)
                evidence.append(self._evidence(
                    candidate_id,
                    family=family,
                    method=f"exact_{kind}",
                    value=value,
                    score=round(contribution, 6),
                    source_node_id=source_id,
                    source_sha256=body.source_sha256,
                    publication_kind=publication_kind,
                    consensus_status="consensus" if consensus else "mention_local",
                ))

        ai_tokens = self._lexical_tokens(ai)
        body_tokens = self._lexical_tokens(mention)
        union = ai_tokens | body_tokens
        shared = ai_tokens & body_tokens
        if union and shared:
            lexical = min(0.08, 0.08 * len(shared) / len(union))
            score += lexical
            evidence.append(self._evidence(
                candidate_id,
                family="lexical_support",
                method="normalized_token_overlap",
                value=" ".join(sorted(shared)),
                score=round(lexical, 6),
                source_node_id=source_id,
                source_sha256=body.source_sha256,
                publication_kind=publication_kind,
            ))
        return score, evidence, hard, strong, families

    def _canonical(
        self,
        corpus_id: str,
        observation: DrawingSourceObservation,
        kind: str,
        number: str,
        level: EvidenceLevel,
        title: str,
        method: str,
    ) -> DrawingData:
        return DrawingData(
            drawing_id=f"drawing:{corpus_id}:{kind}:{number}",
            number=number,
            physical_page=1,
            title=title,
            source_sha256=observation.source_sha256,
            source_kind="drawing_ai",
            reference_corpus_id=corpus_id,
            source_asset_id=observation.source_asset_id,
            evidence_level=level,
            evidence_method=method,
            publication_kind=kind,
        )

    def resolve_observations(
        self,
        *,
        corpus_id: str,
        observations: list[DrawingSourceObservation],
        body_contexts: list[BodyDrawingContext],
        include_filename_evidence: bool = True,
    ) -> DrawingEvidenceResolution:
        body_by_key: dict[tuple[str, str], BodyDrawingContext] = {
            (item.publication_kind or "drawing", str(item.number)): item for item in body_contexts
        }
        mentions_by_key: dict[tuple[str, str], tuple[NormalizedDrawingContext, ...]] = {}
        context_facts: list[ContextFact] = []
        for key, body in body_by_key.items():
            mentions, facts = self._annotate_consensus(self._mention_contexts(body), key[0])
            mentions_by_key[key] = mentions
            context_facts.extend(facts)

        candidates: list[DrawingCandidateResult] = []
        evidence: list[DrawingCandidateEvidence] = []
        direct_claims: dict[tuple[str, str], list[DrawingSourceObservation]] = {}
        source_by_id = {item.source_asset_id: item for item in observations}
        sources_with_direct: set[str] = set()

        for observation in observations:
            ai = self._normalizer.normalize(
                observation.raw_text,
                source_kind="drawing_ai",
                source_node_id=observation.source_asset_id,
                source_sha256=observation.source_sha256,
            )
            context_facts.extend(ai.facts)
            source_kind = self._observation_kind(observation)
            internal_numbers = tuple(sorted(set(observation.internal_numbers)))
            if len(internal_numbers) == 1:
                kind = source_kind or "drawing"
                number = internal_numbers[0]
                candidate_id = self._candidate_id(corpus_id, observation.source_asset_id, kind, number)
                direct_ev = self._evidence(
                    candidate_id,
                    family="identity",
                    method="pdf_internal_identifier",
                    value=f"{kind}:{number}",
                    score=1.0,
                    source_node_id=observation.source_asset_id,
                    source_sha256=observation.source_sha256,
                    publication_kind=kind,
                    tie_breaker_class="semantic",
                )
                evidence.append(direct_ev)
                candidates.append(DrawingCandidateResult(
                    candidate_id=candidate_id,
                    reference_corpus_id=corpus_id,
                    source_asset_id=observation.source_asset_id,
                    source_sha256=observation.source_sha256,
                    candidate_number=number,
                    status="verified",
                    evidence_level=EvidenceLevel.DIRECT,
                    resolver_version=self.resolver_version,
                    score=1.0,
                    runner_up_score=0.0,
                    margin=1.0,
                    evidence_families=("identity",),
                    evidence_ids=(direct_ev.id,),
                    publication_kind=kind,
                ))
                direct_claims.setdefault((kind, number), []).append(observation)
                sources_with_direct.add(observation.source_asset_id)
                continue

            filename_kind, filename_number = self._filename_identity(observation.original_name)
            scored: list[tuple[DrawingCandidateResult, list[DrawingCandidateEvidence]]] = []
            for (kind, number), body in body_by_key.items():
                candidate_id = self._candidate_id(corpus_id, observation.source_asset_id, kind, number)
                kind_hard = bool(source_kind and source_kind != kind)
                best: tuple[float, list[DrawingCandidateEvidence], bool, bool, set[str]] | None = None
                for mention in mentions_by_key[(kind, number)]:
                    row = self._score_mention(
                        candidate_id=candidate_id,
                        ai=ai,
                        mention=mention,
                        body=body,
                        publication_kind=kind,
                    )
                    if best is None or row[0] > best[0]:
                        best = row
                if best is None:
                    best = (0.0, [], False, False, set())
                score, row_evidence, hard, strong, families = best
                hard = hard or kind_hard
                tie_classes: set[str] = set()
                if kind_hard:
                    row_evidence.append(self._evidence(
                        candidate_id,
                        family="identity",
                        method="contradicting_publication_kind",
                        value=f"AI={source_kind} BODY={kind}",
                        score=-1.0,
                        source_node_id=observation.source_asset_id,
                        source_sha256=observation.source_sha256,
                        publication_kind=kind,
                        supports=False,
                    ))

                if include_filename_evidence and filename_number == number and (not filename_kind or filename_kind == kind):
                    score += 0.10
                    tie_classes.add("filename")
                    row_evidence.append(self._evidence(
                        candidate_id,
                        family="identity",
                        method="filename_identifier",
                        value=observation.original_name,
                        score=0.10,
                        source_node_id=observation.source_asset_id,
                        source_sha256=observation.source_sha256,
                        publication_kind=kind,
                        tie_breaker_class="filename",
                    ))

                path_context = self._normalizer.normalize(
                    observation.source_path,
                    source_kind="path",
                    source_node_id=observation.source_asset_id,
                    source_sha256=observation.source_sha256,
                )
                path_points = self._by_kind(path_context).get("site_point", set())
                body_points = set()
                for mention in mentions_by_key[(kind, number)]:
                    body_points |= self._by_kind(mention).get("site_point", set())
                if path_points and body_points and not path_points.isdisjoint(body_points):
                    score += 0.04
                    tie_classes.add("path")
                    row_evidence.append(self._evidence(
                        candidate_id,
                        family="path_context",
                        method="path_site_point",
                        value=next(iter(path_points & body_points)),
                        score=0.04,
                        source_node_id=observation.source_asset_id,
                        source_sha256=observation.source_sha256,
                        publication_kind=kind,
                        tie_breaker_class="path",
                    ))

                if score > 0 or hard or strong or (filename_number == number and include_filename_evidence):
                    scored.append((
                        DrawingCandidateResult(
                            candidate_id=candidate_id,
                            reference_corpus_id=corpus_id,
                            source_asset_id=observation.source_asset_id,
                            source_sha256=observation.source_sha256,
                            candidate_number=number,
                            resolver_version=self.resolver_version,
                            score=round(score, 6),
                            evidence_families=tuple(sorted(families | ({"identity"} if any(e.method == "filename_identifier" for e in row_evidence) else set()))),
                            evidence_ids=tuple(e.id for e in row_evidence),
                            has_hard_contradiction=hard,
                            publication_kind=kind,
                            tie_breaker_classes=tuple(sorted(tie_classes)),
                            has_strong_contradiction=strong,
                        ),
                        row_evidence,
                    ))

            scored.sort(key=lambda item: (-item[0].score, item[0].publication_kind, item[0].candidate_number))
            kept = scored[: self.maximum_content_candidates]
            scores = [item[0].score for item in kept]
            for index, (candidate, row_evidence) in enumerate(kept):
                runner = max((value for j, value in enumerate(scores) if j != index), default=0.0)
                candidate = replace(
                    candidate,
                    runner_up_score=round(runner, 6),
                    margin=round(candidate.score - runner, 6),
                )
                candidates.append(candidate)
                evidence.extend(row_evidence)

        canonical: list[DrawingData] = []
        ambiguous: set[str] = set()
        unresolved: set[str] = set()
        locked_targets: set[tuple[str, str]] = set()
        locked_sources: set[str] = set()
        for key, claims in direct_claims.items():
            if len(claims) != 1:
                ambiguous.update(item.source_asset_id for item in claims)
                continue
            observation = claims[0]
            body = body_by_key.get(key)
            title = body.raw_texts[0] if body and body.raw_texts else ""
            canonical.append(self._canonical(
                corpus_id, observation, key[0], key[1], EvidenceLevel.DIRECT, title, "pdf_internal_identifier"
            ))
            locked_targets.add(key)
            locked_sources.add(observation.source_asset_id)

        by_source: dict[str, list[DrawingCandidateResult]] = {}
        for candidate in candidates:
            if candidate.source_asset_id in sources_with_direct:
                continue
            by_source.setdefault(candidate.source_asset_id, []).append(candidate)

        eligible: list[DrawingCandidateResult] = []
        for source_id, rows in by_source.items():
            rows = sorted(rows, key=lambda item: (-item.score, item.publication_kind, item.candidate_number))
            if not rows:
                unresolved.add(source_id)
                continue
            top = rows[0]
            semantic_families = _PROMOTION_FAMILIES & set(top.evidence_families)
            if (
                top.has_hard_contradiction
                or top.has_strong_contradiction
                or top.score < self.minimum_score
                or top.margin < self.minimum_margin
                or len(semantic_families) < 2
                or (top.publication_kind, top.candidate_number) in locked_targets
            ):
                if len(rows) > 1 and top.score >= 0.20 and top.margin < self.minimum_margin:
                    ambiguous.add(source_id)
                else:
                    unresolved.add(source_id)
                continue
            eligible.append(top)

        graph = nx.Graph()
        eligible_by_pair: dict[tuple[str, str, str], DrawingCandidateResult] = {}
        for candidate in eligible:
            source_node = f"source:{candidate.source_asset_id}"
            target_node = f"target:{candidate.publication_kind}:{candidate.candidate_number}"
            graph.add_edge(source_node, target_node, weight=candidate.score)
            eligible_by_pair[(candidate.source_asset_id, candidate.publication_kind, candidate.candidate_number)] = candidate

        promoted_ids: set[str] = set()
        for left, right in nx.algorithms.matching.max_weight_matching(graph, weight="weight"):
            source_node, target_node = (left, right) if left.startswith("source:") else (right, left)
            source_id = source_node.removeprefix("source:")
            _, kind, number = target_node.split(":", 2)
            candidate = eligible_by_pair[(source_id, kind, number)]
            observation = source_by_id[source_id]
            body = body_by_key.get((kind, number))
            title = body.raw_texts[0] if body and body.raw_texts else ""
            canonical.append(self._canonical(
                corpus_id, observation, kind, number, EvidenceLevel.DERIVED_VERIFIED, title, self.resolver_version
            ))
            promoted_ids.add(candidate.candidate_id)

        final_candidates = []
        for candidate in candidates:
            if candidate.evidence_level == EvidenceLevel.DIRECT:
                final_candidates.append(candidate)
            elif candidate.candidate_id in promoted_ids:
                final_candidates.append(replace(
                    candidate, status="verified", evidence_level=EvidenceLevel.DERIVED_VERIFIED
                ))
            elif candidate.source_asset_id in ambiguous:
                final_candidates.append(replace(candidate, status="ambiguous"))
            else:
                final_candidates.append(candidate)

        promoted = [item for item in final_candidates if item.status == "verified"]
        filename_only_verified = sum(
            1 for item in promoted
            if item.evidence_level != EvidenceLevel.DIRECT
            and not (_PROMOTION_FAMILIES & set(item.evidence_families))
        )
        hard_promoted = sum(1 for item in promoted if item.has_hard_contradiction)
        target_keys = [(item.publication_kind, item.number) for item in canonical]
        kind_collision_count = 0
        # Same number across kinds is valid; collision means one source was promoted
        # to conflicting explicit kinds, which the one-to-one source side prevents.
        for source_id in {item.source_asset_id for item in canonical if item.source_asset_id}:
            kinds = {item.publication_kind for item in canonical if item.source_asset_id == source_id}
            if len(kinds) > 1:
                kind_collision_count += 1

        resolved_source_ids = {item.source_asset_id for item in canonical if item.source_asset_id}
        for observation in observations:
            if observation.source_asset_id not in resolved_source_ids and observation.source_asset_id not in ambiguous:
                unresolved.add(observation.source_asset_id)

        return DrawingEvidenceResolution(
            canonical_drawings=tuple(sorted(canonical, key=lambda item: (item.publication_kind, item.number, item.drawing_id))),
            candidates=tuple(final_candidates),
            evidence=tuple(evidence),
            context_facts=tuple(context_facts),
            unresolved_source_ids=tuple(sorted(unresolved)),
            ambiguous_source_ids=tuple(sorted(ambiguous)),
            diagnostics={
                "resolverVersion": self.resolver_version,
                "canonicalDrawingCount": len(canonical),
                "filenameOnlyVerifiedCount": filename_only_verified,
                "hardContradictionPromotedCount": hard_promoted,
                "kindCollisionCount": kind_collision_count,
                "targetIdentityCount": len(set(target_keys)),
            },
        )
