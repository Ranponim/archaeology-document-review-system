from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Literal

AssetMatchStatus = Literal["exact", "multiple", "missing", "semantic_review"]


@dataclass(frozen=True, slots=True)
class MatchedAssetResult:
    ref_type: Literal["drawing", "plate", "photo"]
    number: str
    status: AssetMatchStatus
    matched_path: Path | None
    candidate_paths: list[Path] = field(default_factory=list)
    rationale: str = ""


class AssetMatcher:
    def __init__(
        self,
        drawings_dir: Path,
        plates_dir: Path,
        env_dir: Path | None = None,
    ) -> None:
        self.drawings_dir = Path(drawings_dir)
        self.plates_dir = Path(plates_dir)
        self.env_dir = Path(env_dir) if env_dir else None

        self._drawing_files: list[Path] = []
        self._plate_files: list[Path] = []
        self._index_assets()

    def _index_assets(self) -> None:
        drawing_files_set: set[Path] = set()
        if self.drawings_dir.is_dir():
            drawing_files_set.update(self.drawings_dir.glob("**/*.ai"))
            drawing_files_set.update(self.drawings_dir.glob("**/*.AI"))
        if self.env_dir and self.env_dir.is_dir():
            drawing_files_set.update(self.env_dir.glob("**/*.ai"))
            drawing_files_set.update(self.env_dir.glob("**/*.AI"))
        self._drawing_files = sorted(drawing_files_set)

        if self.plates_dir.is_dir():
            plate_files_set: set[Path] = set()
            plate_files_set.update(self.plates_dir.glob("**/*.jpg"))
            plate_files_set.update(self.plates_dir.glob("**/*.JPG"))
            plate_files_set.update(self.plates_dir.glob("**/*.png"))
            plate_files_set.update(self.plates_dir.glob("**/*.PNG"))
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
            r"도면\s*:\s*(?:,|\)|\]|\s*$)",
            r"도판\s*:\s*(?:,|\)|\]|\s*$)",
            r"【\s*도면\s*】",
            r"【\s*도판\s*】",
            r"\(\s*도면\s*[:\s]*,\s*도판\s*[:\s]*\)",
            r"\(\s*도면\s*[:\s]*\)",
            r"\(\s*도판\s*[:\s]*\)",
            r"\(도면\s*,\s*도판\s*\)",
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
            if "【도면  】" in f.name or "【도면 】" in f.name or "【도판  】" in f.name or "【도판 】" in f.name:
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
                rf"【\s*도면\s*0*{re.escape(num_str)}\s*】",
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
                rf"【\s*도판\s*0*{re.escape(num_str)}\s*】",
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
