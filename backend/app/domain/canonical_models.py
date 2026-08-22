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
    """Photo/panel region in normalized page coordinates (0..1, PDF top-left
    origin), derived from panel segmentation of the full page — never the bbox
    of a circled label. None when the region could not be safely isolated."""
    bbox_status: str | None = None
    """'segmented' when bbox is the segmented photo region; 'insufficient' when
    the region could not be safely isolated (bbox None, no render_uri); None
    when no segmentation was attempted."""
    physical_page: int | None = None
    render_uri: str | None = None
    source_sha256: str | None = None
    source_asset_id: str | None = None


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
    reference_corpus_id: str | None = None


@dataclass(frozen=True, slots=True)
class DrawingRegionData:
    region_id: str
    drawing_id: str
    number: str
    title: str = ""
    bbox: tuple[float, float, float, float] | None = None
    """Region bbox in normalized page coordinates (0..1, PDF top-left origin),
    derived from region segmentation of the full page — never the bbox of a
    circled label. None when the region could not be safely isolated."""
    bbox_status: str | None = None
    """'segmented' when bbox is the segmented region; 'insufficient' when the
    region could not be safely isolated (bbox None, no render_uri); None
    when no segmentation was attempted."""
    physical_page: int | None = None
    render_uri: str | None = None
    source_sha256: str | None = None
    source_asset_id: str | None = None


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
    reference_corpus_id: str | None = None


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
    project_id: str | None = None


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

