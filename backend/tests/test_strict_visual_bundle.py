from app.graph.strict_asset_repository import StrictAssetRepository
from app.services.strict_visual_asset_service import StrictVisualAssetService


class FakeRecord(dict):
    pass


class FakeDriver:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []

    def execute_query(self, query, **kwargs):
        self.queries.append((query, kwargs))
        return [FakeRecord(r) for r in self.rows], None, None


class StubRepo:
    def __init__(self, bundle):
        self.bundle = bundle

    def get_candidate_visual_bundle(self, candidate_id, project_id):
        return self.bundle


def test_repository_scopes_candidate_to_project_and_returns_owning_version():
    driver = FakeDriver([])
    repo = StrictAssetRepository(driver)
    assert repo.get_candidate_visual_bundle("cand_1", "p1") is None
    query, kwargs = driver.queries[0]
    assert "(proj:Project {id: $project_id})-[:HAS_CANDIDATE]->" in query
    assert "RESOLVES_TO" in query
    assert "document_version" in query
    assert kwargs == {"candidate_id": "cand_1", "project_id": "p1"}


def test_service_selects_exact_plate_reference_instead_of_first_asset(tmp_path):
    bundle = {
        "candidate": {"id": "cand_1", "original_text": "본문 도판 45 확인"},
        "evidence_chain": [],
        "canonical_assets": [
            {
                "ref": {"ref_type": "plate", "number": 46},
                "label": "Plate",
                "props": {"id": "plate_46", "raw_identifier": "【도판 46】"},
                "parent": None,
                "children": [],
                "document_version": {"id": "pv1", "uri": "plate.pdf", "sha256": "sha"},
            },
            {
                "ref": {"ref_type": "plate", "number": 45},
                "label": "Plate",
                "props": {"id": "plate_45", "raw_identifier": "【도판 45】"},
                "parent": None,
                "children": [],
                "document_version": {"id": "pv1", "uri": "plate.pdf", "sha256": "sha"},
            },
        ],
    }
    service = StrictVisualAssetService(asset_repo=StubRepo(bundle), data_root=tmp_path)
    result = service.get_candidate_visual_bundle("cand_1", "p1")
    assert result["canonical"]["region_id"] == "plate_45"
    assert result["canonical"]["document_version_id"] == "pv1"


def test_service_fails_closed_when_multiple_reference_targets_are_ambiguous(tmp_path):
    bundle = {
        "candidate": {"id": "cand_1", "original_text": "사진 대조 필요"},
        "evidence_chain": [],
        "canonical_assets": [
            {"ref": {"ref_type": "plate", "number": 45}, "label": "Plate", "props": {"id": "p45"}, "parent": None, "children": [], "document_version": {}},
            {"ref": {"ref_type": "drawing", "number": 30}, "label": "Drawing", "props": {"id": "d30"}, "parent": None, "children": [], "document_version": {}},
        ],
    }
    service = StrictVisualAssetService(asset_repo=StubRepo(bundle), data_root=tmp_path)
    result = service.get_candidate_visual_bundle("cand_1", "p1")
    assert result["canonical"] is None
    assert result["unresolved_reason"] == "ambiguous_canonical_target"
