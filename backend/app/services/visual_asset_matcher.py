from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps
import pymupdf

from app.domain.source_assets import OriginalAssetData
from app.services.geometric_visual_retriever import GeometricVisualRetriever


@dataclass(frozen=True, slots=True)
class VisualAssetMatch:
    source_asset_id: str
    score: float
    method: str = "pixel_thumbnail_similarity"
    geometric_good_matches: int | None = None
    geometric_inliers: int | None = None
    geometric_inlier_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class RankedVisualCandidate:
    source_asset_id: str
    score: float


@dataclass(frozen=True, slots=True)
class VisualPanelAssessment:
    status: str
    best_score: float | None
    margin: float | None
    candidates: tuple[RankedVisualCandidate, ...]
    match: VisualAssetMatch | None = None


@dataclass(frozen=True, slots=True)
class VisualPanelRequest:
    panel_id: str
    pdf_path: str | Path
    physical_page: int
    bbox: tuple[float, float, float, float]
    uniqueness_scope_id: str | None = None

    @property
    def resolved_uniqueness_scope_id(self) -> str:
        """Return the explicit revision scope, or a stable PDF-path fallback.

        The fallback is used only to scope collision detection. It is never
        visual-match evidence and cannot promote an unresolved panel.
        """

        if self.uniqueness_scope_id:
            return self.uniqueness_scope_id
        return str(Path(self.pdf_path).resolve())

    @property
    def geometry_key(self) -> tuple[str, int, tuple[float, float, float, float]]:
        """Identify one physical panel geometry inside a revision.

        Parser aliases may emit multiple panel IDs for the exact same page and
        bbox. Those aliases represent one physical image placement and must not
        manufacture a source collision. Rounding removes insignificant parser
        float noise while keeping genuinely different geometries distinct.
        """

        return (
            self.resolved_uniqueness_scope_id,
            int(self.physical_page),
            tuple(round(float(value), 9) for value in self.bbox),
        )


