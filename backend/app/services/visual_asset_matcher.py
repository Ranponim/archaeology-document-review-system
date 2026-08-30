from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps
import pymupdf

from app.domain.source_assets import OriginalAssetData


@dataclass(frozen=True, slots=True)
class VisualAssetMatch:
    source_asset_id: str
    score: float
    method: str = "pixel_thumbnail_similarity"


@dataclass(frozen=True, slots=True)
class VisualPanelRequest:
    panel_id: str
    pdf_path: str | Path
    physical_page: int
    bbox: tuple[float, float, float, float]


class VisualAssetMatcher:
    """Conservatively match safely segmented PDF panels to original images.

    Local matching is deterministic and fail-closed: the best normalized
    thumbnail similarity must clear a high threshold and be separated from the
    second-best candidate. Batch matching additionally requires the selected
    source JPG to be unique across the supplied panels.
    """

    _CANDIDATE_CROP_FRACTIONS = (1.0, 0.9, 0.8)
    _LIGHT_BORDER_THRESHOLD = 245
    _MIN_TRIMMED_CONTENT_FRACTION = 0.25
    _MIN_BORDER_TRIM_FRACTION = 0.03

    def __init__(
        self,
        *,
        minimum_score: float = 0.97,
        minimum_margin: float = 0.03,
        fingerprint_size: tuple[int, int] = (32, 32),
    ) -> None:
        self._minimum_score = float(minimum_score)
        self._minimum_margin = float(minimum_margin)
        self._fingerprint_size = fingerprint_size

    @staticmethod
    def _normalize_image(image: Image.Image) -> Image.Image:
        return ImageOps.exif_transpose(image).convert("L")

    @staticmethod
    def _center_crop(image: Image.Image, fraction: float) -> Image.Image:
        if fraction >= 1.0:
            return image.copy()
        width, height = image.size
        crop_width = max(1, round(width * fraction))
        crop_height = max(1, round(height * fraction))
        left = max(0, (width - crop_width) // 2)
        top = max(0, (height - crop_height) // 2)
        return image.crop((left, top, left + crop_width, top + crop_height))

    @classmethod
    def _trim_light_border(cls, image: Image.Image) -> Image.Image | None:
        """Return one conservative border-trimmed view, never a replacement.

        The original image is always retained as a candidate view.  This helper
        only contributes an additional view when a material light border
        surrounds a reasonably sized darker content region.
        """

        width, height = image.size
        if width < 2 or height < 2:
            return None
        mask = image.point(
            lambda value: 255 if value < cls._LIGHT_BORDER_THRESHOLD else 0
        )
        bbox = mask.getbbox()
        if bbox is None:
            return None
        left, top, right, bottom = bbox
        content_width = right - left
        content_height = bottom - top
        if (
            content_width < width * cls._MIN_TRIMMED_CONTENT_FRACTION
            or content_height < height * cls._MIN_TRIMMED_CONTENT_FRACTION
        ):
            return None
        horizontal_trim = (width - content_width) / width
        vertical_trim = (height - content_height) / height
        if max(horizontal_trim, vertical_trim) < cls._MIN_BORDER_TRIM_FRACTION:
            return None
        return image.crop(bbox)

    def _fingerprint_normalized(self, normalized: Image.Image) -> bytes:
        thumbnail = normalized.copy()
        thumbnail.thumbnail(self._fingerprint_size, Image.Resampling.LANCZOS)
        canvas = Image.new("L", self._fingerprint_size, 255)
        left = (self._fingerprint_size[0] - thumbnail.width) // 2
        top = (self._fingerprint_size[1] - thumbnail.height) // 2
        canvas.paste(thumbnail, (left, top))
        return canvas.tobytes()

    def _fingerprint_image(self, image: Image.Image) -> bytes:
        return self._fingerprint_normalized(self._normalize_image(image))

    def _candidate_fingerprints(self, image: Image.Image) -> tuple[bytes, ...]:
        normalized = self._normalize_image(image)
        views = [normalized]
        trimmed = self._trim_light_border(normalized)
        if trimmed is not None:
            views.append(trimmed)

        fingerprints = []
        for view in views:
            fingerprints.extend(
                self._fingerprint_normalized(self._center_crop(view, fraction))
                for fraction in self._CANDIDATE_CROP_FRACTIONS
            )
        return tuple(fingerprints)

    def _candidate_fingerprints_path(self, path: Path) -> tuple[bytes, ...]:
        with Image.open(path) as image:
            image.load()
            return self._candidate_fingerprints(image)

    @staticmethod
    def _similarity(left: bytes, right: bytes) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        error = sum(abs(a - b) for a, b in zip(left, right, strict=True))
        return max(0.0, 1.0 - error / (255.0 * len(left)))

    @staticmethod
    def _target_rect(page: pymupdf.Page, bbox: tuple[float, float, float, float]) -> pymupdf.Rect:
        x0, y0, x1, y1 = bbox
        return pymupdf.Rect(
            x0 * page.rect.width,
            y0 * page.rect.height,
            x1 * page.rect.width,
            y1 * page.rect.height,
        )

    @staticmethod
    def _rect_similarity(left: pymupdf.Rect, right: pymupdf.Rect) -> float:
        intersection = left & right
        if intersection.is_empty:
            return 0.0
        inter_area = max(0.0, intersection.width) * max(0.0, intersection.height)
        union_area = left.width * left.height + right.width * right.height - inter_area
        return inter_area / union_area if union_area > 0 else 0.0

    def _panel_fingerprint(
        self,
        pdf_path: Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
    ) -> bytes | None:
        doc = pymupdf.open(str(pdf_path))
        try:
            if physical_page < 1 or physical_page > len(doc):
                return None
            page = doc[physical_page - 1]
            target = self._target_rect(page, bbox)
            occurrences: list[tuple[float, int]] = []
            for image_info in page.get_images(full=True):
                xref = int(image_info[0])
                for rect in page.get_image_rects(xref):
                    score = self._rect_similarity(rect, target)
                    if score >= 0.90:
                        occurrences.append((score, xref))
            if not occurrences:
                return None
            occurrences.sort(key=lambda item: item[0], reverse=True)
            best_score = occurrences[0][0]
            best_xrefs = {xref for score, xref in occurrences if abs(score - best_score) < 1e-6}
            if len(best_xrefs) != 1:
                return None
            xref = next(iter(best_xrefs))
            extracted = doc.extract_image(xref)
            data = extracted.get("image")
            if not data:
                return None
            with Image.open(BytesIO(data)) as image:
                image.load()
                return self._fingerprint_image(image)
        finally:
            doc.close()

    def match_panel(
        self,
        *,
        pdf_path: str | Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
        candidates: list[tuple[OriginalAssetData, str | Path]] | tuple[tuple[OriginalAssetData, str | Path], ...],
    ) -> VisualAssetMatch | None:
        panel_fingerprint = self._panel_fingerprint(Path(pdf_path), physical_page, bbox)
        if panel_fingerprint is None:
            return None

        scored: list[tuple[float, str]] = []
        for asset, candidate_path in candidates:
            path = Path(candidate_path)
            if not path.is_file():
                continue
            try:
                fingerprints = self._candidate_fingerprints_path(path)
            except (OSError, ValueError):
                continue
            score = max(
                self._similarity(panel_fingerprint, fingerprint)
                for fingerprint in fingerprints
            )
            scored.append((score, asset.id))

        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score, best_id = scored[0]
        if best_score < self._minimum_score:
            return None
        if len(scored) > 1 and best_score - scored[1][0] < self._minimum_margin:
            return None
        return VisualAssetMatch(source_asset_id=best_id, score=best_score)

    def match_panels(
        self,
        *,
        panels: list[VisualPanelRequest] | tuple[VisualPanelRequest, ...],
        candidates: list[tuple[OriginalAssetData, str | Path]] | tuple[tuple[OriginalAssetData, str | Path], ...],
    ) -> dict[str, VisualAssetMatch]:
        local_matches: dict[str, VisualAssetMatch] = {}
        for panel in panels:
            match = self.match_panel(
                pdf_path=panel.pdf_path,
                physical_page=panel.physical_page,
                bbox=panel.bbox,
                candidates=candidates,
            )
            if match is not None:
                local_matches[panel.panel_id] = match

        source_counts = Counter(
            match.source_asset_id for match in local_matches.values()
        )
        return {
            panel_id: match
            for panel_id, match in local_matches.items()
            if source_counts[match.source_asset_id] == 1
        }
