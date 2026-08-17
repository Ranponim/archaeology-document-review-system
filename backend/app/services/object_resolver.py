from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    ObjectResolutionResult,
)
from app.domain.document_structure import CaptionData, TextBlockData

# Canonical archaeological periods mapping
PERIOD_NORMALIZATION: dict[str, str] = {
    "구석기": "구석기시대",
    "구석기시대": "구석기시대",
    "신석기": "신석기시대",
    "신석기시대": "신석기시대",
    "청동기": "청동기시대",
    "청동기시대": "청동기시대",
    "초기철기": "초기철기시대",
    "초기철기시대": "초기철기시대",
    "철기": "초기철기시대",
    "철기시대": "초기철기시대",
    "원삼국": "원삼국시대",
    "원삼국시대": "원삼국시대",
    "삼국": "삼국시대",
    "삼국시대": "삼국시대",
    "백제": "백제",
    "백제시대": "백제",
    "신라": "신라",
    "신라시대": "신라",
    "통일신라": "통일신라",
    "통일신라시대": "통일신라",
    "고려": "고려시대",
    "고려시대": "고려시대",
    "조선": "조선시대",
    "조선시대": "조선시대",
    "근대": "근대",
    "시대미상": "시대미상",
    "미상": "시대미상",
}

# Archeological feature and artifact types (ordered by descending length)
ARCHAEOLOGICAL_TYPES: list[str] = [
    "수혈주거지",
    "수혈건물지",
    "원형수혈유구",
    "방형수혈유구",
    "수혈유구",
    "구상유구",
    "소성유구",
    "함정유구",
    "도작유구",
    "수전유구",
    "석관묘",
    "토광묘",
    "석곽묘",
    "석실묘",
    "옹관묘",
    "분구묘",
    "지석묘",
    "적석총",
    "목관묘",
    "목곽묘",
    "주구묘",
    "화장묘",
    "회곽묘",
    "고분",
    "주거지",
    "건물지",
    "가마터",
    "배수로",
    "기둥자리",
    "저장혈",
    "패총",
    "우물",
    "가마",
    "노지",
    "주공",
    "담장",
    "수혈",
    "함정",
    "유구",
    "마제석검",
    "간돌검",
    "환두대도",
    "무문토기",
    "연질토기",
    "경질토기",
    "와질토기",
    "분청사기",
    "찍개",
    "긁개",
    "홈날",
    "공이",
    "패식",
    "동경",
    "곡옥",
    "철촉",
    "토기",
    "석부",
    "석촉",
    "백자",
    "청자",
    "도기",
    "철검",
    "철도",
    "철부",
    "방추차",
    "갈판",
    "갈돌",
    "돌도끼",
    "돌칼",
    "화살촉",
    "지석",
    "홍도",
    "유물",
]


@dataclass(frozen=True, slots=True)
class ExtractedMention:
    raw_text: str
    site: str
    point: str
    period: str
    number: str
    type: str
    canonical_name: str
    source_id: str
    span: tuple[int, int]
    source_sha256: str | None = None


