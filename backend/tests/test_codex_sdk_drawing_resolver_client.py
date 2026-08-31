from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import CodexDrawingResolverConfig
from app.domain.drawing_evidence_v3 import (
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
    DrawingVisualRegion,
)
from app.services.codex_drawing_resolver_client import CodexDrawingDecisionError
from app.services.codex_sdk_drawing_resolver_client import CodexSdkDrawingResolverClient


def _write_image(path: Path) -> str:
    path.write_bytes(b"fake-png-bytes")
    return str(path)


def _source(tmp_path: Path) -> DrawingSourceEvidencePacket:
    evidence = DrawingV3Evidence(
        id="ev:source:site",
        family="spatial_signature",
        method="exact_site_point",
        value="2",
    )
    return DrawingSourceEvidencePacket(
        source_asset_id="asset-1",
        source_sha256="source-sha",
        original_name="mystery.ai",
        source_path="site/mystery.ai",
        raw_text="2지점 1호 토광묘",
        publication_kind="drawing",
        internal_numbers=(),
        facts=(),
        visual_regions=(
            DrawingVisualRegion(
                region_id="source:asset-1",
                image_path=_write_image(tmp_path / "source.png"),
                page=1,
                bbox=None,
                confidence=1.0,
            ),
        ),
        evidence=(evidence,),
    )


def _candidate(tmp_path: Path) -> DrawingCandidatePacket:
    site = DrawingV3Evidence(
        id="ev:candidate:52:site",
        family="spatial_signature",
        method="exact_site_point",
        value="2",
    )
    feature = DrawingV3Evidence(
        id="ev:candidate:52:feature",
        family="archaeology_signature",
        method="exact_feature_pair",
        value="토광묘:1",
    )
    return DrawingCandidatePacket(
        candidate_id="candidate:drawing:52",
        publication_kind="drawing",
        number="52",
        raw_texts=("도면 52. 2지점 1호 토광묘",),
        facts=(),
        visual_regions=(
            DrawingVisualRegion(
                region_id="body:drawing:52",
                image_path=_write_image(tmp_path / "candidate.png"),
                page=1,
                bbox=(1.0, 1.0, 10.0, 10.0),
                confidence=1.0,
            ),
        ),
        local_score=18.0,
        evidence=(site, feature),
        hard_contradiction=False,
        strong_contradiction_ids=(),
    )


def _decision(candidate: DrawingCandidatePacket, *, candidate_id: str | None = None) -> dict:
    return {
        "verdict": "match",
        "candidate_id": candidate_id or candidate.candidate_id,
        "confidence": 0.98,
        "cited_support_ids": [candidate.evidence[0].id, candidate.evidence[1].id],
        "cited_contradiction_ids": [],
        "reason_codes": ["site_match", "feature_pair_match"],
        "summary": "same site and feature",
    }


def _stream_events(turn_id: str, response: str) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(method="turn/started", payload=SimpleNamespace()),
        SimpleNamespace(
            method="item/completed",
            payload=SimpleNamespace(
                item=SimpleNamespace(
                    root=SimpleNamespace(type="agentMessage", text=response, phase="final_answer")
                )
            ),
        ),
        SimpleNamespace(
            method="turn/completed",
            payload=SimpleNamespace(
                turn=SimpleNamespace(
                    id=turn_id,
                    status=SimpleNamespace(value="completed"),
                    error=None,
                )
            ),
        ),
    ]


class _FakeTurn:
    def __init__(
        self,
        turn_id: str,
        events: list[SimpleNamespace] | None = None,
        *,
        block_until_interrupt: bool = False,
    ) -> None:
        self.id = turn_id
        self.events = list(events or [])
        self.block_until_interrupt = block_until_interrupt
        self.interrupt_calls = 0
        self._release = threading.Event()

    def stream(self):
        if self.block_until_interrupt:
            self._release.wait(timeout=1.0)
        yield from self.events

    def interrupt(self):
        self.interrupt_calls += 1
        self._release.set()
        return SimpleNamespace()


class _FakeThread:
    def __init__(self, turns: list[_FakeTurn]) -> None:
        self.turns = list(turns)
        self.turn_calls: list[tuple[object, dict]] = []

    def turn(self, inputs, **kwargs):
        self.turn_calls.append((inputs, kwargs))
        return self.turns.pop(0)


