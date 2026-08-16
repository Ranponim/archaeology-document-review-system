from __future__ import annotations

from dataclasses import dataclass, field
import difflib
import re
from typing import Any, Literal

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    PlateData,
    ReferenceData,
)
from app.domain.document_structure import ParsedPage
from app.domain.review_models import (
    ChangeType,
    CorrectionCandidateData,
    EvidenceData,
    ReviewStatus,
    RuleCategory,
    RuleCheckResult,
)
from app.services.object_resolver import (
    ARCHAEOLOGICAL_TYPES,
    PERIOD_NORMALIZATION,
    ObjectResolver,
)
from app.services.page_aligner import AlignedPageRow
from app.services.plate_parser import PlateIndex


@dataclass(frozen=True, slots=True)
class NormalizedDimension:
    raw_text: str
    numeric_value: float
    unit: str | None
    base_unit: str | None
    normalized_value: float
    dimension_type: str = ""


LENGTH_CONVERSIONS_TO_CM: dict[str, float] = {
    "m": 100.0,
    "meter": 100.0,
    "meters": 100.0,
    "미터": 100.0,
    "cm": 1.0,
    "centimeter": 1.0,
    "centimeters": 1.0,
    "센티미터": 1.0,
    "센치": 1.0,
    "센치미터": 1.0,
    "mm": 0.1,
    "millimeter": 0.1,
    "millimeters": 0.1,
    "밀리미터": 0.1,
    "밀리": 0.1,
    "km": 100000.0,
}

WEIGHT_CONVERSIONS_TO_G: dict[str, float] = {
    "kg": 1000.0,
    "kilogram": 1000.0,
    "kilograms": 1000.0,
    "킬로그램": 1000.0,
    "킬로": 1000.0,
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "그램": 1.0,
    "mg": 0.001,
    "milligram": 0.001,
    "milligrams": 0.001,
    "밀리그램": 0.001,
}

DIMENSION_TYPE_CANONICAL: dict[str, str] = {
    "장축": "길이",
    "잔존길이": "길이",
    "길이": "길이",
    "length": "길이",
    "단축": "너비",
    "폭": "너비",
    "잔존너비": "너비",
    "너비": "너비",
    "width": "너비",
    "잔존깊이": "깊이",
    "깊이": "깊이",
    "depth": "깊이",
    "잔존높이": "높이",
    "신고": "높이",
    "기고": "높이",
    "높이": "높이",
    "height": "높이",
    "두께": "두께",
    "thickness": "두께",
    "중량": "무게",
    "무게": "무게",
    "weight": "무게",
    "구경": "구경",
    "저경": "저경",
    "동경": "동경",
    "최대경": "최대경",
    "직경": "직경",
}


