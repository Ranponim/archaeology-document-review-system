from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

ReferenceType = Literal["plate", "drawing"]


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class ReferenceData:
    ref_type: ReferenceType | str
    number: str
    source_block_id: str | None = None
    raw_text: str | None = None
    source_sha256: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    physical_page: int | None = None


@dataclass(frozen=True, slots=True)
class PlatePanelData:
    panel_id: str
    plate_id: str
    panel_index: int
    caption: str = ""
    bbox: tuple[float, float, float, float] | None = None
    physical_page: int | None = None
    render_uri: str | None = None
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class PlateData:
    plate_id: str
    number: str
    physical_page: int
    title: str = ""
    bbox: tuple[float, float, float, float] | None = None
    source_sha256: str | None = None
    document_version_id: str | None = None
    panels: list[PlatePanelData] = field(default_factory=list)
    raw_identifier: str | None = None
    source_kind: str = "plate_pdf"


@dataclass(frozen=True, slots=True)
class DrawingRegionData:
    region_id: str
    drawing_id: str
    number: str
    title: str = ""
    bbox: tuple[float, float, float, float] | None = None
    physical_page: int | None = None
    render_uri: str | None = None
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class DrawingData:
    drawing_id: str
    number: str
    physical_page: int
    title: str = ""
    bbox: tuple[float, float, float, float] | None = None
    source_sha256: str | None = None
    document_version_id: str | None = None
    regions: list[DrawingRegionData] = field(default_factory=list)
    raw_identifier: str | None = None
    source_kind: str = "drawing_pdf"


@dataclass(frozen=True, slots=True)
class ArchaeologyObjectData:
    object_id: str
    site: str
    point: str = ""
    period: str = ""
    type: str = ""
    number: str = ""
    canonical_name: str = ""
    source_block_ids: list[str] = field(default_factory=list)
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ObjectResolutionResult:
    object_data: ArchaeologyObjectData
    confidence: float
    status: str = "candidate"
    source_block_ids: list[str] = field(default_factory=list)
    method: str = "deterministic_rule"


Reference = ReferenceData
PlatePanel = PlatePanelData
Plate = PlateData
DrawingRegion = DrawingRegionData
Drawing = DrawingData
ArchaeologyObject = ArchaeologyObjectData
ResolutionResult = ObjectResolutionResult

from app.domain.models import VersionInput  # noqa: E402


