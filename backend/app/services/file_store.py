import hashlib
import mimetypes
import os
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
DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
FILE_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW


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
        self._write_once(uri, content)

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

    def _write_once(self, uri: Path, content: bytes) -> None:
        directory_fds: list[int] = []
        file_fds: list[int] = []
        try:
            directory_fd = self._open_data_root()
            directory_fds.append(directory_fd)
            for component in uri.parts[:-1]:
                child_fd = self._open_or_create_directory(directory_fd, component)
                directory_fd = child_fd
                directory_fds.append(directory_fd)

            try:
                file_fd = os.open(uri.name, FILE_CREATE_FLAGS, 0o600, dir_fd=directory_fd)
                file_fds.append(file_fd)
            except FileExistsError:
                if self._read_existing_file(directory_fd, uri.name) != content:
                    raise FileExistsError(f"A different file already exists at {uri}") from None
            else:
                self._write_all(file_fd, content)
        finally:
            for file_fd in reversed(file_fds):
                os.close(file_fd)
            for directory_fd in reversed(directory_fds):
                os.close(directory_fd)

    def _open_data_root(self) -> int:
        self._data_root.mkdir(parents=True, exist_ok=True)
        try:
            return os.open(self._data_root, DIRECTORY_OPEN_FLAGS)
        except OSError:
            raise ValueError("A valid data root is required") from None

    @staticmethod
    def _open_or_create_directory(parent_fd: int, name: str) -> int:
        try:
            return os.open(name, DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            try:
                return os.open(name, DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)
            except OSError:
                raise ValueError("Symlinked storage paths are not allowed") from None
        except OSError:
            raise ValueError("Symlinked storage paths are not allowed") from None

    @staticmethod
    def _read_existing_file(directory_fd: int, name: str) -> bytes:
        try:
            file_fd = os.open(name, FILE_READ_FLAGS, dir_fd=directory_fd)
        except OSError:
            raise ValueError("Symlinked storage paths are not allowed") from None
        try:
            chunks = bytearray()
            while chunk := os.read(file_fd, 1024 * 1024):
                chunks.extend(chunk)
            return bytes(chunks)
        finally:
            os.close(file_fd)

    @staticmethod
    def _write_all(file_fd: int, content: bytes) -> None:
        remaining = memoryview(content)
        while remaining:
            written = os.write(file_fd, remaining)
            remaining = remaining[written:]
