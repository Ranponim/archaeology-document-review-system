from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Literal

from app.domain.canonical_models import (
    DrawingData,
    PlateData,
    ReferenceData,
    ResolutionStatus,
)
from app.services.plate_parser import PlateIndex

AssetMatchStatus = Literal["exact", "multiple", "missing", "semantic_review"]


@dataclass(frozen=True, slots=True)
class MatchedAssetResult:
    ref_type: Literal["drawing", "plate", "photo"]
    number: str
    status: AssetMatchStatus
    matched_path: Path | None
    candidate_paths: list[Path] = field(default_factory=list)
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    status: ResolutionStatus
    target: PlateData | DrawingData | None = None
    identity_source: str = ""
    identity_evidence: list[str] = field(default_factory=list)
    rationale: str = ""


def resolve_reference(
    reference: ReferenceData,
    plate_index: PlateIndex | None = None,
    drawing_index: Any | None = None,
) -> ResolutionResult:
    """Resolve a publication reference canonically without numeric filename fallback.

    Invariants:
    1. Plate references are resolved solely against canonical explicit publication identifiers (PlateIndex).
    2. Drawing references are resolved solely against canonical drawing index.
    3. Filenames on disk (e.g. '4. 조사 후_45.JPG' or '_91.JPG') are NEVER used to infer canonical identity.
    4. Missing or unindexed references return ResolutionStatus.MISSING or UNRESOLVED with target=None.
    """
    ref_type = str(reference.ref_type).strip().lower()
    ref_num = str(reference.number).strip()

    if not ref_num:
        return ResolutionResult(
            status=ResolutionStatus.UNRESOLVED,
            target=None,
            identity_source="unresolved",
            identity_evidence=[],
            rationale="Reference has empty number",
        )

    if ref_type in ("plate", "도판"):
        if plate_index is None:
            return ResolutionResult(
                status=ResolutionStatus.UNRESOLVED,
                target=None,
                identity_source="unresolved",
                identity_evidence=[],
                rationale=f"No canonical PlateIndex provided to resolve plate '{ref_num}'",
            )

        plate = plate_index.get_plate(ref_num)
        if plate is None and hasattr(plate_index, "get"):
            plate = plate_index.get(ref_num)

        if plate is not None:
            evidence: list[str] = []
            if getattr(plate, "raw_identifier", None):
                evidence.append(plate.raw_identifier)
            if getattr(plate, "title", None):
                evidence.append(plate.title)
            if not evidence:
                evidence.append(f"도판 {plate.number}")

            return ResolutionResult(
                status=ResolutionStatus.RESOLVED,
                target=plate,
                identity_source="plate_pdf",
                identity_evidence=evidence,
                rationale=f"Canonical resolution from explicit publication identifier {plate.raw_identifier or plate.number}",
            )
        else:
            return ResolutionResult(
                status=ResolutionStatus.MISSING,
                target=None,
                identity_source="plate_pdf",
                identity_evidence=[],
                rationale=f"Plate '{ref_num}' not found in canonical plate index",
            )

    elif ref_type in ("drawing", "도면"):
        if drawing_index is None:
            return ResolutionResult(
                status=ResolutionStatus.UNRESOLVED,
                target=None,
                identity_source="unresolved",
                identity_evidence=[],
                rationale=f"No canonical DrawingIndex provided to resolve drawing '{ref_num}'",
            )

        drawing = None
        if hasattr(drawing_index, "get_drawing"):
            drawing = drawing_index.get_drawing(ref_num)
        elif hasattr(drawing_index, "get"):
            drawing = drawing_index.get(ref_num)
        elif hasattr(drawing_index, "drawings_by_number"):
            drawing = drawing_index.drawings_by_number.get(ref_num)

        if drawing is not None:
            evidence: list[str] = []
            if getattr(drawing, "raw_identifier", None):
                evidence.append(drawing.raw_identifier)
            if getattr(drawing, "title", None):
                evidence.append(drawing.title)
            if not evidence:
                evidence.append(f"도면 {drawing.number}")

            return ResolutionResult(
                status=ResolutionStatus.RESOLVED,
                target=drawing,
                identity_source="drawing_pdf",
                identity_evidence=evidence,
                rationale=f"Canonical resolution from explicit drawing index {drawing.raw_identifier or drawing.number}",
            )
        else:
            return ResolutionResult(
                status=ResolutionStatus.MISSING,
                target=None,
                identity_source="drawing_pdf",
                identity_evidence=[],
                rationale=f"Drawing '{ref_num}' not found in canonical drawing index",
            )

    return ResolutionResult(
        status=ResolutionStatus.UNRESOLVED,
        target=None,
        identity_source="unresolved",
        identity_evidence=[],
        rationale=f"Unknown or unsupported reference type: '{reference.ref_type}'",
    )


