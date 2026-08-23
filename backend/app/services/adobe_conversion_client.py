from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import tempfile
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from app.domain.adobe_manifest import AdobeManifestV1


ADOBE_WINDOWS_AGENT_VERSION = "adobe-windows-agent-v1"


@dataclass(frozen=True, slots=True)
class ConversionRequest:
    project_id: str
    reference_corpus_id: str
    source_asset_id: str
    source_path: str
    source_role: str
    output_dir: str
    manifest_schema_version: int = 1
    workspace_root: str | None = None
    source_relative_path: str | None = None


@dataclass(frozen=True, slots=True)
class ConversionArtifact:
    artifact_type: str
    path: str
    sha256: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class ConversionResult:
    manifest: AdobeManifestV1
    artifacts: tuple[ConversionArtifact, ...] = ()
    converter_version: str = ADOBE_WINDOWS_AGENT_VERSION


class AdobeConversionError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class AdobeConversionClient(Protocol):
    @property
    def version(self) -> str: ...

    def convert(self, request: ConversionRequest) -> ConversionResult: ...


class SubprocessAdobeConversionClient:
    def __init__(
        self,
        command: list[str] | tuple[str, ...] | None = None,
        *,
        timeout_seconds: int = 300,
        version: str = ADOBE_WINDOWS_AGENT_VERSION,
    ) -> None:
        configured = os.environ.get("ADOBE_CONVERTER_COMMAND")
        if command is None and configured:
            command = shlex.split(configured)
        if command is None:
            repo_root = Path(__file__).resolve().parents[3]
            command = [sys.executable, str(repo_root / "tools" / "adobe_converter" / "agent.py")]
        self._command = list(command)
        self._timeout_seconds = timeout_seconds
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def convert(self, request: ConversionRequest) -> ConversionResult:
        with tempfile.TemporaryDirectory(prefix="adobe-conversion-") as temp_dir:
            root = Path(temp_dir)
            request_path = root / "request.json"
            result_path = root / "result.json"
            request_path.write_text(
                json.dumps(asdict(request), ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            try:
                completed = subprocess.run(
                    [*self._command, "--request", str(request_path), "--result", str(result_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                )
            except subprocess.TimeoutExpired as error:
                raise AdobeConversionError("CONVERSION_TIMEOUT") from error
            except OSError as error:
                raise AdobeConversionError("ADOBE_UNAVAILABLE") from error

            if completed.returncode != 0:
                code = "CONVERSION_FAILED"
                if result_path.is_file():
                    try:
                        failure = json.loads(result_path.read_text(encoding="utf-8"))
                        code = str(failure.get("errorCode") or code)
                    except (OSError, ValueError, TypeError):
                        pass
                raise AdobeConversionError(code, completed.stderr.strip())
            if not result_path.is_file():
                raise AdobeConversionError("CONVERSION_FAILED", "Adobe converter returned no result")

            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                manifest = AdobeManifestV1.from_dict(payload["manifest"])
                artifacts = tuple(
                    ConversionArtifact(
                        artifact_type=str(item.get("artifactType") or item.get("type") or ""),
                        path=str(item.get("path") or ""),
                        sha256=(str(item["sha256"]) if item.get("sha256") is not None else None),
                        mime_type=(str(item["mimeType"]) if item.get("mimeType") is not None else None),
                    )
                    for item in payload.get("artifacts", [])
                    if isinstance(item, dict)
                )
                return ConversionResult(
                    manifest=manifest,
                    artifacts=artifacts,
                    converter_version=str(payload.get("converterVersion") or self._version),
                )
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise AdobeConversionError("MANIFEST_INVALID") from error


RemoteTransport = Callable[[str, bytes, dict[str, str], int], bytes]


def _safe_archive_path(value: str, *, prefix: str | None = None) -> PurePosixPath:
    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AdobeConversionError("WORKSPACE_INVALID", "workspace archive path is unsafe")
    if prefix is not None and (not path.parts or path.parts[0] != prefix):
        raise AdobeConversionError("WORKSPACE_INVALID", "workspace archive path is outside expected root")
    return path


def _default_remote_transport(
    url: str,
    payload: bytes,
    headers: dict[str, str],
    timeout: int,
) -> bytes:
    request = UrlRequest(url, data=payload, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit configured bridge URL
            return response.read()
    except HTTPError as error:
        code = "CONVERSION_FAILED"
        try:
            body = error.read().decode("utf-8", errors="replace")
            parsed = json.loads(body)
            code = str(parsed.get("errorCode") or code)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        raise AdobeConversionError(code, f"Adobe bridge HTTP {error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise AdobeConversionError("ADOBE_UNAVAILABLE", "Windows Adobe bridge is unavailable") from error


class RemoteAdobeConversionClient:
    """ZIP-over-HTTP transport from Linux/Docker to a Windows Adobe host.

    The complete ReferenceCorpus workspace is sent so InDesign can resolve its
    Links using the same relative layout that was uploaded. Windows-local paths
    never become graph authority; only the returned manifest and verified
    artifact bytes are materialized back into the Linux build output directory.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        timeout_seconds: int = 300,
        version: str = ADOBE_WINDOWS_AGENT_VERSION,
        transport: RemoteTransport | None = None,
    ) -> None:
        endpoint = str(endpoint or "").strip().rstrip("/")
        if not endpoint:
            raise ValueError("Adobe converter endpoint is required")
        self._endpoint = endpoint
        self._token = token
        self._timeout_seconds = int(timeout_seconds)
        self._version = version
        self._transport = transport or _default_remote_transport

    @property
    def version(self) -> str:
        return self._version

    @staticmethod
    def _workspace(request: ConversionRequest) -> tuple[Path, PurePosixPath]:
        if not request.workspace_root or not request.source_relative_path:
            raise AdobeConversionError(
                "WORKSPACE_INVALID",
                "remote Adobe conversion requires workspace_root and source_relative_path",
            )
        root = Path(request.workspace_root).resolve()
        if not root.is_dir():
            raise AdobeConversionError("WORKSPACE_INVALID", "workspace root does not exist")
        relative = _safe_archive_path(request.source_relative_path)
        source = (root / Path(*relative.parts)).resolve()
        try:
            source.relative_to(root)
        except ValueError as error:
            raise AdobeConversionError("WORKSPACE_INVALID", "source must stay inside workspace") from error
        requested_source = Path(request.source_path).resolve()
        if source != requested_source or not source.is_file():
            raise AdobeConversionError(
                "WORKSPACE_INVALID",
                "source path does not match the selected workspace source",
            )
        return root, relative

    @staticmethod
    def _package(request: ConversionRequest, root: Path, source_relative: PurePosixPath) -> bytes:
        request_payload = {
            "projectId": request.project_id,
            "referenceCorpusId": request.reference_corpus_id,
            "sourceAssetId": request.source_asset_id,
            "sourceRole": request.source_role,
            "workspaceRoot": "workspace",
            "sourceRelativePath": source_relative.as_posix(),
            "manifestSchemaVersion": request.manifest_schema_version,
        }
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr(
                "request.json",
                json.dumps(request_payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            )
            for path in sorted(root.rglob("*")):
                if path.is_symlink():
                    raise AdobeConversionError("WORKSPACE_INVALID", "workspace symlinks are not allowed")
                if not path.is_file():
                    continue
                resolved = path.resolve()
                try:
                    relative = resolved.relative_to(root)
                except ValueError as error:
                    raise AdobeConversionError("WORKSPACE_INVALID", "workspace file escaped root") from error
                archive_name = PurePosixPath("workspace", *relative.parts).as_posix()
                _safe_archive_path(archive_name, prefix="workspace")
                archive.write(resolved, archive_name)
        return buffer.getvalue()

    @staticmethod
    def _materialize_response(request: ConversionRequest, payload: bytes) -> ConversionResult:
        output_root = Path(request.output_dir).resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        try:
            with ZipFile(BytesIO(payload), "r") as archive:
                names = set(archive.namelist())
                if "result.json" not in names:
                    raise AdobeConversionError("MANIFEST_INVALID", "Adobe bridge response has no result.json")
                result_payload = json.loads(archive.read("result.json").decode("utf-8"))
                manifest = AdobeManifestV1.from_dict(result_payload["manifest"])
                if manifest.source_asset_id != request.source_asset_id:
                    raise AdobeConversionError("MANIFEST_INVALID", "Adobe bridge source asset mismatch")

                artifacts: list[ConversionArtifact] = []
                for item in result_payload.get("artifacts", []):
                    if not isinstance(item, dict):
                        continue
                    archive_path_value = str(item.get("archivePath") or "")
                    archive_path = _safe_archive_path(archive_path_value, prefix="artifacts")
                    if archive_path.as_posix() not in names:
                        raise AdobeConversionError("CONVERSION_FAILED", "Adobe bridge artifact is missing")
                    data = archive.read(archive_path.as_posix())
                    expected_sha = str(item.get("sha256") or "") or None
                    actual_sha = hashlib.sha256(data).hexdigest()
                    if expected_sha is not None and expected_sha != actual_sha:
                        raise AdobeConversionError("CONVERSION_FAILED", "Adobe bridge artifact hash mismatch")
                    destination = (output_root / Path(*archive_path.parts)).resolve()
                    try:
                        destination.relative_to(output_root)
                    except ValueError as error:
                        raise AdobeConversionError("WORKSPACE_INVALID", "artifact escaped output root") from error
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                    artifacts.append(
                        ConversionArtifact(
                            artifact_type=str(item.get("artifactType") or item.get("type") or ""),
                            path=str(destination),
                            sha256=expected_sha or actual_sha,
                            mime_type=(str(item["mimeType"]) if item.get("mimeType") is not None else None),
                        )
                    )
                return ConversionResult(
                    manifest=manifest,
                    artifacts=tuple(artifacts),
                    converter_version=str(
                        result_payload.get("converterVersion") or ADOBE_WINDOWS_AGENT_VERSION
                    ),
                )
        except AdobeConversionError:
            raise
        except (BadZipFile, KeyError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise AdobeConversionError("MANIFEST_INVALID", "Adobe bridge response is invalid") from error

    def convert(self, request: ConversionRequest) -> ConversionResult:
        root, source_relative = self._workspace(request)
        payload = self._package(request, root, source_relative)
        headers = {"Content-Type": "application/zip"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        response = self._transport(
            f"{self._endpoint}/convert",
            payload,
            headers,
            self._timeout_seconds,
        )
        return self._materialize_response(request, response)


def build_adobe_conversion_client() -> AdobeConversionClient:
    remote_url = str(os.environ.get("ADOBE_CONVERTER_URL") or "").strip()
    if remote_url:
        return RemoteAdobeConversionClient(
            remote_url,
            token=os.environ.get("ADOBE_CONVERTER_TOKEN") or None,
            timeout_seconds=int(os.environ.get("ADOBE_CONVERTER_TIMEOUT_SECONDS", "300")),
        )
    return SubprocessAdobeConversionClient(
        timeout_seconds=int(os.environ.get("ADOBE_CONVERTER_TIMEOUT_SECONDS", "300"))
    )


class FixtureAdobeConversionClient:
    def __init__(self, manifests: dict[str, AdobeManifestV1], *, version: str = "fixture-adobe-v1") -> None:
        self._manifests = dict(manifests)
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def convert(self, request: ConversionRequest) -> ConversionResult:
        manifest = self._manifests.get(request.source_asset_id)
        if manifest is None:
            raise AdobeConversionError("CONVERSION_FAILED", "No fixture manifest for source asset")
        return ConversionResult(manifest=manifest, converter_version=self._version)
