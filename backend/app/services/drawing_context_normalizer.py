from __future__ import annotations

import re

from app.domain.drawing_evidence import ContextFact, NormalizedDrawingContext


_KIND_PATTERN = re.compile(r"(도면|삽도)\s*\d", re.IGNORECASE)
_POINT_PATTERN = re.compile(r"(?:제\s*)?(\d+)\s*지점", re.IGNORECASE)
_PERIOD_PATTERN = re.compile(
    r"구석기시대|신석기시대|청동기시대|철기시대|원삼국시대|삼국시대|백제시대|통일신라시대|고려시대|조선시대"
)
_GRID_PATTERN = re.compile(
    r"\b([A-Za-z]\s*\d+)\s*([A-Za-z]\s*\d+)\b",
    re.IGNORECASE,
)
_DIRECTION_PATTERN = re.compile(
    r"북동쪽|북서쪽|남동쪽|남서쪽|북동|북서|남동|남서|동쪽|서쪽|남쪽|북쪽|동|서|남|북"
)
_DRAWING_TYPE_PATTERN = re.compile(
    r"평\s*[·ㆍ・]?\s*입단면도?|평\s*[·ㆍ・]?\s*단면도?|입단면도?|토층도?|평면도?|단면도?|현황도?|위치도?|배치도?"
)
_FEATURE_PATTERN = re.compile(
    r"(\d+)\s*호\s*(토광묘|옹관묘|석곽묘|석관묘|주거지|수혈|구상유구|분구묘|구덩이|건물지|주혈|묘|유구)"
)
_FEATURE_TYPE_PATTERN = re.compile(
    r"토광묘|옹관묘|석곽묘|석관묘|주거지|수혈|구상유구|분구묘|구덩이|건물지|주혈|묘|유구"
)
_CONTENT_TYPE_PATTERN = re.compile(r"출토\s*유물")
_MAP_TYPE_PATTERN = re.compile(r"위성지도|항공지도|주변유적분포도|유적분포도|분포도|해동지도|광여도")
_YEAR_PATTERN = re.compile(r"(?<!\d)((?:18|19|20)\d{2})(?!\d)")
_SECTION_PATTERN = re.compile(
    r"\b([A-Za-z])\s*-\s*([A-Za-z])\s*(['′’]?)",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"[A-Za-z]+\d*|\d+[A-Za-z]+|[가-힣]+|\d+")

_DIRECTION_NORMALIZATION = {
    "북동쪽": "북동",
    "북서쪽": "북서",
    "남동쪽": "남동",
    "남서쪽": "남서",
    "동쪽": "동",
    "서쪽": "서",
    "남쪽": "남",
    "북쪽": "북",
}

_DRAWING_TYPE_NORMALIZATION = {
    "평입단면": "평입단면",
    "평단면": "평단면",
    "입단면": "입단면",
    "토층": "토층",
    "평면": "평면",
    "단면": "단면",
    "현황": "현황",
    "위치": "위치",
    "배치": "배치",
}


