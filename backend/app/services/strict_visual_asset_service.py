from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.services.visual_asset_service import (
    _CROP_ASSET_TYPES,
    _LABEL_TO_ASSET_TYPE,
    VisualAssetIncompleteError,
    VisualAssetService,
)


_PLATE_PATTERN = re.compile(r"(?:도판|plate)\s*[:#-]?\s*(\d+)", re.IGNORECASE)
_DRAWING_PATTERN = re.compile(r"(?:도면|drawing)\s*[:#-]?\s*(\d+)", re.IGNORECASE)


class StrictVisualAssetService(VisualAssetService):
    """Project-scoped comparison bundle service with canonical identity checks.

    The service distinguishes four user-visible comparison meanings:
    version_change, plate_reference, drawing_reference and text_evidence.
    A candidate only enters a visual reference mode when its own evidence/text
    names an exact reference already resolved by the graph.
    """

    @staticmethod
    def _candidate_text(data: dict[str, Any]) -> str:
        candidate = data.get("candidate") or {}
        parts: list[str] = []
        for key in ("original_text", "proposed_text", "originalText", "proposedText"):
            if candidate.get(key):
                parts.append(str(candidate[key]))
        for entry in data.get("evidence_chain") or []:
            evidence = entry.get("evidence") or {}
            value = evidence.get("value")
            if isinstance(value, str):
                parts.append(value)
            elif value not in (None, ""):
                try:
                    parts.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
                except TypeError:
                    parts.append(str(value))
        return " ".join(parts)

    @classmethod
    def _requested_targets(cls, data: dict[str, Any]) -> set[tuple[str, str]]:
        text = cls._candidate_text(data)
        requested: set[tuple[str, str]] = set()
        requested.update(("plate", number) for number in _PLATE_PATTERN.findall(text))
        requested.update(("drawing", number) for number in _DRAWING_PATTERN.findall(text))
        return requested

    @staticmethod
    def _entry_reference_key(entry: dict[str, Any]) -> tuple[str, str] | None:
        ref = entry.get("ref") or {}
        ref_type = str(ref.get("ref_type") or ref.get("type") or "").lower()
        number = ref.get("number")
        if ref_type not in {"plate", "drawing"} or number is None:
            return None
        return ref_type, str(number)

    @classmethod
    def _select_canonical_entry(
        cls,
        data: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        entries = [
            entry
            for entry in (data.get("canonical_assets") or [])
            if cls._entry_reference_key(entry) is not None
        ]
        requested = cls._requested_targets(data)

        # A canonical asset depicting the same object is not enough. The
        # candidate itself must name a Reference before a visual target can be
        # selected. This prevents numeric/text findings from showing arbitrary
        # plate placeholders.
        if not requested:
            if len(entries) > 1:
                return None, "ambiguous_canonical_target"
            return None, "no_candidate_reference"
        if not entries:
            return None, "requested_reference_not_resolved"

        matches = [
            entry
            for entry in entries
            if cls._entry_reference_key(entry) in requested
        ]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, "ambiguous_canonical_target"
        return None, "requested_reference_not_resolved"

    @staticmethod
    def _find_evidence_for_version(
        data: dict[str, Any], version_id: str | None
    ) -> dict[str, Any] | None:
        if not version_id:
            return None
        for entry in data.get("evidence_chain") or []:
            evidence = entry.get("evidence") or {}
            version = entry.get("version") or {}
            if (
                evidence.get("document_version_id") == version_id
                or version.get("id") == version_id
            ):
                return entry
        return None

    def _metadata_from_evidence_entry(
        self,
        entry: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, bool]:
        if not entry:
            return None, False
        evidence = entry.get("evidence") or {}
        page = entry.get("page") or {}
        version = entry.get("version") or {}
        page_id = evidence.get("page_id") or page.get("id")
        physical_page = (
            page.get("physical_page")
            if page.get("physical_page") is not None
            else evidence.get("physical_page_from")
        )
        if not page_id or physical_page is None:
            return None, False
        try:
            render_path = self._resolve_page_render(
                version.get("uri"),
                evidence.get("document_version_id") or version.get("id"),
                int(physical_page),
            )
        except VisualAssetIncompleteError:
            render_path = None
        metadata = self._build_metadata(
            "page",
            page_id,
            document_version_id=evidence.get("document_version_id") or version.get("id"),
            source_sha256=evidence.get("source_sha256") or version.get("sha256"),
            physical_page=physical_page,
            printed_identifier=(
                str(page.get("printed_page"))
                if page.get("printed_page") is not None
                else None
            ),
            region_id=evidence.get("region_id") or page_id,
            bbox=self._normalize_bbox(
                evidence.get("bbox"), version.get("uri"), physical_page
            ),
            render_path=render_path,
            content_type="image/png",
        )
        return metadata, render_path is not None and render_path.is_file()

    def _canonical_metadata(
        self,
        selected: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, bool]:
        asset_type = _LABEL_TO_ASSET_TYPE.get(selected.get("label"))
        props = selected.get("props") or {}
        parent = selected.get("parent") or {}
        version = selected.get("document_version") or {}
        asset_id = props.get("id")
        if not asset_type or not asset_id:
            return None, False

        render_path: Path | None = None
        content_type = "image/png"
        try:
            if asset_type in _CROP_ASSET_TYPES:
                render_path = self._resolve_render_path(props.get("render_uri"))
                if render_path is not None and not render_path.is_file():
                    render_path = None
                content_type = "image/jpeg"
            else:
                render_path = self._resolve_asset_page_render(
                    asset_id,
                    props.get("physical_page") or parent.get("physical_page"),
                    version,
                    selected.get("children") or [],
                    "render_uri",
                )
        except VisualAssetIncompleteError:
            render_path = None

        metadata = self._build_metadata(
            asset_type,
            asset_id,
            document_version_id=(
                props.get("document_version_id")
                or parent.get("document_version_id")
                or version.get("id")
            ),
            source_sha256=(
                props.get("source_sha256")
                or parent.get("source_sha256")
                or version.get("sha256")
            ),
            physical_page=props.get("physical_page") or parent.get("physical_page"),
            printed_identifier=(
                props.get("raw_identifier") or parent.get("raw_identifier")
            ),
            region_id=asset_id,
            bbox=props.get("bbox"),
            caption=props.get("caption") or props.get("title") or parent.get("title"),
            render_path=render_path,
            content_type=content_type,
        )
        return metadata, render_path is not None and render_path.is_file()

    @staticmethod
    def _reference_metadata(selected: dict[str, Any]) -> dict[str, Any] | None:
        ref = selected.get("ref") or {}
        props = selected.get("props") or {}
        ref_type = ref.get("ref_type") or ref.get("type")
        number = ref.get("number")
        if not ref_type or number is None:
            return None
        return {
            "type": str(ref_type),
            "number": str(number),
            "reference_id": ref.get("id"),
            "target_id": props.get("id"),
        }

    def get_candidate_visual_bundle(
        self,
        candidate_id: str,
        project_id: str,
    ) -> dict | None:
        data = self._asset_repo.get_candidate_visual_bundle(candidate_id, project_id)
        if not data or not data.get("candidate"):
            return None

        bundle: dict[str, Any] = {
            "candidate_id": candidate_id,
            "comparison_type": "text_evidence",
            "source": None,
            "comparison": None,
            "canonical": None,
            "reference": None,
            "render_status": "not_applicable",
            "unresolved_reason": None,
        }

        round_context = data.get("round_context") or {}
        previous_version_id = round_context.get("previous_body_version_id")
        current_version_id = round_context.get("current_body_version_id")
        previous_entry = self._find_evidence_for_version(data, previous_version_id)
        current_entry = self._find_evidence_for_version(data, current_version_id)

        selected, selection_reason = self._select_canonical_entry(data)
        if selected is not None:
            label = selected.get("label")
            if label in {"Drawing", "DrawingRegion"}:
                bundle["comparison_type"] = "drawing_reference"
            elif label in {"Plate", "PlatePanel"}:
                bundle["comparison_type"] = "plate_reference"
            else:
                # Defensive fail-closed: an unexpected target label is never
                # surfaced as a canonical visual comparison.
                bundle["unresolved_reason"] = "canonical_target_missing_metadata"
                return bundle

            source_entry = current_entry or next(
                iter(data.get("evidence_chain") or []), None
            )
            source_metadata, source_ready = self._metadata_from_evidence_entry(source_entry)
            canonical_metadata, canonical_ready = self._canonical_metadata(selected)
            bundle["source"] = source_metadata
            bundle["canonical"] = canonical_metadata
            bundle["reference"] = self._reference_metadata(selected)

            if canonical_metadata is None:
                bundle["render_status"] = "missing_render"
                bundle["unresolved_reason"] = "canonical_target_missing_metadata"
            elif source_ready and canonical_ready:
                bundle["render_status"] = "ready"
            else:
                bundle["render_status"] = "missing_render"
                bundle["unresolved_reason"] = "render_unavailable"
            return bundle

        # A revision comparison is valid only when the candidate evidence
        # actually contains both Graph-authoritative previous/current body ids.
        if (
            previous_version_id
            and current_version_id
            and previous_version_id != current_version_id
            and previous_entry is not None
            and current_entry is not None
        ):
            previous_metadata, previous_ready = self._metadata_from_evidence_entry(previous_entry)
            current_metadata, current_ready = self._metadata_from_evidence_entry(current_entry)
            bundle["comparison_type"] = "version_change"
            bundle["source"] = previous_metadata
            bundle["comparison"] = current_metadata
            bundle["render_status"] = (
                "ready" if previous_ready and current_ready else "missing_render"
            )
            if not (previous_ready and current_ready):
                bundle["unresolved_reason"] = "render_unavailable"
            return bundle

        # Plain text/rule evidence is not a failed visual comparison. Show the
        # current body source when available, but explicitly mark the second
        # visual side as not applicable. Preserve graph ambiguity as an audit
        # warning even though no visual mode is selected.
        source_entry = current_entry or next(iter(data.get("evidence_chain") or []), None)
        source_metadata, _ = self._metadata_from_evidence_entry(source_entry)
        bundle["source"] = source_metadata
        bundle["comparison_type"] = "text_evidence"
        bundle["render_status"] = "not_applicable"
        requested = self._requested_targets(data)
        if selection_reason == "ambiguous_canonical_target":
            bundle["unresolved_reason"] = selection_reason
        elif requested and selection_reason not in {None, "no_candidate_reference"}:
            bundle["unresolved_reason"] = selection_reason
        return bundle