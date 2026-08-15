from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredFile:
    uri: str
    sha256: str
    size_bytes: int
    mime_type: str
    original_name: str