class AssetMatcher:
    DRAWING_EXTENSIONS: tuple[str, ...] = (
        "*.ai", "*.AI", "*.eps", "*.EPS", "*.pdf", "*.PDF", "*.dwg", "*.DWG", "*.dxf", "*.DXF"
    )
    PLATE_EXTENSIONS: tuple[str, ...] = (
        "*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.png", "*.PNG", "*.tiff", "*.TIFF", "*.webp", "*.WEBP"
    )

    def __init__(
        self,
        drawings_dir: Path | str | None = None,
        plates_dir: Path | str | None = None,
        env_dir: Path | str | None = None,
        plate_index: PlateIndex | None = None,
        drawing_index: Any | None = None,
    ) -> None:
        self.drawings_dir = Path(drawings_dir) if drawings_dir else Path("")
        self.plates_dir = Path(plates_dir) if plates_dir else Path("")
        self.env_dir = Path(env_dir) if env_dir else None
        self.plate_index = plate_index
        self.drawing_index = drawing_index

        self._drawing_files: list[Path] = []
        self._plate_files: list[Path] = []
        self._index_assets()

    def resolve_reference(
        self,
        reference: ReferenceData,
        plate_index: PlateIndex | None = None,
        drawing_index: Any | None = None,
    ) -> ResolutionResult:
        p_idx = plate_index if plate_index is not None else self.plate_index
        d_idx = drawing_index if drawing_index is not None else self.drawing_index
        return resolve_reference(reference=reference, plate_index=p_idx, drawing_index=d_idx)

    def _index_assets(self) -> None:
        drawing_files_set: set[Path] = set()
        if self.drawings_dir.is_dir():
            for pat in self.DRAWING_EXTENSIONS:
                drawing_files_set.update(self.drawings_dir.glob(f"**/{pat}"))
        if self.env_dir and self.env_dir.is_dir():
            for pat in self.DRAWING_EXTENSIONS:
                drawing_files_set.update(self.env_dir.glob(f"**/{pat}"))
        self._drawing_files = sorted(drawing_files_set)

        if self.plates_dir.is_dir():
            plate_files_set: set[Path] = set()
            for pat in self.PLATE_EXTENSIONS:
                plate_files_set.update(self.plates_dir.glob(f"**/{pat}"))
            self._plate_files = sorted(plate_files_set)

    def get_index_summary(self) -> dict[str, int]:
        return {
            "drawing_files_count": len(self._drawing_files),
            "plate_files_count": len(self._plate_files),
        }

    @staticmethod
    def _is_blank_caption_text(text: str) -> bool:
        if not text:
            return False
        patterns = [
            r"(?:도면|도판)\s*:\s*(?:[,/\]\)>〉》]|(?=도면|도판)|\s*$)",
            r"[【\[\(<〈《]\s*(?:도면|도판)(?:\s*[:\s]*[,/]\s*(?:도면|도판))?\s*[:\s]*[】\]\)>〉》]",
        ]
        for pat in patterns:
            if re.search(pat, text):
                return True
        return False

    def _context_has_blank_caption(self, context: dict[str, Any]) -> bool:
        for val in context.values():
            if isinstance(val, str) and self._is_blank_caption_text(val):
                return True
            elif isinstance(val, dict) and self._context_has_blank_caption(val):
                return True
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and self._is_blank_caption_text(item):
                        return True
        return False

    def _has_blank_caption(self, context: dict[str, Any], candidates: list[Path]) -> bool:
        if self._context_has_blank_caption(context):
            return True
        for f in candidates:
            if self._is_blank_caption_text(f.name):
                return True
        return False

    def _match_drawing_files(
        self,
        num_str: str,
        context: dict[str, Any],
    ) -> list[Path]:
        site = (
            context.get("site_point")
            or context.get("site")
            or context.get("location")
            or ""
        )
        feature = (
            context.get("feature")
            or context.get("structure")
            or ""
        )

        candidates: list[Path] = []
        if num_str:
            drawing_prefix_pat = re.compile(
                rf"(?:도면|drawing)[_\s\-\.]*0*{re.escape(num_str)}(?!\d)",
                re.IGNORECASE,
            )
            bracket_pat = re.compile(
                rf"[【\[\(<〈《]\s*도면\s*0*{re.escape(num_str)}\s*[】\]\)>〉》]",
                re.IGNORECASE,
            )
            exact_matches = [
                f for f in self._drawing_files
                if drawing_prefix_pat.search(f.name) or bracket_pat.search(f.name)
            ]
            if exact_matches:
                candidates = exact_matches
            else:
                stem_num_pat = re.compile(
                    rf"(?<!\d)0*{re.escape(num_str)}(?!\d)",
                    re.IGNORECASE,
                )
                candidates = [
                    f for f in self._drawing_files
                    if stem_num_pat.search(f.stem)
                ]

        # Context fallback if no candidate matched by number
        if not candidates and (site or feature):
            candidates = [
                f for f in self._drawing_files
                if (not site or site in str(f)) and (not feature or feature in f.name)
            ]

        # Context narrowing if candidates were found
        if candidates and site:
            site_candidates = [f for f in candidates if site in str(f)]
            if site_candidates:
                candidates = site_candidates

        if candidates and feature:
            feature_candidates = [f for f in candidates if feature in f.name]
            if feature_candidates:
                candidates = feature_candidates

        return candidates

    def _match_plate_files(
        self,
        num_str: str,
        context: dict[str, Any],
    ) -> list[Path]:
        site = (
            context.get("site_point")
            or context.get("site")
            or context.get("location")
            or ""
        )
        feature = (
            context.get("feature")
            or context.get("structure")
            or ""
        )

        candidates: list[Path] = []
        if num_str:
            plate_prefix_pat = re.compile(
                rf"(?:도판|plate|photo)[_\s\-\.]*0*{re.escape(num_str)}(?!\d)",
                re.IGNORECASE,
            )
            bracket_pat = re.compile(
                rf"[【\[\(<〈《]\s*도판\s*0*{re.escape(num_str)}\s*[】\]\)>〉》]",
                re.IGNORECASE,
            )
            exact_matches = [
                f for f in self._plate_files
                if plate_prefix_pat.search(f.name) or bracket_pat.search(f.name)
            ]
            if exact_matches:
                candidates = exact_matches
            else:
                num_pat = re.compile(
                    rf"(?<!\d)0*{re.escape(num_str)}(?!\d)",
                    re.IGNORECASE,
                )
                candidates = [
                    f for f in self._plate_files
                    if num_pat.search(f.stem)
                ]

        # Context fallback if no candidate matched by number
        if not candidates and (site or feature):
            candidates = [
                f for f in self._plate_files
                if (not site or site in str(f)) and (not feature or feature in f.name)
            ]

        # Context narrowing if candidates were found
        if candidates and site:
            site_candidates = [f for f in candidates if site in str(f)]
            if site_candidates:
                candidates = site_candidates

        if candidates and feature:
            feature_candidates = [f for f in candidates if feature in f.name]
            if feature_candidates:
                candidates = feature_candidates

        return candidates

    def match_reference(
        self,
        ref_type: Literal["drawing", "plate", "photo"],
        number: str,
        context: dict[str, Any] | None = None,
    ) -> MatchedAssetResult:
        ctx = context or {}
        num_str = str(number).strip() if number is not None else ""

        if ref_type == "drawing":
            candidates = self._match_drawing_files(num_str, ctx)
        elif ref_type in ["plate", "photo"]:
            candidates = self._match_plate_files(num_str, ctx)
        else:
            return MatchedAssetResult(
                ref_type=ref_type,
                number=num_str,
                status="missing",
                matched_path=None,
                candidate_paths=[],
                rationale=f"Unknown reference type: {ref_type}",
            )

        if not candidates:
            return MatchedAssetResult(
                ref_type=ref_type,
                number=num_str,
                status="missing",
                matched_path=None,
                candidate_paths=[],
                rationale=f"No asset file found matching {ref_type} reference '{num_str}'",
            )

        has_blank_caption = self._has_blank_caption(ctx, candidates)
        if has_blank_caption:
            return MatchedAssetResult(
                ref_type=ref_type,
                number=num_str,
                status="semantic_review",
                matched_path=candidates[0] if candidates else None,
                candidate_paths=candidates,
                rationale="Reference context or candidate file contains blank captions/placeholders; requires visual review",
            )

        if len(candidates) == 1:
            return MatchedAssetResult(
                ref_type=ref_type,
                number=num_str,
                status="exact",
                matched_path=candidates[0],
                candidate_paths=candidates,
                rationale=f"Single exact match: {candidates[0].name}",
            )

        return MatchedAssetResult(
            ref_type=ref_type,
            number=num_str,
            status="multiple",
            matched_path=None,
            candidate_paths=candidates,
            rationale=f"Found {len(candidates)} candidate files matching {ref_type} reference '{num_str}'",
        )
