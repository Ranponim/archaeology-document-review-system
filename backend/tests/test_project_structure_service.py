from uuid import uuid4

from app.api.project_structure_contract import ProjectStructureNodeType
from app.services.file_store import FileStore
from app.services.project_structure_service import ProjectStructureService


class FakeStructureRepository:
    def __init__(self, stored_uri: str) -> None:
        self.stored_uri = stored_uri

    def project_summary(self, project_id: str):
        return {
            "id": project_id,
            "name": "산노리",
            "internal_code": "N-1",
            "materials": [
                {"kind": "report_body", "document_count": 1, "version_count": 1, "completed_count": 1, "page_count": 132, "plate_count": 0, "panel_count": 0, "drawing_count": 0, "region_count": 0},
                {"kind": "plate_book", "document_count": 1, "version_count": 1, "completed_count": 1, "page_count": 20, "plate_count": 89, "panel_count": 214, "drawing_count": 0, "region_count": 0},
                {"kind": "drawing_book", "document_count": 1, "version_count": 1, "completed_count": 1, "page_count": 10, "plate_count": 0, "panel_count": 0, "drawing_count": 59, "region_count": 127},
            ],
            "review_round_count": 2,
            "object_count": 4,
        }

    def list_children(self, project_id, node_type, node_id, offset, limit):
        assert project_id == "p1"
        if node_type == ProjectStructureNodeType.document:
            return ([{
                "id": "v1",
                "label": "3차교정본.pdf",
                "kind": "report_body",
                "uri": self.stored_uri,
                "sha256": "abc",
                "size_bytes": 3,
                "mime_type": "application/pdf",
                "stage": "source",
                "ingest_status": "completed",
                "page_count": 132,
                "plate_count": 0,
                "drawing_count": 0,
            }], 1)
        return ([], 0)

    def get_detail(self, project_id, node_type, node_id):
        assert project_id == "p1"
        if node_type == ProjectStructureNodeType.reference and node_id == "ref45":
            return {
                "id": "ref45",
                "ref_type": "plate",
                "number": "45",
                "raw_text": "도판 45",
                "physical_page": 78,
                "page_id": "page78",
                "target_label": "Plate",
                "target_id": "plate45",
                "target_properties": {"id": "plate45", "number": "45", "raw_identifier": "【도판 45】"},
            }
        return None


def test_root_explains_material_counts_for_archaeologists(tmp_path):
    service = ProjectStructureService(FakeStructureRepository("missing"), FileStore(tmp_path))
    root = service.get_root("p1")
    by_label = {node.label: node for node in root.groups}
    assert by_label["본문"].badges == ["파일 1", "ingest 완료 1/1", "페이지 132"]
    assert "도판 89" in by_label["도판 / 사진"].badges
    assert "패널 214" in by_label["도판 / 사진"].badges
    assert "도면 59" in by_label["도면"].badges
    assert "영역 127" in by_label["도면"].badges


def test_document_version_merges_real_filestore_presence(tmp_path):
    store = FileStore(tmp_path)
    project_uuid = uuid4()
    stored = store.store_bytes(project_uuid, "3차교정본.pdf", b"PDF", "application/pdf")
    repository = FakeStructureRepository(stored.uri)
    service = ProjectStructureService(repository, store)

    response = service.get_children("p1", ProjectStructureNodeType.document, "doc1")
    node = response.items[0]
    assert node.details["storageStatus"] == "present"
    assert "파일 존재" in node.badges
    assert "ingest completed" in node.badges
    assert "Page 132" in node.badges


def test_reference_detail_exposes_graph_resolution_not_filename_guess(tmp_path):
    service = ProjectStructureService(FakeStructureRepository("missing"), FileStore(tmp_path))
    node = service.get_node("p1", ProjectStructureNodeType.reference, "ref45")
    assert node.label == "도판 45"
    assert len(node.relationships) == 1
    relation = node.relationships[0]
    assert relation.type == "RESOLVES_TO"
    assert relation.target.id == "plate45"
    assert relation.target.label == "【도판 45】"