class DrawingContextNormalizer:
    """Extract deterministic drawing-context facts from Korean archaeology text."""

    @staticmethod
    def _publication_kind(text: str) -> str | None:
        match = _KIND_PATTERN.search(text)
        if not match:
            return None
        return "illustration" if match.group(1) == "삽도" else "drawing"

    @staticmethod
    def _fact(
        kind: str,
        value: str,
        normalized_value: str,
        *,
        source_kind: str,
        source_node_id: str | None,
        source_sha256: str | None,
        publication_kind: str | None,
        tie_breaker_class: str = "semantic",
    ) -> ContextFact:
        return ContextFact(
            kind=kind,
            value=value,
            normalized_value=normalized_value,
            source_kind=source_kind,
            source_node_id=source_node_id,
            source_sha256=source_sha256,
            publication_kind=publication_kind,
            mention_context_id=source_node_id,
            tie_breaker_class=tie_breaker_class,
        )

    def normalize(
        self,
        text: str,
        *,
        source_kind: str,
        source_node_id: str | None = None,
        source_sha256: str | None = None,
    ) -> NormalizedDrawingContext:
        raw_text = str(text or "")
        compact = re.sub(r"\s+", " ", raw_text).strip()
        publication_kind = self._publication_kind(compact)
        facts: list[ContextFact] = []

        def add(kind: str, value: str, normalized: str) -> None:
            facts.append(
                self._fact(
                    kind,
                    value,
                    normalized,
                    source_kind=source_kind,
                    source_node_id=source_node_id,
                    source_sha256=source_sha256,
                    publication_kind=publication_kind,
                )
            )

        if publication_kind:
            add("publication_kind", "삽도" if publication_kind == "illustration" else "도면", publication_kind)

        for match in _POINT_PATTERN.finditer(compact):
            normalized = str(int(match.group(1)))
            add("site_point", match.group(0), normalized)
            # v1 compatibility alias.
            add("point", match.group(0), normalized)

        for match in _PERIOD_PATTERN.finditer(compact):
            add("period", match.group(0), match.group(0))

        for match in _GRID_PATTERN.finditer(compact):
            first = re.sub(r"\s+", "", match.group(1)).upper()
            second = re.sub(r"\s+", "", match.group(2)).upper()
            add("grid", match.group(0), f"{first}{second}")

        for match in _DIRECTION_PATTERN.finditer(compact):
            value = match.group(0)
            add("direction", value, _DIRECTION_NORMALIZATION.get(value, value))

        for match in _DRAWING_TYPE_PATTERN.finditer(compact):
            value = match.group(0)
            normalized = re.sub(r"[\s·ㆍ・]", "", value)
            if normalized.endswith("도"):
                normalized = normalized[:-1]
            normalized = _DRAWING_TYPE_NORMALIZATION.get(normalized, normalized)
            add("drawing_type", value, normalized)
            # Keep the useful component aliases consumed by v1 scoring.
            if normalized in {"평단면", "평입단면"}:
                add("drawing_type", value, "평면")
                add("drawing_type", value, "단면" if normalized == "평단면" else "입단면")

        occupied_feature_spans: list[tuple[int, int]] = []
        for match in _FEATURE_PATTERN.finditer(compact):
            number = str(int(match.group(1)))
            feature_type = match.group(2)
            occupied_feature_spans.append(match.span())
            add("feature_type", feature_type, feature_type)
            add("feature_number", match.group(1) + "호", number)
            # v1 compatibility alias.
            add("feature", match.group(0), f"{number}호:{feature_type}")

        for match in _FEATURE_TYPE_PATTERN.finditer(compact):
            if any(start <= match.start() < end for start, end in occupied_feature_spans):
                continue
            add("feature_type", match.group(0), match.group(0))

        for match in _CONTENT_TYPE_PATTERN.finditer(compact):
            add("content_type", match.group(0), "출토유물")

        map_matches = list(_MAP_TYPE_PATTERN.finditer(compact))
        for match in map_matches:
            value = match.group(0)
            normalized = "분포도" if value in {"주변유적분포도", "유적분포도"} else value
            add("map_type", value, normalized)
        if map_matches:
            for match in _YEAR_PATTERN.finditer(compact):
                add("year", match.group(0), match.group(1))

        for match in _SECTION_PATTERN.finditer(compact):
            left = match.group(1).upper()
            right = match.group(2).upper()
            if left != right:
                continue
            add("section_label", match.group(0), f"{left}-{right}'")

        token_values: set[str] = set()
        for token in _TOKEN_PATTERN.findall(compact):
            normalized = token.upper() if re.search(r"[A-Za-z]", token) else token
            token_values.add(normalized)
        for fact in facts:
            token_values.add(fact.normalized_value)

        deduped: dict[tuple[str, str, str | None], ContextFact] = {}
        for fact in facts:
            key = (fact.kind, fact.normalized_value, fact.source_node_id)
            deduped[key] = fact

        return NormalizedDrawingContext(
            raw_text=raw_text,
            tokens=tuple(sorted(token_values)),
            facts=tuple(deduped.values()),
            publication_kind=publication_kind,
        )
