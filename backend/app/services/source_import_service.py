from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from uuid import uuid4

from app.domain.source_assets import OriginalAssetData, SourceImportResult
from app.services.file_store import FileStore


_IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}
_SUPPORTED_SUFFIXES = {'.hwp', '.hwpx', '.ai', '.indd', *_IMAGE_SUFFIXES}


class SourceImportService:
    def __init__(self, file_store: FileStore, repository) -> None:
        self.file_store = file_store
        self.repository = repository

    @staticmethod
    def _inside(boundary: Path, path: Path) -> bool:
        return path == boundary or boundary in path.parents

    @staticmethod
    def _normalized_relative(path: Path) -> str:
        return unicodedata.normalize('NFC', path.as_posix())

    @staticmethod
    def _asset_id(project_id: str, relative_path: str, sha256: str) -> str:
        raw = f'{project_id}\0{relative_path}\0{sha256}'.encode('utf-8')
        return 'asset_' + hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _kind(relative: Path) -> str:
        lowered = '/'.join(part.lower() for part in relative.parts)
        suffix = relative.suffix.lower()
        if suffix in {'.hwp', '.hwpx'}:
            return 'body_source'
        if suffix == '.ai' or '환경 도면' in lowered:
            return 'drawing_source'
        if suffix == '.indd':
            return 'layout_source'
        if suffix in _IMAGE_SUFFIXES and ('links' in lowered or '도판' in lowered):
            return 'linked_photo'
        return 'other_source'

    @staticmethod
    def _inspect_ai(content: bytes) -> tuple[str, dict[str, object]]:
        if not content.startswith(b'%PDF'):
            return 'stored', {}
        try:
            import fitz
            document = fitz.open(stream=content, filetype='pdf')
            page_text = '\n'.join(page.get_text() for page in document)
            identifiers = sorted(set(re.findall(r'도면\s*[:：]?\s*(\d+)', page_text)))
            metadata: dict[str, object] = {'pageCount': document.page_count}
            if identifiers:
                metadata['internalDrawingIdentifiers'] = identifiers
            document.close()
            return 'parsed', metadata
        except Exception:
            return 'stored', {}

    def import_folder(
        self,
        project_id: str,
        source_root: str | Path,
        *,
        manifest_path: str | Path | None = None,
    ) -> SourceImportResult:
        boundary = Path(source_root).resolve(strict=True)
        if not boundary.is_dir():
            raise ValueError('sourceRoot must resolve to a directory')
        batch_id = str(uuid4())
        errors: list[str] = []
        imported: list[OriginalAssetData] = []
        assets_by_relative: dict[str, OriginalAssetData] = {}

        for path in sorted(boundary.rglob('*'), key=lambda item: item.as_posix()):
            if path.is_dir():
                continue
            try:
                resolved = path.resolve(strict=True)
                if not self._inside(boundary, resolved):
                    raise ValueError('Symlink boundary escape rejected')
                relative = resolved.relative_to(boundary)
                normalized = self._normalized_relative(relative)
                suffix = resolved.suffix.lower()
                if suffix not in _SUPPORTED_SUFFIXES:
                    # A supplied manifest is processed separately, not as a generic source file.
                    if manifest_path and resolved == Path(manifest_path).resolve(strict=True):
                        continue
                    raise ValueError(f'Unsupported source type: {normalized}')
                content = resolved.read_bytes()
                stored = self.file_store.store_bytes(project_id, resolved.name, content)
                parse_status = 'unsupported' if suffix == '.indd' else 'stored'
                metadata: dict[str, object] = {}
                if suffix == '.ai':
                    parse_status, metadata = self._inspect_ai(content)
                asset = OriginalAssetData(
                    id=self._asset_id(project_id, normalized, stored.sha256),
                    project_id=project_id,
                    uri=stored.uri,
                    sha256=stored.sha256,
                    size_bytes=stored.size_bytes,
                    mime_type=stored.mime_type,
                    original_name=stored.original_name,
                    relative_path=normalized,
                    asset_kind=self._kind(relative),
                    source_root_name=Path(source_root).name,
                    import_batch_id=batch_id,
                    parse_status=parse_status,
                    provenance_status='unlinked',
                    source_metadata=metadata,
                )
                self.repository.save_original_asset(asset)
                imported.append(asset)
                assets_by_relative[normalized] = asset
            except Exception as error:
                errors.append(f'{path.name}: {error}')

        if manifest_path is not None:
            self._apply_manifest(
                project_id,
                boundary,
                Path(manifest_path),
                assets_by_relative,
                imported,
                errors,
            )

        return SourceImportResult(batch_id, tuple(imported), tuple(errors))

    def _apply_manifest(
        self,
        project_id: str,
        boundary: Path,
        manifest_path: Path,
        assets: dict[str, OriginalAssetData],
        imported: list[OriginalAssetData],
        errors: list[str],
    ) -> None:
        try:
            resolved_manifest = manifest_path.resolve(strict=True)
            if not self._inside(boundary, resolved_manifest):
                raise ValueError('Manifest must be inside sourceRoot boundary')
            raw = resolved_manifest.read_bytes()
            manifest_sha = hashlib.sha256(raw).hexdigest()
            payload = json.loads(raw.decode('utf-8'))
            if payload.get('version') != 1 or not isinstance(payload.get('mappings'), list):
                raise ValueError('Unsupported provenance manifest')
        except Exception as error:
            errors.append(f'manifest: {error}')
            return

        mapped_assets: set[str] = set()
        for index, mapping in enumerate(payload['mappings']):
            try:
                asset_ref = str(mapping.get('asset') or '')
                ref_path = Path(asset_ref)
                if not asset_ref or ref_path.is_absolute() or '..' in ref_path.parts:
                    raise ValueError('Manifest asset path must be a relative in-boundary path')
                candidate = (boundary / ref_path).resolve(strict=True)
                if not self._inside(boundary, candidate):
                    raise ValueError('Manifest asset path escapes sourceRoot boundary')
                relative = self._normalized_relative(candidate.relative_to(boundary))
                asset = assets.get(relative)
                if asset is None:
                    raise ValueError('Manifest asset is not an imported OriginalAsset')
                if asset.id in mapped_assets:
                    raise ValueError('Conflicting mapping for one OriginalAsset')
                target = mapping.get('target') or {}
                version_id = target.get('documentVersionId')
                node_type = target.get('nodeType')
                if not version_id:
                    raise ValueError('documentVersionId is required for provenance mapping')
                if not node_type:
                    raise ValueError('nodeType is required for provenance mapping')
                method = mapping.get('method')
                if method != 'manifest_mapping':
                    raise ValueError('Only manifest_mapping is accepted for automated provenance')
                resolved = self.repository.resolve_scoped_target(
                    project_id,
                    str(version_id),
                    str(node_type),
                    node_id=target.get('nodeId'),
                    publication_identifier=target.get('publicationIdentifier'),
                )
                if resolved is None:
                    raise ValueError('Missing or ambiguous scoped canonical target')
                self.repository.link_derived_from(
                    project_id,
                    resolved['label'],
                    resolved['id'],
                    asset.id,
                    method='manifest_mapping',
                    manifest_sha256=manifest_sha,
                )
                updated = asset.with_provenance_status('declared')
                self.repository.save_original_asset(updated)
                imported[imported.index(asset)] = updated
                assets[relative] = updated
                mapped_assets.add(asset.id)
            except Exception as error:
                errors.append(f'manifest mapping {index}: {error}')
