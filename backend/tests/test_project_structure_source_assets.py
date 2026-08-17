from pathlib import Path

from app.api.project_structure_contract import ProjectStructureNodeType
from app.services.file_store import FileStore
from app.services.project_structure_service import ProjectStructureService


class FakeStructureRepository:
    def project_summary(self, project_id):
        return {
            'id': project_id,
            'name': '산노리',
            'internal_code': None,
            'materials': [],
            'review_round_count': 0,
            'object_count': 0,
            'original_asset_count': 2,
        }

    def list_children(self, project_id, node_type, node_id, offset, limit):
        if node_type == ProjectStructureNodeType.source_asset_group:
            return ([
                {'id': 'source-kind:linked_photo', 'node_type': 'source_kind_group', 'label': '링크 사진', 'child_count': 1, 'asset_kind': 'linked_photo'},
            ], 1)
        if node_type == ProjectStructureNodeType.source_kind_group:
            return ([{
                'id': 'asset-1', 'node_type': 'original_asset',
                'original_name': '4. 조사 후_45.JPG', 'relative_path': 'Links/4. 조사 후_45.JPG',
                'asset_kind': 'linked_photo', 'parse_status': 'stored', 'provenance_status': 'unlinked',
                'uri': 'incoming/p/hash/4. 조사 후_45.JPG', 'sha256': 'hash', 'mime_type': 'image/jpeg',
            }], 1)
        return ([], 0)

    def get_detail(self, project_id, node_type, node_id):
        if node_type == ProjectStructureNodeType.original_asset and node_id == 'asset-1':
            return {
                'id': 'asset-1', 'original_name': '4. 조사 후_45.JPG',
                'relative_path': 'Links/4. 조사 후_45.JPG', 'asset_kind': 'linked_photo',
                'parse_status': 'stored', 'provenance_status': 'unlinked',
                'uri': 'incoming/p/hash/4. 조사 후_45.JPG', 'sha256': 'hash', 'mime_type': 'image/jpeg',
                'relationships': [],
            }
        return None


def test_root_contains_sixth_source_assets_group(tmp_path):
    service = ProjectStructureService(FakeStructureRepository(), FileStore(tmp_path))
    result = service.get_root('project-1')
    assert [group.label for group in result.groups] == [
        '본문', '도판 / 사진', '도면', '원천 자료', '검수 세트', '고고학 객체'
    ]
    assert result.root.child_count == 6


def test_source_asset_tree_keeps_filename_as_provenance_not_canonical_identity(tmp_path):
    service = ProjectStructureService(FakeStructureRepository(), FileStore(tmp_path))
    groups = service.get_children('project-1', ProjectStructureNodeType.source_asset_group, 'source-assets')
    assert groups.items[0].label == '링크 사진'
    assets = service.get_children('project-1', ProjectStructureNodeType.source_kind_group, 'source-kind:linked_photo')
    assert assets.items[0].label == '[원천 사진] 4. 조사 후_45.JPG · canonical 미연결'
    assert assets.items[0].node_type == ProjectStructureNodeType.original_asset
