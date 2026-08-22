#!/usr/bin/env python3
"""Windows-only Adobe conversion bridge for ReferenceCorpus builds.

This process is intentionally separate from FastAPI/RQ. It launches Adobe via
Windows COM, executes a structural JSX extractor, validates the returned
manifest envelope, and writes one machine-readable result for
SubprocessAdobeConversionClient.

Publication identity is *not* inferred here. Filenames, PDF text, and rendered
artifacts never establish Plate/Drawing identity; that remains the job of the
Python ReferenceCanonicalizer after a manifest has been produced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any

CONVERTER_VERSION = "adobe-windows-agent-v1"


class AgentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def _load_request(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AgentError("MANIFEST_INVALID", "converter request JSON is invalid") from error
    if not isinstance(payload, dict):
        raise AgentError("MANIFEST_INVALID", "converter request must be an object")
    required = (
        "project_id",
        "reference_corpus_id",
        "source_asset_id",
        "source_path",
        "source_role",
        "output_dir",
    )
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise AgentError("MANIFEST_INVALID", f"converter request missing: {', '.join(missing)}")
    return payload


def _resolve_extractor(request: dict[str, Any], root: Path) -> tuple[str, Path]:
    role = str(request["source_role"])
    source = Path(str(request["source_path"]))
    suffix = source.suffix.lower()
    scripts = root / "scripts"
    if role == "plate_layout" and suffix == ".indd":
        return "indesign", scripts / "indesign_extract.jsx"
    if role == "drawing_source" and suffix == ".ai":
        return "illustrator", scripts / "illustrator_extract.jsx"
    raise AgentError(
        "CONVERSION_FAILED",
        f"unsupported Adobe source role/type: {role} ({suffix or 'no extension'})",
    )


def _find_powershell() -> str:
    for candidate in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        executable = shutil.which(candidate)
        if executable:
            return executable
    raise AgentError("ADOBE_UNAVAILABLE", "PowerShell is unavailable on the Adobe Windows agent")


def _run_com_extractor(application: str, script_path: Path, context_path: Path) -> None:
    powershell = _find_powershell()
    # Reading the JSX text and passing it to Adobe avoids ambiguous COM handling
    # of a string path versus script source. The extractor receives only a path
    # to the structural context through an inherited environment variable.
    ps_script = r"""
