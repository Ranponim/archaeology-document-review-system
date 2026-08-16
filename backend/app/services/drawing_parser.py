from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Iterator, Sequence

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

from app.domain.canonical_models import DrawingData, DrawingRegionData

CIRCLED_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
CIRCLED_MAP: dict[str, int] = {c: i + 1 for i, c in enumerate(CIRCLED_CHARS)}

PAREN_CHARS = "⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽⑾⑿⒀⒁⒂⒃⒄⒅⒆⒇"
for i, c in enumerate(PAREN_CHARS):
    CIRCLED_MAP[c] = i + 1


@dataclass(frozen=True, slots=True)
class DrawingIndex:
    drawings_by_number: dict[str, DrawingData] = field(default_factory=dict)
    drawings: list[DrawingData] = field(default_factory=list)

    def get_drawing(self, number: str) -> DrawingData | None:
        return self.drawings_by_number.get(str(number).strip())

    def get(self, number: str, default: DrawingData | None = None) -> DrawingData | None:
        """Dict-like get with optional default."""
        result = self.drawings_by_number.get(str(number).strip())
        if result is None:
            return default
        return result

    def get_region(self, drawing_number: str, region_number: str | int) -> DrawingRegionData | None:
        drawing = self.get_drawing(drawing_number)
        if not drawing:
            return None
        # Normalise region_number to a string digit
        rn = str(region_number).strip()
        if rn in CIRCLED_MAP:
            rn = str(CIRCLED_MAP[rn])
        elif isinstance(region_number, int):
            rn = str(region_number)
        for r in drawing.regions:
            if r.number == rn:
                return r
        return None

    def __getitem__(self, key: str | int) -> DrawingData:
        if isinstance(key, int):
            return self.drawings[key]
        return self.drawings_by_number[str(key).strip()]

    def __contains__(self, number: str) -> bool:
        return str(number).strip() in self.drawings_by_number

    def __iter__(self) -> Iterator[DrawingData]:
        return iter(self.drawings)

    def __len__(self) -> int:
        return len(self.drawings)


