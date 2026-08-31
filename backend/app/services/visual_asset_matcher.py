from __future__ import annotations

from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageOps
import pymupdf

from app.domain.source_assets import OriginalAssetData


@dataclass(frozen=True, slots=True)
class _BatchScoreIndex:
    variant_asset_ids: tuple[str, ...]
    candidate_image: Image.Image
    fingerprint_length: int
    variant_count: int


_BATCH_CANDIDATE_FINGERPRINTS: ContextVar[dict[Path, tuple[bytes, ...] | None] | None] = ContextVar(
    "visual_asset_matcher_batch_candidate_fingerprints",
    default=None,
)
_BATCH_PDF_DOCUMENTS: ContextVar[dict[tuple[int, str], pymupdf.Document] | None] = ContextVar(
    "visual_asset_matcher_batch_pdf_documents",
    default=None,
)
_BATCH_SCORE_INDEX: ContextVar[_BatchScoreIndex | None] = ContextVar(
    "visual_asset_matcher_batch_score_index",
    default=None,
)


@dataclass(frozen=True, slots=True)
class VisualAssetMatch:
    source_asset_id: str
    score: float
    method: str = "pixel_thumbnail_similarity"


@dataclass(frozen=True, slots=True)
class VisualAssetCandidateScore:
    """One retrieval candidate, independent of the automatic verification gate."""

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
    second-best candidate. Retrieval can expose below-threshold Top-K candidates
    for a separate review/model layer without weakening that automatic gate.
    Batch operations reuse expensive candidate/PDF work, perform pixel-difference
    work in Pillow's native implementation instead of one Python byte loop per
    panel/candidate pair, and matching additionally requires the selected source
    JPG to be unique within each supplied PDF. The same original may be reused by
    a distinct PDF revision/version.
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

        The original image is always retained as a candidate view. This helper
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

    def _fingerprint_variants(self, normalized: Image.Image) -> tuple[bytes, ...]:
        """Keep the raw signal and add one exposure-normalized fallback."""

        raw = self._fingerprint_normalized(normalized)
        tonal = self._fingerprint_normalized(ImageOps.autocontrast(normalized))
        if tonal == raw:
            return (raw,)
        return (raw, tonal)

    def _fingerprint_image(self, image: Image.Image) -> tuple[bytes, ...]:
        return self._fingerprint_variants(self._normalize_image(image))

    def _candidate_fingerprints(self, image: Image.Image) -> tuple[bytes, ...]:
        normalized = self._normalize_image(image)
        views = [normalized]
        trimmed = self._trim_light_border(normalized)
        if trimmed is not None:
            views.append(trimmed)

        fingerprints: list[bytes] = []
        for view in views:
            for fraction in self._CANDIDATE_CROP_FRACTIONS:
                fingerprints.extend(
                    self._fingerprint_variants(self._center_crop(view, fraction))
                )
        return tuple(fingerprints)

    def _candidate_fingerprints_path(self, path: Path) -> tuple[bytes, ...]:
        with Image.open(path) as image:
            image.load()
            return self._candidate_fingerprints(image)

    def _candidate_fingerprints_for_match(self, path: Path) -> tuple[bytes, ...] | None:
        batch_cache = _BATCH_CANDIDATE_FINGERPRINTS.get()
        if batch_cache is not None and path in batch_cache:
            return batch_cache[path]
        try:
            return self._candidate_fingerprints_path(path)
        except (OSError, ValueError):
            return None

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

    @staticmethod
    def _pdf_identity(pdf_path: str | Path) -> str:
        # PDF paths can arrive with Windows or POSIX separators. Collision
        # safety is scoped to one PDF, so normalize only enough to make the same
        # path compare consistently without requiring that the path exists.
        return str(pdf_path).replace("\\", "/").casefold()

    def _panel_fingerprint_from_document(
        self,
        doc: pymupdf.Document,
        physical_page: int,
        bbox: tuple[float, float, float, float],
    ) -> tuple[bytes, ...] | None:
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

    def _panel_fingerprint(
        self,
        pdf_path: Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
    ) -> tuple[bytes, ...] | None:
        batch_documents = _BATCH_PDF_DOCUMENTS.get()
        if batch_documents is not None:
            key = (id(self), self._pdf_identity(pdf_path))
            doc = batch_documents.get(key)
            if doc is None:
                doc = pymupdf.open(str(pdf_path))
                batch_documents[key] = doc
            return self._panel_fingerprint_from_document(doc, physical_page, bbox)

        doc = pymupdf.open(str(pdf_path))
        try:
            return self._panel_fingerprint_from_document(doc, physical_page, bbox)
        finally:
            doc.close()

    @staticmethod
    def _panel_fingerprint_variants(
        value: bytes | tuple[bytes, ...],
    ) -> tuple[bytes, ...]:
        # Preserve test/integration compatibility with callers that replace the
        # private extractor with one legacy fingerprint.
        if isinstance(value, bytes):
            return (value,)
        return value

    @staticmethod
    def _build_batch_score_index(
        candidates: list[tuple[OriginalAssetData, str | Path]]
        | tuple[tuple[OriginalAssetData, str | Path], ...],
        candidate_cache: dict[Path, tuple[bytes, ...] | None],
    ) -> _BatchScoreIndex | None:
        variant_asset_ids: list[str] = []
        variant_fingerprints: list[bytes] = []
        fingerprint_length: int | None = None

        for asset, candidate_path in candidates:
            fingerprints = candidate_cache.get(Path(candidate_path))
            if not fingerprints:
                continue
            for fingerprint in fingerprints:
                if not fingerprint:
                    continue
                if fingerprint_length is None:
                    fingerprint_length = len(fingerprint)
                if len(fingerprint) != fingerprint_length:
                    continue
                variant_asset_ids.append(asset.id)
                variant_fingerprints.append(fingerprint)

        if not variant_fingerprints or not fingerprint_length:
            return None

        candidate_image = Image.frombytes(
            "L",
            (fingerprint_length, len(variant_fingerprints)),
            b"".join(variant_fingerprints),
        )
        return _BatchScoreIndex(
            variant_asset_ids=tuple(variant_asset_ids),
            candidate_image=candidate_image,
            fingerprint_length=fingerprint_length,
            variant_count=len(variant_fingerprints),
        )

    @staticmethod
    def _bulk_candidate_scores(
        panel_fingerprints: tuple[bytes, ...],
        index: _BatchScoreIndex,
    ) -> list[tuple[float, str]]:
        best_error_by_asset: dict[str, int] = {}
        width = index.fingerprint_length
        count = index.variant_count

        for panel_fingerprint in panel_fingerprints:
            if len(panel_fingerprint) != width:
                continue
            panel_image = Image.frombytes(
                "L",
                (width, count),
                panel_fingerprint * count,
            )
            differences = ImageChops.difference(
                index.candidate_image,
                panel_image,
            ).tobytes()

            for row, asset_id in enumerate(index.variant_asset_ids):
                start = row * width
                error = sum(differences[start : start + width])
                previous = best_error_by_asset.get(asset_id)
                if previous is None or error < previous:
                    best_error_by_asset[asset_id] = error

        denominator = 255.0 * width
        return [
            (max(0.0, 1.0 - error / denominator), asset_id)
            for asset_id, error in best_error_by_asset.items()
        ]

    def _score_panel_candidates(
        self,
        *,
        pdf_path: str | Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
        candidates: list[tuple[OriginalAssetData, str | Path]]
        | tuple[tuple[OriginalAssetData, str | Path], ...],
    ) -> list[tuple[float, str]]:
        panel_value = self._panel_fingerprint(Path(pdf_path), physical_page, bbox)
        if panel_value is None:
            return []
        panel_fingerprints = self._panel_fingerprint_variants(panel_value)

        batch_score_index = _BATCH_SCORE_INDEX.get()
        if batch_score_index is not None:
            scored = self._bulk_candidate_scores(panel_fingerprints, batch_score_index)
        else:
            scored = []
            for asset, candidate_path in candidates:
                path = Path(candidate_path)
                if not path.is_file():
                    continue
                fingerprints = self._candidate_fingerprints_for_match(path)
                if not fingerprints:
                    continue
                score = max(
                    self._similarity(panel_fingerprint, fingerprint)
                    for panel_fingerprint in panel_fingerprints
                    for fingerprint in fingerprints
                )
                scored.append((score, asset.id))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored

    def rank_panel_candidates(
        self,
        *,
        pdf_path: str | Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
        candidates: list[tuple[OriginalAssetData, str | Path]]
        | tuple[tuple[OriginalAssetData, str | Path], ...],
        limit: int = 5,
    ) -> tuple[VisualAssetCandidateScore, ...]:
        """Return retrieval candidates without applying the automatic match gate."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        scored = self._score_panel_candidates(
            pdf_path=pdf_path,
            physical_page=physical_page,
            bbox=bbox,
            candidates=candidates,
        )
        return tuple(
            VisualAssetCandidateScore(source_asset_id=asset_id, score=score)
            for score, asset_id in scored[:limit]
        )

    def match_panel(
        self,
        *,
        pdf_path: str | Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
        candidates: list[tuple[OriginalAssetData, str | Path]] | tuple[tuple[OriginalAssetData, str | Path], ...],
    ) -> VisualAssetMatch | None:
        scored = self._score_panel_candidates(
            pdf_path=pdf_path,
            physical_page=physical_page,
            bbox=bbox,
            candidates=candidates,
        )
        if not scored:
            return None
        best_score, best_id = scored[0]
        if best_score < self._minimum_score:
            return None
        if len(scored) > 1 and best_score - scored[1][0] < self._minimum_margin:
            return None
        return VisualAssetMatch(source_asset_id=best_id, score=best_score)

    def _candidate_cache(
        self,
        candidates: list[tuple[OriginalAssetData, str | Path]]
        | tuple[tuple[OriginalAssetData, str | Path], ...],
    ) -> dict[Path, tuple[bytes, ...] | None]:
        candidate_cache: dict[Path, tuple[bytes, ...] | None] = {}
        for _, candidate_path in candidates:
            path = Path(candidate_path)
            if path in candidate_cache:
                continue
            if not path.is_file():
                candidate_cache[path] = None
                continue
            try:
                candidate_cache[path] = self._candidate_fingerprints_path(path)
            except (OSError, ValueError):
                candidate_cache[path] = None
        return candidate_cache

    def rank_panels(
        self,
        *,
        panels: list[VisualPanelRequest] | tuple[VisualPanelRequest, ...],
        candidates: list[tuple[OriginalAssetData, str | Path]]
        | tuple[tuple[OriginalAssetData, str | Path], ...],
        limit: int = 5,
    ) -> dict[str, tuple[VisualAssetCandidateScore, ...]]:
        """Batch Top-K retrieval with the same caches/native scoring as matching."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        candidate_cache = self._candidate_cache(candidates)
        score_index = self._build_batch_score_index(candidates, candidate_cache)
        batch_documents: dict[tuple[int, str], pymupdf.Document] = {}
        candidate_token = _BATCH_CANDIDATE_FINGERPRINTS.set(candidate_cache)
        document_token = _BATCH_PDF_DOCUMENTS.set(batch_documents)
        score_token = _BATCH_SCORE_INDEX.set(score_index)
        try:
            return {
                panel.panel_id: self.rank_panel_candidates(
                    pdf_path=panel.pdf_path,
                    physical_page=panel.physical_page,
                    bbox=panel.bbox,
                    candidates=candidates,
                    limit=limit,
                )
                for panel in panels
            }
        finally:
            for doc in batch_documents.values():
                doc.close()
            _BATCH_SCORE_INDEX.reset(score_token)
            _BATCH_PDF_DOCUMENTS.reset(document_token)
            _BATCH_CANDIDATE_FINGERPRINTS.reset(candidate_token)

    def match_panels(
        self,
        *,
        panels: list[VisualPanelRequest] | tuple[VisualPanelRequest, ...],
        candidates: list[tuple[OriginalAssetData, str | Path]] | tuple[tuple[OriginalAssetData, str | Path], ...],
    ) -> dict[str, VisualAssetMatch]:
        candidate_cache = self._candidate_cache(candidates)
        score_index = self._build_batch_score_index(candidates, candidate_cache)
        batch_documents: dict[tuple[int, str], pymupdf.Document] = {}
        candidate_token = _BATCH_CANDIDATE_FINGERPRINTS.set(candidate_cache)
        document_token = _BATCH_PDF_DOCUMENTS.set(batch_documents)
        score_token = _BATCH_SCORE_INDEX.set(score_index)
        try:
            local_matches: dict[str, tuple[VisualAssetMatch, str]] = {}
            for panel in panels:
                match = self.match_panel(
                    pdf_path=panel.pdf_path,
                    physical_page=panel.physical_page,
                    bbox=panel.bbox,
                    candidates=candidates,
                )
                if match is not None:
                    local_matches[panel.panel_id] = (
                        match,
                        self._pdf_identity(panel.pdf_path),
                    )
        finally:
            for doc in batch_documents.values():
                doc.close()
            _BATCH_SCORE_INDEX.reset(score_token)
            _BATCH_PDF_DOCUMENTS.reset(document_token)
            _BATCH_CANDIDATE_FINGERPRINTS.reset(candidate_token)

        source_counts = Counter(
            (pdf_identity, match.source_asset_id)
            for match, pdf_identity in local_matches.values()
        )
        return {
            panel_id: match
            for panel_id, (match, pdf_identity) in local_matches.items()
            if source_counts[(pdf_identity, match.source_asset_id)] == 1
        }
