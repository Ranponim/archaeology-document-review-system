from __future__ import annotations

import json
from pathlib import Path

import pymupdf
from PIL import Image
import pytest
from openai_codex import ApprovalMode, LocalImageInput, Sandbox, TextInput

from app.services.codex_sdk_plate_panel_client import (
    CodexPlatePanelDecisionError,
    CodexSdkPlatePanelClient,
)
from app.services.plate_panel_model_resolver import (
    PlatePanelModelCandidate,
    PlatePanelModelRequest,
)


def _write_pdf(path: Path) -> None:
    image_path = path.with_suffix(".jpg")
    Image.new("RGB", (100, 80), (80, 120, 160)).save(image_path, "JPEG")
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_image(pymupdf.Rect(20, 20, 180, 148), filename=str(image_path))
        doc.save(str(path))
    finally:
        doc.close()


def _request(tmp_path: Path) -> PlatePanelModelRequest:
    pdf_path = tmp_path / "plate.pdf"
    _write_pdf(pdf_path)
    candidates = []
    for asset_id, tone, score in (("a", 40, 0.92), ("b", 190, 0.88)):
        image_path = tmp_path / f"{asset_id}.jpg"
        Image.new("RGB", (90, 70), (tone, tone, tone)).save(image_path, "JPEG")
        candidates.append(
            PlatePanelModelCandidate(
                source_asset_id=asset_id,
                image_path=image_path,
                retrieval_score=score,
            )
        )
    return PlatePanelModelRequest(
        panel_id="panel-1",
        pdf_path=pdf_path,
        physical_page=1,
        bbox=(0.1, 0.1, 0.9, 0.74),
        candidates=tuple(candidates),
    )


def test_sdk_inputs_render_panel_and_label_each_candidate(tmp_path: Path) -> None:
    request = _request(tmp_path)
    client = CodexSdkPlatePanelClient(
        model="gpt-5.6-luna",
        cwd=tmp_path,
        codex_client=object(),
    )

    inputs = client._sdk_inputs(request)

    texts = [item.text for item in inputs if isinstance(item, TextInput)]
    image_paths = [Path(item.path) for item in inputs if isinstance(item, LocalImageInput)]
    assert any("same original photograph" in text for text in texts)
    assert any("PANEL_ID=panel-1" in text for text in texts)
    assert any("CANDIDATE_ID=a" in text and "0.920000" in text for text in texts)
    assert any("CANDIDATE_ID=b" in text and "0.880000" in text for text in texts)
    assert len(image_paths) == 3
    assert image_paths[0].is_file()
    assert image_paths[1:] == [
        Path(request.candidates[0].image_path).resolve(),
        Path(request.candidates[1].image_path).resolve(),
    ]


def test_thread_contract_is_ephemeral_read_only_and_deny_all(tmp_path: Path) -> None:
    client = CodexSdkPlatePanelClient(
        model="gpt-5.6-luna",
        cwd=tmp_path,
        codex_client=object(),
    )

    kwargs = client._thread_start_kwargs()

    assert kwargs["ephemeral"] is True
    assert kwargs["sandbox"] == Sandbox.read_only
    assert kwargs["approval_mode"] == ApprovalMode.deny_all
    assert "Do not inspect the filesystem" in kwargs["developer_instructions"]


def test_parse_decision_accepts_closed_world_json(tmp_path: Path) -> None:
    request = _request(tmp_path)
    client = CodexSdkPlatePanelClient(
        model="gpt-5.6-luna",
        cwd=tmp_path,
        codex_client=object(),
    )
    raw = json.dumps(
        {
            "verdict": "match",
            "candidate_id": "a",
            "confidence": 0.98,
            "rationale": "same crop and scene geometry",
        }
    )

    decision = client._parse_decision(raw, request=request)

    assert decision.verdict == "match"
    assert decision.candidate_id == "a"
    assert decision.confidence == pytest.approx(0.98)


def test_parse_decision_fails_on_candidate_outside_closed_world(tmp_path: Path) -> None:
    request = _request(tmp_path)
    client = CodexSdkPlatePanelClient(
        model="gpt-5.6-luna",
        cwd=tmp_path,
        codex_client=object(),
    )
    raw = json.dumps(
        {
            "verdict": "match",
            "candidate_id": "outside",
            "confidence": 0.99,
            "rationale": "invalid candidate",
        }
    )

    with pytest.raises(CodexPlatePanelDecisionError, match="outside closed world"):
        client._parse_decision(raw, request=request)


def test_parse_decision_fails_closed_on_malformed_json(tmp_path: Path) -> None:
    request = _request(tmp_path)
    client = CodexSdkPlatePanelClient(
        model="gpt-5.6-luna",
        cwd=tmp_path,
        codex_client=object(),
    )

    with pytest.raises(CodexPlatePanelDecisionError, match="JSON"):
        client._parse_decision("not json", request=request)
