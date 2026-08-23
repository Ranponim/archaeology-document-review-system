from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import mimetypes
from pathlib import Path, PurePosixPath
import shutil
from typing import Callable, Iterable

from app.config import DATA_ROOT
from app.domain.reference_corpus import (
    DerivedArtifactData,
    ReferenceCorpusData,
    ReferenceCorpusFailureCode,
    ReferenceCorpusStatus,
    compute_build_identity,
)
from app.domain.source_assets import OriginalAssetData
from app.domain.models import StoredFile
from app.services.adobe_conversion_client import (
    AdobeConversionClient,
    AdobeConversionError,
    ConversionArtifact,
    ConversionRequest,
)
from app.services.reference_canonicalizer import CanonicalizationError, ReferenceCanonicalizer


_ROLE_SUFFIXES = {
    "plate_layout": frozenset({".indd"}),
    "plate_link": frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"}),
    "drawing_source": frozenset({".ai"}),
}
_CONVERTER_ROLES = frozenset({"plate_layout", "drawing_source"})


class ReferenceCorpusNotFoundError(LookupError):
    pass


class ReferenceCorpusService:
    """Build immutable graph-first visual reference corpora.

    Upload roles choose the conversion route only. Plate/Drawing publication
    identity is never read from a filename, upload role, or rendered artifact.
    That authority remains in ReferenceCanonicalizer over Adobe DOM manifests.
    """

    manifest_schema_version = "1"

    def __init__(
        self,
        repository,
        converter: AdobeConversionClient,
        canonicalizer: ReferenceCanonicalizer,
        *,
        source_asset_repository=None,
        artifact_root: Path | str | None = None,
        source_path_resolver: Callable[[str], str | Path] | None = None,
    ) -> None:
        self._repository = repository
        self._converter = converter
        self._canonicalizer = canonicalizer
        self._source_asset_repository = source_asset_repository
        self._artifact_root = Path(artifact_root) if artifact_root is not None else DATA_ROOT / "derived" / "reference-corpora"
        self._source_path_resolver = source_path_resolver or self._default_source_path

    @staticmethod
    def validate_source_role(role: str, filename: str) -> str:
        normalized = str(role or "").strip().lower()
        allowed = _ROLE_SUFFIXES.get(normalized)
        if allowed is None:
            raise ValueError("Unsupported reference corpus source role")
        suffix = Path(filename or "").suffix.lower()
        if suffix not in allowed:
            raise ValueError(f"File type {suffix or '<none>'} is invalid for source role {normalized}")
        return normalized

    @staticmethod
    def _safe_relative_path(value: str) -> str:
        normalized = value.replace("\\", "/").strip().lstrip("./")
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("A safe relative source path is required")
        return path.as_posix()

    @staticmethod
    def _default_source_path(uri: str) -> Path:
        relative = Path(uri)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError("Stored source URI must be relative to DATA_ROOT")
        return DATA_ROOT.joinpath(relative)

    @staticmethod
    def _source_set_hash(sources: Iterable[dict]) -> str:
        triples = sorted(
            (
                str(item["role"]),
                str(item["sha256"]),
                str(item.get("relative_path") or item.get("original_name") or "").replace("\\", "/"),
            )
            for item in sources
        )
        payload = "\n".join(
            f"{role}\0{sha}\0{relative_path}" for role, sha, relative_path in triples
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _asset_from_row(row: dict) -> OriginalAssetData:
        metadata = None
        raw_metadata = row.get("source_metadata_json")
        if raw_metadata:
            try:
                parsed = json.loads(raw_metadata)
                if isinstance(parsed, dict):
                    metadata = parsed
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = None
        return OriginalAssetData(
            id=str(row["id"]),
            project_id=str(row.get("project_id") or ""),
            uri=str(row.get("uri") or ""),
            sha256=str(row.get("sha256") or ""),
            size_bytes=int(row.get("size_bytes") or 0),
            mime_type=str(row.get("mime_type") or "application/octet-stream"),
            original_name=str(row.get("original_name") or ""),
            relative_path=str(row.get("relative_path") or row.get("original_name") or ""),
            asset_kind=str(row.get("asset_kind") or "reference_source"),
            source_root_name=str(row.get("source_root_name") or "reference-corpus"),
            import_batch_id=str(row.get("import_batch_id") or ""),
            parse_status=str(row.get("parse_status") or "stored"),
            provenance_status=str(row.get("provenance_status") or "unlinked"),
            created_at=row.get("created_at"),
            source_metadata=metadata,
        )

    @staticmethod
    def _artifact_id(corpus_id: str, source_asset_id: str | None, artifact_type: str, sha256: str) -> str:
        payload = "\0".join((corpus_id, source_asset_id or "", artifact_type, sha256)).encode("utf-8")
        return "artifact_" + hashlib.sha256(payload).hexdigest()[:32]

    @staticmethod
    def _sha_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def create(self, project_id: str) -> ReferenceCorpusData:
        return self._repository.create_staging(project_id)

    def list(self, project_id: str) -> list[ReferenceCorpusData]:
        return self._repository.list_for_project(project_id)

    def get(self, project_id: str, corpus_id: str) -> ReferenceCorpusData:
        corpus = self._repository.get(project_id, corpus_id)
        if corpus is None:
            raise ReferenceCorpusNotFoundError(corpus_id)
        return corpus

    def _workspace_root(self, corpus_id: str) -> Path:
        return self._artifact_root / corpus_id / "workspace"

    def _output_root(self, corpus_id: str) -> Path:
        return self._artifact_root / corpus_id / "converted"

    def _workspace_path(self, corpus_id: str, relative_path: str) -> Path:
        safe_path = self._safe_relative_path(relative_path)
        root = self._workspace_root(corpus_id).resolve()
        target = root.joinpath(*PurePosixPath(safe_path).parts).resolve()
        if target != root and root not in target.parents:
            raise ValueError("Reference corpus source path escapes workspace")
        return target

    def stage_stored_source(
        self,
        project_id: str,
        corpus_id: str,
        stored: StoredFile,
        role: str,
        *,
        relative_path: str | None = None,
    ) -> OriginalAssetData:
        corpus = self.get(project_id, corpus_id)
        if corpus.status != ReferenceCorpusStatus.STAGING:
            raise ValueError("Reference corpus sources can only be staged while status is staging")
        if self._source_asset_repository is None:
            raise RuntimeError("source asset repository is required to stage uploaded corpus files")
        normalized_role = self.validate_source_role(role, stored.original_name)
        safe_relative = self._safe_relative_path(relative_path or stored.original_name)
        asset_seed = "\0".join((project_id, stored.sha256, safe_relative)).encode("utf-8")
        asset = OriginalAssetData(
            id="asset_" + hashlib.sha256(asset_seed).hexdigest()[:32],
            project_id=project_id,
            uri=stored.uri,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type=stored.mime_type,
            original_name=stored.original_name,
            relative_path=safe_relative,
            asset_kind=normalized_role,
            source_root_name="reference-corpus",
            import_batch_id=corpus_id,
            parse_status="stored",
            provenance_status="unlinked",
            source_metadata={"referenceCorpusRole": normalized_role},
        )
        self._source_asset_repository.save_original_asset(asset)
        self._repository.attach_source(project_id, corpus_id, asset.id, normalized_role)

        source_path = Path(self._source_path_resolver(stored.uri))
        if source_path.is_file():
            workspace_path = self._workspace_path(corpus_id, safe_relative)
            workspace_path.parent.mkdir(parents=True, exist_ok=True)
            if not workspace_path.exists():
                shutil.copy2(source_path, workspace_path)
            elif self._sha_file(workspace_path) != stored.sha256:
                raise ValueError("Reference corpus workspace source conflicts with staged bytes")
        return asset

    def stage_sources(
        self,
        project_id: str,
        corpus_id: str,
        sources: Iterable[tuple[StoredFile, str, str | None]],
    ) -> list[OriginalAssetData]:
        return [
            self.stage_stored_source(project_id, corpus_id, stored, role, relative_path=relative_path)
            for stored, role, relative_path in sources
        ]

    def _source_path(self, corpus_id: str, asset: OriginalAssetData) -> Path:
        workspace = self._workspace_path(corpus_id, asset.relative_path)
        if workspace.is_file():
            return workspace
        return Path(self._source_path_resolver(asset.uri))

    def _save_normalized_manifest(self, corpus_id: str, source: OriginalAssetData, manifest, converter_version: str) -> None:
        root = self._output_root(corpus_id)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{source.id}.normalized-manifest.json"
        payload = json.dumps(asdict(manifest), ensure_ascii=False, sort_keys=True, indent=2, default=str).encode("utf-8")
        path.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
        self._repository.save_artifact(
            source.project_id,
            corpus_id,
            DerivedArtifactData(
                id=self._artifact_id(corpus_id, source.id, "manifest", sha),
                reference_corpus_id=corpus_id,
                artifact_type="manifest",
                uri=str(path),
                sha256=sha,
                mime_type="application/json",
                source_asset_id=source.id,
                converter_version=converter_version,
            ),
        )

    def _save_conversion_artifact(
        self,
        project_id: str,
        corpus_id: str,
        source_asset_id: str,
        converter_version: str,
        artifact: ConversionArtifact,
    ) -> None:
        if not artifact.path:
            raise AdobeConversionError("CONVERSION_FAILED", "Adobe artifact path is empty")
        path = Path(artifact.path)
        sha = artifact.sha256
        if not sha:
            if not path.is_file():
                raise AdobeConversionError("CONVERSION_FAILED", "Adobe artifact is missing")
            sha = self._sha_file(path)
        artifact_type = artifact.artifact_type or path.suffix.lstrip(".") or "render"
        mime = artifact.mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._repository.save_artifact(
            project_id,
            corpus_id,
            DerivedArtifactData(
                id=self._artifact_id(corpus_id, source_asset_id, artifact_type, sha),
                reference_corpus_id=corpus_id,
                artifact_type=artifact_type,
                uri=str(path),
                sha256=sha,
                mime_type=mime,
                source_asset_id=source_asset_id,
                converter_version=converter_version,
            ),
        )

    @staticmethod
    def _failure_code(error: BaseException) -> ReferenceCorpusFailureCode:
        code = getattr(error, "code", None)
        if code:
            try:
                return ReferenceCorpusFailureCode(str(code))
            except ValueError:
                pass
        if isinstance(error, AdobeConversionError):
            return ReferenceCorpusFailureCode.CONVERSION_FAILED
        if isinstance(error, CanonicalizationError):
            return ReferenceCorpusFailureCode.GRAPH_INVALID
        return ReferenceCorpusFailureCode.GRAPH_INVALID

    def _fail_build(self, project_id: str, corpus_id: str, error: BaseException) -> None:
        try:
            corpus = self._repository.get(project_id, corpus_id)
            if corpus is not None and not corpus.status.is_terminal:
                self._repository.transition_status(
                    project_id,
                    corpus_id,
                    ReferenceCorpusStatus.FAILED,
                    failure_code=self._failure_code(error),
                )
        except Exception:
            # Preserve the original build exception; diagnostics may still be
            # recovered from already-persisted sources/artifacts.
            pass

    def build(self, project_id: str, corpus_id: str) -> ReferenceCorpusData:
        corpus = self.get(project_id, corpus_id)
        if corpus.status != ReferenceCorpusStatus.STAGING:
            if corpus.status == ReferenceCorpusStatus.READY:
                return corpus
            raise ValueError("Only a staging reference corpus can be built")

        source_rows = self._repository.list_sources(project_id, corpus_id)
        if not source_rows:
            raise ValueError("Reference corpus has no staged sources")
        roles = {str(item.get("role") or "") for item in source_rows}
        missing_roles = sorted({"plate_layout", "drawing_source"} - roles)
        if missing_roles:
            raise ValueError("Reference corpus is missing required source roles: " + ", ".join(missing_roles))

        source_set_hash = self._source_set_hash(source_rows)
        converter_version = str(self._converter.version)
        canonicalizer_version = str(self._canonicalizer.version)
        build_identity = compute_build_identity(
            source_set_hash,
            converter_version,
            self.manifest_schema_version,
            canonicalizer_version,
        )
        reusable = self._repository.find_ready_by_build_identity(project_id, build_identity)
        if reusable is not None:
            return reusable

        try:
            self._repository.transition_status(
                project_id,
                corpus_id,
                ReferenceCorpusStatus.CONVERTING,
                source_set_hash=source_set_hash,
                converter_version=converter_version,
                manifest_schema_version=self.manifest_schema_version,
                canonicalizer_version=canonicalizer_version,
                build_identity=build_identity,
            )
            assets = [self._asset_from_row({**row, "project_id": project_id}) for row in source_rows]
            by_id = {asset.id: asset for asset in assets}
            output_dir = self._output_root(corpus_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            workspace_root = self._workspace_root(corpus_id).resolve()
            manifests = []
            conversion_rows = sorted(
                (row for row in source_rows if row.get("role") in _CONVERTER_ROLES),
                key=lambda row: (str(row.get("role")), str(row.get("id"))),
            )
            for row in conversion_rows:
                source = by_id[str(row["id"])]
                result = self._converter.convert(
                    ConversionRequest(
                        project_id=project_id,
                        reference_corpus_id=corpus_id,
                        source_asset_id=source.id,
                        source_path=str(self._source_path(corpus_id, source)),
                        source_role=str(row["role"]),
                        output_dir=str(output_dir),
                        manifest_schema_version=int(self.manifest_schema_version),
                        workspace_root=str(workspace_root),
                        source_relative_path=source.relative_path,
                    )
                )
                if result.converter_version != converter_version:
                    raise AdobeConversionError("MANIFEST_INVALID", "converter version changed during corpus build")
                if result.manifest.source_asset_id != source.id or result.manifest.source_sha256 != source.sha256:
                    raise AdobeConversionError("MANIFEST_INVALID", "manifest source provenance does not match staged asset")
                manifests.append(result.manifest)
                self._save_normalized_manifest(corpus_id, source, result.manifest, result.converter_version)
                for artifact in result.artifacts:
                    self._save_conversion_artifact(
                        project_id,
                        corpus_id,
                        source.id,
                        result.converter_version,
                        artifact,
                    )

            self._repository.transition_status(project_id, corpus_id, ReferenceCorpusStatus.VALIDATING)
            self._repository.transition_status(project_id, corpus_id, ReferenceCorpusStatus.CANONICALIZING)
            canonical = self._canonicalizer.canonicalize(corpus_id, manifests, assets)
            if not canonical.plates and not canonical.drawings:
                error = CanonicalizationError("EMPTY_CANONICAL_GRAPH", "Adobe sources produced no canonical visuals")
                raise error
            self._repository.save_canonical_visuals(
                project_id,
                corpus_id,
                plates=canonical.plates,
                drawings=canonical.drawings,
            )
            self._repository.transition_status(project_id, corpus_id, ReferenceCorpusStatus.GRAPH_VALIDATING)
            if not self._repository.validate_ready_graph(project_id, corpus_id):
                raise CanonicalizationError("GRAPH_INVALID", "Reference corpus graph validation failed")
            return self._repository.transition_status(project_id, corpus_id, ReferenceCorpusStatus.READY)
        except Exception as error:
            self._fail_build(project_id, corpus_id, error)
            raise

    def retry_failed_build(self, project_id: str, corpus_id: str) -> ReferenceCorpusData:
        failed = self.get(project_id, corpus_id)
        if failed.status != ReferenceCorpusStatus.FAILED:
            raise ValueError("Only a failed reference corpus can be retried")
        sources = self._repository.list_sources(project_id, corpus_id)
        retry = self._repository.create_staging(project_id)
        for source in sources:
            self._repository.attach_source(project_id, retry.id, str(source["id"]), str(source["role"]))
        return self.build(project_id, retry.id)
