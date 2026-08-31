from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re

from app.domain.canonical_models import (
    DrawingData,
    DrawingRegionData,
    EvidenceLevel,
)
from app.domain.source_assets import OriginalAssetData
from app.services.drawing_parser import DrawingParser


_FILENAME_IDENTIFIER = re.compile(r"(?:도면|삽도)\s*(\d+(?:-\d+)?)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class DrawingIdentityResolution:
    drawings: tuple[DrawingData, ...] = ()
    unresolved_source_ids: tuple[str, ...] = ()


class DrawingIdentityResolver:
    """Resolve publication drawing identity from PDF-compatible AI without Adobe.

    Explicit identifiers embedded in the PDF-compatible AI are direct evidence.
    A unique identifier in the basename is retained only as heuristic evidence;
    it is never promoted to direct identity. Sources with neither are left
    unresolved rather than assigned a guessed number.
    """

    def __init__(self, parser: DrawingParser | None = None) -> None:
        self._parser = parser or DrawingParser()

    @staticmethod
    def _region_for_corpus(
        corpus_id: str,
        drawing_number: str,
        source_asset_id: str,
        source_sha256: str,
        region: DrawingRegionData,
    ) -> DrawingRegionData:
        return replace(
            region,
            region_id=f"drawing-region:{corpus_id}:{drawing_number}:{region.number}",
            drawing_id=f"drawing:{corpus_id}:{drawing_number}",
            source_sha256=source_sha256,
            source_asset_id=source_asset_id,
            evidence_level=EvidenceLevel.DIRECT,
            evidence_method="pdf_internal_identifier",
        )

    def _direct_drawings(
        self,
        corpus_id: str,
        asset: OriginalAssetData,
        source_path: Path,
    ) -> tuple[DrawingData, ...]:
        parsed = self._parser.parse(source_path).drawings
        resolved: list[DrawingData] = []
        for drawing in parsed:
            regions = [
                self._region_for_corpus(
                    corpus_id,
                    drawing.number,
                    asset.id,
                    asset.sha256,
                    region,
                )
                for region in drawing.regions
            ]
            resolved.append(
                replace(
                    drawing,
                    drawing_id=f"drawing:{corpus_id}:{drawing.number}",
                    source_sha256=asset.sha256,
                    document_version_id=None,
                    regions=regions,
                    source_kind="drawing_ai",
                    reference_corpus_id=corpus_id,
                    source_asset_id=asset.id,
                    evidence_level=EvidenceLevel.DIRECT,
                    evidence_method="pdf_internal_identifier",
                )
            )
        return tuple(resolved)

    @staticmethod
    def _filename_number(name: str) -> tuple[str, str] | None:
        matches = list(_FILENAME_IDENTIFIER.finditer(Path(name).stem))
        numbers = {match.group(1) for match in matches}
        if len(numbers) != 1:
            return None
        number = next(iter(numbers))
        raw = next(match.group(0) for match in matches if match.group(1) == number)
        return number, raw

    def resolve(
        self,
        *,
        corpus_id: str,
        asset: OriginalAssetData,
        source_path: str | Path,
    ) -> DrawingIdentityResolution:
        path = Path(source_path)
        direct = self._direct_drawings(corpus_id, asset, path)
        if direct:
            return DrawingIdentityResolution(drawings=direct)

        filename_identity = self._filename_number(asset.original_name or path.name)
        if filename_identity is None:
            return DrawingIdentityResolution(unresolved_source_ids=(asset.id,))

        number, raw_identifier = filename_identity
        return DrawingIdentityResolution(
            drawings=(
                DrawingData(
                    drawing_id=f"drawing:{corpus_id}:{number}",
                    number=number,
                    physical_page=1,
                    source_sha256=asset.sha256,
                    raw_identifier=raw_identifier,
                    source_kind="drawing_ai",
                    reference_corpus_id=corpus_id,
                    source_asset_id=asset.id,
                    evidence_level=EvidenceLevel.HEURISTIC,
                    evidence_method="filename_identifier",
                ),
            )
        )