class _FakeCodex:
    def __init__(self, turns: list[_FakeTurn]) -> None:
        self.thread = _FakeThread(turns)
        self.thread_start_calls: list[dict] = []

    def thread_start(self, **kwargs):
        self.thread_start_calls.append(kwargs)
        return self.thread


def test_sdk_config_defaults_to_high_reasoning_and_bounded_turn_timeout(monkeypatch):
    monkeypatch.delenv("DRAWING_CODEX_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("DRAWING_CODEX_TURN_TIMEOUT_SECONDS", raising=False)

    config = CodexDrawingResolverConfig.from_env()

    assert config.reasoning_effort == "high"
    assert config.turn_timeout_seconds == 180.0


def test_sdk_client_streams_luna_high_and_reuses_codex_session_without_api_key(
    monkeypatch,
    tmp_path,
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    source = _source(tmp_path)
    candidate = _candidate(tmp_path)
    response = json.dumps(_decision(candidate), ensure_ascii=False)
    fake_turn = _FakeTurn("turn-1", _stream_events("turn-1", response))
    fake = _FakeCodex([fake_turn])
    workdir = tmp_path / "codex-work"
    workdir.mkdir()
    progress: list[str] = []

    client = CodexSdkDrawingResolverClient(
        codex_client=fake,
        model="gpt-5.6-luna",
        reasoning_effort="high",
        turn_timeout_seconds=0.5,
        cwd=workdir,
        progress_callback=progress.append,
    )
    result = client.resolve(source, (candidate,))

    assert result.run_id == "turn-1"
    assert result.candidate_id == candidate.candidate_id
    start = fake.thread_start_calls[0]
    assert start["model"] == "gpt-5.6-luna"
    assert start["cwd"] == str(workdir.resolve())
    assert start["sandbox"].value == "read-only"
    assert start["approval_mode"].value == "deny_all"

    inputs, kwargs = fake.thread.turn_calls[0]
    assert inputs[0].text.startswith("You are resolving archaeology drawing identity")
    assert [Path(item.path).name for item in inputs[1:]] == ["source.png", "candidate.png"]
    assert kwargs["effort"] == "high"
    assert kwargs["output_schema"]["type"] == "object"
    assert kwargs["sandbox"].value == "read-only"
    assert kwargs["approval_mode"].value == "deny_all"
    assert any("turn/started" in message for message in progress)
    assert any("turn/completed" in message for message in progress)


def test_sdk_client_interrupts_timed_out_turn_then_retries(tmp_path):
    source = _source(tmp_path)
    candidate = _candidate(tmp_path)
    response = json.dumps(_decision(candidate), ensure_ascii=False)
    blocked = _FakeTurn("turn-timeout", block_until_interrupt=True)
    successful = _FakeTurn("turn-2", _stream_events("turn-2", response))
    fake = _FakeCodex([blocked, successful])
    workdir = tmp_path / "codex-work"
    workdir.mkdir()

    client = CodexSdkDrawingResolverClient(
        codex_client=fake,
        model="gpt-5.6-luna",
        reasoning_effort="high",
        turn_timeout_seconds=0.02,
        cwd=workdir,
    )
    result = client.resolve(source, (candidate,))

    assert result.run_id == "turn-2"
    assert blocked.interrupt_calls == 1
    assert len(fake.thread.turn_calls) == 2


def test_sdk_client_keeps_closed_world_validation_and_retries_once(tmp_path):
    source = _source(tmp_path)
    candidate = _candidate(tmp_path)
    invented = json.dumps(
        _decision(candidate, candidate_id="candidate:drawing:999"),
        ensure_ascii=False,
    )
    first = _FakeTurn("turn-1", _stream_events("turn-1", invented))
    second = _FakeTurn("turn-2", _stream_events("turn-2", invented))
    fake = _FakeCodex([first, second])
    workdir = tmp_path / "codex-work"
    workdir.mkdir()
    client = CodexSdkDrawingResolverClient(
        codex_client=fake,
        model="gpt-5.6-luna",
        reasoning_effort="high",
        turn_timeout_seconds=0.5,
        cwd=workdir,
    )

    with pytest.raises(CodexDrawingDecisionError, match="invented or invalid candidate id"):
        client.resolve(source, (candidate,))

    assert len(fake.thread_start_calls) == 2
    assert len(fake.thread.turn_calls) == 2
