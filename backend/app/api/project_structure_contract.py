from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, computed_field

from app.api.schemas import ApiModel


class ProjectStructureNodeType(str, Enum):
    project = "project"
    material_group = "material_group"
    document = "document"
    document_version = "document_version"
    page_group = "page_group"
    page = "page"
    textblock_group = "textblock_group"
    text_block = "text_block"
    caption_group = "caption_group"
    caption = "caption"
    reference_group = "reference_group"
    reference = "reference"
    plate_group = "plate_group"
    plate = "plate"
    panel_group = "panel_group"
    plate_panel = "plate_panel"
    drawing_group = "drawing_group"
    drawing = "drawing"
    region_group = "region_group"
    drawing_region = "drawing_region"
    review_round_group = "review_round_group"
    review_round = "review_round"
    version_reference = "version_reference"
    archaeology_object_group = "archaeology_object_group"
    archaeology_object = "archaeology_object"


class ProjectStructureRelationshipTarget(ApiModel):
    id: str
    node_type: ProjectStructureNodeType = Field(alias="nodeType")
    label: str


class ProjectStructureRelationship(ApiModel):
    type: str
    direction: str
    target: ProjectStructureRelationshipTarget


class ProjectStructureNode(ApiModel):
    id: str
    node_type: ProjectStructureNodeType = Field(alias="nodeType")
    label: str
    subtitle: str | None = None
    source_system: str = Field(alias="sourceSystem")
    status: str | None = None
    expandable: bool = False
    child_count: int = Field(default=0, ge=0, alias="childCount")
    badges: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    relationships: list[ProjectStructureRelationship] = Field(default_factory=list)


class ProjectStructureRootResponse(ApiModel):
    project_id: str = Field(alias="projectId")
    root: ProjectStructureNode
    groups: list[ProjectStructureNode]


class ProjectStructureChildrenResponse(ApiModel):
    items: list[ProjectStructureNode]
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
    total: int = Field(default=0, ge=0)

    @computed_field(alias="hasMore")
    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total
