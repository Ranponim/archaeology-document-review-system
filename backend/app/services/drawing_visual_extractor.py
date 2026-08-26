from __future__ import annotations

from pathlib import Path
import re

import pymupdf

from app.domain.drawing_evidence_v3 import DrawingVisualRegion


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class DrawingVisualExtractor:
    def __init__(self, render_scale: float = 2.0) -> None:
        if render_scale <= 0:
            raise ValueError("render_scale must be positive")
        self._matrix = pymupdf.Matrix(render_scale, render_scale)

    @staticmethod
    def _safe_name(value: str) -> str:
        normalized = _SAFE_NAME_RE.sub("-", value).strip("-._")
        return normalized or "region"

    def render_source(
        self,
        path: str | Path,
        output_dir: str | Path,
        source_asset_id: str,
        source_sha256: str,
    ) -> DrawingVisualRegion:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        document = pymupdf.open(str(path))
        try:
            if document.page_count < 1:
                raise ValueError("source document has no pages")
            page = document[0]
            pixmap = page.get_pixmap(matrix=self._matrix, alpha=False)
            target = target_dir / f"source-{self._safe_name(source_asset_id)}.png"
            pixmap.save(str(target))
            return DrawingVisualRegion(
                region_id=f"source:{source_asset_id}",
                image_path=str(target),
                page=1,
                bbox=None,
                confidence=1.0,
                source_sha256=source_sha256,
            )
        finally:
            document.close()

    def crop_body_region(
        self,
        path: str | Path,
        output_dir: str | Path,
        region_id: str,
        page_number: int,
        bbox: tuple[float, float, float, float],
        source_sha256: str | None = None,
    ) -> DrawingVisualRegion:
        if page_number < 1:
            raise ValueError("page_number must be 1-based")
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        document = pymupdf.open(str(path))
        try:
            if page_number > document.page_count:
                raise ValueError("page_number is outside the document")
            page = document[page_number - 1]
            clip = pymupdf.Rect(*bbox) & page.rect
            if clip.is_empty or clip.width <= 0 or clip.height <= 0:
                raise ValueError("body bbox produced an empty crop")
            pixmap = page.get_pixmap(matrix=self._matrix, clip=clip, alpha=False)
            target = target_dir / f"{self._safe_name(region_id)}.png"
            pixmap.save(str(target))
            return DrawingVisualRegion(
                region_id=region_id,
                image_path=str(target),
                page=page_number,
                bbox=(float(clip.x0), float(clip.y0), float(clip.x1), float(clip.y1)),
                confidence=1.0,
                source_sha256=source_sha256,
            )
        finally:
            document.close()
