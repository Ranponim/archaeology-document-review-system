import hashlib
import re
from pathlib import Path

try:
    import pymupdf  # type: ignore
    HAS_PYMUPDF = True
except ImportError:
    try:
        import fitz as pymupdf  # type: ignore
        HAS_PYMUPDF = True
    except ImportError:
        HAS_PYMUPDF = False

import pypdf

from app.domain.canonical_models import EvidenceLevel, ReferenceData
from app.domain.document_structure import (
    CaptionData,
    ParsedPage,
    TextBlockData,
    make_block_id,
    make_caption_id,
    make_page_id,
    make_reference_id,
)


class PDFParser:
    HEADER_PATTERN_LEFT = re.compile(r"^(\d+)\s*\|\s*(.*)$")
    HEADER_PATTERN_RIGHT = re.compile(r"^(.*?)\s*\|\s*(\d+)$")
    REFERENCE_PATTERN = re.compile(
        r"(?:【\s*)?"
        r"(?P<label>원색\s*도판|도판|사진|도면|삽도)"
        r"\s*(?::\s*)?"
        r"(?P<numbers>"
        r"\d+(?:\s*[~\-]\s*\d+)?"
        r"(?:\s*[,，·ㆍ•・/]\s*\d+(?:\s*[~\-]\s*\d+)?)*"
        r")"
        r"\s*(?:】)?"
    )

    @staticmethod
    def normalize_text(text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def expand_reference_numbers(raw: str) -> list[str]:
        if not raw or not raw.strip():
            return []
        tokens = re.split(r"[,·ㆍ•・/，\s]+", raw.strip())
        numbers: list[str] = []
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            m = re.match(r"^(\d+)\s*[~\-]\s*(\d+)$", tok)
            if m:
                start, end = int(m.group(1)), int(m.group(2))
                if start <= end and (end - start) < 500:
                    for n in range(start, end + 1):
                        numbers.append(str(n))
                else:
                    numbers.append(tok)
            elif tok.isdigit():
                numbers.append(tok)
            else:
                numbers.append(tok)
        return numbers

    def _extract_references(
        self,
        text: str,
        source_block_id: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        source_sha256: str | None = None,
        physical_page: int | None = None,
    ) -> list[ReferenceData]:
        refs: list[ReferenceData] = []
        for match in self.REFERENCE_PATTERN.finditer(text):
            label = re.sub(r"\s+", "", match.group("label"))
            ref_type = "drawing" if label in {"도면", "삽도"} else "plate"
            for number in self.expand_reference_numbers(match.group("numbers")):
                refs.append(
                    ReferenceData(
                        ref_type=ref_type,
                        number=number,
                        source_block_id=source_block_id,
                        raw_text=match.group(0).strip(),
                        source_sha256=source_sha256,
                        bbox=bbox,
                        physical_page=physical_page,
                        evidence_level=EvidenceLevel.DIRECT,
                        evidence_method="body_explicit_identifier",
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
        m_full = re.search(r"도면\s*:\s*([^,\)]*)\s*,\s*도판\s*:\s*([^,\)]*)", line)
        if m_full:
            raw_draw = m_full.group(1).strip()
            raw_plate = m_full.group(2).strip()
            draw_nums = self.expand_reference_numbers(raw_draw)
            plate_nums = self.expand_reference_numbers(raw_plate)
            is_blank = len(draw_nums) == 0 and len(plate_nums) == 0

            refs: list[ReferenceData] = []
            for num in draw_nums:
                refs.append(
                    ReferenceData(
                        ref_type="drawing",
                        number=num,
                        source_block_id=caption_id,
                        raw_text=line,
                        source_sha256=source_sha256,
                        bbox=bbox,
                        physical_page=physical_page,
                        evidence_level=EvidenceLevel.DIRECT,
                        evidence_method="body_caption_identifier",
                    )
                )
            for num in plate_nums:
                refs.append(
                    ReferenceData(
                        ref_type="plate",
                        number=num,
                        source_block_id=caption_id,
                        raw_text=line,
                        source_sha256=source_sha256,
                        bbox=bbox,
                        physical_page=physical_page,
                        evidence_level=EvidenceLevel.DIRECT,
                        evidence_method="body_caption_identifier",
                    )
                )

            return CaptionData(
                caption_id=caption_id,
                raw_text=line,
                drawing_number=draw_nums[0] if draw_nums else None,
                plate_number=plate_nums[0] if plate_nums else None,
                is_blank_reference=is_blank,
                bbox=bbox,
                source_sha256=source_sha256,
                references=refs,
            )

        m_draw = re.search(r"도면\s*:\s*([^,\)]*)", line)
        m_plate = re.search(r"도판\s*:\s*([^,\)]*)", line)
        if m_draw or m_plate:
            raw_draw = m_draw.group(1).strip() if m_draw else ""
            raw_plate = m_plate.group(1).strip() if m_plate else ""
            draw_nums = self.expand_reference_numbers(raw_draw)
            plate_nums = self.expand_reference_numbers(raw_plate)
            is_blank = len(draw_nums) == 0 and len(plate_nums) == 0

            refs: list[ReferenceData] = []
            for num in draw_nums:
                refs.append(
                    ReferenceData(
                        ref_type="drawing",
                        number=num,
                        source_block_id=caption_id,
                        raw_text=line,
                        source_sha256=source_sha256,
                        bbox=bbox,
                        physical_page=physical_page,
                        evidence_level=EvidenceLevel.DIRECT,
                        evidence_method="body_caption_identifier",
                    )
                )
            for num in plate_nums:
                refs.append(
                    ReferenceData(
                        ref_type="plate",
                        number=num,
                        source_block_id=caption_id,
                        raw_text=line,
                        source_sha256=source_sha256,
                        bbox=bbox,
                        physical_page=physical_page,
                        evidence_level=EvidenceLevel.DIRECT,
                        evidence_method="body_caption_identifier",
                    )
                )

            return CaptionData(
                caption_id=caption_id,
                raw_text=line,
                drawing_number=draw_nums[0] if draw_nums else None,
                plate_number=plate_nums[0] if plate_nums else None,
                is_blank_reference=is_blank,
                bbox=bbox,
                source_sha256=source_sha256,
                references=refs,
            )

        return None

    def _extract_captions(
        self,
        lines: list[str],
        physical_page: int,
        source_sha256: str | None = None,
        version_id: str = "doc_ver",
    ) -> list[CaptionData]:
        captions: list[CaptionData] = []
        for line in lines:
            caption_id = make_caption_id(version_id, physical_page, len(captions) + 1)
            caption = self._extract_caption(
                line,
                caption_id,
                source_sha256=source_sha256,
                physical_page=physical_page,
            )
            if caption:
                captions.append(caption)
        return captions

    def parse_pdf(
        self,
        file_path: Path,
        mode: str = "report_body",
        version_id: str = "doc_ver",
    ) -> list[ParsedPage]:
        if HAS_PYMUPDF:
            try:
                return self._parse_with_pymupdf(file_path, mode=mode, version_id=version_id)
            except Exception:
                pass
        return self._parse_with_pypdf(file_path, mode=mode, version_id=version_id)

    def parse_page_range(
        self,
        file_path: Path,
        start_page: int,
        end_page: int,
        mode: str = "report_body",
        version_id: str = "doc_ver",
    ) -> list[ParsedPage]:
        """start_page and end_page are 1-indexed physical page numbers."""
        if HAS_PYMUPDF:
            try:
                return self._parse_with_pymupdf(
                    file_path,
                    start_page=start_page,
                    end_page=end_page,
                    mode=mode,
                    version_id=version_id,
                )
            except Exception:
                pass
        return self._parse_with_pypdf(
            file_path,
            start_page=start_page,
            end_page=end_page,
            mode=mode,
            version_id=version_id,
        )

    def _parse_with_pymupdf(
        self,
        file_path: Path,
        start_page: int | None = None,
        end_page: int | None = None,
        mode: str = "report_body",
        version_id: str = "doc_ver",
    ) -> list[ParsedPage]:
        source_sha256 = self.compute_sha256(file_path) if file_path.is_file() else None
        doc = pymupdf.open(str(file_path))
        total_pages = len(doc)
        s_page = 1 if start_page is None else max(1, start_page)
        e_page = total_pages if end_page is None else min(total_pages, end_page)

        pages: list[ParsedPage] = []
        for p in range(s_page, e_page + 1):
            page_obj = doc[p - 1]
            parsed_page = self._parse_single_pymupdf_page(
                page_obj,
                physical_page=p,
                source_sha256=source_sha256,
                version_id=version_id,
            )
            pages.append(parsed_page)
        return pages

    def _parse_single_pymupdf_page(
        self,
        page: "pymupdf.Page",
        physical_page: int,
        source_sha256: str | None = None,
        version_id: str = "doc_ver",
    ) -> ParsedPage:
        raw_text = page.get_text() or ""
        raw_blocks = page.get_text("blocks") or []
        text_blocks_raw = [b for b in raw_blocks if len(b) >= 7 and b[6] == 0 and b[4].strip()]

        header = ""
        printed_page = None
        content_blocks_raw = text_blocks_raw

        if text_blocks_raw:
            first_line = text_blocks_raw[0][4].strip().splitlines()[0]
            m_left = self.HEADER_PATTERN_LEFT.match(first_line)
            m_right = self.HEADER_PATTERN_RIGHT.match(first_line)
            if m_left:
                printed_page = int(m_left.group(1))
                header = m_left.group(2).strip()
                content_blocks_raw = text_blocks_raw[1:]
            elif m_right:
                header = m_right.group(1).strip()
                printed_page = int(m_right.group(2))
                content_blocks_raw = text_blocks_raw[1:]

        text_blocks: list[TextBlockData] = []
        captions: list[CaptionData] = []

        for idx, b in enumerate(content_blocks_raw):
            b_text = b[4].strip()
            bbox = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
            order = idx + 1
            block_id = make_block_id(version_id, physical_page, order)
            norm_line = self.normalize_text(b_text)

            caption_id = make_caption_id(version_id, physical_page, len(captions) + 1)
            caption = self._extract_caption(
                b_text,
                caption_id=caption_id,
                bbox=bbox,
                source_sha256=source_sha256,
                physical_page=physical_page,
            )

            if caption:
                captions.append(caption)
                text_blocks.append(
                    TextBlockData(
                        block_id=block_id,
                        text=b_text,
                        normalized_text=norm_line,
                        order=order,
                        block_type="caption",
                        bbox=bbox,
                        source_sha256=source_sha256,
                        references=caption.references,
                    )
                )
            else:
                refs = self._extract_references(
                    b_text,
                    source_block_id=block_id,
                    bbox=bbox,
                    source_sha256=source_sha256,
                    physical_page=physical_page,
                )
                text_blocks.append(
                    TextBlockData(
                        block_id=block_id,
                        text=b_text,
                        normalized_text=norm_line,
                        order=order,
                        block_type="paragraph",
                        bbox=bbox,
                        source_sha256=source_sha256,
                        references=refs,
                    )
                )

        full_content_text = " ".join([b.text for b in text_blocks])
        normalized_text = self.normalize_text(full_content_text)

        return ParsedPage(
            physical_page=physical_page,
            printed_page=printed_page,
            header=header,
            raw_text=raw_text,
            normalized_text=normalized_text,
            text_blocks=text_blocks,
            captions=captions,
            source_sha256=source_sha256,
            page_id=make_page_id(version_id, physical_page),
        )

    def _parse_with_pypdf(
        self,
        file_path: Path,
        start_page: int | None = None,
        end_page: int | None = None,
        mode: str = "report_body",
        version_id: str = "doc_ver",
    ) -> list[ParsedPage]:
        source_sha256 = self.compute_sha256(file_path) if file_path.is_file() else None
        reader = pypdf.PdfReader(str(file_path))
        total_pages = len(reader.pages)
        s_page = 1 if start_page is None else max(1, start_page)
        e_page = total_pages if end_page is None else min(total_pages, end_page)

        pages: list[ParsedPage] = []
        for p in range(s_page, e_page + 1):
            page_obj = reader.pages[p - 1]
            parsed_page = self._parse_single_pypdf_page(
                page_obj,
                physical_page=p,
                source_sha256=source_sha256,
                version_id=version_id,
            )
            pages.append(parsed_page)
        return pages

    def _parse_single_pypdf_page(
        self,
        page: pypdf.PageObject,
        physical_page: int,
        source_sha256: str | None = None,
        version_id: str = "doc_ver",
    ) -> ParsedPage:
        raw_text = page.extract_text() or ""
        raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        header = ""
        printed_page = None
        content_lines: list[str] = []

        if raw_lines:
            first_line = raw_lines[0]
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

        text_blocks: list[TextBlockData] = []
        captions: list[CaptionData] = []

        for idx, line in enumerate(content_lines):
            norm_line = self.normalize_text(line)
            order = idx + 1
            block_id = make_block_id(version_id, physical_page, order)
            caption_id = make_caption_id(version_id, physical_page, len(captions) + 1)
            caption = self._extract_caption(
                line,
                caption_id=caption_id,
                bbox=None,
                source_sha256=source_sha256,
                physical_page=physical_page,
            )
            if caption:
                captions.append(caption)
                text_blocks.append(
                    TextBlockData(
                        block_id=block_id,
                        text=line,
                        normalized_text=norm_line,
                        order=order,
                        block_type="caption",
                        bbox=None,
                        source_sha256=source_sha256,
                        references=caption.references,
                    )
                )
            else:
                refs = self._extract_references(
                    line,
                    source_block_id=block_id,
                    bbox=None,
                    source_sha256=source_sha256,
                    physical_page=physical_page,
                )
                text_blocks.append(
                    TextBlockData(
                        block_id=block_id,
                        text=line,
                        normalized_text=norm_line,
                        order=order,
                        block_type="paragraph",
                        bbox=None,
                        source_sha256=source_sha256,
                        references=refs,
                    )
                )

        full_content_text = " ".join([b.text for b in text_blocks])
        normalized_text = self.normalize_text(full_content_text)

        return ParsedPage(
            physical_page=physical_page,
            printed_page=printed_page,
            header=header,
            raw_text=raw_text,
            normalized_text=normalized_text,
            text_blocks=text_blocks,
            captions=captions,
            source_sha256=source_sha256,
            page_id=make_page_id(version_id, physical_page),
        )
