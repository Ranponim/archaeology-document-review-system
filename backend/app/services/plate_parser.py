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

from app.domain.canonical_models import PlateData, PlatePanelData


CIRCLED_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
CIRCLED_MAP: dict[str, int] = {c: i + 1 for i, c in enumerate(CIRCLED_CHARS)}

PAREN_CHARS = "⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽⑾⑿⒀⒁⒂⒃⒄⒅⒆⒇"
for i, c in enumerate(PAREN_CHARS):
    CIRCLED_MAP[c] = i + 1

PAGE_RENDER_ZOOM = 2.0
PAGE_RENDER_MIN_WIDTH = 1191.0
LABEL_ASSOCIATION_MARGIN = 8.0


@dataclass(frozen=True, slots=True)
class PlateIndex:
    plates_by_number: dict[str, PlateData] = field(default_factory=dict)
    plates: list[PlateData] = field(default_factory=list)

    def get_plate(self, number: str) -> PlateData | None:
        return self.plates_by_number.get(str(number).strip())

    def get_panel(self, plate_number: str, panel_index: int) -> PlatePanelData | None:
        plate = self.get_plate(plate_number)
        if not plate:
            return None
        for p in plate.panels:
            if p.panel_index == panel_index:
                return p
        return None

    def __getitem__(self, key: str | int) -> PlateData:
        if isinstance(key, int):
            return self.plates[key]
        return self.plates_by_number[str(key).strip()]

    def __contains__(self, number: str) -> bool:
        return str(number).strip() in self.plates_by_number

    def __iter__(self) -> Iterator[PlateData]:
        return iter(self.plates)

    def __len__(self) -> int:
        return len(self.plates)


PlateBookResult = PlateIndex


