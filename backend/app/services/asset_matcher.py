from dataclasses import dataclass, field
from pathlib import Path
import re
import warnings
from typing import Any, Literal

from app.domain.canonical_models import (
    DrawingData,
    DrawingRegionData,
    PlateData,
    PlatePanelData,
    ReferenceData,
    ResolutionStatus,
)
from app.services.plate_parser import PlateIndex

AssetMatchStatus = Literal["exact", "multiple", "missing", "semantic_review"]

# Circled / parenthesised numeral mapping (①→1, ⑴→1, etc.)
CIRCLED_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CIRCLED_MAP: dict[str, int] = {c: i + 1 for i, c in enumerate(CIRCLED_CHARS)}
PAREN_CHARS = "⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽⑾⑿⒀⒁⒂⒃⒄⒅⒆⒇"
for _i, _c in enumerate(PAREN_CHARS):
    _CIRCLED_MAP[_c] = _i + 1


def _parse_compound_number(raw: str) -> tuple[str, int | None]:
    """Parse a potentially compound reference number into (base_number, sub_index | None).

    Supports:
      '30-1'     -> ('30', 1)
      '30-①'    -> ('30', 1)
      '30 (2)'   -> ('30', 2)
      '85-②'    -> ('85', 2)
      '30'       -> ('30', None)
    """
    raw = raw.strip()

    # 1. Pattern: base-circled (e.g. 30-①)
    for ch, val in _CIRCLED_MAP.items():
        if ch in raw:
            base = raw.split(ch)[0].rstrip("-").rstrip().rstrip("-").strip()
            if base:
                return base, val

    # 2. Pattern: base (N) or base(N) (e.g. 30 (2), 30(2))
    m_paren = re.match(r"^(\d+)\s*\((\d+)\)$", raw)
    if m_paren:
        return m_paren.group(1), int(m_paren.group(2))

    # 3. Pattern: base-N (e.g. 30-1, 85-1)
    m_hyphen = re.match(r"^(\d+)\s*[-–—]\s*(\d+)$", raw)
    if m_hyphen:
        return m_hyphen.group(1), int(m_hyphen.group(2))

    return raw, None


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
    target: PlateData | PlatePanelData | DrawingData | DrawingRegionData | None = None
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

        # Parse compound number (e.g. 85-1, 85-②)
        base_num, sub_idx = _parse_compound_number(ref_num)

        plate = plate_index.get_plate(base_num)
        if plate is None and hasattr(plate_index, "get"):
            plate = plate_index.get(base_num)

        if plate is not None:
            # If sub_idx specified, try to resolve to panel
            if sub_idx is not None and plate.panels:
                panel = None
                if hasattr(plate_index, "get_panel"):
                    panel = plate_index.get_panel(base_num, sub_idx)
                if panel is None:
                    for p in plate.panels:
                        if p.panel_index == sub_idx:
                            panel = p
                            break
                if panel is not None:
                    evidence: list[str] = []
                    if getattr(panel, "caption", None):
                        evidence.append(panel.caption)
                    if getattr(plate, "title", None):
                        evidence.append(plate.title)
                    if not evidence:
                        evidence.append(f"도판 {plate.number}-{sub_idx}")
                    return ResolutionResult(
                        status=ResolutionStatus.RESOLVED,
                        target=panel,
                        identity_source="plate_pdf",
                        identity_evidence=evidence,
                        rationale=f"Canonical resolution from plate {plate.number} panel {sub_idx}",
                    )
                # Panel not found - fall through to resolve to plate itself

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

        # Parse compound number (e.g. 30-1, 30-①, 30 (2))
        base_num, sub_idx = _parse_compound_number(ref_num)

        drawing = None
        if hasattr(drawing_index, "get_drawing"):
            drawing = drawing_index.get_drawing(base_num)
        elif hasattr(drawing_index, "get"):
            drawing = drawing_index.get(base_num)
        elif hasattr(drawing_index, "drawings_by_number"):
            drawing = drawing_index.drawings_by_number.get(base_num)

        if drawing is not None:
            # If sub_idx specified, try to resolve to region
            if sub_idx is not None and drawing.regions:
                region = None
                sub_str = str(sub_idx)
                if hasattr(drawing_index, "get_region"):
                    region = drawing_index.get_region(base_num, sub_str)
                if region is None:
                    for r in drawing.regions:
                        if r.number == sub_str:
                            region = r
                            break
                if region is not None:
                    evidence: list[str] = []
                    if getattr(region, "title", None):
                        evidence.append(region.title)
                    if getattr(drawing, "title", None):
                        evidence.append(drawing.title)
                    if not evidence:
                        evidence.append(f"도면 {drawing.number}-{sub_idx}")
                    return ResolutionResult(
                        status=ResolutionStatus.RESOLVED,
                        target=region,
                        identity_source="drawing_pdf",
                        identity_evidence=evidence,
                        rationale=f"Canonical resolution from drawing {drawing.number} region {sub_idx}",
                    )
                # Region not found - fall back to base drawing
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
                    rationale=f"Canonical resolution from drawing {drawing.number} (region {sub_idx} not indexed, fallback to base drawing)",
                )

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
        """Legacy filename-based matching. DEPRECATED: use resolve_reference() instead."""
        warnings.warn(
            "match_reference is deprecated and quarantined; use resolve_reference() for canonical identity resolution",
            DeprecationWarning,
            stacklevel=2,
        )
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
