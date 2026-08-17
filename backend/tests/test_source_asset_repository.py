import pytest
from app.domain.source_assets import OriginalAssetData
from app.graph.source_asset_repository import SourceAssetRepository

class FakeDriver:
    def __init__(self, rows=None): self.rows=rows or []; self.queries=[]
    def execute_query(self, query, **kwargs): self.queries.append((query,kwargs)); return self.rows,None,None

def make_asset():
    return OriginalAssetData(id='asset-1',project_id='project-1',uri='incoming/x/a.jpg',sha256='abc',size_bytes=3,mime_type='image/jpeg',original_name='4. 조사 후_45.JPG',relative_path='Links/4. 조사 후_45.JPG',asset_kind='linked_photo',source_root_name='src',import_batch_id='batch-1',parse_status='stored',provenance_status='unlinked')

def test_save_original_asset_is_project_owned():
    d=FakeDriver(); SourceAssetRepository(d).save_original_asset(make_asset())
    q,k=d.queries[0]
    assert 'MATCH (p:Project {id: $project_id})' in q
    assert 'HAS_ORIGINAL_ASSET' in q
    assert 'p.updatedAt = datetime()' in q
    assert k['asset']['projectId']=='project-1'

def test_scoped_target_starts_from_project_and_version():
    d=FakeDriver([{'id':'panel-45-1','label':'PlatePanel'}]); r=SourceAssetRepository(d)
    assert r.resolve_scoped_target('project-1','plate-v1','PlatePanel',node_id='panel-45-1')=={'id':'panel-45-1','label':'PlatePanel'}
    q,_=d.queries[0]
    assert 'HAS_DOCUMENT' in q and 'HAS_VERSION' in q and 'HAS_PLATE' in q and 'HAS_PANEL' in q

def test_derived_from_rejects_filename_match_and_is_project_scoped():
    d=FakeDriver(); r=SourceAssetRepository(d)
    with pytest.raises(ValueError,match='manifest_mapping'):
        r.link_derived_from('project-1','PlatePanel','panel-45-1','asset-1',method='filename_match',manifest_sha256='m')
    assert d.queries==[]
    r.link_derived_from('project-1','PlatePanel','panel-45-1','asset-1',method='manifest_mapping',manifest_sha256='m')
    q,k=d.queries[0]
    assert 'HAS_ORIGINAL_ASSET' in q and 'HAS_DOCUMENT' in q and 'HAS_VERSION' in q
    assert 'MERGE (target)-[rel:DERIVED_FROM]->(asset)' in q
    assert k['method']=='manifest_mapping'
