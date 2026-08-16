from dataclasses import dataclass, field
from typing import Literal

from app.domain.canonical_models import ReferenceData


@dataclass(frozen=True, slots=True)
class TextBlockData:
    block_id: str
    text: str
    normalized_text: str
    order: int
    block_type: Literal["paragraph", "heading", "caption", "table_row", "footnote"] = "paragraph"
    bbox: tuple[float, float, float, float] | None = None
    source_sha256: str | None = None
    references: list[ReferenceData] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CaptionData:
    caption_id: str
    raw_text: str
    drawing_number: str | None = None
    plate_number: str | None = None
    is_blank_reference: bool = False
    bbox: tuple[float, float, float, float] | None = None
    source_sha256: str | None = None
    references: list[ReferenceData] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ParsedPage:
    physical_page: int
    printed_page: int | None
    header: str
    raw_text: str
    normalized_text: str
    text_blocks: list[TextBlockData] = field(default_factory=list)
    captions: list[CaptionData] = field(default_factory=list)
    source_sha256: str | None = None


TextBlock = TextBlockData
Caption = CaptionData

