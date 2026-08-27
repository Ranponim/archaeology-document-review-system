from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.domain.drawing_evidence_v3 import (
    BodyDrawingEvidencePacket,
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Resolution,
    DrawingV3SourceResult,
)
from app.services.codex_drawing_resolver_client import CodexDrawingDecisionError


class DrawingEvidenceResolverV3:
    resolver_version = "drawing-evidence-v3"

    def __init__(
        self,
        candidate_generator,
        codex_client,
        *,
        auto_confidence: float = 0.95,
        max_candidates: int = 10,
        max_expansions: int = 1,
    ) -> None:
        if not 0.0 <= auto_confidence <= 1.0:
            raise ValueError("auto_confidence must be between 0 and 1")
        if max_candidates <= 0:
            raise ValueError("max_candidates must be positive")
        if max_expansions < 0:
            raise ValueError("max_expansions must be non-negative")
        self._generator = candidate_generator
        self._codex = codex_client
        self._auto_confidence = auto_confidence
        self._max_candidates = max_candidates
        self._max_expansions = max_expansions

    @staticmethod
    def _selected_candidate(
        decision: CodexDrawingDecision | None,
        candidates: tuple[DrawingCandidatePacket, ...],
    ) -> DrawingCandidatePacket | None:
        if decision is None or decision.verdict != "match" or not decision.candidate_id:
            return None
        return next(
            (row for row in candidates if row.candidate_id == decision.candidate_id),
            None,
        )

    def _final_status(
        self,
        source: DrawingSourceEvidencePacket,
        candidates: tuple[DrawingCandidatePacket, ...],
        decision: CodexDrawingDecision | None,
    ) -> str:
        if decision is None:
            return "REVIEW_REQUIRED"
        if decision.verdict == "none":
            return "UNRESOLVED"
        if decision.verdict != "match":
            return "REVIEW_REQUIRED"

        candidate = self._selected_candidate(decision, candidates)
        if candidate is None:
            return "REVIEW_REQUIRED"
        if candidate.hard_contradiction:
            return "REVIEW_REQUIRED"
        if decision.confidence < self._auto_confidence:
            return "REVIEW_REQUIRED"
        if decision.cited_contradiction_ids:
            return "REVIEW_REQUIRED"

        evidence_by_id = {item.id: item for item in source.evidence}
        evidence_by_id.update({item.id: item for item in candidate.evidence})
        cited = []
        for evidence_id in decision.cited_support_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None or not item.supports:
                return "REVIEW_REQUIRED"
            cited.append(item)
        families = {item.family for item in cited}
        if len(families) < 2:
            return "REVIEW_REQUIRED"
        if not any(not item.weak for item in cited):
            return "REVIEW_REQUIRED"
        return "AUTO_VERIFIED"

    def _resolve_one(
        self,
        source: DrawingSourceEvidencePacket,
        bodies: list[BodyDrawingEvidencePacket],
    ) -> DrawingV3SourceResult:
        candidates = tuple(
            self._generator.generate(
                source,
                bodies,
                limit=self._max_candidates,
            )
        )
        decision: CodexDrawingDecision | None = None
        last_error: str | None = None
        expansion_count = 0

        try:
            decision = self._codex.resolve(source, candidates)
        except CodexDrawingDecisionError as exc:
            last_error = str(exc)

        should_expand = (
            self._max_expansions > 0
            and last_error is None
            and decision is not None
            and decision.verdict in {"ambiguous", "none"}
        )
        if should_expand:
            for _ in range(self._max_expansions):
                expansion_count += 1
                candidates = tuple(
                    self._generator.expand(
                        source,
                        bodies,
                        existing_candidate_ids={row.candidate_id for row in candidates},
                        limit=max(20, self._max_candidates),
                    )
                )
                try:
                    decision = self._codex.resolve(source, candidates)
                    last_error = None
                except CodexDrawingDecisionError as exc:
                    decision = None
                    last_error = str(exc)
                # v3 currently permits one bounded expansion. Keep the loop
                # generic so config=0/1 remains explicit and fail closed.
                break

        selected = self._selected_candidate(decision, candidates)
        status = self._final_status(source, candidates, decision)
        return DrawingV3SourceResult(
            source_asset_id=source.source_asset_id,
            status=status,
            candidates=candidates,
            decision=decision,
            selected_candidate_id=selected.candidate_id if selected else None,
            diagnostics={
                "resolver_version": self.resolver_version,
                "candidate_count": len(candidates),
                "expansion_count": expansion_count,
                "codex_error": last_error,
                "assignment_conflict": False,
            },
        )

    @staticmethod
    def _nonweak_cited_count(
        source: DrawingSourceEvidencePacket,
        result: DrawingV3SourceResult,
        candidate: DrawingCandidatePacket,
    ) -> int:
        if result.decision is None:
            return 0
        evidence_by_id = {item.id: item for item in source.evidence}
        evidence_by_id.update({item.id: item for item in candidate.evidence})
        return sum(
            1
            for evidence_id in result.decision.cited_support_ids
            if (item := evidence_by_id.get(evidence_id)) is not None and not item.weak
        )

    def _apply_assignment_conflicts(
        self,
        sources: list[DrawingSourceEvidencePacket],
        results: list[DrawingV3SourceResult],
    ) -> list[DrawingV3SourceResult]:
        source_by_id = {source.source_asset_id: source for source in sources}
        grouped: dict[tuple[str, str], list[int]] = {}
        candidate_by_index: dict[int, DrawingCandidatePacket] = {}

        for index, result in enumerate(results):
            if result.status != "AUTO_VERIFIED" or not result.selected_candidate_id:
                continue
            candidate = next(
                (
                    row
                    for row in result.candidates
                    if row.candidate_id == result.selected_candidate_id
                ),
                None,
            )
            if candidate is None:
                continue
            candidate_by_index[index] = candidate
            grouped.setdefault(
                (candidate.publication_kind, candidate.number), []
            ).append(index)

        updated = list(results)
        for target, indexes in grouped.items():
            if len(indexes) <= 1:
                continue

            def rank(index: int) -> tuple[int, float, int, str]:
                result = results[index]
                source = source_by_id[result.source_asset_id]
                candidate = candidate_by_index[index]
                internal_agreement = int(candidate.number in source.internal_numbers)
                confidence = result.decision.confidence if result.decision else 0.0
                nonweak = self._nonweak_cited_count(source, result, candidate)
                return (
                    -internal_agreement,
                    -confidence,
                    -nonweak,
                    result.source_asset_id,
                )

            winner = sorted(indexes, key=rank)[0]
            for index in indexes:
                if index == winner:
                    continue
                diagnostics = dict(updated[index].diagnostics)
                diagnostics.update(
                    {
                        "assignment_conflict": True,
                        "assignment_target": f"{target[0]}:{target[1]}",
                        "assignment_winner_source_asset_id": results[winner].source_asset_id,
                    }
                )
                updated[index] = replace(
                    updated[index],
                    status="REVIEW_REQUIRED",
                    diagnostics=diagnostics,
                )
        return updated

    def resolve_observations(
        self,
        corpus_id: str,
        sources: list[DrawingSourceEvidencePacket],
        bodies: list[BodyDrawingEvidencePacket],
        body_pdf_path: str | None = None,
        render_dir: str | None = None,
    ) -> DrawingV3Resolution:
        del body_pdf_path, render_dir  # visual packet assembly is wired by the corpus/evaluator layer.
        results = [self._resolve_one(source, bodies) for source in sources]
        results = self._apply_assignment_conflicts(sources, results)
        return DrawingV3Resolution(
            source_results=tuple(results),
            diagnostics={
                "resolver_version": self.resolver_version,
                "reference_corpus_id": corpus_id,
                "source_count": len(sources),
                "auto_verified_count": sum(
                    result.status == "AUTO_VERIFIED" for result in results
                ),
                "review_required_count": sum(
                    result.status == "REVIEW_REQUIRED" for result in results
                ),
                "unresolved_count": sum(
                    result.status == "UNRESOLVED" for result in results
                ),
            },
        )