class RuleEngine:
    DEFAULT_HEADER_PATTERNS: list[str] = [
        r"^(?:\d+\s*\|\s*(?:백제문화유산연구원|문화유적\s*보고서)|(?:백제문화유산연구원|문화유적\s*보고서)\s*\|\s*\d+)$",
        r"^(?:\d+\s*\|\s*.*(?:연구원|보고서|학술조사|문화재|문화유산|발굴조사|지표조사|시굴조사).*|.*(?:연구원|보고서|학술조사|문화재|문화유산|발굴조사|지표조사|시굴조사).*\s*\|\s*\d+)$",
        r"^(?:백제문화유산연구원|문화유적\s*보고서)$",
        r"^(?:연구원|보고서|학술조사|문화재|문화유산|발굴조사|지표조사|시굴조사)$",
    ]

    FEATURE_ID_PATTERN = re.compile(
        r"(?:\d+호\s*(?:토광묘|주거지|수혈유구|수혈|함정유구|함정|석관묘|석곽묘|석실묘|지석묘|고분|적석총|분구묘|옹관묘|가마|가마터|건물지|우물|구|배수로|패총|목관묘|유구|유물))"
    )

    DIMENSION_EXTRACT_PATTERN = re.compile(
        r"(?P<dim_type>잔존길이|잔존너비|잔존깊이|잔존높이|길이|너비|폭|깊이|높이|두께|중량|무게|구경|저경|동경|최대경|직경|장축|단축|신고|기고|length|width|depth|height|thickness|weight)\s*[:=]?\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>cm|m|mm|kg|g|mg|센티미터|미터|밀리미터|킬로그램|그램)?",
        re.IGNORECASE,
    )

    STANDALONE_NUMERIC_PATTERN = re.compile(
        r"^[^\d]*?(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>cm|m|mm|kg|g|mg|센티미터|미터|밀리미터|킬로그램|그램)?$",
        re.IGNORECASE,
    )

    ORIENTATION_PATTERN = re.compile(
        r"(?P<ns>[NESWnesw남북])\s*[-–—]?\s*(?P<deg>\d+(?:\.\d+)?)\s*°?\s*[-–—]?\s*(?P<ew>[NESWnesw동서])|(?P<named>남북향?|동서향?|북동[-–—]남서|북서[-–—]남동)",
        re.IGNORECASE,
    )

    BLANK_REF_PATTERN = re.compile(
        r"(?:\(\s*(?:도면|도판|사진|표)\s*:\s*(?:,\s*(?:도면|도판|사진|표)\s*:\s*)?\)|(?:도면|도판|사진|표)\s*:\s*(?=[,\s\)]|$))"
    )

    REF_PATTERN = re.compile(
        r"(?P<type>도판|도면|사진|표|Plate|Drawing|Photo|Table)\s*[:=]?\s*(?P<num>\d+(?:[-~]\d+)?)",
        re.IGNORECASE,
    )

    def __init__(self, header_patterns: list[str] | None = None) -> None:
        self._header_patterns: list[str] = (
            list(header_patterns)
            if header_patterns is not None
            else list(self.DEFAULT_HEADER_PATTERNS)
        )
        self._resolver = ObjectResolver()

    # -------------------------------------------------------------------------
    # Legacy Header / Page Diff Methods (Aligned with ReviewStatus = 'pending_review')
    # -------------------------------------------------------------------------

    def _is_header_noise(self, line: str) -> bool:
        stripped = line.strip()
        for pattern in self._header_patterns:
            if isinstance(pattern, str):
                if re.search(pattern, stripped):
                    return True
            elif hasattr(pattern, "search"):
                if pattern.search(stripped):
                    return True
        return False

    def _classify_rule_category(
        self, old_text: str | None, new_text: str | None
    ) -> RuleCategory:
        combined = f"{old_text or ''} {new_text or ''}"

        # 1. Figure / Plate / Photo / Table references
        if "도면" in combined or "도판" in combined or "표 " in combined:
            return "figure_plate_table_photo_ref"

        # 2. Feature / Artifact ID
        if self.FEATURE_ID_PATTERN.search(combined):
            if old_text and new_text and (old_text.replace(" ", "") == new_text.replace(" ", "")):
                return "annotation_resolution"
            return "feature_or_artifact_id"

        # 3. Annotation / spacing / punctuation / arrows
        if "→" in combined or "괄호" in combined or "(" in combined:
            return "annotation_resolution"
        if old_text and new_text and (old_text.replace(" ", "") == new_text.replace(" ", "")):
            return "annotation_resolution"

        return "annotation_resolution"

    def compare_pages(
        self,
        page_a: ParsedPage,
        page_b: ParsedPage,
        stage_from: str,
        stage_to: str,
    ) -> list[CorrectionCandidateData]:
        lines_a = [b.text for b in page_a.text_blocks if not self._is_header_noise(b.text)]
        lines_b = [b.text for b in page_b.text_blocks if not self._is_header_noise(b.text)]

        matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
        candidates: list[CorrectionCandidateData] = []
        cand_idx = 1

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue

            chunk_a = lines_a[i1:i2]
            chunk_b = lines_b[j1:j2]

            old_str = " ".join(chunk_a) if chunk_a else None
            new_str = " ".join(chunk_b) if chunk_b else None

            if tag == "replace":
                change_type: ChangeType = "modified"
            elif tag == "insert":
                change_type = "added"
            elif tag == "delete":
                change_type = "deleted"
            else:
                change_type = "modified"

            category = self._classify_rule_category(old_str, new_str)
            status: ReviewStatus = "pending_review"

            evidence = EvidenceData(
                version_from=stage_from,
                version_to=stage_to,
                physical_page_from=page_a.physical_page,
                physical_page_to=page_b.physical_page,
                printed_page_from=page_a.printed_page,
                printed_page_to=page_b.printed_page,
                rule_name=category,
                rationale=f"Diff detected between {stage_from} and {stage_to}: [{change_type}]",
            )

            cand = CorrectionCandidateData(
                candidate_id=f"cand_{stage_from}_{stage_to}_p{page_a.physical_page}_{cand_idx}",
                rule_category=category,
                change_type=change_type,
                status=status,
                original_text=old_str,
                proposed_text=new_str,
                evidence=evidence,
                evidence_list=[evidence],
            )
            candidates.append(cand)
            cand_idx += 1

        return candidates

    def analyze_alignment_rows(
        self, rows: list[AlignedPageRow]
    ) -> RuleCheckResult:
        all_candidates: list[CorrectionCandidateData] = []

        summary = {
            "total": 0,
            "status": {
                "pending_review": 0,
                "confirmed": 0,
                "layout_noise": 0,
                "manual_review": 0,
                "unresolved": 0,
            },
            "rule": {
                "site_or_area_name": 0,
                "feature_or_artifact_id": 0,
                "figure_plate_table_photo_ref": 0,
                "numeric_value": 0,
                "direction_period_term": 0,
                "annotation_resolution": 0,
            },
            "change_type": {
                "added": 0,
                "deleted": 0,
                "modified": 0,
                "moved": 0,
            },
        }

        paths = [("1차", "2차"), ("2차", "3차"), ("1차", "3차")]

        for row in rows:
            for st_from, st_to in paths:
                page_from = row.pages.get(st_from)
                page_to = row.pages.get(st_to)
                if page_from is not None and page_to is not None:
                    cands = self.compare_pages(
                        page_from,
                        page_to,
                        st_from,
                        st_to,
                    )
                    all_candidates.extend(cands)

        summary["total"] = len(all_candidates)
        for c in all_candidates:
            if c.status in summary["status"]:
                summary["status"][c.status] += 1
            if c.rule_category in summary["rule"]:
                summary["rule"][c.rule_category] += 1
            if c.change_type in summary["change_type"]:
                summary["change_type"][c.change_type] += 1

        return RuleCheckResult(candidates=all_candidates, summary=summary)

    # -------------------------------------------------------------------------
    # Unit Normalization & Dimension Parsers
    # -------------------------------------------------------------------------

    def normalize_dimension_unit(
        self, val: str | float | int | NormalizedDimension, dimension_type: str = ""
    ) -> NormalizedDimension:
        if isinstance(val, NormalizedDimension):
            if dimension_type and not val.dimension_type:
                return NormalizedDimension(
                    raw_text=val.raw_text,
                    numeric_value=val.numeric_value,
                    unit=val.unit,
                    base_unit=val.base_unit,
                    normalized_value=val.normalized_value,
                    dimension_type=dimension_type,
                )
            return val

        if isinstance(val, (int, float)):
            f_val = float(val)
            return NormalizedDimension(
                raw_text=str(val),
                numeric_value=f_val,
                unit=None,
                base_unit=None,
                normalized_value=f_val,
                dimension_type=dimension_type,
            )

        raw_str = str(val).strip()
        match = self.STANDALONE_NUMERIC_PATTERN.search(raw_str)
        if not match:
            # Try to extract first numeric with unit
            match = self.DIMENSION_EXTRACT_PATTERN.search(raw_str)
            if match:
                dim_type_extracted = match.groupdict().get("dim_type") or dimension_type
                dim_type = DIMENSION_TYPE_CANONICAL.get(dim_type_extracted.lower(), dim_type_extracted)
                num_str = match.group("num")
                unit_str = match.group("unit")
            else:
                return NormalizedDimension(
                    raw_text=raw_str,
                    numeric_value=0.0,
                    unit=None,
                    base_unit=None,
                    normalized_value=0.0,
                    dimension_type=dimension_type,
                )
        else:
            num_str = match.group("num")
            unit_str = match.group("unit")
            dim_type = dimension_type

        numeric_val = float(num_str)
        unit_clean = unit_str.strip().lower() if unit_str else None

        base_unit: str | None = None
        normalized_val: float = numeric_val

        if unit_clean:
            if unit_clean in LENGTH_CONVERSIONS_TO_CM:
                base_unit = "cm"
                normalized_val = numeric_val * LENGTH_CONVERSIONS_TO_CM[unit_clean]
            elif unit_clean in WEIGHT_CONVERSIONS_TO_G:
                base_unit = "g"
                normalized_val = numeric_val * WEIGHT_CONVERSIONS_TO_G[unit_clean]
            else:
                base_unit = unit_clean

        return NormalizedDimension(
            raw_text=raw_str,
            numeric_value=numeric_val,
            unit=unit_clean,
            base_unit=base_unit,
            normalized_value=normalized_val,
            dimension_type=dim_type,
        )

    def are_dimensions_consistent(
        self,
        d1: str | float | int | NormalizedDimension,
        d2: str | float | int | NormalizedDimension,
        tolerance: float = 1e-4,
    ) -> bool:
        norm1 = self.normalize_dimension_unit(d1)
        norm2 = self.normalize_dimension_unit(d2)

        # Both have known base units (e.g. length "cm" or weight "g")
        if norm1.base_unit is not None and norm2.base_unit is not None:
            if norm1.base_unit == norm2.base_unit:
                return abs(norm1.normalized_value - norm2.normalized_value) < tolerance
            return False

        # One has unit, the other is unitless
        if norm1.base_unit is not None and norm2.base_unit is None:
            return (
                abs(norm1.normalized_value - norm2.numeric_value) < tolerance
                or abs(norm1.numeric_value - norm2.numeric_value) < tolerance
            )
        if norm2.base_unit is not None and norm1.base_unit is None:
            return (
                abs(norm2.normalized_value - norm1.numeric_value) < tolerance
                or abs(norm2.numeric_value - norm1.numeric_value) < tolerance
            )

        # Both are unitless
        return abs(norm1.numeric_value - norm2.numeric_value) < tolerance

    def parse_dimensions(self, text_or_data: Any) -> list[NormalizedDimension]:
        if isinstance(text_or_data, NormalizedDimension):
            return [text_or_data]

        dims: list[NormalizedDimension] = []
        if isinstance(text_or_data, dict):
            for k, v in text_or_data.items():
                k_clean = str(k).strip()
                k_canon = DIMENSION_TYPE_CANONICAL.get(k_clean.lower(), k_clean)
                if isinstance(v, (int, float, str)):
                    dim = self.normalize_dimension_unit(v, dimension_type=k_canon)
                    if dim.numeric_value > 0 or dim.raw_text:
                        dims.append(dim)
            return dims

        text = str(text_or_data or "").strip()
        if not text:
            return []

        for match in self.DIMENSION_EXTRACT_PATTERN.finditer(text):
            dim_type_raw = match.group("dim_type")
            canon_type = DIMENSION_TYPE_CANONICAL.get(dim_type_raw.lower(), dim_type_raw)
            num_str = match.group("num")
            unit_str = match.group("unit")
            full_match = match.group(0)

            numeric_val = float(num_str)
            unit_clean = unit_str.strip().lower() if unit_str else None

            base_unit = None
            normalized_val = numeric_val
            if unit_clean:
                if unit_clean in LENGTH_CONVERSIONS_TO_CM:
                    base_unit = "cm"
                    normalized_val = numeric_val * LENGTH_CONVERSIONS_TO_CM[unit_clean]
                elif unit_clean in WEIGHT_CONVERSIONS_TO_G:
                    base_unit = "g"
                    normalized_val = numeric_val * WEIGHT_CONVERSIONS_TO_G[unit_clean]
                else:
                    base_unit = unit_clean

            dims.append(
                NormalizedDimension(
                    raw_text=full_match,
                    numeric_value=numeric_val,
                    unit=unit_clean,
                    base_unit=base_unit,
                    normalized_value=normalized_val,
                    dimension_type=canon_type,
                )
            )

        if not dims:
            standalone = self.STANDALONE_NUMERIC_PATTERN.match(text)
            if standalone:
                dims.append(self.normalize_dimension_unit(text))

        return dims

    # -------------------------------------------------------------------------
    # Categorical & Entity Normalizers
    # -------------------------------------------------------------------------

    def normalize_period(self, text: str) -> str:
        return ObjectResolver.normalize_period(text)

    def normalize_type(self, text: str) -> str:
        return ObjectResolver.normalize_type(text)

    def normalize_orientation(self, text: str) -> str:
        if not text:
            return ""
        clean = text.strip()
        match = self.ORIENTATION_PATTERN.search(clean)
        if match:
            gd = match.groupdict()
            if gd.get("named"):
                named = gd["named"].replace("향", "").strip()
                return named
            ns = (gd.get("ns") or "").upper().strip()
            deg = (gd.get("deg") or "").strip()
            ew = (gd.get("ew") or "").upper().strip()
            if ns and deg and ew:
                return f"{ns}-{deg}°-E" if ew in ("E", "동") else f"{ns}-{deg}°-W"
        return clean.replace(" ", "")

    def extract_periods_from_evidence(self, ev: EvidenceData) -> list[str]:
        texts: list[str] = []
        if isinstance(ev.value, dict):
            p = ev.value.get("period")
            if p:
                texts.append(str(p))
        if isinstance(ev.value, str):
            texts.append(ev.value)
        if ev.rationale:
            texts.append(ev.rationale)

        periods: list[str] = []
        for t in texts:
            for match in re.finditer(ObjectResolver.PERIODS_PATTERN, t):
                norm = self.normalize_period(match.group(0))
                if norm and norm not in periods:
                    periods.append(norm)
        return periods

    def extract_types_from_evidence(self, ev: EvidenceData) -> list[str]:
        texts: list[str] = []
        if isinstance(ev.value, dict):
            t = ev.value.get("type")
            if t:
                texts.append(str(t))
        if isinstance(ev.value, str):
            texts.append(ev.value)
        if ev.rationale:
            texts.append(ev.rationale)

        types: list[str] = []
        for txt in texts:
            for ftype in ARCHAEOLOGICAL_TYPES:
                if ftype in txt:
                    norm = self.normalize_type(ftype)
                    if norm and norm not in types:
                        types.append(norm)
        return types

    def extract_orientations_from_evidence(self, ev: EvidenceData) -> list[str]:
        texts: list[str] = []
        if isinstance(ev.value, dict):
            o = ev.value.get("orientation") or ev.value.get("direction")
            if o:
                texts.append(str(o))
        if isinstance(ev.value, str):
            texts.append(ev.value)
        if ev.rationale:
            texts.append(ev.rationale)

        orientations: list[str] = []
        for t in texts:
            for match in self.ORIENTATION_PATTERN.finditer(t):
                norm = self.normalize_orientation(match.group(0))
                if norm and norm not in orientations:
                    orientations.append(norm)
        return orientations

    def extract_references_from_evidence(
        self, ev: EvidenceData
    ) -> list[tuple[str, str, str]]:
        """Extracts (ref_type, ref_number, raw_text) from evidence."""
        refs: list[tuple[str, str, str]] = []
        if isinstance(ev.value, dict):
            ref_t = str(ev.value.get("ref_type") or ev.value.get("reference_type") or "")
            ref_num = str(ev.value.get("number") or ev.value.get("reference_number") or "")
            if ref_t and ref_num:
                refs.append((ref_t, ref_num, f"{ref_t} {ref_num}"))

        texts: list[str] = []
        if isinstance(ev.value, str):
            texts.append(ev.value)
        if ev.rationale:
            texts.append(ev.rationale)

        for t in texts:
            for match in self.REF_PATTERN.finditer(t):
                rt = match.group("type")
                rn = match.group("num")
                refs.append((rt, rn, match.group(0)))

        return refs

    # -------------------------------------------------------------------------
    # Object & Evidence Consistency Engine
    # -------------------------------------------------------------------------

    def check_object_consistency(
        self,
        archaeology_object: ArchaeologyObjectData | None = None,
        evidences: list[EvidenceData] | None = None,
        plate_index: PlateIndex | None = None,
        drawing_index: Any | None = None,
        plates: list[PlateData] | None = None,
        drawings: list[DrawingData] | None = None,
    ) -> list[CorrectionCandidateData]:
        """Evaluates semantic and factual consistency across Evidence collections

        linked to an ArchaeologyObject, generating evidence-backed
        CorrectionCandidateData records strictly starting in 'pending_review'.
        """
        candidates: list[CorrectionCandidateData] = []
        ev_list = list(evidences) if evidences is not None else []
        obj_id = archaeology_object.object_id if archaeology_object else "unspecified"
        obj_canonical = archaeology_object.canonical_name if archaeology_object else ""
        cand_idx = 1

        if plate_index is None and plates is not None:
            plate_index = PlateIndex(plates=plates)

        # 1. Blank reference detection
        for ev in ev_list:
            text_sources = []
            if isinstance(ev.value, str):
                text_sources.append(ev.value)
            if ev.rationale:
                text_sources.append(ev.rationale)

            for t in text_sources:
                for match in self.BLANK_REF_PATTERN.finditer(t):
                    raw_blank = match.group(0)
                    cand = CorrectionCandidateData(
                        candidate_id=f"cand_blank_ref_{obj_id}_{ev.id or cand_idx}",
                        rule_category="figure_plate_table_photo_ref",
                        change_type="modified",
                        status="pending_review",
                        original_text=raw_blank,
                        proposed_text=None,
                        evidence=ev,
                        evidence_list=[ev],
                        archaeology_object_id=obj_id if obj_id != "unspecified" else None,
                        confidence=0.95,
                    )
                    candidates.append(cand)
                    cand_idx += 1

        # 2. Numeric unit & dimension conflict detection across evidences
        ev_dims: list[tuple[EvidenceData, list[NormalizedDimension]]] = [
            (ev, self.parse_dimensions(ev.value)) for ev in ev_list
        ]

        seen_dim_conflicts: set[tuple[str, str, str]] = set()
        for i in range(len(ev_dims)):
            ev_i, dims_i = ev_dims[i]
            for j in range(i + 1, len(ev_dims)):
                ev_j, dims_j = ev_dims[j]
                for d1 in dims_i:
                    for d2 in dims_j:
                        # Match dimensions by dimension_type
                        if (d1.dimension_type and d2.dimension_type and d1.dimension_type == d2.dimension_type) or (
                            not d1.dimension_type and not d2.dimension_type
                        ):
                            if not self.are_dimensions_consistent(d1, d2):
                                conflict_key = (
                                    d1.dimension_type,
                                    str(d1.normalized_value),
                                    str(d2.normalized_value),
                                )
                                if conflict_key not in seen_dim_conflicts:
                                    seen_dim_conflicts.add(conflict_key)
                                    cand = CorrectionCandidateData(
                                        candidate_id=f"cand_dim_conflict_{obj_id}_{d1.dimension_type or 'dim'}_{cand_idx}",
                                        rule_category="numeric_value",
                                        change_type="modified",
                                        status="pending_review",
                                        original_text=d1.raw_text,
                                        proposed_text=d2.raw_text,
                                        evidence=ev_i,
                                        evidence_list=[ev_i, ev_j],
                                        archaeology_object_id=obj_id if obj_id != "unspecified" else None,
                                        confidence=0.95,
                                    )
                                    candidates.append(cand)
                                    cand_idx += 1

        # 3. Feature type conflict detection
        ev_types: list[tuple[EvidenceData, list[str]]] = [
            (ev, self.extract_types_from_evidence(ev)) for ev in ev_list
        ]
        if archaeology_object and archaeology_object.type:
            obj_type = self.normalize_type(archaeology_object.type)
            for ev, types in ev_types:
                for t in types:
                    if t != obj_type:
                        cand = CorrectionCandidateData(
                            candidate_id=f"cand_type_mismatch_{obj_id}_{cand_idx}",
                            rule_category="feature_or_artifact_id",
                            change_type="modified",
                            status="pending_review",
                            original_text=obj_type,
                            proposed_text=t,
                            evidence=ev,
                            evidence_list=[ev],
                            archaeology_object_id=obj_id if obj_id != "unspecified" else None,
                            confidence=0.95,
                        )
                        candidates.append(cand)
                        cand_idx += 1

        for i in range(len(ev_types)):
            ev_i, types_i = ev_types[i]
            for j in range(i + 1, len(ev_types)):
                ev_j, types_j = ev_types[j]
                for t1 in types_i:
                    for t2 in types_j:
                        if t1 != t2:
                            cand = CorrectionCandidateData(
                                candidate_id=f"cand_type_inconsistency_{obj_id}_{cand_idx}",
                                rule_category="feature_or_artifact_id",
                                change_type="modified",
                                status="pending_review",
                                original_text=t1,
                                proposed_text=t2,
                                evidence=ev_i,
                                evidence_list=[ev_i, ev_j],
                                archaeology_object_id=obj_id if obj_id != "unspecified" else None,
                                confidence=0.95,
                            )
                            candidates.append(cand)
                            cand_idx += 1

        # 4. Period conflict detection
        ev_periods: list[tuple[EvidenceData, list[str]]] = [
            (ev, self.extract_periods_from_evidence(ev)) for ev in ev_list
        ]
        if archaeology_object and archaeology_object.period:
            obj_period = self.normalize_period(archaeology_object.period)
            for ev, periods in ev_periods:
                for p in periods:
                    if p != obj_period:
                        cand = CorrectionCandidateData(
                            candidate_id=f"cand_period_mismatch_{obj_id}_{cand_idx}",
                            rule_category="direction_period_term",
                            change_type="modified",
                            status="pending_review",
                            original_text=obj_period,
                            proposed_text=p,
                            evidence=ev,
                            evidence_list=[ev],
                            archaeology_object_id=obj_id if obj_id != "unspecified" else None,
                            confidence=0.95,
                        )
                        candidates.append(cand)
                        cand_idx += 1

        for i in range(len(ev_periods)):
            ev_i, periods_i = ev_periods[i]
            for j in range(i + 1, len(ev_periods)):
                ev_j, periods_j = ev_periods[j]
                for p1 in periods_i:
                    for p2 in periods_j:
                        if p1 != p2:
                            cand = CorrectionCandidateData(
                                candidate_id=f"cand_period_inconsistency_{obj_id}_{cand_idx}",
                                rule_category="direction_period_term",
                                change_type="modified",
                                status="pending_review",
                                original_text=p1,
                                proposed_text=p2,
                                evidence=ev_i,
                                evidence_list=[ev_i, ev_j],
                                archaeology_object_id=obj_id if obj_id != "unspecified" else None,
                                confidence=0.95,
                            )
                            candidates.append(cand)
                            cand_idx += 1

        # 5. Orientation conflict detection
        ev_orientations: list[tuple[EvidenceData, list[str]]] = [
            (ev, self.extract_orientations_from_evidence(ev)) for ev in ev_list
        ]
        for i in range(len(ev_orientations)):
            ev_i, orients_i = ev_orientations[i]
            for j in range(i + 1, len(ev_orientations)):
                ev_j, orients_j = ev_orientations[j]
                for o1 in orients_i:
                    for o2 in orients_j:
                        if o1 != o2:
                            cand = CorrectionCandidateData(
                                candidate_id=f"cand_orientation_inconsistency_{obj_id}_{cand_idx}",
                                rule_category="direction_period_term",
                                change_type="modified",
                                status="pending_review",
                                original_text=o1,
                                proposed_text=o2,
                                evidence=ev_i,
                                evidence_list=[ev_i, ev_j],
                                archaeology_object_id=obj_id if obj_id != "unspecified" else None,
                                confidence=0.95,
                            )
                            candidates.append(cand)
                            cand_idx += 1

        # 6. Reference resolution mismatch
        if plate_index is not None or plates is not None or drawings is not None or drawing_index is not None:
            for ev in ev_list:
                refs = self.extract_references_from_evidence(ev)
                for ref_type, ref_num, ref_raw in refs:
                    target_title: str | None = None
                    target_id: str | None = None

                    if ref_type in ("plate", "도판", "Plate"):
                        plate: PlateData | None = None
                        if plate_index is not None:
                            plate = plate_index.get_plate(ref_num)
                            if plate is None:
                                for p in getattr(plate_index, "plates", []):
                                    if str(p.number).strip() == str(ref_num).strip():
                                        plate = p
                                        break
                        if plate is None and plates is not None:
                            for p in plates:
                                if str(p.number).strip() == str(ref_num).strip():
                                    plate = p
                                    break
                        if plate is not None:
                            target_title = plate.title
                            target_id = plate.plate_id

                    elif ref_type in ("drawing", "도면", "Drawing"):
                        drawing: DrawingData | None = None
                        if drawing_index is not None:
                            if hasattr(drawing_index, "get_drawing"):
                                drawing = drawing_index.get_drawing(ref_num)
                            if drawing is None:
                                for d in getattr(drawing_index, "drawings", []):
                                    if str(d.number).strip() == str(ref_num).strip():
                                        drawing = d
                                        break
                        if drawing is None and drawings is not None:
                            for d in drawings:
                                if str(d.number).strip() == str(ref_num).strip():
                                    drawing = d
                                    break
                        if drawing is not None:
                            target_title = drawing.title
                            target_id = drawing.drawing_id

                    # Also check if evidence value already has target_title
                    if not target_title and isinstance(ev.value, dict):
                        target_title = ev.value.get("target_title") or ev.value.get("title")

                    if target_title and archaeology_object:
                        # Extract number and types from target_title
                        plate_mentions = self._resolver.extract_mentions_from_text(target_title)
                        extracted_num = ""
                        extracted_types = []

                        if plate_mentions:
                            first_m = plate_mentions[0]
                            extracted_num = first_m.number
                            if first_m.type:
                                extracted_types.append(first_m.type)
                        else:
                            # Direct regex extraction
                            num_match = re.search(r"(\d+)호", target_title)
                            if num_match:
                                extracted_num = f"{num_match.group(1)}호"
                            for ftype in ARCHAEOLOGICAL_TYPES:
                                if ftype in target_title:
                                    extracted_types.append(self.normalize_type(ftype))

                        mismatch = False
                        if archaeology_object.number and extracted_num and extracted_num != archaeology_object.number:
                            mismatch = True
                        if archaeology_object.type and extracted_types and all(t != archaeology_object.type for t in extracted_types):
                            mismatch = True

                        if mismatch:
                            cand = CorrectionCandidateData(
                                candidate_id=f"cand_ref_mismatch_{obj_id}_{target_id or ref_num}_{cand_idx}",
                                rule_category="figure_plate_table_photo_ref",
                                change_type="modified",
                                status="pending_review",
                                original_text=ref_raw,
                                proposed_text=target_title,
                                evidence=EvidenceData(
                                    id=f"ev_ref_mismatch_{cand_idx}",
                                    kind="reference",
                                    source_sha256=ev.source_sha256 or (plate.source_sha256 if plate else None),
                                    document_version_id=ev.document_version_id,
                                    page_id=ev.page_id,
                                    rationale=f"Referenced {ref_raw} resolves to '{target_title}', which does not match object '{obj_canonical}'",
                                ),
                                evidence_list=[ev],
                                archaeology_object_id=obj_id if obj_id != "unspecified" else None,
                                confidence=0.90,
                            )
                            candidates.append(cand)
                            cand_idx += 1

        # Strict validation: ensure all candidates are in pending_review
        validated_candidates: list[CorrectionCandidateData] = []
        for cand in candidates:
            if cand.status != "pending_review":
                cand = CorrectionCandidateData(
                    candidate_id=cand.candidate_id,
                    rule_category=cand.rule_category,
                    change_type=cand.change_type,
                    status="pending_review",
                    original_text=cand.original_text,
                    proposed_text=cand.proposed_text,
                    evidence=cand.evidence,
                    evidence_list=cand.evidence_list,
                    archaeology_object_id=cand.archaeology_object_id,
                    confidence=cand.confidence,
                    analysis_run_id=cand.analysis_run_id,
                )
            validated_candidates.append(cand)

        return validated_candidates

    def check_objects_consistency(
        self,
        objects_with_evidences: list[tuple[ArchaeologyObjectData, list[EvidenceData]]],
        plate_index: PlateIndex | None = None,
        drawing_index: Any | None = None,
        plates: list[PlateData] | None = None,
        drawings: list[DrawingData] | None = None,
    ) -> list[CorrectionCandidateData]:
        all_candidates: list[CorrectionCandidateData] = []
        for obj, evidences in objects_with_evidences:
            cands = self.check_object_consistency(
                archaeology_object=obj,
                evidences=evidences,
                plate_index=plate_index,
                drawing_index=drawing_index,
                plates=plates,
                drawings=drawings,
            )
            all_candidates.extend(cands)
        return all_candidates
