from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredFile:
    uri: str
    sha256: str
    size_bytes: int
    mime_type: str
    original_name: str


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    internal_code: str | None


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    project_id: str
    kind: str = "report_body"
    title: str = ""


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    id: str
    document_id: str
    analysis_run_id: str
    uri: str
    sha256: str
    size_bytes: int
    mime_type: str
    original_name: str
    stage: str


@dataclass(frozen=True, slots=True)
class VersionInput:
    version_id: str
    document_id: str
    project_id: str
    kind: str
    stage: str
    uri: str
    sha256: str
    mime_type: str = "application/pdf"


from app.domain.review_round import ReviewRound  # noqa: E402


