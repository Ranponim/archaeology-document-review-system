import hashlib
import mimetypes
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile

from app.config import DATA_ROOT
from app.domain.models import StoredFile

ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/x-hwp",
        "application/vnd.hancom.hwp",
        "application/x-hwpx",
        "application/vnd.hancom.hwpx",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "application/postscript",
        "application/illustrator",
        "image/vnd.adobe.illustrator",
    }
)


class FileStore:
    def __init__(self, data_root: Path = DATA_ROOT) -> None:
        self._data_root = Path(data_root)

    def store_bytes(
        self,
        project_id: str | UUID,
        original_name: str,
        content: bytes,
        mime_type: str | None = None,
    ) -> StoredFile:
        sha256 = hashlib.sha256(content).hexdigest()
        filename = self._safe_filename(original_name)
        resolved_mime_type = mime_type or mimetypes.guess_type(filename)[0]
        self._validate_mime_type(resolved_mime_type)
        uri = Path("incoming") / str(project_id) / sha256 / filename
        destination = self._data_root / uri
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as stored_file:
                stored_file.write(content)
        except FileExistsError:
            if destination.read_bytes() != content:
                raise FileExistsError(f"A different file already exists at {uri}") from None

        return StoredFile(
            uri=uri.as_posix(),
            sha256=sha256,
            size_bytes=len(content),
            mime_type=resolved_mime_type,
            original_name=original_name,
        )

    def store_upload(self, project_id: UUID, upload: UploadFile) -> StoredFile:
        if upload.content_type not in ALLOWED_MIME_TYPES:
            raise ValueError("Unsupported file type")
        return self.store_bytes(
            project_id,
            upload.filename or "upload",
            upload.file.read(),
            upload.content_type,
        )

    @staticmethod
    def _safe_filename(original_name: str) -> str:
        filename = Path(original_name.replace("\\", "/")).name
        if filename in {"", ".", ".."} or "\x00" in filename:
            raise ValueError("A valid filename is required")
        return filename

    @staticmethod
    def _validate_mime_type(mime_type: str | None) -> None:
        if mime_type not in ALLOWED_MIME_TYPES:
            raise ValueError("Unsupported file type")
