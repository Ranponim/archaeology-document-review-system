import hashlib
from io import BytesIO
from uuid import uuid4

import pytest
from app.services.file_store import FileStore
from fastapi import UploadFile
from starlette.datastructures import Headers


def test_store_bytes_preserves_bytes_and_returns_content_addressed_uri(tmp_path):
    stored = FileStore(tmp_path).store_bytes("p1", "보고서.pdf", b"PDF")

    assert stored.sha256 == hashlib.sha256(b"PDF").hexdigest()
    assert (tmp_path / stored.uri).read_bytes() == b"PDF"


def test_store_bytes_returns_existing_metadata_for_duplicate_content(tmp_path):
    store = FileStore(tmp_path)

    first = store.store_bytes("p1", "report.pdf", b"PDF")
    duplicate = store.store_bytes("p1", "report.pdf", b"PDF")

    assert duplicate == first


def test_store_bytes_never_overwrites_different_existing_bytes(tmp_path):
    store = FileStore(tmp_path)
    stored = store.store_bytes("p1", "report.pdf", b"PDF")
    (tmp_path / stored.uri).write_bytes(b"UNIQUE-EXISTING-BYTES")

    with pytest.raises(FileExistsError) as error:
        store.store_bytes("p1", "report.pdf", b"PDF")

    assert "PDF" not in str(error.value)
    assert "UNIQUE-EXISTING-BYTES" not in str(error.value)


def test_store_upload_rejects_disallowed_mime_without_writing_source_bytes(tmp_path):
    upload = UploadFile(
        file=BytesIO(b"PRIVATE-ORIGINAL-BYTES"),
        filename="malware.exe",
        headers=Headers({"content-type": "application/x-msdownload"}),
    )

    with pytest.raises(ValueError) as error:
        FileStore(tmp_path).store_upload(uuid4(), upload)

    assert "PRIVATE-ORIGINAL-BYTES" not in str(error.value)
    assert list(tmp_path.rglob("*")) == []


def test_store_upload_preserves_the_allowed_declared_mime_type(tmp_path):
    upload = UploadFile(
        file=BytesIO(b"HWP"),
        filename="report.hwp",
        headers=Headers({"content-type": "application/x-hwp"}),
    )

    stored = FileStore(tmp_path).store_upload(uuid4(), upload)

    assert stored.mime_type == "application/x-hwp"
    assert (tmp_path / stored.uri).read_bytes() == b"HWP"


def test_store_bytes_uses_only_the_filename_component_for_windows_paths(tmp_path):
    stored = FileStore(tmp_path).store_bytes("p1", r"..\private\report.pdf", b"PDF")

    assert stored.uri.endswith("/report.pdf")
    assert (tmp_path / stored.uri).read_bytes() == b"PDF"


def test_store_bytes_rejects_unknown_file_types_before_writing_bytes(tmp_path):
    with pytest.raises(ValueError) as error:
        FileStore(tmp_path).store_bytes("p1", "malware.exe", b"PRIVATE-ORIGINAL-BYTES")

    assert "PRIVATE-ORIGINAL-BYTES" not in str(error.value)
    assert list(tmp_path.rglob("*")) == []


def test_store_bytes_rejects_an_empty_safe_filename_before_writing_bytes(tmp_path):
    with pytest.raises(ValueError) as error:
        FileStore(tmp_path).store_bytes(
            "p1", "..\\", b"PRIVATE-ORIGINAL-BYTES", "application/pdf"
        )

    assert "PRIVATE-ORIGINAL-BYTES" not in str(error.value)
    assert list(tmp_path.rglob("*")) == []