$ErrorActionPreference = 'Stop'
$jsxPath = $env:ARCHAEOLOGY_ADOBE_SCRIPT
$code = [System.IO.File]::ReadAllText($jsxPath, [System.Text.Encoding]::UTF8)
if ($env:ARCHAEOLOGY_ADOBE_APPLICATION -eq 'indesign') {
    $app = New-Object -ComObject 'InDesign.Application'
    # 1246973031 is InDesign's JavaScript/ExtendScript language enum.
    $null = $app.DoScript($code, 1246973031)
} elseif ($env:ARCHAEOLOGY_ADOBE_APPLICATION -eq 'illustrator') {
    $app = New-Object -ComObject 'Illustrator.Application'
    $null = $app.DoJavaScript($code)
} else {
    throw 'Unsupported Adobe application'
}
"""
    env = os.environ.copy()
    env["ARCHAEOLOGY_ADOBE_APPLICATION"] = application
    env["ARCHAEOLOGY_ADOBE_SCRIPT"] = str(script_path.resolve())
    env["ARCHAEOLOGY_ADOBE_CONTEXT"] = str(context_path.resolve())
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", ps_script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "Adobe COM execution failed").strip()
        lowered = message.lower()
        if "comobject" in lowered or "class not registered" in lowered or "activex" in lowered:
            raise AgentError("ADOBE_UNAVAILABLE", message)
        raise AgentError("CONVERSION_FAILED", message)


def _artifact_payload(item: dict[str, Any], output_dir: Path) -> dict[str, Any] | None:
    raw_path = str(item.get("path") or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = (output_dir / path).resolve()
    if not path.is_file():
        raise AgentError("CONVERSION_FAILED", f"declared Adobe artifact does not exist: {path}")
    artifact_type = str(item.get("type") or item.get("artifactType") or path.suffix.lstrip(".") or "render")
    mime = str(item.get("mimeType") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    return {
        "artifactType": artifact_type,
        "path": str(path),
        "sha256": _sha256(path),
        "mimeType": mime,
    }


def _validate_manifest(
    manifest_path: Path,
    *,
    application: str,
    request: dict[str, Any],
    source_sha256: str,
) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AgentError("MANIFEST_INVALID", "Adobe extractor returned an invalid manifest") from error
    if not isinstance(manifest, dict):
        raise AgentError("MANIFEST_INVALID", "Adobe extractor manifest must be an object")
    expected = {
        "schemaVersion": int(request.get("manifest_schema_version") or 1),
        "application": application,
        "sourceAssetId": str(request["source_asset_id"]),
        "sourceSha256": source_sha256,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise AgentError("MANIFEST_INVALID", f"Adobe manifest {key} does not match conversion request")
    if application == "indesign" and not isinstance(manifest.get("pages"), list):
        raise AgentError("MANIFEST_INVALID", "InDesign manifest pages are required")
    if application == "illustrator" and not isinstance(manifest.get("artboards"), list):
        raise AgentError("MANIFEST_INVALID", "Illustrator manifest artboards are required")
    return manifest


def convert(request_path: Path) -> dict[str, Any]:
    request = _load_request(request_path)

    # Fail before touching the requested output directory. Non-Windows machines
    # must never fabricate a PDF/text/filename fallback that could become corpus
    # identity by accident.
    if platform.system().lower() != "windows":
        raise AgentError("ADOBE_UNAVAILABLE", "Adobe converter requires a Windows host with Adobe applications")

    root = Path(__file__).resolve().parent
    application, extractor = _resolve_extractor(request, root)
    if not extractor.is_file():
        raise AgentError("ADOBE_UNAVAILABLE", f"Adobe extractor is missing: {extractor.name}")

    source = Path(str(request["source_path"])).resolve()
    if not source.is_file():
        raise AgentError("CONVERSION_FAILED", "Adobe source file does not exist")
    source_sha = _sha256(source)
    output_dir = Path(str(request["output_dir"])).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"{request['source_asset_id']}.manifest.json"

    context = {
        "schemaVersion": int(request.get("manifest_schema_version") or 1),
        "application": application,
        "projectId": str(request["project_id"]),
        "referenceCorpusId": str(request["reference_corpus_id"]),
        "sourceAssetId": str(request["source_asset_id"]),
        "sourceSha256": source_sha,
        "sourcePath": str(source),
        "sourceRole": str(request["source_role"]),
        "manifestPath": str(manifest_path),
        "outputDir": str(output_dir),
    }
    with tempfile.TemporaryDirectory(prefix="adobe-agent-context-") as temp_dir:
        context_path = Path(temp_dir) / "context.json"
        _write_json(context_path, context)
        _run_com_extractor(application, extractor, context_path)

    manifest = _validate_manifest(
        manifest_path,
        application=application,
        request=request,
        source_sha256=source_sha,
    )
    artifacts: list[dict[str, Any]] = []
    for item in manifest.get("artifacts", []):
        if isinstance(item, dict):
            artifact = _artifact_payload(item, output_dir)
            if artifact:
                artifacts.append(artifact)
    artifacts.append(
        {
            "artifactType": "manifest",
            "path": str(manifest_path),
            "sha256": _sha256(manifest_path),
            "mimeType": "application/json",
        }
    )
    return {
        "manifest": manifest,
        "artifacts": artifacts,
        "converterVersion": CONVERTER_VERSION,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(argv)
    result_path = Path(args.result)
    try:
        payload = convert(Path(args.request))
        _write_json(result_path, payload)
        return 0
    except AgentError as error:
        _write_json(
            result_path,
            {
                "errorCode": error.code,
                "message": str(error),
                "converterVersion": CONVERTER_VERSION,
            },
        )
        return 2
    except subprocess.TimeoutExpired as error:
        _write_json(
            result_path,
            {
                "errorCode": "CONVERSION_TIMEOUT",
                "message": str(error),
                "converterVersion": CONVERTER_VERSION,
            },
        )
        return 2
    except Exception as error:  # boundary: never leak an unstructured converter failure
        _write_json(
            result_path,
            {
                "errorCode": "CONVERSION_FAILED",
                "message": str(error),
                "converterVersion": CONVERTER_VERSION,
            },
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
