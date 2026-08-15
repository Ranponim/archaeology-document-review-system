from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class TextBlockData:
    block_id: str
    text: str
    normalized_text: str
    order: int
    block_type: Literal["paragraph", "heading", "caption", "table_row", "footnote"] = "paragraph"


@dataclass(frozen=True, slots=True)
class CaptionData:
    caption_id: str
    raw_text: str
    drawing_number: str | None = None
    plate_number: str | None = None
    is_blank_reference: bool = False


@dataclass(frozen=True, slots=True)
class ParsedPage:
    physical_page: int
    printed_page: int | None
    header: str
    raw_text: str
    normalized_text: str
    text_blocks: list[TextBlockData] = field(default_factory=list)
    captions: list[CaptionData] = field(default_factory=list)


TextBlock = TextBlockData
Caption = CaptionData
