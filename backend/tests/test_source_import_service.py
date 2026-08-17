import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.file_store import FileStore
from app.services.source_import_service import SourceImportService


class FakeSourceRepository:
    def __init__(self):
        self.assets = []
        self.links = []
        self.targets = {}

    def save_original_asset(self, asset):
        self.assets.append(asset)
        return asset

    def resolve_scoped_target(self, project_id, document_version_id, node_type, node_id=None, publication_identifier=None):
        return self.targets.get((project_id, document_version_id, node_type, node_id, publication_identifier))

    def link_derived_from(self, project_id, target_label, target_id, asset_id, *, method, manifest_sha256):
        self.links.append((project_id, target_label, target_id, asset_id, method, manifest_sha256))


def test_symlink_root_is_allowed_but_filename_digits_never_create_identity(tmp_path):
    project_id = str(uuid4())
    actual = tmp_path / 'actual-src'
    links = actual / '도판(사진들)' / 'Links'
    drawings = actual / '환경 도면'
    links.mkdir(parents=True)
    drawings.mkdir(parents=True)
    (links / '4. 조사 후_45.JPG').write_bytes(b'jpeg-bytes')
    (drawings / '도면30. 1지점.ai').write_bytes(b'%PDF-not-really')
    (actual / 'layout.indd').write_bytes(b'indd-bytes')
    (actual / 'body.hwp').write_bytes(b'hwp-bytes')
    root = tmp_path / 'src'
    root.symlink_to(actual, target_is_directory=True)

    repo = FakeSourceRepository()
    service = SourceImportService(FileStore(tmp_path / 'store'), repo)
    result = service.import_folder(project_id, root)

    by_name = {asset.original_name: asset for asset in result.imported}
    assert by_name['4. 조사 후_45.JPG'].asset_kind == 'linked_photo'
    assert by_name['4. 조사 후_45.JPG'].provenance_status == 'unlinked'
    assert by_name['도면30. 1지점.ai'].asset_kind == 'drawing_source'
    assert by_name['도면30. 1지점.ai'].provenance_status == 'unlinked'
    assert by_name['layout.indd'].asset_kind == 'layout_source'
    assert by_name['layout.indd'].parse_status == 'unsupported'
    assert by_name['body.hwp'].asset_kind == 'body_source'
    assert repo.links == []
    assert (links / '4. 조사 후_45.JPG').read_bytes() == b'jpeg-bytes'


def test_nested_symlink_escape_is_rejected(tmp_path):
    project_id = str(uuid4())
    root = tmp_path / 'src'
    root.mkdir()
    outside = tmp_path / 'outside.jpg'
    outside.write_bytes(b'outside')
    (root / 'escape.jpg').symlink_to(outside)

    service = SourceImportService(FileStore(tmp_path / 'store'), FakeSourceRepository())
    result = service.import_folder(project_id, root)

    assert result.imported == ()
    assert any('boundary' in error.lower() or 'symlink' in error.lower() for error in result.errors)


def test_manifest_requires_scoped_existing_target_before_derived_from(tmp_path):
    project_id = str(uuid4())
    root = tmp_path / 'src'
    links = root / 'Links'
    links.mkdir(parents=True)
    photo = links / '4. 조사 후_45.JPG'
    photo.write_bytes(b'jpeg')
    manifest = root / 'provenance.json'
    manifest.write_text(json.dumps({
        'version': 1,
        'mappings': [{
            'asset': 'Links/4. 조사 후_45.JPG',
            'target': {
                'documentVersionId': 'plate-v1',
                'nodeType': 'PlatePanel',
                'nodeId': 'panel-45-1',
            },
            'method': 'manifest_mapping',
        }],
    }), encoding='utf-8')

    repo = FakeSourceRepository()
    repo.targets[(project_id, 'plate-v1', 'PlatePanel', 'panel-45-1', None)] = {
        'label': 'PlatePanel', 'id': 'panel-45-1'
    }
    service = SourceImportService(FileStore(tmp_path / 'store'), repo)
    result = service.import_folder(project_id, root, manifest_path=manifest)

    photo_asset = next(asset for asset in result.imported if asset.original_name == photo.name)
    assert photo_asset.provenance_status == 'declared'
    assert len(repo.links) == 1
    assert repo.links[0][1:3] == ('PlatePanel', 'panel-45-1')
    assert repo.links[0][4] == 'manifest_mapping'


def test_manifest_without_document_version_scope_creates_no_edge(tmp_path):
    project_id = str(uuid4())
    root = tmp_path / 'src'
    root.mkdir()
    (root / 'x_91.JPG').write_bytes(b'jpeg')
    manifest = root / 'provenance.json'
    manifest.write_text(json.dumps({
        'version': 1,
        'mappings': [{
            'asset': 'x_91.JPG',
            'target': {'nodeType': 'Plate', 'nodeId': 'plate-91'},
            'method': 'manifest_mapping',
        }],
    }), encoding='utf-8')

    repo = FakeSourceRepository()
    service = SourceImportService(FileStore(tmp_path / 'store'), repo)
    result = service.import_folder(project_id, root, manifest_path=manifest)

    assert repo.links == []
    assert any('documentVersionId' in error for error in result.errors)
