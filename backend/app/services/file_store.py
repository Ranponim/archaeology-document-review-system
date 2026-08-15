import hashlib
import mimetypes
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import DATA_ROOT
from app.domain.models import StoredFile

MIME_TYPES_BY_SUFFIX = {
    ".pdf": frozenset({"application/pdf"}),
    ".hwp": frozenset({"application/x-hwp", "application/vnd.hancom.hwp"}),
    ".hwpx": frozenset({"application/x-hwpx", "application/vnd.hancom.hwpx"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".png": frozenset({"image/png"}),
    ".tif": frozenset({"image/tiff"}),
    ".tiff": frozenset({"image/tiff"}),
    ".ai": frozenset(
        {
            "application/postscript",
            "application/illustrator",
            "image/vnd.adobe.illustrator",
        }
    ),
}

DEFAULT_MIME_TYPE_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".hwp": "application/x-hwp",
    ".hwpx": "application/x-hwpx",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".ai": "application/postscript",
}

WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
WINDOWS_INVALID_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')


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
        normalized_project_id = self._normalized_project_id(project_id)
        sha256 = hashlib.sha256(content).hexdigest()
        filename = self._safe_filename(original_name)
        resolved_mime_type = self._resolved_mime_type(filename, mime_type)
        uri = Path("incoming") / str(normalized_project_id) / sha256 / filename
        destination = self._data_root / uri
        self._reject_symlink_components(uri)
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

    async def store_upload(self, project_id: UUID, upload: UploadFile) -> StoredFile:
        """Read an upload asynchronously and store its bytes off the event loop."""
        filename = upload.filename or ""
        self._safe_filename(filename)
        self._resolved_mime_type(filename, upload.content_type)
        content = await upload.read()
        return await run_in_threadpool(
            self.store_bytes,
            project_id,
            filename,
            content,
            upload.content_type,
        )

    @staticmethod
    def _safe_filename(original_name: str) -> str:
        if (
            not original_name
            or original_name in {".", ".."}
            or original_name[-1] in {".", " "}
            or any(
                character in WINDOWS_INVALID_FILENAME_CHARACTERS
                or ord(character) < 32
                or ord(character) == 127
                for character in original_name
            )
        ):
            raise ValueError("A valid filename is required")
        device_name = original_name.split(".", maxsplit=1)[0].rstrip(" ").upper()
        if device_name in WINDOWS_RESERVED_NAMES:
            raise ValueError("A valid filename is required")
        return original_name

    @staticmethod
    def _normalized_project_id(project_id: str | UUID) -> UUID:
        try:
            return UUID(str(project_id))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("A valid project ID is required") from None

    @staticmethod
    def _resolved_mime_type(filename: str, mime_type: str | None) -> str:
        suffix = Path(filename).suffix.lower()
        allowed_mime_types = MIME_TYPES_BY_SUFFIX.get(suffix)
        if not allowed_mime_types:
            raise ValueError("Unsupported file type")
        resolved_mime_type = mime_type or mimetypes.guess_type(filename)[0]
        resolved_mime_type = resolved_mime_type or DEFAULT_MIME_TYPE_BY_SUFFIX[suffix]
        if resolved_mime_type not in allowed_mime_types:
            raise ValueError("Unsupported file type")
        return resolved_mime_type

    def _reject_symlink_components(self, uri: Path) -> None:
        path = self._data_root
        for component in uri.parts:
            path /= component
            if path.is_symlink():
                raise ValueError("Symlinked storage paths are not allowed")
