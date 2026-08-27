from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import queue
import threading
from tempfile import TemporaryDirectory
from typing import Any, Callable

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
    reasoning_effort: str
    turn_timeout_seconds: float


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
        reasoning_effort: str = "high",
        turn_timeout_seconds: float = 180.0,
        codex_client: Any | None = None,
        cwd: str | Path | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        model = str(model or "").strip()
        if not model:
            raise ValueError("DRAWING_CODEX_MODEL must not be empty")
        reasoning_effort = str(reasoning_effort or "").strip()
        if not reasoning_effort:
            raise ValueError("DRAWING_CODEX_REASONING_EFFORT must not be empty")
        if turn_timeout_seconds <= 0:
            raise ValueError("DRAWING_CODEX_TURN_TIMEOUT_SECONDS must be positive")
        self._config = _SdkConfig(
            model=model,
            reasoning_effort=reasoning_effort,
            turn_timeout_seconds=float(turn_timeout_seconds),
        )
        self._progress_callback = progress_callback
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

    def _emit(self, message: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(message)

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

    @staticmethod
    def _status_value(value: object) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "")

    def _collect_stream(
        self,
        turn: Any,
        *,
        source: DrawingSourceEvidencePacket,
        attempt: int,
    ) -> str:
        final_answers: list[str] = []
        fallback_answers: list[str] = []
        completed_status: str | None = None
        completed_error: object | None = None

        for event in turn.stream():
            method = str(getattr(event, "method", "unknown"))
            self._emit(
                f"source={source.source_path} attempt={attempt}/2 "
                f"turn={turn.id} event={method}"
            )
            payload = getattr(event, "payload", None)
            if method == "item/completed" and payload is not None:
                item = getattr(payload, "item", None)
                root = getattr(item, "root", item)
                if getattr(root, "type", None) == "agentMessage":
                    text = getattr(root, "text", None)
                    if isinstance(text, str) and text.strip():
                        phase = self._status_value(getattr(root, "phase", None))
                        if phase == "final_answer":
                            final_answers.append(text)
                        else:
                            fallback_answers.append(text)
                continue
            if method == "turn/completed" and payload is not None:
                completed = getattr(payload, "turn", None)
                completed_status = self._status_value(getattr(completed, "status", None))
                completed_error = getattr(completed, "error", None)

        if completed_status is None:
            raise CodexDrawingDecisionError("Codex SDK stream ended without turn/completed")
        if completed_status == "failed":
            message = getattr(completed_error, "message", None)
            raise CodexDrawingDecisionError(
                str(message or "Codex SDK turn failed without an error message")
            )
        final_response = (
            final_answers[-1]
            if final_answers
            else fallback_answers[-1]
            if fallback_answers
            else None
        )
        if final_response is None:
            raise CodexDrawingDecisionError("Codex SDK returned no final_response")
        return final_response

    def _stream_with_timeout(
        self,
        turn: Any,
        *,
        source: DrawingSourceEvidencePacket,
        attempt: int,
    ) -> str:
        outcomes: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def consume() -> None:
            try:
                outcomes.put(
                    (
                        "ok",
                        self._collect_stream(turn, source=source, attempt=attempt),
                    )
                )
            except Exception as exc:  # pragma: no cover - exercised via outcome
                outcomes.put(("error", exc))

        worker = threading.Thread(
            target=consume,
            name=f"drawing-codex-turn-{getattr(turn, 'id', 'unknown')}",
            daemon=True,
        )
        worker.start()
        try:
            kind, value = outcomes.get(timeout=self._config.turn_timeout_seconds)
        except queue.Empty as exc:
            self._emit(
                f"source={source.source_path} attempt={attempt}/2 "
                f"turn={getattr(turn, 'id', 'unknown')} timeout="
                f"{self._config.turn_timeout_seconds:g}s interrupt"
            )
            try:
                turn.interrupt()
            except Exception as interrupt_error:
                self._emit(
                    f"source={source.source_path} attempt={attempt}/2 "
                    f"turn={getattr(turn, 'id', 'unknown')} "
                    f"interrupt_error={interrupt_error}"
                )
            worker.join(timeout=1.0)
            raise CodexDrawingDecisionError(
                "Codex SDK turn timed out after "
                f"{self._config.turn_timeout_seconds:g}s"
            ) from exc

        if kind == "error":
            if isinstance(value, CodexDrawingDecisionError):
                raise value
            if isinstance(value, Exception):
                raise CodexDrawingDecisionError(str(value)) from value
            raise CodexDrawingDecisionError(str(value))
        if not isinstance(value, str) or not value.strip():
            raise CodexDrawingDecisionError("Codex SDK returned no final_response")
        return value

    def resolve(
        self,
        source: DrawingSourceEvidencePacket,
        candidates: tuple[DrawingCandidatePacket, ...],
    ) -> CodexDrawingDecision:
        inputs = self._sdk_inputs(source, candidates)
        last_error: Exception | None = None
        for attempt_index in range(2):
            attempt = attempt_index + 1
            try:
                self._emit(
                    f"source={source.source_path} attempt={attempt}/2 "
                    f"model={self._config.model} effort={self._config.reasoning_effort} start"
                )
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
                turn = thread.turn(
                    inputs,
                    effort=self._config.reasoning_effort,
                    output_schema=_DECISION_SCHEMA,
                    sandbox=Sandbox.read_only,
                    approval_mode=ApprovalMode.deny_all,
                )
                self._emit(
                    f"source={source.source_path} attempt={attempt}/2 "
                    f"turn={turn.id} accepted"
                )
                final_response = self._stream_with_timeout(
                    turn,
                    source=source,
                    attempt=attempt,
                )
                run_id = getattr(turn, "id", None)
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
                self._emit(
                    f"source={source.source_path} attempt={attempt}/2 error={exc}"
                )
                if attempt_index == 0:
                    continue
                if isinstance(exc, CodexDrawingDecisionError):
                    raise exc
                raise CodexDrawingDecisionError(str(exc)) from exc
        raise CodexDrawingDecisionError(str(last_error or "Codex SDK decision failed"))
