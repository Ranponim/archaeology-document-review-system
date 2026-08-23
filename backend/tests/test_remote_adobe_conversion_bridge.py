from __future__ import annotations

from dataclasses import asdict
import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import app.services.adobe_conversion_client as adobe
from app.services.reference_corpus_service import ReferenceCorpusService


def _response_zip(*, source_asset_id: str, source_sha256: str) -> bytes:
    artifact = b"%PDF-1.4\npreview\n"
    artifact_sha = hashlib.sha256(artifact).hexdigest()
    result = {
        "converterVersion": adobe.ADOBE_WINDOWS_AGENT_VERSION,
        "manifest": {
            "schemaVersion": 1,
            "application": "indesign",
            "applicationVersion": "21.0",
            "sourceAssetId": source_asset_id,
            "sourceSha256": source_sha256,
            "pages": [{"index": 0, "label": "1", "textFrames": [], "graphics": []}],
            "artboards": [],
            "artifacts": [],
        },
        "artifacts": [
            {
                "artifactType": "pdf",
                "archivePath": "artifacts/preview.pdf",
                "sha256": artifact_sha,
                "mimeType": "application/pdf",
            }
        ],
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("result.json", json.dumps(result))
        archive.writestr("artifacts/preview.pdf", artifact)
    return buffer.getvalue()


def test_conversion_request_carries_workspace_and_source_relative_path(tmp_path):
    workspace = tmp_path / "workspace"
    request = adobe.ConversionRequest(
        project_id="p1",
        reference_corpus_id="c1",
        source_asset_id="asset-indd",
        source_path=str(workspace / "Job" / "book.indd"),
        source_role="plate_layout",
        output_dir=str(tmp_path / "out"),
        workspace_root=str(workspace),
        source_relative_path="Job/book.indd",
    )

    payload = asdict(request)
    assert payload["workspace_root"] == str(workspace)
    assert payload["source_relative_path"] == "Job/book.indd"


def test_remote_client_archives_complete_workspace_and_materializes_artifacts(tmp_path):
    remote_cls = getattr(adobe, "RemoteAdobeConversionClient", None)
    assert remote_cls is not None, "RemoteAdobeConversionClient is required"

    workspace = tmp_path / "workspace"
    (workspace / "Job" / "Links").mkdir(parents=True)
    (workspace / "Drawings").mkdir(parents=True)
    indd = workspace / "Job" / "book.indd"
    link = workspace / "Job" / "Links" / "photo.jpg"
    ai = workspace / "Drawings" / "plan.ai"
    indd.write_bytes(b"indd-source")
    link.write_bytes(b"jpeg-source")
    ai.write_bytes(b"ai-source")
    source_sha = hashlib.sha256(indd.read_bytes()).hexdigest()

    seen: dict[str, object] = {}

    def transport(url: str, payload: bytes, headers: dict[str, str], timeout: int) -> bytes:
        seen["url"] = url
        seen["headers"] = headers
        seen["timeout"] = timeout
        with ZipFile(BytesIO(payload), "r") as archive:
            names = set(archive.namelist())
            seen["names"] = names
            request_payload = json.loads(archive.read("request.json"))
            seen["request"] = request_payload
        return _response_zip(source_asset_id="asset-indd", source_sha256=source_sha)

    output = tmp_path / "output"
    client = remote_cls(
        "http://adobe-windows:8765",
        token="secret-token",
        timeout_seconds=123,
        transport=transport,
    )
    result = client.convert(
        adobe.ConversionRequest(
            project_id="p1",
            reference_corpus_id="c1",
            source_asset_id="asset-indd",
            source_path=str(indd),
            source_role="plate_layout",
            output_dir=str(output),
            workspace_root=str(workspace),
            source_relative_path="Job/book.indd",
        )
    )

    assert seen["url"] == "http://adobe-windows:8765/convert"
    assert seen["headers"] == {
        "Content-Type": "application/zip",
        "Authorization": "Bearer secret-token",
    }
    assert seen["timeout"] == 123
    assert seen["names"] == {
        "request.json",
        "workspace/Job/book.indd",
        "workspace/Job/Links/photo.jpg",
        "workspace/Drawings/plan.ai",
    }
    request_payload = seen["request"]
    assert request_payload["sourceRelativePath"] == "Job/book.indd"
    assert request_payload["workspaceRoot"] == "workspace"
    assert result.manifest.source_asset_id == "asset-indd"
    assert len(result.artifacts) == 1
    artifact_path = Path(result.artifacts[0].path)
    assert artifact_path.is_file()
    assert artifact_path.is_relative_to(output.resolve())
    assert artifact_path.read_bytes().startswith(b"%PDF-1.4")


def test_remote_client_rejects_workspace_escape_before_transport(tmp_path):
    remote_cls = getattr(adobe, "RemoteAdobeConversionClient", None)
    assert remote_cls is not None, "RemoteAdobeConversionClient is required"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "outside.indd"
    source.write_bytes(b"outside")
    called = False

    def transport(*_args, **_kwargs):
        nonlocal called
        called = True
        return b""

    client = remote_cls("http://adobe-windows:8765", transport=transport)
    with pytest.raises(adobe.AdobeConversionError, match="workspace"):
        client.convert(
            adobe.ConversionRequest(
                project_id="p1",
                reference_corpus_id="c1",
                source_asset_id="asset-indd",
                source_path=str(source),
                source_role="plate_layout",
                output_dir=str(tmp_path / "out"),
                workspace_root=str(workspace),
                source_relative_path="../outside.indd",
            )
        )
    assert called is False


def test_source_set_hash_includes_relative_path():
    base = [{"role": "plate_link", "sha256": "same", "relative_path": "Job/Links/a.jpg"}]
    moved = [{"role": "plate_link", "sha256": "same", "relative_path": "Job/Other/a.jpg"}]
    assert ReferenceCorpusService._source_set_hash(base) != ReferenceCorpusService._source_set_hash(moved)


def test_build_adobe_conversion_client_uses_remote_url(monkeypatch):
    builder = getattr(adobe, "build_adobe_conversion_client", None)
    assert builder is not None, "build_adobe_conversion_client is required"
    monkeypatch.setenv("ADOBE_CONVERTER_URL", "http://windows-host:8765")
    monkeypatch.setenv("ADOBE_CONVERTER_TOKEN", "token")
    client = builder()
    assert client.__class__.__name__ == "RemoteAdobeConversionClient"
    assert client.version == adobe.ADOBE_WINDOWS_AGENT_VERSION
