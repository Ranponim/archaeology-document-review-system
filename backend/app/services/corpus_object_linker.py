from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from app.domain.canonical_models import ArchaeologyObjectData


@dataclass(frozen=True, slots=True)
class CorpusDepictsLink:
    asset_label: str
    asset_id: str
    object_id: str


@dataclass(frozen=True, slots=True)
class LinkResult:
    created: list[CorpusDepictsLink] = field(default_factory=list)
    ambiguous: list[tuple[str, str]] = field(default_factory=list)
    unmatched: list[tuple[str, str]] = field(default_factory=list)


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def _strong_identifiers(obj: ArchaeologyObjectData) -> tuple[str, ...]:
    identifiers: list[str] = []
    canonical = _normalize(obj.canonical_name)
    if canonical:
        identifiers.append(canonical)
    point = _normalize(obj.point)
    number = _normalize(obj.number)
    type_ = _normalize(obj.type)
    if point and number and type_:
        combined = f"{point}{number}{type_}"
        if combined not in identifiers:
            identifiers.append(combined)
    return tuple(identifiers)


class CorpusObjectLinker:
    """Create corpus-scoped DEPICTS only for unique strong identifiers.

    Plate/Drawing filenames and weak number/type fragments have no authority.
    The repository supplies visual descriptors rooted at one project+corpus;
    this service performs deterministic matching and asks the repository to
    persist only unique, strong matches.
    """

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def link(
        self,
        project_id: str,
        corpus_id: str,
        objects: list[ArchaeologyObjectData],
    ) -> LinkResult:
        descriptors = self.repository.list_visual_descriptors(project_id, corpus_id)
        created: list[CorpusDepictsLink] = []
        ambiguous: list[tuple[str, str]] = []
        unmatched: list[tuple[str, str]] = []

        object_identifiers = {
            obj.object_id: _strong_identifiers(obj)
            for obj in objects
            if obj.project_id in {None, project_id}
        }

        for descriptor in descriptors:
            label = str(descriptor.get("label") or "")
            asset_id = str(descriptor.get("id") or "")
            text = _normalize(str(descriptor.get("text") or ""))
            if not label or not asset_id or not text:
                if label and asset_id:
                    unmatched.append((label, asset_id))
                continue

            matches: list[str] = []
            for object_id, identifiers in object_identifiers.items():
                if any(identifier and identifier in text for identifier in identifiers):
                    matches.append(object_id)
            matches = sorted(set(matches))

            if len(matches) == 1:
                created.append(CorpusDepictsLink(label, asset_id, matches[0]))
            elif len(matches) > 1:
                ambiguous.append((label, asset_id))
            else:
                unmatched.append((label, asset_id))

        if created:
            self.repository.link_depicts(project_id, corpus_id, created)
        if ambiguous:
            self.repository.mark_depicts_ambiguous(project_id, corpus_id, ambiguous)

        return LinkResult(
            created=created,
            ambiguous=ambiguous,
            unmatched=unmatched,
        )
