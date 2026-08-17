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
    """Project-scoped visual bundle service with canonical identity checks."""

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
        if not entries:
            return None, "no_canonical_reference_target"

        requested = cls._requested_targets(data)
        if requested:
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

        if len(entries) == 1:
            return entries[0], None
        return None, "ambiguous_canonical_target"

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
            "source": None,
            "canonical": None,
            "unresolved_reason": None,
        }

        for entry in data.get("evidence_chain") or []:
            evidence = entry.get("evidence") or {}
            page = entry.get("page") or {}
            version = entry.get("version") or {}
            page_id = evidence.get("page_id") or page.get("id")
            physical_page = page.get("physical_page")
            if not page_id or physical_page is None:
                continue
            try:
                render_path = self._resolve_page_render(
                    version.get("uri"), version.get("id"), physical_page
                )
            except VisualAssetIncompleteError:
                render_path = None
            bundle["source"] = self._build_metadata(
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
                region_id=page_id,
                bbox=self._normalize_bbox(
                    evidence.get("bbox"), version.get("uri"), physical_page
                ),
                render_path=render_path,
                content_type="image/png",
            )
            break

        selected, unresolved_reason = self._select_canonical_entry(data)
        if selected is None:
            bundle["unresolved_reason"] = unresolved_reason
            return bundle

        asset_type = _LABEL_TO_ASSET_TYPE.get(selected.get("label"))
        props = selected.get("props") or {}
        parent = selected.get("parent") or {}
        version = selected.get("document_version") or {}
        asset_id = props.get("id")
        if not asset_type or not asset_id:
            bundle["unresolved_reason"] = "canonical_target_missing_metadata"
            return bundle

        render_path: Path | None = None
        content_type = "image/png"
        try:
            if asset_type in _CROP_ASSET_TYPES:
                render_path = self._resolve_render_path(props.get("render_uri"))
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

        bundle["canonical"] = self._build_metadata(
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
        return bundle
