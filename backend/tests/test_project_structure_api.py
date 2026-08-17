from fastapi.testclient import TestClient

from app.api.project_structure_contract import (
    ProjectStructureChildrenResponse,
    ProjectStructureNode,
    ProjectStructureRootResponse,
)
from app.main import create_app


class FakeStructureService:
    def __init__(self) -> None:
        self.children_calls = []
        self.node_calls = []

    def get_root(self, project_id: str):
        return ProjectStructureRootResponse(
            project_id=project_id,
            root=ProjectStructureNode(
                id=project_id,
                node_type="project",
                label="산노리",
                source_system="neo4j",
                expandable=True,
                child_count=5,
            ),
            groups=[
                ProjectStructureNode(
                    id="material:report_body",
                    node_type="material_group",
                    label="본문",
                    source_system="derived_group",
                    expandable=True,
                    child_count=1,
                )
            ],
        )

    def get_children(self, project_id, node_type, node_id, offset, limit):
        self.children_calls.append((project_id, str(node_type.value), node_id, offset, limit))
        return ProjectStructureChildrenResponse(
            items=[
                ProjectStructureNode(
                    id="doc-1",
                    node_type="document",
                    label="보고서 본문",
                    source_system="neo4j",
                    expandable=True,
                    child_count=2,
                )
            ],
            offset=offset,
            limit=limit,
            total=1,
        )

    def get_node(self, project_id, node_type, node_id):
        self.node_calls.append((project_id, str(node_type.value), node_id))
        return ProjectStructureNode(
            id=node_id,
            node_type=node_type,
            label="도판 45",
            source_system="neo4j",
            details={"number": "45"},
        )


def client_and_service():
    service = FakeStructureService()
    app = create_app(project_repository=object(), project_structure_service=service)
    return TestClient(app), service


def test_structure_root_is_read_only_get_contract():
    client, _ = client_and_service()
    response = client.get("/api/projects/p1/structure")
    assert response.status_code == 200
    payload = response.json()
    assert payload["projectId"] == "p1"
    assert payload["groups"][0]["label"] == "본문"
    assert client.post("/api/projects/p1/structure").status_code == 405


def test_structure_children_pass_allowlisted_type_and_pagination():
    client, service = client_and_service()
    response = client.get(
        "/api/projects/p1/structure/nodes/material_group/material%3Areport_body/children?offset=0&limit=50"
    )
    assert response.status_code == 200
    assert service.children_calls == [("p1", "material_group", "material:report_body", 0, 50)]
    assert response.json()["hasMore"] is False


def test_structure_invalid_node_type_and_excessive_limit_fail_validation():
    client, _ = client_and_service()
    bad_type = client.get(
        "/api/projects/p1/structure/nodes/MATCH_DELETE/node/children"
    )
    assert bad_type.status_code == 422
    bad_limit = client.get(
        "/api/projects/p1/structure/nodes/material_group/material%3Areport_body/children?limit=101"
    )
    assert bad_limit.status_code == 422


def test_structure_node_detail_is_project_scoped_parameter():
    client, service = client_and_service()
    response = client.get("/api/projects/p1/structure/nodes/reference/ref45")
    assert response.status_code == 200
    assert service.node_calls == [("p1", "reference", "ref45")]
