from __future__ import annotations

from collections import defaultdict
import hashlib
from pathlib import Path
import re

from app.domain.drawing_evidence import ContextFact
from app.domain.drawing_evidence_v3 import (
    BodyDrawingEvidencePacket,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
)
from app.services.drawing_context_normalizer import DrawingContextNormalizer


WEIGHTS = {
    "site_point": 8.0,
    "grid": 10.0,
    "feature_pair": 10.0,
    "period": 4.0,
    "drawing_type": 3.0,
    "map_type": 4.0,
    "year": 4.0,
    "token_overlap": 2.0,
    "sequence_neighbor": 1.0,
    "filename": 0.25,
    "path": 0.25,
}

_FAMILY_BY_KIND = {
    "site_point": "spatial_signature",
    "grid": "spatial_signature",
    "period": "archaeology_signature",
    "feature_type": "archaeology_signature",
    "feature_number": "archaeology_signature",
    "drawing_type": "drawing_signature",
    "map_type": "map_signature",
    "year": "map_signature",
}
_STRONG_NEGATIVE_KINDS = ("period", "map_type", "year")
_FILENAME_IDENTIFIER = re.compile(r"(도면|삽도)\s*(\d+(?:-\d+)?)", re.IGNORECASE)
_FILENAME_SEMANTIC_KINDS = ("site_point", "grid", "period", "drawing_type", "map_type", "year")
_FILENAME_SEMANTIC_SCALE = 0.5
_GENERIC_TOKENS = {"도면", "삽도", "도", "제", "및"}


