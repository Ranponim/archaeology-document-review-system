from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


Bounds = tuple[float, float, float, float]


def _bounds(value: Any) -> Bounds | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("Adobe manifest bounds must contain four numbers")
    try:
        return tuple(float(item) for item in value)  # type: ignore[return-value]
    except (TypeError, ValueError) as error:
        raise ValueError("Adobe manifest bounds must contain four numbers") from error


@dataclass(frozen=True, slots=True)
class ManifestTextFrame:
    object_id: str
    text: str
    bounds: Bounds | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ManifestTextFrame":
        return cls(
            object_id=str(payload.get("objectId") or ""),
            text=str(payload.get("text") or ""),
            bounds=_bounds(payload.get("bounds")),
        )


@dataclass(frozen=True, slots=True)
class ManifestGraphic:
    object_id: str
    bounds: Bounds | None = None
    link_id: str | None = None
    link_path: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ManifestGraphic":
        link_id = payload.get("linkId")
        link_path = payload.get("linkPath")
        return cls(
            object_id=str(payload.get("objectId") or ""),
            bounds=_bounds(payload.get("bounds")),
            link_id=str(link_id) if link_id is not None else None,
            link_path=str(link_path) if link_path is not None else None,
        )


@dataclass(frozen=True, slots=True)
class ManifestPage:
    index: int
    label: str
    text_frames: tuple[ManifestTextFrame, ...] = field(default_factory=tuple)
    graphics: tuple[ManifestGraphic, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ManifestPage":
        return cls(
            index=int(payload.get("index", 0)),
            label=str(payload.get("label") or ""),
            text_frames=tuple(
                ManifestTextFrame.from_dict(item)
                for item in payload.get("textFrames", [])
                if isinstance(item, dict)
            ),
            graphics=tuple(
                ManifestGraphic.from_dict(item)
                for item in payload.get("graphics", [])
                if isinstance(item, dict)
            ),
        )


@dataclass(frozen=True, slots=True)
class ManifestArtboard:
    index: int
    name: str
    text_frames: tuple[ManifestTextFrame, ...] = field(default_factory=tuple)
    placed_items: tuple[ManifestGraphic, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ManifestArtboard":
        return cls(
            index=int(payload.get("index", 0)),
            name=str(payload.get("name") or ""),
            text_frames=tuple(
                ManifestTextFrame.from_dict(item)
                for item in payload.get("textFrames", [])
                if isinstance(item, dict)
            ),
            placed_items=tuple(
                ManifestGraphic.from_dict(item)
                for item in payload.get("placedItems", [])
                if isinstance(item, dict)
            ),
        )


@dataclass(frozen=True, slots=True)
class ManifestArtifact:
    artifact_type: str
    path: str
    sha256: str | None = None
    mime_type: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ManifestArtifact":
        return cls(
            artifact_type=str(payload.get("type") or payload.get("artifactType") or ""),
            path=str(payload.get("path") or ""),
            sha256=(str(payload["sha256"]) if payload.get("sha256") is not None else None),
            mime_type=(str(payload["mimeType"]) if payload.get("mimeType") is not None else None),
        )


@dataclass(frozen=True, slots=True)
class AdobeManifestV1:
    schema_version: int
    application: str
    source_asset_id: str
    source_sha256: str
    pages: tuple[ManifestPage, ...] = field(default_factory=tuple)
    artboards: tuple[ManifestArtboard, ...] = field(default_factory=tuple)
    artifacts: tuple[ManifestArtifact, ...] = field(default_factory=tuple)
    application_version: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AdobeManifestV1":
        if payload.get("schemaVersion") != 1:
            raise ValueError("Unsupported Adobe manifest schema version")
        application = str(payload.get("application") or "").strip().lower()
        if application not in {"indesign", "illustrator"}:
            raise ValueError("Unsupported Adobe manifest application")
        source_asset_id = str(payload.get("sourceAssetId") or "")
        source_sha256 = str(payload.get("sourceSha256") or "")
        if not source_asset_id or not source_sha256:
            raise ValueError("Adobe manifest source identity is required")
        return cls(
            schema_version=1,
            application=application,
            source_asset_id=source_asset_id,
            source_sha256=source_sha256,
            pages=tuple(
                ManifestPage.from_dict(item)
                for item in payload.get("pages", [])
                if isinstance(item, dict)
            ),
            artboards=tuple(
                ManifestArtboard.from_dict(item)
                for item in payload.get("artboards", [])
                if isinstance(item, dict)
            ),
            artifacts=tuple(
                ManifestArtifact.from_dict(item)
                for item in payload.get("artifacts", [])
                if isinstance(item, dict)
            ),
            application_version=(
                str(payload["applicationVersion"])
                if payload.get("applicationVersion") is not None
                else None
            ),
        )
