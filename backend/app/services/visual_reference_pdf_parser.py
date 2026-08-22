from __future__ import annotations

from dataclasses import replace
import re

from app.domain.canonical_models import ReferenceData
from app.domain.document_structure import CaptionData
from app.services.pdf_parser import PDFParser


_PHOTO_REFERENCE_RE = re.compile(
    r"사진\s*:\s*([^,\)\s]+(?:\s*[·ㆍ•・~\-]\s*[^,\)\s]+)*)?"
)


class VisualReferencePDFParser(PDFParser):
    """Production report parser that normalizes `사진 N` to the plate channel.

    `사진` is a body-reference vocabulary alias. It never creates a separate
    publication identity and never consults filenames; the resolved identity
    is still the canonical Plate/PlatePanel graph built from the plate book.
    """

    def _extract_references(
        self,
        text: str,
        source_block_id: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        source_sha256: str | None = None,
        physical_page: int | None = None,
    ) -> list[ReferenceData]:
        refs = list(
            super()._extract_references(
                text,
                source_block_id=source_block_id,
                bbox=bbox,
                source_sha256=source_sha256,
                physical_page=physical_page,
            )
        )
        seen = {(str(ref.ref_type), str(ref.number)) for ref in refs}
        for match in _PHOTO_REFERENCE_RE.finditer(text):
            raw_value = match.group(1) or ""
            for number in self.expand_reference_numbers(raw_value):
                key = ("plate", str(number))
                if key in seen:
                    continue
                seen.add(key)
                refs.append(
                    ReferenceData(
                        ref_type="plate",
                        number=str(number),
                        source_block_id=source_block_id,
                        raw_text=match.group(0),
                        source_sha256=source_sha256,
                        bbox=bbox,
                        physical_page=physical_page,
                    )
                )
        return refs

    def _extract_caption(
        self,
        line: str,
        caption_id: str,
        bbox: tuple[float, float, float, float] | None = None,
        source_sha256: str | None = None,
        physical_page: int | None = None,
    ) -> CaptionData | None:
        base = super()._extract_caption(
            line,
            caption_id,
            bbox=bbox,
            source_sha256=source_sha256,
            physical_page=physical_page,
        )
        photo_refs: list[ReferenceData] = []
        existing_keys = {
            (str(ref.ref_type), str(ref.number))
            for ref in (base.references if base is not None else [])
        }
        for match in _PHOTO_REFERENCE_RE.finditer(line):
            raw_value = match.group(1) or ""
            for number in self.expand_reference_numbers(raw_value):
                key = ("plate", str(number))
                if key in existing_keys:
                    continue
                existing_keys.add(key)
                photo_refs.append(
                    ReferenceData(
                        ref_type="plate",
                        number=str(number),
                        source_block_id=caption_id,
                        raw_text=match.group(0),
                        source_sha256=source_sha256,
                        bbox=bbox,
                        physical_page=physical_page,
                    )
                )

        if base is None:
            if not photo_refs:
                return None
            return CaptionData(
                caption_id=caption_id,
                raw_text=line,
                drawing_number=None,
                plate_number=photo_refs[0].number,
                is_blank_reference=False,
                bbox=bbox,
                source_sha256=source_sha256,
                references=photo_refs,
            )

        if not photo_refs:
            return base

        return replace(
            base,
            plate_number=base.plate_number or photo_refs[0].number,
            is_blank_reference=False,
            references=list(base.references) + photo_refs,
        )
