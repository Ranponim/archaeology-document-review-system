from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from openai_codex import (
    ApprovalMode,
    Codex,
    CodexError,
    LocalImageInput,
    Sandbox,
    TextInput,
)

from app.domain.drawing_evidence_v3 import (
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingVisualRegion,
)
from app.services.codex_drawing_resolver_openai_client import (
    CodexDrawingDecisionError,
    CodexDrawingResolverClient as _DecisionParser,
    _DECISION_SCHEMA,
)


@dataclass(frozen=True, slots=True)
class _SdkConfig:
    model: str


class CodexSdkDrawingResolverClient(_DecisionParser):
    """Local Codex SDK transport for drawing-evidence-v3 acceptance.

    The SDK reuses the user's existing Codex authentication. It receives only
    the closed-world prompt and rendered local images. Threads are ephemeral,
    read-only, and deny permission escalation. A dedicated temporary cwd keeps
    the repository and source tree outside the agent workspace.
    """

    def __init__(
        self,
        *,
        model: str,
        codex_client: Any | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        model = str(model or "").strip()
        if not model:
            raise ValueError("DRAWING_CODEX_MODEL must not be empty")
        self._config = _SdkConfig(model=model)
        self._owns_codex = codex_client is None
        self._codex = codex_client or Codex()
        self._temp_workdir: TemporaryDirectory[str] | None = None
        if cwd is None:
            self._temp_workdir = TemporaryDirectory(prefix="drawing-codex-sdk-")
            self._cwd = str(Path(self._temp_workdir.name).resolve())
        else:
            resolved = Path(cwd).resolve()
            if not resolved.is_dir():
                raise ValueError(f"Codex SDK cwd must be an existing directory: {cwd}")
            self._cwd = str(resolved)

    def close(self) -> None:
        if self._owns_codex and self._codex is not None:
            close = getattr(self._codex, "close", None)
            if callable(close):
                close()
            self._codex = None
        if self._temp_workdir is not None:
            self._temp_workdir.cleanup()
            self._temp_workdir = None

    def __del__(self) -> None:  # pragma: no cover - best-effort process cleanup
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def _local_image(region: DrawingVisualRegion) -> LocalImageInput:
        path = Path(region.image_path).resolve()
        if not path.is_file():
            raise CodexDrawingDecisionError(
                f"visual region file is missing: {region.region_id}"
            )
        return LocalImageInput(path=str(path))

    def _sdk_inputs(
        self,
        source: DrawingSourceEvidencePacket,
        candidates: tuple[DrawingCandidatePacket, ...],
    ) -> list[TextInput | LocalImageInput]:
        inputs: list[TextInput | LocalImageInput] = [
            TextInput(text=self._prompt(source, candidates))
        ]
        inputs.extend(self._local_image(region) for region in source.visual_regions)
        for candidate in candidates:
            inputs.extend(
                self._local_image(region) for region in candidate.visual_regions
            )
        return inputs

    def resolve(
        self,
        source: DrawingSourceEvidencePacket,
        candidates: tuple[DrawingCandidatePacket, ...],
    ) -> CodexDrawingDecision:
        inputs = self._sdk_inputs(source, candidates)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                thread = self._codex.thread_start(
                    model=self._config.model,
                    cwd=self._cwd,
                    ephemeral=True,
                    sandbox=Sandbox.read_only,
                    approval_mode=ApprovalMode.deny_all,
                    developer_instructions=(
                        "This is a read-only classification turn. Use only the supplied "
                        "text and local images. Do not inspect the filesystem, run commands, "
                        "edit files, or invoke external tools."
                    ),
                )
                result = thread.run(
                    inputs,
                    output_schema=_DECISION_SCHEMA,
                    sandbox=Sandbox.read_only,
                    approval_mode=ApprovalMode.deny_all,
                )
                final_response = getattr(result, "final_response", None)
                if not isinstance(final_response, str) or not final_response.strip():
                    raise CodexDrawingDecisionError(
                        "Codex SDK returned no final_response"
                    )
                run_id = getattr(result, "id", None)
                if not isinstance(run_id, str) or not run_id:
                    raise CodexDrawingDecisionError("Codex SDK returned no turn id")
                return self._parse_decision(
                    {
                        "id": run_id,
                        "model": self._config.model,
                        "output_text": final_response,
                    },
                    candidates=candidates,
                    source=source,
                )
            except (CodexError, ValueError, CodexDrawingDecisionError) as exc:
                last_error = exc
                if attempt == 0:
                    continue
                if isinstance(exc, CodexDrawingDecisionError):
                    raise exc
                raise CodexDrawingDecisionError(str(exc)) from exc
        raise CodexDrawingDecisionError(str(last_error or "Codex SDK decision failed"))
