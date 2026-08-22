from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib


class ReferenceCorpusStatus(str, Enum):
    STAGING = "staging"
    CONVERTING = "converting"
    VALIDATING = "validating"
    CANONICALIZING = "canonicalizing"
    GRAPH_VALIDATING = "graph_validating"
    READY = "ready"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.READY, self.FAILED}


class ReferenceCorpusFailureCode(str, Enum):
    ADOBE_UNAVAILABLE = "ADOBE_UNAVAILABLE"
    CONVERSION_TIMEOUT = "CONVERSION_TIMEOUT"
    CONVERSION_FAILED = "CONVERSION_FAILED"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    LINK_MISSING = "LINK_MISSING"
    IDENTIFIER_UNRESOLVED = "IDENTIFIER_UNRESOLVED"
    AMBIGUOUS_IDENTIFIER = "AMBIGUOUS_IDENTIFIER"
    DUPLICATE_CANONICAL_IDENTIFIER = "DUPLICATE_CANONICAL_IDENTIFIER"
    PROVENANCE_INCOMPLETE = "PROVENANCE_INCOMPLETE"
    EMPTY_CANONICAL_GRAPH = "EMPTY_CANONICAL_GRAPH"
    GRAPH_INVALID = "GRAPH_INVALID"


@dataclass(frozen=True, slots=True)
class ReferenceCorpusData:
    id: str
    project_id: str
    revision: int
    status: ReferenceCorpusStatus
    source_set_hash: str = ""
    converter_version: str = ""
    manifest_schema_version: str = ""
    canonicalizer_version: str = ""
    build_identity: str = ""
    created_at: str | None = None
    ready_at: str | None = None
    failure_code: ReferenceCorpusFailureCode | str | None = None


@dataclass(frozen=True, slots=True)
class DerivedArtifactData:
    id: str
    reference_corpus_id: str
    artifact_type: str
    uri: str
    sha256: str
    mime_type: str
    source_asset_id: str | None = None
    converter_version: str = ""
    created_at: str | None = None


def compute_build_identity(
    source_set_hash: str,
    converter_version: str,
    manifest_schema_version: str,
    canonicalizer_version: str,
) -> str:
    payload = "\0".join(
        (
            source_set_hash,
            converter_version,
            manifest_schema_version,
            canonicalizer_version,
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
