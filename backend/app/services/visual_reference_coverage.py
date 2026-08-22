from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from app.domain.canonical_models import ArchaeologyObjectData
from app.domain.evidence_bundle import ObjectEvidenceBundle
from app.domain.review_models import CorrectionCandidateData, EvidenceData


_BLANK_BOTH_RE = re.compile(
    r"\(\s*도면\s*:\s*(?P<drawing>[^,\)]*)\s*,\s*도판\s*:\s*(?P<plate>[^\)]*)\s*\)"
)


@dataclass(frozen=True, slots=True)
class _CanonicalGroup:
    ref_type: str
    number: str
    evidences: tuple[EvidenceData, ...]

    @property
    def key(self) -> tuple[str, str]:
        return self.ref_type, self.number


class VisualReferenceCoverageService:
    """Detect missing visual references from graph-derived evidence only.

    The service has deliberately no filesystem or OriginalAsset dependency.
    Publication identity comes only from plate/drawing claim evidence already
    reached through the canonical graph.
    """

    @staticmethod
    def _dict_value(ev: EvidenceData) -> dict[str, Any]:
        return ev.value if isinstance(ev.value, dict) else {}

    @staticmethod
    def _norm_number(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _reference_key(cls, ev: EvidenceData) -> tuple[str, str] | None:
        value = cls._dict_value(ev)
        ref_type = str(value.get("ref_type") or value.get("reference_type") or "").lower().strip()
        if ref_type in {"도판", "photo", "사진", "plate"}:
            ref_type = "plate"
        elif ref_type in {"도면", "drawing"}:
            ref_type = "drawing"
        else:
            return None
        number = cls._norm_number(value.get("number") or value.get("reference_number"))
        return (ref_type, number) if number else None

    @classmethod
    def _canonical_groups(
        cls, bundle: ObjectEvidenceBundle
    ) -> dict[str, dict[str, _CanonicalGroup]]:
        grouped: dict[str, dict[str, list[EvidenceData]]] = {"drawing": {}, "plate": {}}
        for ref_type, evidences, number_key in (
            ("drawing", bundle.drawing_claims, "drawing_number"),
            ("plate", bundle.plate_claims, "plate_number"),
        ):
            for ev in evidences:
                value = cls._dict_value(ev)
                number = cls._norm_number(value.get(number_key))
                if not number:
                    continue
                grouped[ref_type].setdefault(number, []).append(ev)
        return {
            ref_type: {
                number: _CanonicalGroup(ref_type, number, tuple(evidences))
                for number, evidences in by_number.items()
            }
            for ref_type, by_number in grouped.items()
        }

    @staticmethod
    def _body_regions(bundle: ObjectEvidenceBundle) -> list[EvidenceData]:
        seen: set[tuple[str | None, str | None, str | None]] = set()
        regions: list[EvidenceData] = []
        for ev in bundle.text_claims:
            text = str(ev.value or "").strip()
            if not text:
                continue
            key = (ev.document_version_id, ev.page_id, ev.region_id)
            if key in seen:
                continue
            seen.add(key)
            regions.append(ev)
        return regions

    @staticmethod
    def _stable_digest(parts: list[Any]) -> str:
        raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _finding_evidence(
        self,
        *,
        rule_name: str,
        body_evidence: EvidenceData | None,
        fallback_evidence: EvidenceData,
        archaeology_object: ArchaeologyObjectData,
        analysis_run_id: str,
        reference_keys: list[tuple[str, str]],
        rationale: str,
    ) -> EvidenceData:
        anchor = body_evidence or fallback_evidence
        digest = self._stable_digest(
            [analysis_run_id, archaeology_object.object_id, rule_name, anchor.region_id, reference_keys]
        )
        return EvidenceData(
            id=f"ev_visual_coverage_{digest[:20]}",
            kind="rule_finding",
            source_sha256=anchor.source_sha256,
            document_version_id=anchor.document_version_id,
            page_id=anchor.page_id,
            region_id=anchor.region_id,
            bbox=anchor.bbox,
            method="visual_reference_coverage",
            analysis_run_id=analysis_run_id,
            value={
                "object_id": archaeology_object.object_id,
                "reference_keys": [list(key) for key in reference_keys],
                "finding": rule_name,
            },
            rationale=rationale,
            confidence=1.0,
            version_from=anchor.version_from,
            version_to=anchor.version_to,
            physical_page_from=anchor.physical_page_from,
            physical_page_to=anchor.physical_page_to,
            printed_page_from=anchor.printed_page_from,
            printed_page_to=anchor.printed_page_to,
            rule_name=rule_name,
        )

    def _candidate(
        self,
        *,
        rule_name: str,
        archaeology_object: ArchaeologyObjectData,
        analysis_run_id: str,
        body_evidences: list[EvidenceData],
        canonical_evidences: list[EvidenceData],
        reference_evidences: list[EvidenceData] | None = None,
        reference_keys: list[tuple[str, str]],
        change_type: str,
        original_text: str | None,
        proposed_text: str | None,
        rationale: str,
    ) -> CorrectionCandidateData:
        support = body_evidences + (reference_evidences or []) + canonical_evidences
        if not support:
            raise ValueError("visual coverage candidate requires graph evidence")
        finding = self._finding_evidence(
            rule_name=rule_name,
            body_evidence=body_evidences[0] if body_evidences else None,
            fallback_evidence=support[0],
            archaeology_object=archaeology_object,
            analysis_run_id=analysis_run_id,
            reference_keys=reference_keys,
            rationale=rationale,
        )
        fingerprint = self._stable_digest(
            [
                analysis_run_id,
                archaeology_object.object_id,
                rule_name,
                finding.region_id,
                reference_keys,
                original_text,
                proposed_text,
            ]
        )
        return CorrectionCandidateData(
            candidate_id=f"cand_visual_coverage_{fingerprint[:20]}",
            rule_category="figure_plate_table_photo_ref",
            change_type=change_type,
            status="pending_review",
            original_text=original_text,
            proposed_text=proposed_text,
            evidence=finding,
            evidence_list=support,
            archaeology_object_id=archaeology_object.object_id,
            confidence=1.0,
            analysis_run_id=analysis_run_id,
            severity="high",
            finding_fingerprint=fingerprint,
        )

    @staticmethod
    def _token(ref_type: str, number: str) -> str:
        return f"도면 {number}" if ref_type == "drawing" else f"도판 {number}"

    @classmethod
    def _suffix(cls, groups: list[_CanonicalGroup]) -> str:
        ordered = sorted(groups, key=lambda item: (0 if item.ref_type == "drawing" else 1, item.number))
        return "(" + ", ".join(cls._token(item.ref_type, item.number) for item in ordered) + ")"

    @staticmethod
    def _raw_reference(ev: EvidenceData, ref_type: str, number: str) -> str:
        value = ev.value if isinstance(ev.value, dict) else {}
        raw = str(value.get("raw_text") or "").strip()
        if raw:
            return raw
        return f"도면 {number}" if ref_type == "drawing" else f"도판 {number}"

    def review_object(
        self,
        *,
        bundle: ObjectEvidenceBundle,
        archaeology_object: ArchaeologyObjectData,
        analysis_run_id: str,
    ) -> list[CorrectionCandidateData]:
        canonical = self._canonical_groups(bundle)
        if not canonical["drawing"] and not canonical["plate"]:
            return []

        bodies = self._body_regions(bundle)
        refs_by_type: dict[str, list[tuple[EvidenceData, tuple[str, str]]]] = {
            "drawing": [],
            "plate": [],
        }
        for ev in bundle.references:
            key = self._reference_key(ev)
            if key is not None:
                refs_by_type[key[0]].append((ev, key))

        results: list[CorrectionCandidateData] = []
        handled_types: set[str] = set()

        # Existing references are handled before missing-reference insertion.
        # A uniquely wrong reference is replaced; an already-covered key is
        # left to the normal forward consistency/VLM path.
        for ref_type in ("drawing", "plate"):
            canonical_numbers = set(canonical[ref_type])
            ref_entries = refs_by_type[ref_type]
            ref_numbers = {key[1] for _, key in ref_entries}
            if canonical_numbers & ref_numbers:
                handled_types.add(ref_type)
                continue
            if not ref_entries:
                continue

            if len(ref_entries) == 1 and len(canonical_numbers) == 1:
                ref_ev, old_key = ref_entries[0]
                value = self._dict_value(ref_ev)
                target_id = value.get("resolved_target_id")
                depicts = value.get("resolved_depicts_object") is True
                if not depicts:
                    number = next(iter(canonical_numbers))
                    group = canonical[ref_type][number]
                    body = next((ev for ev in bodies if ev.region_id == ref_ev.region_id), None)
                    results.append(
                        self._candidate(
                            rule_name="visual_reference_wrong_target",
                            archaeology_object=archaeology_object,
                            analysis_run_id=analysis_run_id,
                            body_evidences=[body] if body else [],
                            canonical_evidences=list(group.evidences),
                            reference_evidences=[ref_ev],
                            reference_keys=[group.key],
                            change_type="modified",
                            original_text=self._raw_reference(ref_ev, ref_type, old_key[1]),
                            proposed_text=self._token(ref_type, number),
                            rationale=(
                                "WRONG_VISUAL_REFERENCE: existing reference is unresolved or "
                                "does not depict this ArchaeologyObject; one canonical target is uniquely supported"
                            ),
                        )
                    )
                    handled_types.add(ref_type)
                    continue

            # Existing same-type references prevent automatic append when the
            # replacement is not uniquely provable.
            all_claims = [ev for group in canonical[ref_type].values() for ev in group.evidences]
            anchor_body = next(
                (ev for ev in bodies if any(ref_ev.region_id == ev.region_id for ref_ev, _ in ref_entries)),
                bodies[0] if bodies else None,
            )
            results.append(
                self._candidate(
                    rule_name="visual_reference_ambiguous",
                    archaeology_object=archaeology_object,
                    analysis_run_id=analysis_run_id,
                    body_evidences=[anchor_body] if anchor_body else [],
                    canonical_evidences=all_claims,
                    reference_evidences=[ev for ev, _ in ref_entries],
                    reference_keys=[group.key for group in canonical[ref_type].values()],
                    change_type="modified",
                    original_text=None,
                    proposed_text=None,
                    rationale="AMBIGUOUS_VISUAL_REFERENCE: existing reference cannot be replaced deterministically",
                )
            )
            handled_types.add(ref_type)

        missing_types = [
            ref_type
            for ref_type in ("drawing", "plate")
            if ref_type not in handled_types and canonical[ref_type]
        ]
        if not missing_types:
            return results

        # A blank reference placeholder is an explicit insertion location and
        # takes precedence over general missing-reference placement.
        blank_matches: list[tuple[EvidenceData, re.Match[str]]] = []
        for body in bodies:
            match = _BLANK_BOTH_RE.search(str(body.value or ""))
            if match and (not match.group("drawing").strip() or not match.group("plate").strip()):
                blank_matches.append((body, match))

        if len(blank_matches) > 1:
            claims = [
                ev
                for ref_type in missing_types
                for group in canonical[ref_type].values()
                for ev in group.evidences
            ]
            results.append(
                self._candidate(
                    rule_name="visual_reference_location_ambiguous",
                    archaeology_object=archaeology_object,
                    analysis_run_id=analysis_run_id,
                    body_evidences=[item[0] for item in blank_matches],
                    canonical_evidences=claims,
                    reference_keys=[
                        group.key for ref_type in missing_types for group in canonical[ref_type].values()
                    ],
                    change_type="modified",
                    original_text=None,
                    proposed_text=None,
                    rationale="AMBIGUOUS_REFERENCE_LOCATION: multiple blank reference locations mention this object",
                )
            )
            return results

        if len(blank_matches) == 1:
            body, match = blank_matches[0]
            unique_groups: list[_CanonicalGroup] = []
            ambiguous_types: list[str] = []
            for ref_type in missing_types:
                if len(canonical[ref_type]) == 1:
                    unique_groups.append(next(iter(canonical[ref_type].values())))
                else:
                    ambiguous_types.append(ref_type)

            if unique_groups:
                drawing_value = match.group("drawing").strip()
                plate_value = match.group("plate").strip()
                for group in unique_groups:
                    if group.ref_type == "drawing" and not drawing_value:
                        drawing_value = group.number
                    elif group.ref_type == "plate" and not plate_value:
                        plate_value = group.number
                proposed = f"(도면: {drawing_value}, 도판: {plate_value})"
                results.append(
                    self._candidate(
                        rule_name="visual_reference_blank_fill",
                        archaeology_object=archaeology_object,
                        analysis_run_id=analysis_run_id,
                        body_evidences=[body],
                        canonical_evidences=[ev for group in unique_groups for ev in group.evidences],
                        reference_keys=[group.key for group in unique_groups],
                        change_type="modified",
                        original_text=match.group(0),
                        proposed_text=proposed,
                        rationale="BLANK_VISUAL_REFERENCE: explicit blank placeholder has uniquely grounded canonical target(s)",
                    )
                )

            for ref_type in ambiguous_types:
                groups = list(canonical[ref_type].values())
                results.append(
                    self._candidate(
                        rule_name="visual_reference_ambiguous",
                        archaeology_object=archaeology_object,
                        analysis_run_id=analysis_run_id,
                        body_evidences=[body],
                        canonical_evidences=[ev for group in groups for ev in group.evidences],
                        reference_keys=[group.key for group in groups],
                        change_type="modified",
                        original_text=match.group(0),
                        proposed_text=None,
                        rationale="AMBIGUOUS_VISUAL_REFERENCE: multiple canonical targets fit the blank placeholder",
                    )
                )
            return results

        unique_groups = [
            next(iter(canonical[ref_type].values()))
            for ref_type in missing_types
            if len(canonical[ref_type]) == 1
        ]
        ambiguous_types = [ref_type for ref_type in missing_types if len(canonical[ref_type]) > 1]

        for ref_type in ambiguous_types:
            groups = list(canonical[ref_type].values())
            results.append(
                self._candidate(
                    rule_name="visual_reference_ambiguous",
                    archaeology_object=archaeology_object,
                    analysis_run_id=analysis_run_id,
                    body_evidences=bodies[:1],
                    canonical_evidences=[ev for group in groups for ev in group.evidences],
                    reference_keys=[group.key for group in groups],
                    change_type="added",
                    original_text=None,
                    proposed_text=None,
                    rationale="AMBIGUOUS_VISUAL_REFERENCE: multiple canonical targets depict this ArchaeologyObject",
                )
            )

        if not unique_groups:
            return results

        if len(bodies) != 1:
            results.append(
                self._candidate(
                    rule_name="visual_reference_location_ambiguous",
                    archaeology_object=archaeology_object,
                    analysis_run_id=analysis_run_id,
                    body_evidences=bodies,
                    canonical_evidences=[ev for group in unique_groups for ev in group.evidences],
                    reference_keys=[group.key for group in unique_groups],
                    change_type="added",
                    original_text=None,
                    proposed_text=None,
                    rationale="AMBIGUOUS_REFERENCE_LOCATION: canonical target is unique but body insertion location is not",
                )
            )
            return results

        body = bodies[0]
        results.append(
            self._candidate(
                rule_name="visual_reference_missing",
                archaeology_object=archaeology_object,
                analysis_run_id=analysis_run_id,
                body_evidences=[body],
                canonical_evidences=[ev for group in unique_groups for ev in group.evidences],
                reference_keys=[group.key for group in unique_groups],
                change_type="added",
                original_text=str(body.value or ""),
                proposed_text=self._suffix(unique_groups),
                rationale="MISSING_VISUAL_REFERENCE: graph-authoritative visual target(s) depict this ArchaeologyObject but the body has no matching reference",
            )
        )
        return results
