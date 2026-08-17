from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class OriginalAssetData:
    id: str
    project_id: str
    uri: str
    sha256: str
    size_bytes: int
    mime_type: str
    original_name: str
    relative_path: str
    asset_kind: str
    source_root_name: str
    import_batch_id: str
    parse_status: str
    provenance_status: str
    created_at: str | None = None
    source_metadata: dict[str, object] | None = None

    def with_provenance_status(self, status: str) -> "OriginalAssetData":
        return replace(self, provenance_status=status)


@dataclass(frozen=True, slots=True)
class SourceImportResult:
    import_batch_id: str
    imported: tuple[OriginalAssetData, ...]
    errors: tuple[str, ...]