class DrawingCandidateGeneratorV3:
    """Transparent, high-recall retrieval for drawing-evidence-v3.

    Scores are ordering signals only. Hard contradictions are filtered before
    ranking; filename/path/sequence signals remain explicitly weak evidence.
    """

    def __init__(self, normalizer: DrawingContextNormalizer | None = None) -> None:
        self._normalizer = normalizer or DrawingContextNormalizer()

    @staticmethod
    def _candidate_id(source_asset_id: str, publication_kind: str, number: str) -> str:
        return f"drawing-candidate:v3:{source_asset_id}:{publication_kind}:{number}"

    @staticmethod
    def _evidence_id(candidate_id: str, method: str, value: str) -> str:
        payload = "\0".join((candidate_id, method, value)).encode("utf-8")
        return "drawing-v3-evidence:" + hashlib.sha256(payload).hexdigest()[:32]

    @staticmethod
    def _kind_from_label(label: str) -> str:
        return "illustration" if label == "삽도" else "drawing"

    def _filename_identity(self, original_name: str) -> tuple[str | None, str | None]:
        matches = list(_FILENAME_IDENTIFIER.finditer(Path(original_name).stem))
        identities = {
            (self._kind_from_label(match.group(1)), match.group(2))
            for match in matches
        }
        if len(identities) != 1:
            return None, None
        return next(iter(identities))

    @staticmethod
    def _fact_values(facts: tuple[ContextFact, ...]) -> dict[str, set[str]]:
        values: dict[str, set[str]] = defaultdict(set)
        for fact in facts:
            values[fact.kind].add(fact.normalized_value)
        return dict(values)

    @staticmethod
    def _feature_pairs(values: dict[str, set[str]]) -> set[tuple[str, str]]:
        feature_types = values.get("feature_type", set())
        feature_numbers = values.get("feature_number", set())
        return {
            (feature_type, feature_number)
            for feature_type in feature_types
            for feature_number in feature_numbers
        }

    @staticmethod
    def _exact_feature_pairs(facts: tuple[ContextFact, ...]) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for fact in facts:
            if fact.kind != "feature":
                continue
            match = re.fullmatch(r"(\d+)호:(.+)", fact.normalized_value)
            if match:
                pairs.add((match.group(2), match.group(1)))
        return pairs

    @staticmethod
    def _dedupe_facts(facts: list[ContextFact]) -> tuple[ContextFact, ...]:
        deduped: dict[tuple[str, str, str | None], ContextFact] = {}
        for fact in facts:
            deduped[(fact.kind, fact.normalized_value, fact.source_node_id)] = fact
        return tuple(deduped.values())

    @staticmethod
    def _lexical_tokens(tokens: tuple[str, ...]) -> set[str]:
        return {
            token
            for token in tokens
            if token not in _GENERIC_TOKENS and len(token) > 1 and not token.isdigit()
        }

    def _source_context(self, source: DrawingSourceEvidencePacket):
        normalized = self._normalizer.normalize(
            source.raw_text,
            source_kind="drawing_ai",
            source_node_id=source.source_asset_id,
            source_sha256=source.source_sha256,
        )
        facts = self._dedupe_facts([*normalized.facts, *source.facts])
        source_kind = (
            source.publication_kind
            if source.publication_kind in {"drawing", "illustration"}
            else normalized.publication_kind
        )
        return normalized, facts, source_kind

    def _group_bodies(
        self,
        bodies: list[BodyDrawingEvidencePacket],
    ) -> list[tuple[str, str, tuple[str, ...], tuple[ContextFact, ...], tuple, tuple[str, ...]]]:
        grouped: dict[tuple[str, str], dict[str, list]] = {}
        for body in bodies:
            key = (body.publication_kind or "drawing", str(body.number))
            item = grouped.setdefault(
                key,
                {"raw_texts": [], "facts": [], "visual_regions": [], "source_ids": []},
            )
            for index, text in enumerate(body.raw_texts):
                source_node_id = (
                    body.source_node_ids[index]
                    if index < len(body.source_node_ids)
                    else body.source_node_ids[0]
                    if body.source_node_ids
                    else f"{key[0]}:{key[1]}:mention:{index + 1}"
                )
                normalized = self._normalizer.normalize(
                    text,
                    source_kind="body",
                    source_node_id=source_node_id,
                    source_sha256=body.source_sha256,
                )
                item["raw_texts"].append(text)
                item["facts"].extend(normalized.facts)
                item["source_ids"].append(source_node_id)
            item["visual_regions"].extend(body.visual_regions)

        result = []
        for (publication_kind, number), item in grouped.items():
            result.append(
                (
                    publication_kind,
                    number,
                    tuple(dict.fromkeys(item["raw_texts"])),
                    self._dedupe_facts(item["facts"]),
                    tuple(item["visual_regions"]),
                    tuple(dict.fromkeys(item["source_ids"])),
                )
            )
        return result

    def _evidence(
        self,
        candidate_id: str,
        *,
        family: str,
        method: str,
        value: str,
        supports: bool = True,
        weak: bool = False,
    ) -> DrawingV3Evidence:
        return DrawingV3Evidence(
            id=self._evidence_id(candidate_id, method, value),
            family=family,
            method=method,
            value=value,
            supports=supports,
            weak=weak,
        )

    @staticmethod
    def _has_explicit_disjoint(
        source_values: dict[str, set[str]],
        body_values: dict[str, set[str]],
        kind: str,
    ) -> bool:
        left = source_values.get(kind, set())
        right = body_values.get(kind, set())
        return bool(left and right and left.isdisjoint(right))

    def _rank_all(
        self,
        source: DrawingSourceEvidencePacket,
        bodies: list[BodyDrawingEvidencePacket],
    ) -> list[DrawingCandidatePacket]:
        source_normalized, source_facts, source_kind = self._source_context(source)
        source_values = self._fact_values(source_facts)
        source_tokens = self._lexical_tokens(source_normalized.tokens)
        filename_kind, filename_number = self._filename_identity(source.original_name)
        filename_context = self._normalizer.normalize(
            Path(source.original_name).stem,
            source_kind="filename",
            source_node_id=source.source_asset_id,
            source_sha256=source.source_sha256,
        )
        filename_values = self._fact_values(filename_context.facts)
        filename_feature_pairs = self._exact_feature_pairs(filename_context.facts)
        path_context = self._normalizer.normalize(
            source.source_path,
            source_kind="path",
            source_node_id=source.source_asset_id,
            source_sha256=source.source_sha256,
        )
        path_values = self._fact_values(path_context.facts)

        rows: list[DrawingCandidatePacket] = []
        for (
            publication_kind,
            number,
            raw_texts,
            body_facts,
            visual_regions,
            _source_ids,
        ) in self._group_bodies(bodies):
            if source_kind and source_kind != publication_kind:
                continue

            body_values = self._fact_values(body_facts)
            if self._has_explicit_disjoint(source_values, body_values, "site_point"):
                continue
            if self._has_explicit_disjoint(source_values, body_values, "grid"):
                continue
            source_pairs = self._feature_pairs(source_values)
            body_pairs = self._feature_pairs(body_values)
            if source_pairs and body_pairs and source_pairs.isdisjoint(body_pairs):
                continue

            candidate_id = self._candidate_id(
                source.source_asset_id, publication_kind, number
            )
            evidence: list[DrawingV3Evidence] = []
            strong_contradictions: list[str] = []
            score = 0.0

            for kind in ("site_point", "grid"):
                shared = source_values.get(kind, set()) & body_values.get(kind, set())
                for value in sorted(shared):
                    weight = WEIGHTS[kind]
                    score += weight
                    evidence.append(
                        self._evidence(
                            candidate_id,
                            family=_FAMILY_BY_KIND[kind],
                            method=f"exact_{kind}",
                            value=value,
                        )
                    )

            shared_pairs = source_pairs & body_pairs
            for feature_type, feature_number in sorted(shared_pairs):
                score += WEIGHTS["feature_pair"]
                evidence.append(
                    self._evidence(
                        candidate_id,
                        family="archaeology_signature",
                        method="exact_feature_pair",
                        value=f"{feature_type}:{feature_number}",
                    )
                )

            for kind in ("period", "drawing_type", "map_type", "year"):
                shared = source_values.get(kind, set()) & body_values.get(kind, set())
                for value in sorted(shared):
                    score += WEIGHTS[kind]
                    evidence.append(
                        self._evidence(
                            candidate_id,
                            family=_FAMILY_BY_KIND[kind],
                            method=f"exact_{kind}",
                            value=value,
                        )
                    )

            for kind in _STRONG_NEGATIVE_KINDS:
                left = source_values.get(kind, set())
                right = body_values.get(kind, set())
                if left and right and left.isdisjoint(right):
                    value = f"SOURCE={sorted(left)} BODY={sorted(right)}"
                    contradiction = self._evidence(
                        candidate_id,
                        family=_FAMILY_BY_KIND[kind],
                        method=f"strong_contradiction_{kind}",
                        value=value,
                        supports=False,
                    )
                    evidence.append(contradiction)
                    strong_contradictions.append(contradiction.id)
                    score -= WEIGHTS[kind]

            body_tokens: set[str] = set()
            for text in raw_texts:
                normalized = self._normalizer.normalize(text, source_kind="body")
                body_tokens.update(self._lexical_tokens(normalized.tokens))
            union = source_tokens | body_tokens
            shared_tokens = source_tokens & body_tokens
            if union and shared_tokens:
                lexical_score = WEIGHTS["token_overlap"] * len(shared_tokens) / len(union)
                score += lexical_score
                evidence.append(
                    self._evidence(
                        candidate_id,
                        family="lexical_support",
                        method="normalized_token_overlap",
                        value=" ".join(sorted(shared_tokens)),
                    )
                )

            for kind in _FILENAME_SEMANTIC_KINDS:
                shared = filename_values.get(kind, set()) & body_values.get(kind, set())
                for value in sorted(shared):
                    score += WEIGHTS[kind] * _FILENAME_SEMANTIC_SCALE
                    evidence.append(
                        self._evidence(
                            candidate_id,
                            family="weak_filename_semantic",
                            method=f"filename_semantic_exact_{kind}",
                            value=value,
                            weak=True,
                        )
                    )

            body_exact_feature_pairs = self._exact_feature_pairs(body_facts)
            for feature_type, feature_number in sorted(
                filename_feature_pairs & body_exact_feature_pairs
            ):
                score += WEIGHTS["feature_pair"] * _FILENAME_SEMANTIC_SCALE
                evidence.append(
                    self._evidence(
                        candidate_id,
                        family="weak_filename_semantic",
                        method="filename_semantic_feature_pair",
                        value=f"{feature_type}:{feature_number}",
                        weak=True,
                    )
                )

            if filename_kind == publication_kind and filename_number == number:
                score += WEIGHTS["filename"]
                evidence.append(
                    self._evidence(
                        candidate_id,
                        family="weak_identity",
                        method="filename_identity",
                        value=f"{publication_kind}:{number}",
                        weak=True,
                    )
                )

            if filename_kind == publication_kind and filename_number:
                try:
                    if int(filename_number) != int(number) and abs(
                        int(filename_number) - int(number)
                    ) == 1:
                        score += WEIGHTS["sequence_neighbor"]
                        evidence.append(
                            self._evidence(
                                candidate_id,
                                family="sequence_support",
                                method="sequence_neighbor",
                                value=f"{filename_number}->{number}",
                                weak=True,
                            )
                        )
                except ValueError:
                    pass

            path_sites = path_values.get("site_point", set())
            body_sites = body_values.get("site_point", set())
            for value in sorted(path_sites & body_sites):
                score += WEIGHTS["path"]
                evidence.append(
                    self._evidence(
                        candidate_id,
                        family="path_support",
                        method="path_site_point",
                        value=value,
                        weak=True,
                    )
                )

            rows.append(
                DrawingCandidatePacket(
                    candidate_id=candidate_id,
                    publication_kind=publication_kind,
                    number=number,
                    raw_texts=raw_texts,
                    facts=body_facts,
                    visual_regions=visual_regions,
                    local_score=round(score, 6),
                    evidence=tuple(evidence),
                    hard_contradiction=False,
                    strong_contradiction_ids=tuple(strong_contradictions),
                )
            )

        rows.sort(
            key=lambda row: (
                -row.local_score,
                row.publication_kind,
                int(row.number) if row.number.isdigit() else 2**31,
                row.number,
            )
        )
        return rows

    def generate(
        self,
        source: DrawingSourceEvidencePacket,
        bodies: list[BodyDrawingEvidencePacket],
        limit: int = 10,
    ) -> tuple[DrawingCandidatePacket, ...]:
        if limit <= 0:
            return ()
        return tuple(self._rank_all(source, bodies)[:limit])

    def expand(
        self,
        source: DrawingSourceEvidencePacket,
        bodies: list[BodyDrawingEvidencePacket],
        existing_candidate_ids: set[str],
        limit: int = 20,
    ) -> tuple[DrawingCandidatePacket, ...]:
        del existing_candidate_ids  # top-K is deterministic; reranking must remain stable.
        if limit <= 0:
            return ()
        return tuple(self._rank_all(source, bodies)[:limit])
