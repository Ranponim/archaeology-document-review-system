from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextFact:
    kind: str
    value: str
    normalized_value: str
    source_kind: str
    source_node_id: str | None = None
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedDrawingContext:
    raw_text: str
    tokens: tuple[str, ...]
    facts: tuple[ContextFact, ...]