class ObjectResolver:
    """Extracts, normalizes, and resolves archaeological entity mentions from text

    blocks and captions into canonical ArchaeologyObjectData records, enforcing
    ambiguity safety.
    """

    PERIODS_PATTERN = (
        r"(?:구석기(?:시대)?|신석기(?:시대)?|청동기(?:시대)?|초기철기(?:시대)?"
        r"|철기(?:시대)?|원삼국(?:시대)?|삼국(?:시대)?|백제(?:시대)?"
        r"|신라(?:시대)?|통일신라(?:시대)?|고려(?:시대)?|조선(?:시대)?"
        r"|근대|시대미상|미상)"
    )

    POINTS_PATTERN = r"(?:(?:\d+|[A-Za-z]|[가-힣]{1,2})\s*(?:지점|구역|지구))"

    NUMBERS_PATTERN = (
        r"(?:(?:제\s*)?(?:\d+(?:-\d+)?|\d+·\d+)\s*(?:호분|호|번|호\s*유구|점|개)"
        r"|(?:No\.\s*\d+(?:-\d+)?))"
    )

    SITES_PATTERN = (
        r"(?:[가-힣]+(?:\s+[가-힣]+)*\s+(?:산)?\d+(?:-\d+)?번지"
        r"|[가-힣]+(?:\s+[가-힣]+)*\s*유적"
        r"|[가-힣]+(?:시|군|구)\s+[가-힣]+(?:읍|면|동|리)(?:\s+(?:산)?\d+(?:-\d+)?(?:번지)?)?)"
    )

    TYPES_PATTERN = "(?:" + "|".join(ARCHAEOLOGICAL_TYPES) + ")"

    def __init__(self) -> None:
        self._compiled_extractors = self._build_extractors()

    def _build_extractors(self) -> list[tuple[re.Pattern[str], list[str]]]:
        """Build regex extractors ordered by specificity."""
        site_opt = rf"(?:(?P<site>{self.SITES_PATTERN})\s+)?"
        point_req = rf"(?P<point>{self.POINTS_PATTERN})"
        period_req = rf"(?P<period>{self.PERIODS_PATTERN})"
        number_req = rf"(?P<number>{self.NUMBERS_PATTERN})"
        type_req = rf"(?P<type>{self.TYPES_PATTERN})"

        patterns: list[tuple[str, list[str]]] = [
            # 1. Site? + Point + Period + Number + Type
            (
                rf"{site_opt}{point_req}\s*{period_req}\s*{number_req}\s*{type_req}",
                ["site", "point", "period", "number", "type"],
            ),
            # 2. Site? + Period + Point + Number + Type
            (
                rf"{site_opt}{period_req}\s*{point_req}\s*{number_req}\s*{type_req}",
                ["site", "period", "point", "number", "type"],
            ),
            # 3. Site? + Point + Period + Type + Number
            (
                rf"{site_opt}{point_req}\s*{period_req}\s*{type_req}\s*{number_req}",
                ["site", "point", "period", "type", "number"],
            ),
            # 4. Site? + Period + Point + Type + Number
            (
                rf"{site_opt}{period_req}\s*{point_req}\s*{type_req}\s*{number_req}",
                ["site", "period", "point", "type", "number"],
            ),
            # 5. Site? + Point + Number + Type
            (
                rf"{site_opt}{point_req}\s*{number_req}\s*{type_req}",
                ["site", "point", "number", "type"],
            ),
            # 6. Site? + Point + Type + Number
            (
                rf"{site_opt}{point_req}\s*{type_req}\s*{number_req}",
                ["site", "point", "type", "number"],
            ),
            # 7. Site? + Period + Number + Type
            (
                rf"{site_opt}{period_req}\s*{number_req}\s*{type_req}",
                ["site", "period", "number", "type"],
            ),
            # 8. Site? + Period + Type + Number
            (
                rf"{site_opt}{period_req}\s*{type_req}\s*{number_req}",
                ["site", "period", "type", "number"],
            ),
            # 9. Site? + Point + Period + Type
            (
                rf"{site_opt}{point_req}\s*{period_req}\s*{type_req}",
                ["site", "point", "period", "type"],
            ),
            # 10. Site? + Period + Point + Type
            (
                rf"{site_opt}{period_req}\s*{point_req}\s*{type_req}",
                ["site", "period", "point", "type"],
            ),
            # 11. Site? + Number + Type
            (
                rf"{site_opt}{number_req}\s*{type_req}",
                ["site", "number", "type"],
            ),
            # 12. Site? + Type + Number
            (
                rf"{site_opt}{type_req}\s*{number_req}",
                ["site", "type", "number"],
            ),
        ]

        compiled: list[tuple[re.Pattern[str], list[str]]] = []
        for pat_str, fields in patterns:
            compiled.append((re.compile(pat_str), fields))
        return compiled

    @staticmethod
    def normalize_period(period: str) -> str:
        if not period:
            return ""
        clean = re.sub(r"\s+", "", period)
        return PERIOD_NORMALIZATION.get(clean, clean)

    @staticmethod
    def normalize_point(point: str) -> str:
        if not point:
            return ""
        return re.sub(r"\s+", "", point)

    @staticmethod
    def normalize_number(number: str) -> str:
        if not number:
            return ""
        num = re.sub(r"\s+", "", number)
        if num.startswith("제"):
            num = num[1:]
        if num.startswith("No."):
            num = num[3:] + "호"
        return num

    @staticmethod
    def normalize_type(type_str: str) -> str:
        if not type_str:
            return ""
        return re.sub(r"\s+", "", type_str)

    @classmethod
    def build_canonical_name(
        cls, point: str, period: str, number: str, type_str: str
    ) -> str:
        parts = [p for p in [point, period, number, type_str] if p]
        return " ".join(parts)

    @staticmethod
    def generate_object_id(
        project_id: str = "", site: str = "", canonical_name: str = ""
    ) -> str:
        key = f"{project_id}:{site}:{canonical_name}".strip(":")
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        return f"obj_{digest}"

    def extract_mentions_from_text(
        self,
        text: str,
        source_id: str = "",
        default_site: str = "",
        source_sha256: str | None = None,
    ) -> list[ExtractedMention]:
        if not text or not text.strip():
            return []

        mentions: list[ExtractedMention] = []
        occupied_spans: list[tuple[int, int]] = []

        for pattern, _field_names in self._compiled_extractors:
            for match in pattern.finditer(text):
                start, end = match.span()
                # Check overlap with existing matches
                overlap = any(
                    not (end <= occ_start or start >= occ_end)
                    for occ_start, occ_end in occupied_spans
                )
                if overlap:
                    continue

                gd = match.groupdict()
                site_raw = gd.get("site") or default_site or ""
                point_raw = gd.get("point") or ""
                period_raw = gd.get("period") or ""
                number_raw = gd.get("number") or ""
                type_raw = gd.get("type") or ""

                site = site_raw.strip()
                point = self.normalize_point(point_raw)
                period = self.normalize_period(period_raw)
                number = self.normalize_number(number_raw)
                type_norm = self.normalize_type(type_raw)

                canonical_name = self.build_canonical_name(
                    point=point,
                    period=period,
                    number=number,
                    type_str=type_norm,
                )

                if not canonical_name:
                    continue

                occupied_spans.append((start, end))
                mentions.append(
                    ExtractedMention(
                        raw_text=match.group(0),
                        site=site,
                        point=point,
                        period=period,
                        number=number,
                        type=type_norm,
                        canonical_name=canonical_name,
                        source_id=source_id,
                        span=(start, end),
                        source_sha256=source_sha256,
                    )
                )

        # Sort mentions by their appearance in text
        mentions.sort(key=lambda m: m.span[0])
        return mentions

    def resolve_mentions(
        self,
        blocks: list[TextBlockData] | None = None,
        captions: list[CaptionData] | None = None,
        project_id: str = "",
        site: str = "",
        text: str | None = None,
    ) -> list[ObjectResolutionResult]:
        """Resolves mentions from text blocks and captions into canonical

        ArchaeologyObjectData records with ambiguity safety.
        """
        if text and not blocks:
            blocks = [
                TextBlockData(
                    block_id="text_1",
                    text=text,
                    normalized_text=text,
                    order=1,
                )
            ]

        all_mentions: list[ExtractedMention] = []

        if blocks:
            for b in blocks:
                t = b.normalized_text or b.text or ""
                mentions = self.extract_mentions_from_text(
                    text=t,
                    source_id=b.block_id,
                    default_site=site,
                    source_sha256=b.source_sha256,
                )
                all_mentions.extend(mentions)

        if captions:
            for c in captions:
                t = c.raw_text or ""
                mentions = self.extract_mentions_from_text(
                    text=t,
                    source_id=c.caption_id,
                    default_site=site,
                    source_sha256=c.source_sha256,
                )
                all_mentions.extend(mentions)

        if not all_mentions:
            return []

        # Group mentions by (canonical_name, site)
        grouped_mentions: dict[str, list[ExtractedMention]] = {}
        for m in all_mentions:
            key = f"{m.site}|{m.canonical_name}"
            if key not in grouped_mentions:
                grouped_mentions[key] = []
            grouped_mentions[key].append(m)

        # Collect distinct canonical objects and evaluate ambiguity
        results: list[ObjectResolutionResult] = []

        # Find all multi-attribute candidate objects in document to evaluate ambiguity
        candidates_by_type_number: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for group in grouped_mentions.values():
            first = group[0]
            if first.point or first.period:
                key_tn = (first.type, first.number)
                if key_tn not in candidates_by_type_number:
                    candidates_by_type_number[key_tn] = []
                candidates_by_type_number[key_tn].append(
                    {
                        "point": first.point,
                        "period": first.period,
                        "canonical_name": first.canonical_name,
                    }
                )

        for group in grouped_mentions.values():
            first = group[0]
            obj_site = next((m.site for m in group if m.site), site or "")
            obj_point = first.point
            obj_period = first.period
            obj_type = first.type
            obj_number = first.number
            canonical_name = first.canonical_name

            # Collect source block IDs preserving order and deduplicated
            source_ids: list[str] = []
            for m in group:
                if m.source_id and m.source_id not in source_ids:
                    source_ids.append(m.source_id)

            source_sha = next((m.source_sha256 for m in group if m.source_sha256), None)

            # Determine ambiguity & confidence
            # Case 1: Isolated mention without point and without period (e.g. '2호 토광묘')
            if not obj_point and not obj_period:
                status = "semantic_review"
                confidence = 0.5
                method = "deterministic_rule_underspecified"
            # Case 2: Missing period when multiple candidates of same type/number exist
            elif not obj_period and len(candidates_by_type_number.get((obj_type, obj_number), [])) > 1:
                status = "semantic_review"
                confidence = 0.5
                method = "deterministic_rule_ambiguous"
            else:
                status = "candidate"
                confidence = 1.0
                method = "deterministic_rule"

            object_id = self.generate_object_id(
                project_id=project_id, site=obj_site, canonical_name=canonical_name
            )

            obj_data = ArchaeologyObjectData(
                object_id=object_id,
                site=obj_site,
                point=obj_point,
                period=obj_period,
                type=obj_type,
                number=obj_number,
                canonical_name=canonical_name,
                source_block_ids=source_ids,
                source_sha256=source_sha,
                project_id=project_id or None,
            )

            res = ObjectResolutionResult(
                object_data=obj_data,
                confidence=confidence,
                status=status,
                source_block_ids=source_ids,
                method=method,
            )
            results.append(res)

        return results
