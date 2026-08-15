import hashlib
import threading
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from app.services.file_store import FileStore
from fastapi import UploadFile
from starlette.datastructures import Headers


def test_store_bytes_preserves_bytes_and_returns_content_addressed_uri(tmp_path):
    stored = FileStore(tmp_path).store_bytes(uuid4(), "보고서.pdf", b"PDF")

    assert stored.sha256 == hashlib.sha256(b"PDF").hexdigest()
    assert (tmp_path / stored.uri).read_bytes() == b"PDF"


def test_store_bytes_returns_existing_metadata_for_duplicate_content(tmp_path):
    store = FileStore(tmp_path)
    project_id = uuid4()

    first = store.store_bytes(project_id, "report.pdf", b"PDF")
    duplicate = store.store_bytes(project_id, "report.pdf", b"PDF")

    assert duplicate == first


def test_store_bytes_never_overwrites_different_existing_bytes(tmp_path):
    store = FileStore(tmp_path)
    project_id = uuid4()
    stored = store.store_bytes(project_id, "report.pdf", b"PDF")
    (tmp_path / stored.uri).write_bytes(b"UNIQUE-EXISTING-BYTES")

    with pytest.raises(FileExistsError) as error:
        store.store_bytes(project_id, "report.pdf", b"PDF")

    assert "PDF" not in str(error.value)
    assert "UNIQUE-EXISTING-BYTES" not in str(error.value)


@pytest.mark.anyio
async def test_store_upload_rejects_disallowed_mime_without_writing_source_bytes(tmp_path):
    upload = UploadFile(
        file=BytesIO(b"PRIVATE-ORIGINAL-BYTES"),
        filename="malware.exe",
        headers=Headers({"content-type": "application/x-msdownload"}),
    )

    with pytest.raises(ValueError) as error:
        await FileStore(tmp_path).store_upload(uuid4(), upload)

    assert "PRIVATE-ORIGINAL-BYTES" not in str(error.value)
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.anyio
async def test_store_upload_preserves_the_allowed_declared_mime_type(tmp_path):
    upload = UploadFile(
        file=BytesIO(b"HWP"),
        filename="report.hwp",
        headers=Headers({"content-type": "application/x-hwp"}),
    )

    stored = await FileStore(tmp_path).store_upload(uuid4(), upload)

    assert stored.mime_type == "application/x-hwp"
    assert (tmp_path / stored.uri).read_bytes() == b"HWP"


def test_store_bytes_rejects_path_components_in_original_filenames(tmp_path):
    with pytest.raises(ValueError):
        FileStore(tmp_path).store_bytes(uuid4(), r"..\private\report.pdf", b"PDF")

    assert list(tmp_path.rglob("*")) == []


def test_store_bytes_rejects_unknown_file_types_before_writing_bytes(tmp_path):
    with pytest.raises(ValueError) as error:
        FileStore(tmp_path).store_bytes(
            uuid4(), "malware.exe", b"PRIVATE-ORIGINAL-BYTES"
        )

    assert "PRIVATE-ORIGINAL-BYTES" not in str(error.value)
    assert list(tmp_path.rglob("*")) == []


def test_store_bytes_rejects_an_empty_safe_filename_before_writing_bytes(tmp_path):
    with pytest.raises(ValueError) as error:
        FileStore(tmp_path).store_bytes(
            uuid4(), "..\\", b"PRIVATE-ORIGINAL-BYTES", "application/pdf"
        )

    assert "PRIVATE-ORIGINAL-BYTES" not in str(error.value)
    assert list(tmp_path.rglob("*")) == []


def test_store_bytes_rejects_non_uuid_project_ids_before_constructing_a_path(tmp_path):
    outside = tmp_path.parent / "outside"

    with pytest.raises(ValueError):
        FileStore(tmp_path).store_bytes("../../outside", "report.pdf", b"PDF")

    assert not outside.exists()


def test_store_bytes_accepts_a_uuid_string_and_normalizes_the_path_component(tmp_path):
    project_id = uuid4()

    stored = FileStore(tmp_path).store_bytes(str(project_id), "report.pdf", b"PDF")

    assert stored.uri.split("/")[1] == str(project_id)


def test_store_bytes_rejects_an_incoming_symlink_before_it_can_escape_data_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "incoming").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        FileStore(tmp_path).store_bytes(uuid4(), "report.pdf", b"PDF")

    assert list(outside.rglob("*")) == []


@pytest.mark.parametrize(
    "filename",
    [
        "CON.pdf",
        "report<draft>.pdf",
        'report"draft.pdf',
        "report: draft.pdf",
        "report|draft.pdf",
        "report?draft.pdf",
        "report*draft.pdf",
        "report/draft.pdf",
        r"report\draft.pdf",
        "report.pdf ",
        "report.pdf.",
        "report\x01.pdf",
        "report\x7f.pdf",
    ],
)
def test_store_bytes_rejects_windows_invalid_filenames(tmp_path, filename):
    with pytest.raises(ValueError):
        FileStore(tmp_path).store_bytes(uuid4(), filename, b"PDF")

    assert list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize(
    ("filename", "mime_type"),
    [
        ("drawing.eps", "application/postscript"),
        ("drawing.ps", "application/postscript"),
        ("report.pdf", "image/jpeg"),
    ],
)
def test_store_bytes_rejects_mime_types_incompatible_with_the_filename(
    tmp_path, filename, mime_type
):
    with pytest.raises(ValueError):
        FileStore(tmp_path).store_bytes(uuid4(), filename, b"PDF", mime_type)

    assert list(tmp_path.rglob("*")) == []


def test_store_bytes_allows_an_illustrator_mime_only_for_an_ai_filename(tmp_path):
    stored = FileStore(tmp_path).store_bytes(
        uuid4(), "drawing.ai", b"AI", "application/postscript"
    )

    assert stored.mime_type == "application/postscript"
    assert (tmp_path / stored.uri).read_bytes() == b"AI"


@pytest.mark.anyio
async def test_store_upload_is_awaitable_and_preserves_bytes(tmp_path):
    project_id = uuid4()
    upload = UploadFile(
        file=BytesIO(b"PDF"),
        filename="report.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )

    stored = await FileStore(tmp_path).store_upload(project_id, upload)

    assert (tmp_path / stored.uri).read_bytes() == b"PDF"
    assert stored.uri.split("/")[1] == str(UUID(str(project_id)))


@pytest.mark.anyio
async def test_store_upload_runs_sync_storage_off_the_event_loop(tmp_path):
    class ThreadCapturingFileStore(FileStore):
        storage_thread_id: int | None = None

        def store_bytes(self, *args, **kwargs):
            self.storage_thread_id = threading.get_ident()
            return super().store_bytes(*args, **kwargs)

    store = ThreadCapturingFileStore(tmp_path)
    event_loop_thread_id = threading.get_ident()
    upload = UploadFile(
        file=BytesIO(b"PDF"),
        filename="report.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )

    await store.store_upload(uuid4(), upload)

    assert store.storage_thread_id != event_loop_thread_id
