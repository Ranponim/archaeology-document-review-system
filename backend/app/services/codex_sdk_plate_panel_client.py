from __future__ import annotations

import hashlib
import json
from pathlib import Path
import queue
import threading
from tempfile import TemporaryDirectory
from typing import Any, Callable

import pymupdf
from openai_codex import (
    ApprovalMode,
    Codex,
    CodexError,
    LocalImageInput,
    Sandbox,
    TextInput,
)

from app.services.json_utils import strip_markdown_json
from app.services.plate_panel_model_resolver import (
    PlatePanelModelDecision,
    PlatePanelModelRequest,
)


class CodexPlatePanelDecisionError(RuntimeError):
    pass


class CodexSdkPlatePanelClient:
    """Read-only local Codex transport for closed-world panel/JPG review."""

    def __init__(
        self,
        *,
        model: str = "gpt-5.6-luna",
        reasoning_effort: str = "high",
        turn_timeout_seconds: float = 180.0,
        codex_client: Any | None = None,
        cwd: str | Path | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        model = str(model or "").strip()
        reasoning_effort = str(reasoning_effort or "").strip()
        if not model:
            raise ValueError("PLATE_CODEX_MODEL must not be empty")
        if not reasoning_effort:
            raise ValueError("PLATE_CODEX_REASONING_EFFORT must not be empty")
        if turn_timeout_seconds <= 0:
            raise ValueError("PLATE_CODEX_TURN_TIMEOUT_SECONDS must be positive")

        self._model = model
        self._reasoning_effort = reasoning_effort
        self._turn_timeout_seconds = float(turn_timeout_seconds)
        self._progress_callback = progress_callback
        self._owns_codex = codex_client is None
        self._codex = codex_client or Codex()

        self._workdir: TemporaryDirectory[str] | None = None
        if cwd is None:
            self._workdir = TemporaryDirectory(prefix="plate-panel-codex-sdk-")
            self._cwd = str(Path(self._workdir.name).resolve())
        else:
            resolved = Path(cwd).resolve()
            if not resolved.is_dir():
                raise ValueError(f"Codex SDK cwd must be an existing directory: {cwd}")
            self._cwd = str(resolved)

        # Panel crops are always written outside the source PDF/JPG tree.
        self._render_dir = TemporaryDirectory(prefix="plate-panel-render-")

    def close(self) -> None:
        if self._owns_codex and self._codex is not None:
            close = getattr(self._codex, "close", None)
            if callable(close):
                close()
            self._codex = None
        if self._render_dir is not None:
            self._render_dir.cleanup()
        if self._workdir is not None:
            self._workdir.cleanup()
            self._workdir = None

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        try:
            self.close()
        except Exception:
            pass

    def _emit(self, message: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(message)

    @staticmethod
    def _prompt(request: PlatePanelModelRequest) -> str:
        candidate_lines = "\n".join(
            f"- {candidate.source_asset_id}: deterministic retrieval score="
            f"{candidate.retrieval_score:.6f}"
            for candidate in request.candidates
        )
        return (
            "You are verifying image provenance. Determine whether the PDF PANEL is "
            "the same original photograph as exactly one supplied candidate. Treat "
            "crop, resize, recompression, exposure, tone, and minor publication edits "
            "as compatible. Do NOT choose a candidate merely because it depicts a "
            "similar archaeological subject, feature, angle, or scene.\n\n"
            "This is closed-world classification. candidate_id must be one of the "
            "supplied IDs when verdict=match. If multiple candidates remain plausible, "
            "return ambiguous. If none is the same original photograph, return none.\n\n"
            f"PANEL_ID={request.panel_id}\n"
            f"Candidates:\n{candidate_lines}\n\n"
            "Return only JSON with verdict, candidate_id, confidence, rationale."
        )

    @staticmethod
    def _decision_schema(request: PlatePanelModelRequest) -> dict[str, Any]:
        candidate_ids = [candidate.source_asset_id for candidate in request.candidates]
        return {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["match", "ambiguous", "none"],
                },
                "candidate_id": {
                    "anyOf": [
                        {"type": "string", "enum": candidate_ids},
                        {"type": "null"},
                    ]
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "rationale": {"type": "string"},
            },
            "required": ["verdict", "candidate_id", "confidence", "rationale"],
            "additionalProperties": False,
        }

    def _render_panel(self, request: PlatePanelModelRequest) -> Path:
        pdf_path = Path(request.pdf_path).resolve()
        if not pdf_path.is_file():
            raise CodexPlatePanelDecisionError(f"panel PDF is missing: {pdf_path}")
        doc = pymupdf.open(str(pdf_path))
        try:
            if request.physical_page < 1 or request.physical_page > len(doc):
                raise CodexPlatePanelDecisionError(
                    f"physical page is out of range: {request.physical_page}"
                )
            page = doc[request.physical_page - 1]
            x0, y0, x1, y1 = request.bbox
            values = (x0, y0, x1, y1)
            if not all(0.0 <= value <= 1.0 for value in values) or x1 <= x0 or y1 <= y0:
                raise CodexPlatePanelDecisionError(f"invalid normalized panel bbox: {values}")
            clip = pymupdf.Rect(
                x0 * page.rect.width,
                y0 * page.rect.height,
                x1 * page.rect.width,
                y1 * page.rect.height,
            )
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0), clip=clip, alpha=False)
            key = hashlib.sha256(
                f"{pdf_path}|{request.physical_page}|{request.bbox}|{request.panel_id}".encode(
                    "utf-8"
                )
            ).hexdigest()[:20]
            output = Path(self._render_dir.name) / f"panel-{key}.png"
            pixmap.save(str(output))
            return output
        finally:
            doc.close()

    @staticmethod
    def _candidate_image(candidate_path: str | Path) -> LocalImageInput:
        path = Path(candidate_path).resolve()
        if not path.is_file():
            raise CodexPlatePanelDecisionError(f"candidate image is missing: {path}")
        return LocalImageInput(path=str(path))

    def _sdk_inputs(
        self,
        request: PlatePanelModelRequest,
    ) -> list[TextInput | LocalImageInput]:
        panel_path = self._render_panel(request)
        inputs: list[TextInput | LocalImageInput] = [
            TextInput(text=self._prompt(request)),
            TextInput(text=f"PANEL_ID={request.panel_id}"),
            LocalImageInput(path=str(panel_path.resolve())),
        ]
        for candidate in request.candidates:
            inputs.append(
                TextInput(
                    text=(
                        f"CANDIDATE_ID={candidate.source_asset_id} "
                        f"RETRIEVAL_SCORE={candidate.retrieval_score:.6f}"
                    )
                )
            )
            inputs.append(self._candidate_image(candidate.image_path))
        return inputs

    def _thread_start_kwargs(self) -> dict[str, Any]:
        return {
            "model": self._model,
            "cwd": self._cwd,
            "ephemeral": True,
            "sandbox": Sandbox.read_only,
            "approval_mode": ApprovalMode.deny_all,
            "developer_instructions": (
                "This is a read-only image classification turn. Use only the supplied "
                "text and local images. Do not inspect the filesystem, run commands, "
                "edit files, invoke external tools, or request permission escalation."
            ),
        }

    @staticmethod
    def _status_value(value: object) -> str:
        return str(getattr(value, "value", value) or "")

    def _collect_stream(self, turn: Any, *, panel_id: str) -> str:
        final_answers: list[str] = []
        fallback_answers: list[str] = []
        completed_status: str | None = None
        completed_error: object | None = None

        for event in turn.stream():
            method = str(getattr(event, "method", "unknown"))
            self._emit(f"panel={panel_id} turn={getattr(turn, 'id', 'unknown')} event={method}")
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
            elif method == "turn/completed" and payload is not None:
                completed = getattr(payload, "turn", None)
                completed_status = self._status_value(getattr(completed, "status", None))
                completed_error = getattr(completed, "error", None)

        if completed_status is None:
            raise CodexPlatePanelDecisionError("Codex SDK stream ended without turn/completed")
        if completed_status == "failed":
            message = getattr(completed_error, "message", None)
            raise CodexPlatePanelDecisionError(str(message or "Codex SDK turn failed"))
        response = final_answers[-1] if final_answers else fallback_answers[-1] if fallback_answers else ""
        if not response.strip():
            raise CodexPlatePanelDecisionError("Codex SDK returned no final response")
        return response

    def _stream_with_timeout(self, turn: Any, *, panel_id: str) -> str:
        outcomes: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def consume() -> None:
            try:
                outcomes.put(("ok", self._collect_stream(turn, panel_id=panel_id)))
            except Exception as exc:  # pragma: no cover - transport outcome
                outcomes.put(("error", exc))

        worker = threading.Thread(
            target=consume,
            name=f"plate-panel-codex-{getattr(turn, 'id', 'unknown')}",
            daemon=True,
        )
        worker.start()
        try:
            kind, value = outcomes.get(timeout=self._turn_timeout_seconds)
        except queue.Empty as exc:
            try:
                turn.interrupt()
            except Exception:
                pass
            worker.join(timeout=1.0)
            raise CodexPlatePanelDecisionError(
                f"Codex SDK turn timed out after {self._turn_timeout_seconds:g}s"
            ) from exc

        if kind == "error":
            if isinstance(value, Exception):
                raise CodexPlatePanelDecisionError(str(value)) from value
            raise CodexPlatePanelDecisionError(str(value))
        if not isinstance(value, str) or not value.strip():
            raise CodexPlatePanelDecisionError("Codex SDK returned no final response")
        return value

    @staticmethod
    def _parse_decision(
        raw: str,
        *,
        request: PlatePanelModelRequest,
    ) -> PlatePanelModelDecision:
        try:
            data = json.loads(strip_markdown_json(raw))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CodexPlatePanelDecisionError("Codex SDK returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise CodexPlatePanelDecisionError("Codex SDK JSON must be an object")

        verdict = str(data.get("verdict") or "").strip().lower()
        if verdict not in {"match", "ambiguous", "none"}:
            raise CodexPlatePanelDecisionError(f"invalid verdict: {verdict!r}")
        candidate_raw = data.get("candidate_id")
        candidate_id = str(candidate_raw).strip() if candidate_raw is not None else None
        if candidate_id == "":
            candidate_id = None
        allowed_ids = {candidate.source_asset_id for candidate in request.candidates}
        if candidate_id is not None and candidate_id not in allowed_ids:
            raise CodexPlatePanelDecisionError(
                f"candidate outside closed world: {candidate_id}"
            )
        if verdict == "match" and candidate_id is None:
            raise CodexPlatePanelDecisionError("match verdict requires candidate_id")

        try:
            confidence = float(data.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise CodexPlatePanelDecisionError("confidence must be numeric") from exc
        if not 0.0 <= confidence <= 1.0:
            raise CodexPlatePanelDecisionError("confidence must be between 0 and 1")
        rationale = str(data.get("rationale") or "")
        return PlatePanelModelDecision(
            verdict=verdict,
            candidate_id=candidate_id,
            confidence=confidence,
            rationale=rationale,
        )

    def resolve(self, request: PlatePanelModelRequest) -> PlatePanelModelDecision:
        if not request.candidates:
            return PlatePanelModelDecision(
                verdict="none",
                candidate_id=None,
                confidence=1.0,
                rationale="no supplied candidates",
            )
        inputs = self._sdk_inputs(request)
        last_error: Exception | None = None
        for attempt_index in range(2):
            try:
                thread = self._codex.thread_start(**self._thread_start_kwargs())
                turn = thread.turn(
                    inputs,
                    effort=self._reasoning_effort,
                    output_schema=self._decision_schema(request),
                    sandbox=Sandbox.read_only,
                    approval_mode=ApprovalMode.deny_all,
                )
                raw = self._stream_with_timeout(turn, panel_id=request.panel_id)
                return self._parse_decision(raw, request=request)
            except (CodexError, ValueError, CodexPlatePanelDecisionError) as exc:
                last_error = exc
                self._emit(
                    f"panel={request.panel_id} attempt={attempt_index + 1}/2 error={exc}"
                )
                if attempt_index == 0:
                    continue
                if isinstance(exc, CodexPlatePanelDecisionError):
                    raise
                raise CodexPlatePanelDecisionError(str(exc)) from exc
        raise CodexPlatePanelDecisionError(str(last_error or "Codex SDK decision failed"))
