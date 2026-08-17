import pytest
from pydantic import ValidationError

from app.api.project_structure_contract import (
    ProjectStructureChildrenResponse,
    ProjectStructureNode,
    ProjectStructureNodeType,
)


def test_structure_node_type_is_allow_listed():
    assert ProjectStructureNodeType("document_version") == "document_version"
    assert ProjectStructureNodeType("reference") == "reference"
    with pytest.raises(ValueError):
        ProjectStructureNodeType("MATCH (n) DETACH DELETE n")


def test_structure_node_serializes_archaeologist_facing_and_audit_fields():
    node = ProjectStructureNode(
        id="v1",
        node_type="document_version",
        label="3차교정본.pdf",
        subtitle="본문 · DocumentVersion",
        source_system="neo4j",
        status="completed",
        expandable=True,
        child_count=132,
        badges=["파일 존재", "ingest 완료", "Page 132"],
        details={"neo4jLabel": "DocumentVersion", "sha256": "abc"},
    )
    payload = node.model_dump(by_alias=True)
    assert payload["nodeType"] == "document_version"
    assert payload["sourceSystem"] == "neo4j"
    assert payload["childCount"] == 132
    assert payload["badges"][0] == "파일 존재"


def test_children_contract_caps_page_size():
    response = ProjectStructureChildrenResponse(items=[], offset=0, limit=50, total=0)
    assert response.has_more is False
    with pytest.raises(ValidationError):
        ProjectStructureChildrenResponse(items=[], offset=0, limit=101, total=0)
