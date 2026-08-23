#!/usr/bin/env python3
"""HTTP bridge that exposes the Windows Adobe COM converter to Linux/Docker.

Protocol
========
GET /health
    Returns a small JSON health document. This does not launch Adobe.

POST /convert
    Request body is application/zip with:
      request.json
      workspace/<original relative tree...>

    The server safely extracts the workspace, rewrites only machine-local paths,
    invokes the existing Windows COM agent, and returns application/zip with:
      result.json
      artifacts/<verified converter outputs...>

Publication identity is never inferred by this server. The existing JSX +
agent manifest is the only Adobe structural output and ReferenceCanonicalizer
remains the authority for Plate/Drawing identity.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import Any
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

import agent


BRIDGE_VERSION = "adobe-windows-bridge-v1"
DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024


class BridgeError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        self.code = code
        self.status = status
        super().__init__(message)


def _safe_zip_name(value: str, *, prefix: str | None = None) -> PurePosixPath:
    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BridgeError("WORKSPACE_INVALID", "unsafe archive path")
    if prefix is not None and (not path.parts or path.parts[0] != prefix):
        raise BridgeError("WORKSPACE_INVALID", "archive member is outside workspace")
    return path


def _is_symlink(info: ZipInfo) -> bool:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(unix_mode)


def _safe_extract(payload: bytes, destination: Path) -> dict[str, Any]:
    try:
        with ZipFile(BytesIO(payload), "r") as archive:
            names = set(archive.namelist())
            if "request.json" not in names:
                raise BridgeError("MANIFEST_INVALID", "request.json is required")
            try:
                request = json.loads(archive.read("request.json").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                raise BridgeError("MANIFEST_INVALID", "request.json is invalid") from error
            if not isinstance(request, dict):
                raise BridgeError("MANIFEST_INVALID", "request.json must contain an object")

            workspace = destination / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            for info in archive.infolist():
                if info.filename == "request.json" or info.is_dir():
                    continue
                path = _safe_zip_name(info.filename, prefix="workspace")
                if _is_symlink(info):
                    raise BridgeError("WORKSPACE_INVALID", "workspace symlinks are not allowed")
                target = destination.joinpath(*path.parts).resolve()
                root = workspace.resolve()
                try:
                    target.relative_to(root)
                except ValueError as error:
                    raise BridgeError("WORKSPACE_INVALID", "archive member escaped workspace") from error
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            return request
    except BridgeError:
        raise
    except BadZipFile as error:
        raise BridgeError("MANIFEST_INVALID", "request body is not a valid ZIP") from error


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise BridgeError("MANIFEST_INVALID", f"{key} is required")
    return value


def _agent_request(request: dict[str, Any], root: Path) -> dict[str, Any]:
    workspace_root = _required_string(request, "workspaceRoot")
    if workspace_root != "workspace":
        raise BridgeError("WORKSPACE_INVALID", "workspaceRoot must be 'workspace'")
    source_relative = _safe_zip_name(_required_string(request, "sourceRelativePath"))
    workspace = (root / workspace_root).resolve()
    source = workspace.joinpath(*source_relative.parts).resolve()
    try:
        source.relative_to(workspace)
    except ValueError as error:
        raise BridgeError("WORKSPACE_INVALID", "source escaped workspace") from error
    if not source.is_file():
        raise BridgeError("CONVERSION_FAILED", "selected Adobe source is missing")

    output = (root / "output").resolve()
    output.mkdir(parents=True, exist_ok=True)
    return {
        "project_id": _required_string(request, "projectId"),
        "reference_corpus_id": _required_string(request, "referenceCorpusId"),
        "source_asset_id": _required_string(request, "sourceAssetId"),
        "source_path": str(source),
        "source_role": _required_string(request, "sourceRole"),
        "output_dir": str(output),
        "manifest_schema_version": int(request.get("manifestSchemaVersion") or 1),
    }


def _artifact_name(index: int, path: Path) -> str:
    suffix = path.suffix.lower()
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in path.name)
    if not safe_name:
        safe_name = f"artifact-{index}{suffix}"
    return f"artifacts/{index:04d}-{safe_name}"


def _package_result(result: dict[str, Any]) -> bytes:
    packaged: list[dict[str, Any]] = []
    artifact_payloads: list[tuple[str, bytes]] = []
    for index, item in enumerate(result.get("artifacts", []), start=1):
        if not isinstance(item, dict):
            continue
        source = Path(str(item.get("path") or "")).resolve()
        if not source.is_file():
            raise BridgeError("CONVERSION_FAILED", "converter artifact is missing", 500)
        data = source.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        declared_sha = str(item.get("sha256") or "")
        if declared_sha and declared_sha != sha:
            raise BridgeError("CONVERSION_FAILED", "converter artifact hash mismatch", 500)
        archive_path = _artifact_name(index, source)
        packaged.append(
            {
                "artifactType": str(item.get("artifactType") or item.get("type") or source.suffix.lstrip(".") or "render"),
                "archivePath": archive_path,
                "sha256": sha,
                "mimeType": str(item.get("mimeType") or "application/octet-stream"),
            }
        )
        artifact_payloads.append((archive_path, data))

    public_result = {
        "converterVersion": str(result.get("converterVersion") or agent.CONVERTER_VERSION),
        "bridgeVersion": BRIDGE_VERSION,
        "manifest": result.get("manifest"),
        "artifacts": packaged,
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr("result.json", json.dumps(public_result, ensure_ascii=False, sort_keys=True))
        for archive_path, data in artifact_payloads:
            archive.writestr(archive_path, data)
    return buffer.getvalue()


def convert_archive(payload: bytes) -> bytes:
    """Pure protocol entry point, intentionally unit-testable without HTTP."""
    with tempfile.TemporaryDirectory(prefix="archaeology-adobe-bridge-") as temp_dir:
        root = Path(temp_dir)
        request = _safe_extract(payload, root)
        local_request = _agent_request(request, root)
        request_path = root / "agent-request.json"
        request_path.write_text(
            json.dumps(local_request, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        try:
            result = agent.convert(request_path)
        except agent.AgentError as error:
            status = 503 if error.code == "ADOBE_UNAVAILABLE" else 422
            raise BridgeError(error.code, str(error), status) from error
        return _package_result(result)


def _authorized(header: str | None) -> bool:
    expected = os.environ.get("ADOBE_CONVERTER_TOKEN") or ""
    if not expected:
        return True
    supplied = str(header or "")
    prefix = "Bearer "
    if not supplied.startswith(prefix):
        return False
    return hmac.compare_digest(supplied[len(prefix):], expected)


class AdobeBridgeHandler(BaseHTTPRequestHandler):
    server_version = "ArchaeologyAdobeBridge/1"

    def _json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path != "/health":
            self._json(404, {"errorCode": "NOT_FOUND"})
            return
        self._json(
            200,
            {
                "status": "ok",
                "bridgeVersion": BRIDGE_VERSION,
                "converterVersion": agent.CONVERTER_VERSION,
            },
        )

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path != "/convert":
            self._json(404, {"errorCode": "NOT_FOUND"})
            return
        if not _authorized(self.headers.get("Authorization")):
            self._json(401, {"errorCode": "UNAUTHORIZED"})
            return
        if str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower() != "application/zip":
            self._json(415, {"errorCode": "UNSUPPORTED_MEDIA_TYPE"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        max_bytes = int(os.environ.get("ADOBE_BRIDGE_MAX_BYTES", str(DEFAULT_MAX_BYTES)))
        if length <= 0 or length > max_bytes:
            self._json(413, {"errorCode": "PAYLOAD_TOO_LARGE"})
            return
        payload = self.rfile.read(length)
        try:
            response = convert_archive(payload)
        except BridgeError as error:
            self._json(
                error.status,
                {
                    "errorCode": error.code,
                    "message": str(error),
                    "bridgeVersion": BRIDGE_VERSION,
                    "converterVersion": agent.CONVERTER_VERSION,
                },
            )
            return
        except Exception as error:  # keep internals out of the HTTP response
            self._json(
                500,
                {
                    "errorCode": "CONVERSION_FAILED",
                    "message": error.__class__.__name__,
                    "bridgeVersion": BRIDGE_VERSION,
                    "converterVersion": agent.CONVERTER_VERSION,
                },
            )
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        # Preserve the standard timestamp/client log while avoiding request body
        # or corpus source paths in logs.
        super().log_message(format, *args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows Adobe conversion bridge")
    parser.add_argument("--host", default=os.environ.get("ADOBE_BRIDGE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ADOBE_BRIDGE_PORT", "8765")))
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), AdobeBridgeHandler)
    print(
        f"Adobe bridge listening on {args.host}:{args.port} "
        f"({BRIDGE_VERSION}, {agent.CONVERTER_VERSION})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
