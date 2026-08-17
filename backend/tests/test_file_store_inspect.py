from uuid import uuid4

from app.services.file_store import FileStore


def test_inspect_reports_present_for_stored_file(tmp_path):
    store = FileStore(tmp_path)
    stored = store.store_bytes(uuid4(), "body.pdf", b"PDF", "application/pdf")
    assert store.inspect(stored.uri) == "present"


def test_inspect_reports_missing_without_creating_anything(tmp_path):
    store = FileStore(tmp_path)
    assert store.inspect("incoming/00000000-0000-0000-0000-000000000001/abc/body.pdf") == "missing"
    assert not (tmp_path / "incoming").exists()


def test_inspect_rejects_escape_and_symlink_paths_as_unknown(tmp_path):
    store = FileStore(tmp_path)
    assert store.inspect("../outside/private.pdf") == "unknown"

    outside = tmp_path / "outside"
    outside.mkdir()
    incoming = tmp_path / "incoming"
    incoming.symlink_to(outside, target_is_directory=True)
    assert store.inspect("incoming/file.pdf") == "unknown"