class VisualAssetMatcher:
    """Hybrid visual matcher for safely segmented PDF panels.

    Tier 0 keeps the existing conservative pixel-thumbnail contract unchanged:
    score >= ``minimum_score`` and separation >= ``minimum_margin``. When Tier
    0 cannot verify a panel, a bounded shortlist is passed to a SIFT/RANSAC
    geometric verifier that can recover crop, resize and rotation without
    lowering the pixel safety threshold.

    Filename, path, caption and sequence metadata are never verification
    evidence. Batch uniqueness is enforced across distinct physical panel
    geometries within each revision scope; identical parser aliases share one
    geometry and therefore do not manufacture a collision.
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
        geometric_candidate_pool: int = 50,
        geometric_minimum_margin: float = 0.08,
        geometric_retriever: GeometricVisualRetriever | None = None,
    ) -> None:
        if geometric_candidate_pool < 1:
            raise ValueError("geometric_candidate_pool must be at least 1")
        if geometric_minimum_margin < 0.0:
            raise ValueError("geometric_minimum_margin cannot be negative")

        self._minimum_score = float(minimum_score)
        self._minimum_margin = float(minimum_margin)
        self._fingerprint_size = fingerprint_size
        self._geometric_candidate_pool = int(geometric_candidate_pool)
        self._geometric_minimum_margin = float(geometric_minimum_margin)
        self._geometric_retriever = geometric_retriever or GeometricVisualRetriever()

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
        """Return one conservative border-trimmed view, never a replacement."""

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

    def _panel_image(
        self,
        pdf_path: Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
    ) -> Image.Image | None:
        if not pdf_path.is_file():
            return None
        try:
            doc = pymupdf.open(str(pdf_path))
        except (OSError, ValueError):
            return None
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
            best_xrefs = {
                xref
                for score, xref in occurrences
                if abs(score - best_score) < 1e-6
            }
            if len(best_xrefs) != 1:
                return None
            extracted = doc.extract_image(next(iter(best_xrefs)))
            data = extracted.get("image")
            if not data:
                return None
            with Image.open(BytesIO(data)) as image:
                image.load()
                return ImageOps.exif_transpose(image).convert("RGB").copy()
        except (OSError, ValueError):
            return None
        finally:
            doc.close()

    def _panel_fingerprint(
        self,
        pdf_path: Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
    ) -> bytes | None:
        panel_image = self._panel_image(pdf_path, physical_page, bbox)
        if panel_image is None:
            return None
        return self._fingerprint_image(panel_image)

    def _geometric_match(
        self,
        *,
        pdf_path: Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
        candidates: list[tuple[OriginalAssetData, Path]],
    ) -> VisualAssetMatch | None:
        if not candidates:
            return None
        panel_image = self._panel_image(pdf_path, physical_page, bbox)
        if panel_image is None:
            return None
        ranked = self._geometric_retriever.rank(
            panel_image=panel_image,
            candidates=candidates,
            top_k=2,
        )
        if not ranked:
            return None
        best = ranked[0]
        if len(ranked) > 1:
            geometric_margin = best.score - ranked[1].score
            if geometric_margin < self._geometric_minimum_margin:
                return None
        return VisualAssetMatch(
            source_asset_id=best.source_asset_id,
            score=best.score,
            method="sift_ransac",
            geometric_good_matches=best.good_matches,
            geometric_inliers=best.inliers,
            geometric_inlier_ratio=best.inlier_ratio,
        )

    def assess_panel(
        self,
        *,
        pdf_path: str | Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
        candidates: list[tuple[OriginalAssetData, str | Path]] | tuple[tuple[OriginalAssetData, str | Path], ...],
        top_k: int = 5,
    ) -> VisualPanelAssessment:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        resolved_pdf = Path(pdf_path)
        panel_fingerprint = self._panel_fingerprint(resolved_pdf, physical_page, bbox)
        if panel_fingerprint is None:
            return VisualPanelAssessment(
                status="INSUFFICIENT_PANEL",
                best_score=None,
                margin=None,
                candidates=(),
            )

        scored: list[tuple[float, str, OriginalAssetData, Path]] = []
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
            scored.append((score, asset.id, asset, path))

        if not scored:
            return VisualPanelAssessment(
                status="NO_CANDIDATE",
                best_score=None,
                margin=None,
                candidates=(),
            )

        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score, best_id, _, _ = scored[0]
        margin = best_score - scored[1][0] if len(scored) > 1 else None
        ranked = tuple(
            RankedVisualCandidate(source_asset_id=source_asset_id, score=score)
            for score, source_asset_id, _, _ in scored[:top_k]
        )

        pixel_status = "VERIFIED"
        if best_score < self._minimum_score:
            pixel_status = "BELOW_SCORE"
        elif margin is not None and margin < self._minimum_margin:
            pixel_status = "AMBIGUOUS_MARGIN"

        if pixel_status == "VERIFIED":
            match = VisualAssetMatch(source_asset_id=best_id, score=best_score)
            return VisualPanelAssessment(
                status="VERIFIED",
                best_score=best_score,
                margin=margin,
                candidates=ranked,
                match=match,
            )

        geometric_candidates = [
            (asset, path)
            for _, _, asset, path in scored[: self._geometric_candidate_pool]
        ]
        geometric_match = self._geometric_match(
            pdf_path=resolved_pdf,
            physical_page=physical_page,
            bbox=bbox,
            candidates=geometric_candidates,
        )
        if geometric_match is not None:
            return VisualPanelAssessment(
                status="VERIFIED",
                best_score=best_score,
                margin=margin,
                candidates=ranked,
                match=geometric_match,
            )

        return VisualPanelAssessment(
            status=pixel_status,
            best_score=best_score,
            margin=margin,
            candidates=ranked,
        )

    def match_panel(
        self,
        *,
        pdf_path: str | Path,
        physical_page: int,
        bbox: tuple[float, float, float, float],
        candidates: list[tuple[OriginalAssetData, str | Path]] | tuple[tuple[OriginalAssetData, str | Path], ...],
    ) -> VisualAssetMatch | None:
        return self.assess_panel(
            pdf_path=pdf_path,
            physical_page=physical_page,
            bbox=bbox,
            candidates=candidates,
        ).match

    def match_panels(
        self,
        *,
        panels: list[VisualPanelRequest] | tuple[VisualPanelRequest, ...],
        candidates: list[tuple[OriginalAssetData, str | Path]] | tuple[tuple[OriginalAssetData, str | Path], ...],
    ) -> dict[str, VisualAssetMatch]:
        local_matches: dict[str, VisualAssetMatch] = {}
        request_by_panel = {panel.panel_id: panel for panel in panels}
        for panel in panels:
            match = self.match_panel(
                pdf_path=panel.pdf_path,
                physical_page=panel.physical_page,
                bbox=panel.bbox,
                candidates=candidates,
            )
            if match is not None:
                local_matches[panel.panel_id] = match

        geometries_by_source: dict[
            tuple[str, str],
            set[tuple[str, int, tuple[float, float, float, float]]],
        ] = defaultdict(set)
        for panel_id, match in local_matches.items():
            panel = request_by_panel[panel_id]
            geometries_by_source[
                (panel.resolved_uniqueness_scope_id, match.source_asset_id)
            ].add(panel.geometry_key)

        return {
            panel_id: match
            for panel_id, match in local_matches.items()
            if len(
                geometries_by_source[
                    (
                        request_by_panel[panel_id].resolved_uniqueness_scope_id,
                        match.source_asset_id,
                    )
                ]
            )
            == 1
        }
