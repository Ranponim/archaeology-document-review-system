from dataclasses import dataclass, field
import json
from typing import Any

from app.domain.review_models import EvidenceData


@dataclass(frozen=True, slots=True)
class ObjectEvidenceBundle:
    """Graph-derived evidence for one ArchaeologyObject (plan Task 7).

    Every field is populated by CanonicalRepository.get_object_evidence_bundle
    from real Neo4j traversal rows — never from a parallel in-memory structure.
    """

    object_id: str
    canonical_name: str
    text_claims: list[EvidenceData] = field(default_factory=list)
    references: list[EvidenceData] = field(default_factory=list)
    plate_claims: list[EvidenceData] = field(default_factory=list)
    drawing_claims: list[EvidenceData] = field(default_factory=list)
    visual_observations: list[EvidenceData] = field(default_factory=list)
    version_claims: list[EvidenceData] = field(default_factory=list)

    @property
    def evidences(self) -> list[EvidenceData]:
        """Flatten all claim families into one id-deduplicated evidence list."""
        merged: dict[str, EvidenceData] = {}
        for ev in (
            self.text_claims
            + self.references
            + self.plate_claims
            + self.drawing_claims
            + self.visual_observations
            + self.version_claims
        ):
            key = ev.id if ev.id else f"{ev.kind}:{ev.region_id}:{id(ev)}"
            merged.setdefault(key, ev)
        return list(merged.values())

    def has_graph_evidence(self) -> bool:
        return bool(self.evidences)


def evidence_from_row_props(props: dict[str, Any] | None) -> EvidenceData:
    """Reconstruct EvidenceData from stored Evidence node properties.

    Document-bound provenance (source_sha256 / document_version_id / page_id)
    is preserved exactly as stored; EvidenceData raises when a document-bound
    kind lacks any of them. Values that were persisted as JSON text are parsed
    back to their original shape; plain text stays text.
    """
    if not props:
        raise ValueError("cannot build EvidenceData from empty row properties")

    raw_value = props.get("value")
    value: Any = raw_value
    if isinstance(raw_value, str) and (raw_value.startswith("{") or raw_value.startswith("[")):
        try:
            value = json.loads(raw_value)
        except ValueError:
            value = raw_value

    bbox = props.get("bbox")
    if isinstance(bbox, list):
        bbox = tuple(bbox)

    return EvidenceData(
        id=str(props.get("id") or ""),
        kind=props.get("kind"),
        source_sha256=props.get("source_sha256"),
        document_version_id=props.get("document_version_id"),
        page_id=props.get("page_id"),
        region_id=props.get("region_id"),
        bbox=bbox,
        method=props.get("method") or "rule",
        analysis_run_id=props.get("analysis_run_id"),
        value=value if value is not None else "",
        rationale=props.get("rationale"),
        confidence=float(props.get("confidence") or 1.0),
        version_from=props.get("version_from"),
        version_to=props.get("version_to"),
        physical_page_from=props.get("physical_page_from"),
        physical_page_to=props.get("physical_page_to"),
        printed_page_from=props.get("printed_page_from"),
        printed_page_to=props.get("printed_page_to"),
        rule_name=props.get("rule_name"),
    )