class DrawingParser:
    """Parser for archaeological drawing books extracting explicit identifiers and regions."""

    IDENTIFIER_PATTERN = re.compile(
        r"(【\s*도면\s*(\d+(?:-\d+)?)\s*】|"
        r"\[\s*도면\s*(\d+(?:-\d+)?)\s*\]|"
        r"〈\s*도면\s*(\d+(?:-\d+)?)\s*〉|"
        r"<\s*도면\s*(\d+(?:-\d+)?)\s*>|"
        r"〔\s*도면\s*(\d+(?:-\d+)?)\s*〕|"
        r"《\s*도면\s*(\d+(?:-\d+)?)\s*》|"
        r"도면\s*(\d+(?:-\d+)?))"
    )

    REGION_SPLIT_PATTERN = re.compile(
        r"(?:[①-⑳⑴-⒇]|\(\d+\)|\b\d+\))"
    )

    RUNNING_HEADER_PATTERN = re.compile(
        r"^(\d+\s*\|\s*.*|.*\s*\|\s*\d+)$"
    )

    @staticmethod
    def compute_sha256(file_path: Path | str) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def parse_region_token(cls, tok: str) -> list[int]:
        tok = tok.strip()
        if not tok:
            return []

        m_range = re.match(r"^([①-⑳⑴-⒇]|\(?\d+\)?)\s*[~\-–—]\s*([①-⑳⑴-⒇]|\(?\d+\)?)$", tok)
        if m_range:
            t1, t2 = m_range.group(1), m_range.group(2)
            idx1 = cls._token_to_int(t1)
            idx2 = cls._token_to_int(t2)
            if idx1 is not None and idx2 is not None and idx1 <= idx2:
                return list(range(idx1, idx2 + 1))

        if any(c in tok for c in "·ㆍ•・,"):
            parts = re.split(r"[·ㆍ•・,]+", tok)
            res: list[int] = []
            for p in parts:
                p = p.strip()
                val = cls._token_to_int(p)
                if val is not None:
                    res.append(val)
            if res:
                return res

        val = cls._token_to_int(tok)
        if val is not None:
            return [val]
        return []

    @classmethod
    def _token_to_int(cls, tok: str) -> int | None:
        tok = tok.strip()
        if tok in CIRCLED_MAP:
            return CIRCLED_MAP[tok]
        m = re.match(r"^\(?(\d+)\)?$", tok)
        if m:
            return int(m.group(1))
        return None

    @classmethod
    def parse_text_header(cls, text: str) -> tuple[str, str, str, str] | None:
        m = cls.IDENTIFIER_PATTERN.search(text)
        if not m:
            return None

        raw_identifier = m.group(1)
        number = next(g for g in m.groups()[1:] if g is not None)
        after = text[m.end():].strip()

        region_m = cls.REGION_SPLIT_PATTERN.search(after)
        if region_m:
            title_raw = after[:region_m.start()]
            region_text = after[region_m.start():].strip()
        else:
            title_raw = after
            region_text = ""

        title_raw = re.sub(r"\s+", " ", title_raw).strip()
        title = re.sub(r"^[\s\-–—/:]+|[\s\-–—/:]+$", "", title_raw).strip()
        return raw_identifier, number, title, region_text

    @classmethod
    def extract_regions_from_caption(cls, region_text: str) -> dict[int, str]:
        if not region_text or not region_text.strip():
            return {}

        pattern = re.compile(
            r"([①-⑳⑴-⒇](?:\s*[·ㆍ•・,~–—]\s*[①-⑳⑴-⒇])*|\(\d+\)|\b\d+\))"
        )
        matches = list(pattern.finditer(region_text))
        if not matches:
            return {}

        results: dict[int, str] = {}
        for i, m in enumerate(matches):
            marker_str = m.group(1)
            start_idx = m.end()
            end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(region_text)
            caption = region_text[start_idx:end_idx].strip()
            caption = re.sub(r"^[\s\-–—/:]+|[\s\-–—/:]+$", "", caption).strip()
            indices = cls.parse_region_token(marker_str)
            for idx in indices:
                results[idx] = caption
        return results

    def parse(
        self,
        pdf_path: str | Path,
        document_version_id: str | None = None,
    ) -> DrawingIndex:
        drawings = self.parse_drawings(pdf_path, document_version_id=document_version_id)
        drawings_by_number = {d.number: d for d in drawings}
        return DrawingIndex(drawings_by_number=drawings_by_number, drawings=drawings)

    def parse_drawings(
        self,
        pdf_path: str | Path,
        document_version_id: str | None = None,
    ) -> list[DrawingData]:
        path = Path(pdf_path)
        sha256 = self.compute_sha256(path)

        if HAS_PYMUPDF:
            return self._parse_with_pymupdf(
                path, sha256=sha256, document_version_id=document_version_id
            )
        return self._parse_with_pypdf(
            path, sha256=sha256, document_version_id=document_version_id
        )

    def parse_page_range(
        self,
        pdf_path: str | Path,
        start_page: int,
        end_page: int,
        document_version_id: str | None = None,
    ) -> list[DrawingData]:
        path = Path(pdf_path)
        sha256 = self.compute_sha256(path)

        if HAS_PYMUPDF:
            return self._parse_with_pymupdf(
                path,
                start_page=start_page,
                end_page=end_page,
                sha256=sha256,
                document_version_id=document_version_id,
            )
        return self._parse_with_pypdf(
            path,
            start_page=start_page,
            end_page=end_page,
            sha256=sha256,
            document_version_id=document_version_id,
        )

    def _parse_with_pymupdf(
        self,
        pdf_path: Path,
        start_page: int | None = None,
        end_page: int | None = None,
        sha256: str | None = None,
        document_version_id: str | None = None,
    ) -> list[DrawingData]:
        doc = pymupdf.open(pdf_path)
        drawings: list[DrawingData] = []
        total_pages = len(doc)

        p_start = 1 if start_page is None else max(1, start_page)
        p_end = total_pages if end_page is None else min(total_pages, end_page)

        for page_idx in range(p_start - 1, p_end):
            physical_page = page_idx + 1
            page = doc[page_idx]
            text = page.get_text("text") or ""
            lines = [line.strip() for line in text.split("\n") if line.strip()]

            drawing_header_found = None
            for line in lines:
                if self.RUNNING_HEADER_PATTERN.match(line):
                    continue
                hdr = self.parse_text_header(line)
                if hdr:
                    drawing_header_found = hdr
                    break

            if drawing_header_found:
                raw_id, number, title, region_text = drawing_header_found
                drawing_id = f"drawing_{number}"
                regions_dict = self.extract_regions_from_caption(region_text)
                regions: list[DrawingRegionData] = []
                for r_idx, (idx_num, r_cap) in enumerate(regions_dict.items(), start=1):
                    region_id = f"region_{number}_{idx_num}"
                    regions.append(
                        DrawingRegionData(
                            region_id=region_id,
                            drawing_id=drawing_id,
                            number=str(idx_num),
                            title=r_cap,
                            physical_page=physical_page,
                            source_sha256=sha256,
                        )
                    )

                drawing = DrawingData(
                    drawing_id=drawing_id,
                    number=number,
                    physical_page=physical_page,
                    title=title,
                    source_sha256=sha256,
                    document_version_id=document_version_id,
                    regions=regions,
                    raw_identifier=raw_id,
                    source_kind="drawing_pdf",
                )
                drawings.append(drawing)

        doc.close()
        return drawings

    def _parse_with_pypdf(
        self,
        pdf_path: Path,
        start_page: int | None = None,
        end_page: int | None = None,
        sha256: str | None = None,
        document_version_id: str | None = None,
    ) -> list[DrawingData]:
        reader = pypdf.PdfReader(str(pdf_path))
        drawings: list[DrawingData] = []
        total_pages = len(reader.pages)

        p_start = 1 if start_page is None else max(1, start_page)
        p_end = total_pages if end_page is None else min(total_pages, end_page)

        for page_idx in range(p_start - 1, p_end):
            physical_page = page_idx + 1
            page = reader.pages[page_idx]
            text = page.extract_text() or ""
            lines = [line.strip() for line in text.split("\n") if line.strip()]

            drawing_header_found = None
            for line in lines:
                if self.RUNNING_HEADER_PATTERN.match(line):
                    continue
                hdr = self.parse_text_header(line)
                if hdr:
                    drawing_header_found = hdr
                    break

            if drawing_header_found:
                raw_id, number, title, region_text = drawing_header_found
                drawing_id = f"drawing_{number}"
                regions_dict = self.extract_regions_from_caption(region_text)
                regions: list[DrawingRegionData] = []
                for r_idx, (idx_num, r_cap) in enumerate(regions_dict.items(), start=1):
                    region_id = f"region_{number}_{idx_num}"
                    regions.append(
                        DrawingRegionData(
                            region_id=region_id,
                            drawing_id=drawing_id,
                            number=str(idx_num),
                            title=r_cap,
                            physical_page=physical_page,
                            source_sha256=sha256,
                        )
                    )

                drawing = DrawingData(
                    drawing_id=drawing_id,
                    number=number,
                    physical_page=physical_page,
                    title=title,
                    source_sha256=sha256,
                    document_version_id=document_version_id,
                    regions=regions,
                    raw_identifier=raw_id,
                    source_kind="drawing_pdf",
                )
                drawings.append(drawing)

        return drawings
