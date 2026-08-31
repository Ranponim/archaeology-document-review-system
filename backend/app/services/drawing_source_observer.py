from __future__ import annotations

from pathlib import Path
from typing import Callable

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    import fitz as pymupdf  # type: ignore

from app.domain.drawing_evidence import DrawingSourceObservation
from app.services.drawing_parser import DrawingParser


class DrawingSourceObserver:
    """Extract Adobe-free text/identity observations from PDF-compatible AI."""

    def __init__(self, text_extractor: Callable[[Path], str] | None = None) -> None:
        self._text_extractor = text_extractor or self._extract_pdf_text

    @staticmethod
    def _extract_pdf_text(path: Path) -> str:
        document = pymupdf.open(str(path))
        try:
            return "\n".join(page.get_text("text") or "" for page in document)
        finally:
            document.close()

    @staticmethod
    def _internal_numbers(text: str) -> tuple[str, ...]:
        numbers: set[str] = set()
        for match in DrawingParser.IDENTIFIER_PATTERN.finditer(text or ""):
            number = next(
                (group for group in match.groups()[1:] if group is not None),
                None,
            )
            if number:
                numbers.add(str(number))
        return tuple(sorted(numbers))

    def observe(self, asset, source_path: str | Path) -> DrawingSourceObservation:
        path = Path(source_path)
        text = self._text_extractor(path)
        return DrawingSourceObservation(
            source_asset_id=str(asset.id),
            source_sha256=str(asset.sha256),
            original_name=str(asset.original_name or path.name),
            raw_text=text,
            internal_numbers=self._internal_numbers(text),
        )