class PlateParser:
    """Parser for archaeological plate books extracting explicit identifiers and panels."""

    IDENTIFIER_PATTERN = re.compile(
        r"(【\s*도판\s*(\d+(?:-\d+)?)\s*】|"
        r"\[\s*도판\s*(\d+(?:-\d+)?)\s*\]|"
        r"〈\s*도판\s*(\d+(?:-\d+)?)\s*〉|"
        r"<\s*도판\s*(\d+(?:-\d+)?)\s*>|"
        r"〔\s*도판\s*(\d+(?:-\d+)?)\s*〕|"
        r"《\s*도판\s*(\d+(?:-\d+)?)\s*》|"
        r"도판\s*(\d+(?:-\d+)?))"
    )

    PANEL_SPLIT_PATTERN = re.compile(
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
    def parse_panel_token(cls, tok: str) -> list[int]:
        tok = tok.strip()
        if not tok:
            return []

        # Check range pattern: e.g. ②~⑤ or ②-⑤
        m_range = re.match(r"^([①-⑳⑴-⒇]|\(?\d+\)?)\s*[~\-–—]\s*([①-⑳⑴-⒇]|\(?\d+\)?)$", tok)
        if m_range:
            t1, t2 = m_range.group(1), m_range.group(2)
            idx1 = cls._token_to_int(t1)
            idx2 = cls._token_to_int(t2)
            if idx1 is not None and idx2 is not None and idx1 <= idx2:
                return list(range(idx1, idx2 + 1))

        # Check dot/comma joined tokens: e.g. ②·③ or ②ㆍ③
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
    def is_panel_badge_word(
        cls, tok: str, expected_indices: set[int] | None = None
    ) -> list[int]:
        """Check if a word token on a page represents a panel badge."""
        tok = tok.strip()
        if not tok:
            return []

        # Circled characters
        if tok in CIRCLED_MAP:
            return [CIRCLED_MAP[tok]]

        # (1) or 1)
        m = re.match(r"^\((\d+)\)$|^\b(\d+)\)$", tok)
        if m:
            val = int(m.group(1) or m.group(2))
            return [val]

        # Bare numbers only if explicitly expected in panel index set
        if tok.isdigit() and expected_indices and int(tok) in expected_indices:
            return [int(tok)]

        return []

    @classmethod
    def _render_page_png(cls, page: Any, zoom: float | None = None) -> bytes:
        """Render one plate page at high resolution (>=2x, ~1191px wide)."""
        if zoom is None:
            zoom = max(PAGE_RENDER_ZOOM, PAGE_RENDER_MIN_WIDTH / page.rect.width)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")

    @classmethod
    def render_page(
        cls, pdf_path: str | Path, physical_page: int, zoom: float | None = None
    ) -> bytes:
        """Render one physical page of a plate PDF at high resolution."""
        doc = pymupdf.open(str(pdf_path))
        try:
            page = doc[physical_page - 1]
            return cls._render_page_png(page, zoom=zoom)
        finally:
            doc.close()

    @classmethod
    def segment_page_panels(
        cls,
        page: Any,
        label_bboxes: dict[int, tuple[float, float, float, float]],
        expected_indices: set[int] | None = None,
    ) -> dict[int, tuple[float, float, float, float]]:
        """Map panel labels to embedded photo rects on a plate page.

        Every embedded image rectangle of the page is a candidate photo region.
        A label is associated with the photo that contains its center (within
        LABEL_ASSOCIATION_MARGIN); exactly one candidate is required — otherwise
        the panel region cannot be safely isolated and is omitted from the
        result. Returns {panel_index: bbox} with bboxes in normalized page
        coordinates (0..1, top-left origin).
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
        for p_idx, label_bb in label_bboxes.items():
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
                result[p_idx] = (
                    r.x0 / page_width,
                    r.y0 / page_height,
                    r.x1 / page_width,
                    r.y1 / page_height,
                )

        # Some source PDFs rasterize the panel badges into the photo itself,
        # leaving no text bbox to associate. When the page has exactly one
        # embedded image per expected panel, reading order is deterministic
        # and supplies the missing associations without guessing from names.
        if (
            expected_indices
            and len(expected_indices) == len(image_rects)
            and len(result) < len(expected_indices)
        ):
            for p_idx, r in zip(
                sorted(expected_indices),
                sorted(image_rects, key=lambda item: (item.y0, item.x0)),
            ):
                result[p_idx] = (
                    r.x0 / page_width,
                    r.y0 / page_height,
                    r.x1 / page_width,
                    r.y1 / page_height,
                )
        return result

    @classmethod
    def parse_text_header(cls, text: str) -> tuple[str, str, str, str] | None:
        """Parse plate header line into (raw_identifier, number, title, panel_text)."""
        m = cls.IDENTIFIER_PATTERN.search(text)
        if not m:
            return None

        raw_identifier = m.group(1)
        # Find which capture group matched the number
        number = next(g for g in m.groups()[1:] if g is not None)
        after = text[m.end():].strip()

        panel_m = cls.PANEL_SPLIT_PATTERN.search(after)
        if panel_m:
            title_raw = after[:panel_m.start()]
            panel_text = after[panel_m.start():].strip()
        else:
            title_raw = after
            panel_text = ""

        # Normalize whitespace in title
        title_raw = re.sub(r"\s+", " ", title_raw).strip()
        title = re.sub(r"^[\s\-–—/:]+|[\s\-–—/:]+$", "", title_raw).strip()
        return raw_identifier, number, title, panel_text

    @classmethod
    def extract_panels_from_caption(cls, panel_text: str) -> dict[int, str]:
        """Extract mapping from panel_index -> caption from panel caption string."""
        if not panel_text or not panel_text.strip():
            return {}

        pattern = re.compile(
            r"([①-⑳⑴-⒇](?:\s*[·ㆍ•・,~–—]\s*[①-⑳⑴-⒇])*|\(\d+\)|\b\d+\))"
        )
        matches = list(pattern.finditer(panel_text))
        if not matches:
            return {}

        results: dict[int, str] = {}
        for i, m in enumerate(matches):
            marker_str = m.group(1)
            start_idx = m.end()
            end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(panel_text)
            caption = panel_text[start_idx:end_idx].strip()
            # Clean caption leading/trailing delimiters
            caption = re.sub(r"^[\s\-–—/:]+|[\s\-–—/:]+$", "", caption).strip()
            indices = cls.parse_panel_token(marker_str)
            for idx in indices:
                results[idx] = caption
        return results

    def parse(
        self,
        pdf_path: str | Path,
        document_version_id: str | None = None,
        render_dir: str | Path | None = None,
        on_progress: Any | None = None,
    ) -> PlateIndex:
        """Parse plate document and return searchable PlateIndex."""
        plates = self.parse_plates(
            pdf_path,
            document_version_id=document_version_id,
            render_dir=render_dir,
            on_progress=on_progress,
        )
        return PlateIndex(
            plates_by_number={p.number: p for p in plates},
            plates=plates,
        )

    def parse_plates(
        self,
        pdf_path: str | Path,
        document_version_id: str | None = None,
        render_dir: str | Path | None = None,
        on_progress: Any | None = None,
    ) -> list[PlateData]:
        """Parse all plates from a PDF file."""
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
    ) -> list[PlateData]:
        """Parse a specific 1-indexed range of physical pages from a PDF."""
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
    ) -> list[PlateData]:
        doc = pymupdf.open(str(pdf_path))
        total_pages = len(doc)
        s_page = 1 if start_page is None else max(1, start_page)
        e_page = total_pages if end_page is None else min(total_pages, end_page)
        render_root = Path(render_dir) if render_dir is not None else None

        plates: list[PlateData] = []

        for pno in range(s_page - 1, e_page):
            physical_page = pno + 1
            if on_progress is not None and (physical_page % 5 == 1 or physical_page == e_page):
                try:
                    on_progress(
                        physical_page,
                        total_pages,
                        f"도판 {physical_page}/{total_pages}쪽 고해상도 렌더링 및 패널 추출 중",
                    )
                except Exception:
                    pass

            page = doc[pno]
            blocks = page.get_text("blocks")
            words = page.get_text("words")

            header_blocks: list[tuple[Any, tuple[str, str, str, str]]] = []
            for b in blocks:
                header_info = self.parse_text_header(b[4])
                if header_info:
                    header_blocks.append((b, header_info))
            if not header_blocks:
                continue

            # Collect panel badge words outside every header block on the page.
            header_bboxes = [
                (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
                for b, _ in header_blocks
            ]
            expected_indices_all = set()
            for _, info in header_blocks:
                expected_indices_all.update(
                    self.extract_panels_from_caption(info[3]).keys()
                )
            # A long caption can wrap into a second text block below the
            # identifier block. Include those continuation markers so a
            # rasterized badge does not become an orphan panel.
            for block in blocks:
                expected_indices_all.update(
                    self.extract_panels_from_caption(block[4]).keys()
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
                for p_idx in self.is_panel_badge_word(
                    w_text, expected_indices=expected_indices_all
                ):
                    if p_idx not in label_bboxes:
                        label_bboxes[p_idx] = w_bbox

            # Panel segmentation: real photo/panel regions from embedded images.
            segment_bboxes = self.segment_page_panels(
                page,
                label_bboxes,
                expected_indices=expected_indices_all,
            )

            # High-resolution page render, shared by every panel of the page.
            page_render_uri: str | None = None
            if render_root is not None:
                page_render_uri = self._persist_page_render(
                    render_root,
                    document_version_id=document_version_id,
                    physical_page=physical_page,
                    page=page,
                )

            for b, (raw_identifier, plate_number, title, panel_text) in header_blocks:
                plate_bbox = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
                plate_id = (
                    f"plate_{plate_number}"
                    if not document_version_id
                    else f"{document_version_id}_plate_{plate_number}"
                )

                header_panels = self.extract_panels_from_caption(panel_text)
                all_panel_indices = sorted(
                    set(header_panels.keys()).union(label_bboxes.keys())
                )
                panels: list[PlatePanelData] = []
                for p_idx in all_panel_indices:
                    panel_id = f"{plate_id}_panel_{p_idx}"
                    caption = header_panels.get(p_idx, "")
                    seg = segment_bboxes.get(p_idx)
                    if seg is not None:
                        panel_bbox: tuple | None = seg
                        bbox_status = "segmented"
                        render_uri: str | None = page_render_uri
                    else:
                        panel_bbox = None
                        bbox_status = "insufficient"
                        render_uri = None
                    panels.append(
                        PlatePanelData(
                            panel_id=panel_id,
                            plate_id=plate_id,
                            panel_index=p_idx,
                            caption=caption,
                            bbox=panel_bbox,
                            bbox_status=bbox_status,
                            render_uri=render_uri,
                            physical_page=physical_page,
                            source_sha256=sha256,
                        )
                    )

                plates.append(
                    PlateData(
                        plate_id=plate_id,
                        number=plate_number,
                        physical_page=physical_page,
                        title=title,
                        bbox=plate_bbox,
                        source_sha256=sha256,
                        document_version_id=document_version_id,
                        panels=panels,
                        raw_identifier=raw_identifier,
                    )
                )

        doc.close()
        return plates

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
            f"{document_version_id or 'plate'}_p{physical_page:03d}.png"
        )
        render_path = render_root / file_name
        render_path.parent.mkdir(parents=True, exist_ok=True)
        if not render_path.exists() or render_path.stat().st_size == 0:
            render_path.write_bytes(cls._render_page_png(page))
        return str(render_path)

    def _parse_with_pypdf(
        self,
        pdf_path: Path,
        start_page: int | None = None,
        end_page: int | None = None,
        sha256: str | None = None,
        document_version_id: str | None = None,
        render_dir: str | Path | None = None,
    ) -> list[PlateData]:
        reader = pypdf.PdfReader(str(pdf_path))
        total_pages = len(reader.pages)
        s_page = 1 if start_page is None else max(1, start_page)
        e_page = total_pages if end_page is None else min(total_pages, end_page)

        plates: list[PlateData] = []

        for pno in range(s_page - 1, e_page):
            physical_page = pno + 1
            page = reader.pages[pno]
            text = page.extract_text() or ""

            for line in text.split("\n"):
                header_info = self.parse_text_header(line)
                if not header_info:
                    continue

                raw_identifier, plate_number, title, panel_text = header_info
                plate_id = (
                    f"plate_{plate_number}"
                    if not document_version_id
                    else f"{document_version_id}_plate_{plate_number}"
                )

                header_panels = self.extract_panels_from_caption(panel_text)
                panels: list[PlatePanelData] = []
                for p_idx in sorted(header_panels.keys()):
                    panel_id = f"{plate_id}_panel_{p_idx}"
                    caption = header_panels[p_idx]
                    panels.append(
                        PlatePanelData(
                            panel_id=panel_id,
                            plate_id=plate_id,
                            panel_index=p_idx,
                            caption=caption,
                            bbox=None,
                            physical_page=physical_page,
                            source_sha256=sha256,
                        )
                    )

                plates.append(
                    PlateData(
                        plate_id=plate_id,
                        number=plate_number,
                        physical_page=physical_page,
                        title=title,
                        bbox=None,
                        source_sha256=sha256,
                        document_version_id=document_version_id,
                        panels=panels,
                        raw_identifier=raw_identifier,
                    )
                )

        return plates
