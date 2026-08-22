from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

from app.domain.adobe_manifest import AdobeManifestV1, Bounds, ManifestTextFrame
from app.domain.canonical_models import DrawingData, PlateData, PlatePanelData
from app.domain.source_assets import OriginalAssetData


_PLATE_IDENTIFIER = re.compile(r"【\s*도판\s*(\d+(?:-\d+)?)\s*】")
_DRAWING_IDENTIFIER = re.compile(r"【\s*도면\s*(\d+(?:-\d+)?)\s*】")
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CIRCLED_INDEX = {char: index + 1 for index, char in enumerate(_CIRCLED)}


class CanonicalizationError(ValueError):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True, slots=True)
class CanonicalizationResult:
    plates: list[PlateData] = field(default_factory=list)
    drawings: list[DrawingData] = field(default_factory=list)


def _normalized_path(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\\", "/").lstrip("./"))


def _identifier_matches(pattern: re.Pattern[str], frames: tuple[ManifestTextFrame, ...]):
    matches: list[tuple[str, str, ManifestTextFrame]] = []
    for frame in frames:
        for match in pattern.finditer(frame.text):
            matches.append((match.group(1), match.group(0), frame))
    return matches


def _clean_title(text: str, raw_identifier: str) -> str:
    cleaned = text.replace(raw_identifier, " ")
    return re.sub(r"\s+", " ", cleaned).strip(" \t\r\n-–—:：/")


def _center(bounds: Bounds | None) -> tuple[float, float] | None:
    if bounds is None:
        return None
    return ((bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0)


def _contains(bounds: Bounds | None, point: tuple[float, float] | None) -> bool:
    if bounds is None or point is None:
        return False
    x0, y0, x1, y1 = bounds
    px, py = point
    return min(x0, x1) <= px <= max(x0, x1) and min(y0, y1) <= py <= max(y0, y1)


def _panel_marker(frame: ManifestTextFrame) -> tuple[int, str] | None:
    stripped = frame.text.strip()
    if not stripped or stripped[0] not in _CIRCLED_INDEX:
        return None
    index = _CIRCLED_INDEX[stripped[0]]
    caption = stripped[1:].strip(" \t\r\n-–—:：/")
    return index, caption


class ReferenceCanonicalizer:
    """Convert Adobe DOM facts into corpus-scoped canonical visual identity.

    Publication identity is read only from explicit internal text-frame
    identifiers. OriginalAsset filenames are never inspected for a plate or
    drawing number. InDesign link paths are used only to prove placed-source
    provenance after identity has already been established from DOM text.
    """

    version = "reference-canonicalizer-v1"

    def canonicalize(
        self,
        corpus_id: str,
        manifests: list[AdobeManifestV1] | tuple[AdobeManifestV1, ...],
        assets: list[OriginalAssetData] | tuple[OriginalAssetData, ...],
    ) -> CanonicalizationResult:
        assets_by_path: dict[str, OriginalAssetData] = {}
        for asset in assets:
            assets_by_path[_normalized_path(asset.relative_path)] = asset

        plates: list[PlateData] = []
        drawings: list[DrawingData] = []
        seen_plates: set[str] = set()
        seen_drawings: set[str] = set()

        for manifest in manifests:
            if manifest.application == "indesign":
                for page in manifest.pages:
                    matches = _identifier_matches(_PLATE_IDENTIFIER, page.text_frames)
                    numbers = {number for number, _raw, _frame in matches}
                    if not numbers:
                        continue
                    if len(numbers) != 1:
                        raise CanonicalizationError(
                            "AMBIGUOUS_IDENTIFIER",
                            f"InDesign page {page.index} contains multiple plate identifiers",
                        )
                    number = next(iter(numbers))
                    if number in seen_plates:
                        raise CanonicalizationError(
                            "DUPLICATE_CANONICAL_IDENTIFIER",
                            f"Plate {number} occurs more than once in one corpus",
                        )
                    seen_plates.add(number)
                    raw_identifier = next(raw for value, raw, _frame in matches if value == number)
                    header_frame = next(frame for value, _raw, frame in matches if value == number)
                    title = _clean_title(header_frame.text, raw_identifier)
                    panels: list[PlatePanelData] = []
                    seen_panel_indices: set[int] = set()
                    for frame in page.text_frames:
                        marker = _panel_marker(frame)
                        if marker is None:
                            continue
                        panel_index, caption = marker
                        if panel_index in seen_panel_indices:
                            raise CanonicalizationError(
                                "AMBIGUOUS_IDENTIFIER",
                                f"Plate {number} contains duplicate panel marker {panel_index}",
                            )
                        point = _center(frame.bounds)
                        graphics = [graphic for graphic in page.graphics if _contains(graphic.bounds, point)]
                        if len(graphics) != 1:
                            continue
                        graphic = graphics[0]
                        if not graphic.link_path:
                            raise CanonicalizationError(
                                "PROVENANCE_INCOMPLETE",
                                f"Plate {number} panel {panel_index} has no InDesign Link path",
                            )
                        asset = assets_by_path.get(_normalized_path(graphic.link_path))
                        if asset is None:
                            raise CanonicalizationError(
                                "LINK_MISSING",
                                f"InDesign Link '{graphic.link_path}' is not a staged OriginalAsset",
                            )
                        seen_panel_indices.add(panel_index)
                        panels.append(
                            PlatePanelData(
                                panel_id=f"plate-panel:{corpus_id}:{number}:{panel_index}",
                                plate_id=f"plate:{corpus_id}:{number}",
                                panel_index=panel_index,
                                caption=caption,
                                bbox=graphic.bounds,
                                bbox_status="placed_source",
                                physical_page=page.index + 1,
                                source_sha256=asset.sha256,
                                source_asset_id=asset.id,
                            )
                        )
                    panels.sort(key=lambda item: item.panel_index)
                    plates.append(
                        PlateData(
                            plate_id=f"plate:{corpus_id}:{number}",
                            number=number,
                            physical_page=page.index + 1,
                            title=title,
                            source_sha256=manifest.source_sha256,
                            panels=panels,
                            raw_identifier=raw_identifier,
                            source_kind="indesign_source",
                            reference_corpus_id=corpus_id,
                        )
                    )

            elif manifest.application == "illustrator":
                for artboard in manifest.artboards:
                    matches = _identifier_matches(_DRAWING_IDENTIFIER, artboard.text_frames)
                    numbers = {number for number, _raw, _frame in matches}
                    if not numbers:
                        continue
                    if len(numbers) != 1:
                        raise CanonicalizationError(
                            "AMBIGUOUS_IDENTIFIER",
                            f"Illustrator artboard {artboard.index} contains multiple drawing identifiers",
                        )
                    number = next(iter(numbers))
                    if number in seen_drawings:
                        raise CanonicalizationError(
                            "DUPLICATE_CANONICAL_IDENTIFIER",
                            f"Drawing {number} occurs more than once in one corpus",
                        )
                    seen_drawings.add(number)
                    raw_identifier = next(raw for value, raw, _frame in matches if value == number)
                    header_frame = next(frame for value, _raw, frame in matches if value == number)
                    drawings.append(
                        DrawingData(
                            drawing_id=f"drawing:{corpus_id}:{number}",
                            number=number,
                            physical_page=artboard.index + 1,
                            title=_clean_title(header_frame.text, raw_identifier),
                            source_sha256=manifest.source_sha256,
                            raw_identifier=raw_identifier,
                            source_kind="illustrator_source",
                            reference_corpus_id=corpus_id,
                        )
                    )

        plates.sort(key=lambda item: item.number)
        drawings.sort(key=lambda item: item.number)
        return CanonicalizationResult(plates=plates, drawings=drawings)
