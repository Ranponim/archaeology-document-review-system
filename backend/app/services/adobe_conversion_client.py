from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from typing import Protocol

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
