from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Any, Iterator, Sequence

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

PAGE_RENDER_ZOOM = 2.0
PAGE_RENDER_MIN_WIDTH = 1191.0
LABEL_ASSOCIATION_MARGIN = 8.0


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

    @classmethod
    def is_region_badge_word(
        cls, tok: str, expected_indices: set[int] | None = None
    ) -> list[int]:
        """Check if a word token on a page represents a region badge."""
        tok = tok.strip()
        if not tok:
            return []

        if tok in CIRCLED_MAP:
            return [CIRCLED_MAP[tok]]

        m = re.match(r"^\((\d+)\)$|^\b(\d+)\)$", tok)
        if m:
            val = int(m.group(1) or m.group(2))
            return [val]

        if tok.isdigit() and expected_indices and int(tok) in expected_indices:
            return [int(tok)]

        return []

    @classmethod
    def _render_page_png(cls, page: Any, zoom: float | None = None) -> bytes:
        """Render one drawing page at high resolution (>=2x, ~1191px wide)."""
        if zoom is None:
            zoom = max(PAGE_RENDER_ZOOM, PAGE_RENDER_MIN_WIDTH / page.rect.width)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")

    @classmethod
    def render_page(
        cls, pdf_path: str | Path, physical_page: int, zoom: float | None = None
    ) -> bytes:
        """Render one physical page of a drawing PDF at high resolution."""
        doc = pymupdf.open(str(pdf_path))
        try:
            page = doc[physical_page - 1]
            return cls._render_page_png(page, zoom=zoom)
        finally:
            doc.close()

    @classmethod
    def segment_page_regions(
        cls,
        page: Any,
        label_bboxes: dict[int, tuple[float, float, float, float]],
    ) -> dict[int, tuple[float, float, float, float]]:
        """Map region labels to embedded drawing rects on a drawing page.

        Every embedded image rectangle of the page is a candidate region. A
        label is associated with the image that contains its center (within
        LABEL_ASSOCIATION_MARGIN); exactly one candidate is required — otherwise
        the region cannot be safely isolated and is omitted from the result.
        Returns {region_index: bbox} with bboxes in normalized page coordinates
        (0..1, top-left origin).
        """
        image_rects: list[Any] = []
        seen: set[tuple[float, float, float, float]] = set()
        for img in page.get_images(full=True):
            for r in page.get_image_rects(img[0]):
                key = (round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))
                if key in seen or r.width < 2.0 or r.height < 2.0:
                    continue
                seen.add(key)
                image_rects.append(r)

        page_width = page.rect.width
        page_height = page.rect.height
        result: dict[int, tuple[float, float, float, float]] = {}
        for r_idx, label_bb in label_bboxes.items():
            if not label_bb:
                continue
            lx = (label_bb[0] + label_bb[2]) / 2.0
            ly = (label_bb[1] + label_bb[3]) / 2.0
            margin = LABEL_ASSOCIATION_MARGIN
            candidates = [
                r
                for r in image_rects
                if r.x0 - margin <= lx <= r.x1 + margin
                and r.y0 - margin <= ly <= r.y1 + margin
            ]
            if len(candidates) == 1:
                r = candidates[0]
                result[r_idx] = (
                    r.x0 / page_width,
                    r.y0 / page_height,
                    r.x1 / page_width,
                    r.y1 / page_height,
                )
        return result

    @classmethod
    def _persist_page_render(
        cls,
        render_root: Path,
        document_version_id: str | None,
        physical_page: int,
        page: Any,
    ) -> str:
        """Write the high-resolution page render under the derived dir."""
        file_name = (
            f"{document_version_id or 'drawing'}_p{physical_page:03d}.png"
        )
        render_path = render_root / file_name
        render_path.parent.mkdir(parents=True, exist_ok=True)
        if not render_path.exists() or render_path.stat().st_size == 0:
            render_path.write_bytes(cls._render_page_png(page))
        return str(render_path)

    def parse(
        self,
        pdf_path: str | Path,
        document_version_id: str | None = None,
        render_dir: str | Path | None = None,
        on_progress: Any | None = None,
    ) -> DrawingIndex:
        drawings = self.parse_drawings(
            pdf_path,
            document_version_id=document_version_id,
            render_dir=render_dir,
            on_progress=on_progress,
        )
        drawings_by_number = {d.number: d for d in drawings}
        return DrawingIndex(drawings_by_number=drawings_by_number, drawings=drawings)

    def parse_drawings(
        self,
        pdf_path: str | Path,
        document_version_id: str | None = None,
        render_dir: str | Path | None = None,
        on_progress: Any | None = None,
    ) -> list[DrawingData]:
        path = Path(pdf_path)
        sha256 = self.compute_sha256(path)

        if HAS_PYMUPDF:
            return self._parse_with_pymupdf(
                path,
                sha256=sha256,
                document_version_id=document_version_id,
                render_dir=render_dir,
                on_progress=on_progress,
            )
        return self._parse_with_pypdf(
            path,
            sha256=sha256,
            document_version_id=document_version_id,
            render_dir=render_dir,
        )

    def parse_page_range(
        self,
        pdf_path: str | Path,
        start_page: int,
        end_page: int,
        document_version_id: str | None = None,
        render_dir: str | Path | None = None,
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
                render_dir=render_dir,
            )
        return self._parse_with_pypdf(
            path,
            start_page=start_page,
            end_page=end_page,
            sha256=sha256,
            document_version_id=document_version_id,
            render_dir=render_dir,
        )

    def _parse_with_pymupdf(
        self,
        pdf_path: Path,
        start_page: int | None = None,
        end_page: int | None = None,
        sha256: str | None = None,
        document_version_id: str | None = None,
        render_dir: str | Path | None = None,
        on_progress: Any | None = None,
    ) -> list[DrawingData]:
        doc = pymupdf.open(pdf_path)
        drawings: list[DrawingData] = []
        total_pages = len(doc)

        p_start = 1 if start_page is None else max(1, start_page)
        p_end = total_pages if end_page is None else min(total_pages, end_page)
        render_root = Path(render_dir) if render_dir is not None else None

        for page_idx in range(p_start - 1, p_end):
            physical_page = page_idx + 1
            if on_progress is not None and (physical_page % 5 == 1 or physical_page == p_end):
                try:
                    on_progress(
                        physical_page,
                        total_pages,
                        f"도면 {physical_page}/{total_pages}쪽 고해상도 렌더링 및 영역 추출 중",
                    )
                except Exception:
                    pass

            page = doc[page_idx]
            blocks = page.get_text("blocks")
            words = page.get_text("words")

            header_blocks: list[tuple[Any, tuple[str, str, str, str]]] = []
            for b in blocks:
                header_info = self.parse_text_header(b[4])
                if header_info:
                    header_blocks.append((b, header_info))
            if not header_blocks:
                continue

            header_bboxes = [
                (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
                for b, _ in header_blocks
            ]
            expected_indices_all: set[int] = set()
            for _, info in header_blocks:
                expected_indices_all.update(
                    self.extract_regions_from_caption(info[3]).keys()
                )
            label_bboxes: dict[int, tuple[float, float, float, float]] = {}
            for w in words:
                w_text = w[4].strip()
                w_bbox = (float(w[0]), float(w[1]), float(w[2]), float(w[3]))
                if any(
                    w_bbox[0] >= hb[0] - 2
                    and w_bbox[2] <= hb[2] + 2
                    and w_bbox[1] >= hb[1] - 2
                    and w_bbox[3] <= hb[3] + 2
                    for hb in header_bboxes
                ):
                    continue
                for r_idx in self.is_region_badge_word(
                    w_text, expected_indices=expected_indices_all
                ):
                    if r_idx not in label_bboxes:
                        label_bboxes[r_idx] = w_bbox

            segment_bboxes = self.segment_page_regions(page, label_bboxes)

            page_render_uri: str | None = None
            if render_root is not None:
                page_render_uri = self._persist_page_render(
                    render_root,
                    document_version_id=document_version_id,
                    physical_page=physical_page,
                    page=page,
                )

            for b, (raw_id, number, title, region_text) in header_blocks:
                drawing_bbox = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
                drawing_id = (
                    f"doc_drawing_{number}"
                    if not document_version_id
                    else f"{document_version_id}_drawing_{number}"
                )
                header_regions = self.extract_regions_from_caption(region_text)
                all_region_indices = sorted(
                    set(header_regions.keys()).union(label_bboxes.keys())
                )
                regions: list[DrawingRegionData] = []
                for r_idx in all_region_indices:
                    region_id = f"{drawing_id}_region_{r_idx}"
                    caption = header_regions.get(r_idx, "")
                    seg = segment_bboxes.get(r_idx)
                    if seg is not None:
                        region_bbox: tuple | None = seg
                        bbox_status = "segmented"
                        render_uri: str | None = page_render_uri
                    else:
                        region_bbox = None
                        bbox_status = "insufficient"
                        render_uri = None
                    regions.append(
                        DrawingRegionData(
                            region_id=region_id,
                            drawing_id=drawing_id,
                            number=str(r_idx),
                            title=caption,
                            bbox=region_bbox,
                            bbox_status=bbox_status,
                            render_uri=render_uri,
                            physical_page=physical_page,
                            source_sha256=sha256,
                        )
                    )

                drawing = DrawingData(
                    drawing_id=drawing_id,
                    number=number,
                    physical_page=physical_page,
                    title=title,
                    bbox=drawing_bbox,
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
        render_dir: str | Path | None = None,
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
                drawing_id = (
                    f"doc_drawing_{number}"
                    if not document_version_id
                    else f"{document_version_id}_drawing_{number}"
                )
                regions_dict = self.extract_regions_from_caption(region_text)
                regions: list[DrawingRegionData] = []
                for r_idx, (idx_num, r_cap) in enumerate(regions_dict.items(), start=1):
                    region_id = f"{drawing_id}_region_{idx_num}"
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
