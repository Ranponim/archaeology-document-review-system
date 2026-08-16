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
    page_id: str | None = None


TextBlock = TextBlockData
Caption = CaptionData


def make_page_id(version_id: str, physical_page: int) -> str:
    return f"{version_id}_p{physical_page}"


def make_block_id(version_id: str, physical_page: int, order: int) -> str:
    return f"{version_id}_p{physical_page}_b{order}"


def make_caption_id(version_id: str, physical_page: int, order: int) -> str:
    return f"{version_id}_p{physical_page}_c{order}"


def make_reference_id(source_node_id: str, ref_type: str, number: str) -> str:
    clean_num = number.strip().replace(" ", "_").replace("·", "_").replace("ㆍ", "_").replace("~", "_")
    return f"ref_{source_node_id}_{ref_type}_{clean_num}"


