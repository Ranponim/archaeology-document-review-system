import re
from pathlib import Path
import pypdf
from app.domain.document_structure import ParsedPage, TextBlockData, CaptionData


class PDFParser:
    HEADER_PATTERN_LEFT = re.compile(r"^(\d+)\s*\|\s*(.*)$")
    HEADER_PATTERN_RIGHT = re.compile(r"^(.*?)\s*\|\s*(\d+)$")
    
    # Matches reference patterns like ① 유구(도면 : 57, 도판 : 85) or ① 유구(도면 : , 도판 : )
    REF_PATTERN = re.compile(
        r"(?:(?:도면\s*:\s*(\d*))|(?:도판\s*:\s*(\d*)))"
    )
    FULL_REF_PATTERN = re.compile(
        r"도면\s*:\s*(\d*)\s*,\s*도판\s*:\s*(\d*)"
    )

    @staticmethod
    def normalize_text(text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def parse_pdf(self, file_path: Path) -> list[ParsedPage]:
        reader = pypdf.PdfReader(str(file_path))
        return [
            self._parse_single_page(reader.pages[idx], physical_page=idx + 1)
            for idx in range(len(reader.pages))
        ]

    def parse_page_range(
        self, file_path: Path, start_page: int, end_page: int
    ) -> list[ParsedPage]:
        """start_page and end_page are 1-indexed physical page numbers."""
        reader = pypdf.PdfReader(str(file_path))
        pages: list[ParsedPage] = []
        for p in range(start_page, end_page + 1):
            if 1 <= p <= len(reader.pages):
                pages.append(self._parse_single_page(reader.pages[p - 1], physical_page=p))
        return pages

    def _extract_caption(self, line: str, caption_id: str) -> CaptionData | None:
        full_ref_m = self.FULL_REF_PATTERN.search(line)
        if full_ref_m:
            drawing_no = full_ref_m.group(1) or None
            plate_no = full_ref_m.group(2) or None
            is_blank = (drawing_no is None and plate_no is None)
            return CaptionData(
                caption_id=caption_id,
                raw_text=line,
                drawing_number=drawing_no,
                plate_number=plate_no,
                is_blank_reference=is_blank,
            )

        ref_m = self.REF_PATTERN.search(line)
        if ref_m:
            drawing_no = ref_m.group(1) or None
            plate_no = ref_m.group(2) or None
            is_blank = (drawing_no is None and plate_no is None)
            return CaptionData(
                caption_id=caption_id,
                raw_text=line,
                drawing_number=drawing_no,
                plate_number=plate_no,
                is_blank_reference=is_blank,
            )

        return None

    def _extract_captions(self, lines: list[str], physical_page: int) -> list[CaptionData]:
        captions: list[CaptionData] = []
        for line in lines:
            caption_id = f"p{physical_page}_c{len(captions) + 1}"
            caption = self._extract_caption(line, caption_id)
            if caption:
                captions.append(caption)
        return captions

    def _parse_single_page(self, page: pypdf.PageObject, physical_page: int) -> ParsedPage:
        raw_text = page.extract_text() or ""
        raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        
        header = ""
        printed_page = None
        content_lines: list[str] = []
        
        if raw_lines:
            first_line = raw_lines[0]
            # Try to match header line
            m_left = self.HEADER_PATTERN_LEFT.match(first_line)
            m_right = self.HEADER_PATTERN_RIGHT.match(first_line)
            
            if m_left:
                printed_page = int(m_left.group(1))
                header = m_left.group(2).strip()
                content_lines = raw_lines[1:]
            elif m_right:
                header = m_right.group(1).strip()
                printed_page = int(m_right.group(2))
                content_lines = raw_lines[1:]
            else:
                content_lines = raw_lines
        
        # Build text blocks and captions
        text_blocks: list[TextBlockData] = []
        captions: list[CaptionData] = []
        
        for idx, line in enumerate(content_lines):
            norm_line = self.normalize_text(line)
            caption_id = f"p{physical_page}_c{len(captions) + 1}"
            caption = self._extract_caption(line, caption_id)
            if caption:
                captions.append(caption)
                text_blocks.append(TextBlockData(
                    block_id=f"p{physical_page}_b{idx+1}",
                    text=line,
                    normalized_text=norm_line,
                    order=idx + 1,
                    block_type="caption"
                ))
            else:
                text_blocks.append(TextBlockData(
                    block_id=f"p{physical_page}_b{idx+1}",
                    text=line,
                    normalized_text=norm_line,
                    order=idx + 1,
                    block_type="paragraph"
                ))
                
        full_content_text = " ".join([b.text for b in text_blocks])
        normalized_text = self.normalize_text(full_content_text)
        
        return ParsedPage(
            physical_page=physical_page,
            printed_page=printed_page,
            header=header,
            raw_text=raw_text,
            normalized_text=normalized_text,
            text_blocks=text_blocks,
            captions=captions
        )
