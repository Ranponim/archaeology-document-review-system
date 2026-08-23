from __future__ import annotations

import re

from app.domain.drawing_evidence import ContextFact, NormalizedDrawingContext


_POINT_PATTERN = re.compile(r"(?:제\s*)?(\d+)\s*지점", re.IGNORECASE)
_GRID_PATTERN = re.compile(
    r"\b([A-Za-z]\s*\d+)\s*([A-Za-z]\s*\d+)\b",
    re.IGNORECASE,
)
_DIRECTION_PATTERN = re.compile(
    r"북동쪽|북서쪽|남동쪽|남서쪽|북동|북서|남동|남서|동쪽|서쪽|남쪽|북쪽|동|서|남|북"
)
_DRAWING_TYPE_PATTERN = re.compile(r"토층도?|단면도?|평면도?|입면도?|배치도?")
_FEATURE_PATTERN = re.compile(
    r"(\d+)\s*호\s*(수혈|주거지|구덩이|건물지|토광묘|옹관묘|주혈|묘|유구)"
)
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


class DrawingContextNormalizer:
    """Extract deterministic drawing-context facts from Korean archaeology text."""

    @staticmethod
    def _fact(
        kind: str,
        value: str,
        normalized_value: str,
        *,
        source_kind: str,
        source_node_id: str | None,
        source_sha256: str | None,
    ) -> ContextFact:
        return ContextFact(
            kind=kind,
            value=value,
            normalized_value=normalized_value,
            source_kind=source_kind,
            source_node_id=source_node_id,
            source_sha256=source_sha256,
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
        facts: list[ContextFact] = []

        for match in _POINT_PATTERN.finditer(compact):
            facts.append(
                self._fact(
                    "point",
                    match.group(0),
                    str(int(match.group(1))),
                    source_kind=source_kind,
                    source_node_id=source_node_id,
                    source_sha256=source_sha256,
                )
            )

        for match in _GRID_PATTERN.finditer(compact):
            first = re.sub(r"\s+", "", match.group(1)).upper()
            second = re.sub(r"\s+", "", match.group(2)).upper()
            facts.append(
                self._fact(
                    "grid",
                    match.group(0),
                    f"{first}{second}",
                    source_kind=source_kind,
                    source_node_id=source_node_id,
                    source_sha256=source_sha256,
                )
            )

        for match in _DIRECTION_PATTERN.finditer(compact):
            value = match.group(0)
            normalized = _DIRECTION_NORMALIZATION.get(value, value)
            facts.append(
                self._fact(
                    "direction",
                    value,
                    normalized,
                    source_kind=source_kind,
                    source_node_id=source_node_id,
                    source_sha256=source_sha256,
                )
            )

        for match in _DRAWING_TYPE_PATTERN.finditer(compact):
            value = match.group(0)
            normalized = value[:-1] if value.endswith("도") else value
            facts.append(
                self._fact(
                    "drawing_type",
                    value,
                    normalized,
                    source_kind=source_kind,
                    source_node_id=source_node_id,
                    source_sha256=source_sha256,
                )
            )

        for match in _FEATURE_PATTERN.finditer(compact):
            facts.append(
                self._fact(
                    "feature",
                    match.group(0),
                    f"{int(match.group(1))}호:{match.group(2)}",
                    source_kind=source_kind,
                    source_node_id=source_node_id,
                    source_sha256=source_sha256,
                )
            )

        for match in _SECTION_PATTERN.finditer(compact):
            left = match.group(1).upper()
            right = match.group(2).upper()
            if left != right:
                continue
            normalized = f"{left}-{right}'"
            facts.append(
                self._fact(
                    "section_label",
                    match.group(0),
                    normalized,
                    source_kind=source_kind,
                    source_node_id=source_node_id,
                    source_sha256=source_sha256,
                )
            )

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
        )
