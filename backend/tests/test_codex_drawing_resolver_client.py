import json
from pathlib import Path

import httpx
import pytest

from app.config import CodexDrawingResolverConfig
from app.domain.drawing_evidence_v3 import (
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
    DrawingVisualRegion,
)
from app.services.codex_drawing_resolver_client import (
    CodexDrawingDecisionError,
    CodexDrawingResolverClient,
)


def _write_image(path: Path) -> str:
    path.write_bytes(b"fake-png-bytes")
    return str(path)


def _source(tmp_path: Path) -> DrawingSourceEvidencePacket:
    source_ev = DrawingV3Evidence(
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
        evidence=(source_ev,),
    )


def _candidate(tmp_path: Path, number: str = "52") -> DrawingCandidatePacket:
    site_ev = DrawingV3Evidence(
        id=f"ev:candidate:{number}:site",
        family="spatial_signature",
        method="exact_site_point",
        value="2",
    )
    feature_ev = DrawingV3Evidence(
        id=f"ev:candidate:{number}:feature",
        family="archaeology_signature",
        method="exact_feature_pair",
        value="토광묘:1",
    )
    return DrawingCandidatePacket(
        candidate_id=f"candidate:drawing:{number}",
        publication_kind="drawing",
        number=number,
        raw_texts=(f"도면 {number}. 2지점 1호 토광묘",),
        facts=(),
        visual_regions=(
            DrawingVisualRegion(
                region_id=f"body:drawing:{number}",
                image_path=_write_image(tmp_path / f"candidate-{number}.png"),
                page=1,
                bbox=(1.0, 1.0, 10.0, 10.0),
                confidence=1.0,
            ),
        ),
        local_score=18.0,
        evidence=(site_ev, feature_ev),
        hard_contradiction=False,
        strong_contradiction_ids=(),
    )


def _response_text(payload: dict, *, response_id: str = "resp-1") -> dict:
    return {
        "id": response_id,
        "model": "gpt-5.3-codex",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(payload, ensure_ascii=False),
                    }
                ],
            }
        ],
    }


def _valid_payload(candidate: DrawingCandidatePacket) -> dict:
    return {
        "verdict": "match",
        "candidate_id": candidate.candidate_id,
        "confidence": 0.98,
        "cited_support_ids": [
            candidate.evidence[0].id,
            candidate.evidence[1].id,
        ],
        "cited_contradiction_ids": [],
        "reason_codes": ["site_match", "feature_pair_match"],
        "summary": "same site and feature",
    }


def _config() -> CodexDrawingResolverConfig:
    return CodexDrawingResolverConfig(
        api_key="test-key",
        model="gpt-5.3-codex",
        timeout_seconds=3.0,
        auto_confidence=0.95,
        max_candidates=10,
        max_expansions=1,
    )


def test_client_sends_closed_world_multimodal_structured_request(tmp_path):
    source = _source(tmp_path)
    candidate = _candidate(tmp_path)
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        return httpx.Response(200, json=_response_text(_valid_payload(candidate)))

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = CodexDrawingResolverClient(_config(), http_client=http_client)

    decision = client.resolve(source, (candidate,))

    assert decision.verdict == "match"
    assert decision.candidate_id == candidate.candidate_id
    assert decision.confidence == 0.98
    assert decision.run_id == "resp-1"
    assert decision.model == "gpt-5.3-codex"

    request = captured[0]
    assert request["model"] == "gpt-5.3-codex"
    assert request["store"] is False
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    content = request["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    prompt = content[0]["text"]
    assert candidate.candidate_id in prompt
    assert candidate.evidence[0].id in prompt
    assert source.evidence[0].id in prompt
    image_parts = [item for item in content if item["type"] == "input_image"]
    assert len(image_parts) == 2
    assert all(item["image_url"].startswith("data:image/png;base64,") for item in image_parts)


@pytest.mark.parametrize(
    "mutator,error_match",
    [
        (lambda payload: payload.update(candidate_id="candidate:drawing:999"), "candidate"),
        (lambda payload: payload.update(cited_support_ids=["ev:invented"]), "evidence"),
        (lambda payload: payload.update(cited_contradiction_ids=["ev:invented"]), "evidence"),
        (lambda payload: payload.update(confidence=1.5), "confidence"),
    ],
)
def test_client_rejects_invented_or_invalid_closed_world_output(tmp_path, mutator, error_match):
    source = _source(tmp_path)
    candidate = _candidate(tmp_path)
    payload = _valid_payload(candidate)
    mutator(payload)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_response_text(payload, response_id=f"resp-{calls}"))

    client = CodexDrawingResolverClient(
        _config(), http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(CodexDrawingDecisionError, match=error_match):
        client.resolve(source, (candidate,))
    assert calls == 2


def test_client_accepts_ambiguous_and_none_without_candidate(tmp_path):
    source = _source(tmp_path)
    candidate = _candidate(tmp_path)
    payloads = [
        {
            "verdict": "ambiguous",
            "candidate_id": None,
            "confidence": 0.55,
            "cited_support_ids": [],
            "cited_contradiction_ids": [],
            "reason_codes": ["insufficient_margin"],
            "summary": "two candidates remain plausible",
        },
        {
            "verdict": "none",
            "candidate_id": None,
            "confidence": 0.2,
            "cited_support_ids": [],
            "cited_contradiction_ids": [],
            "reason_codes": ["no_supported_candidate"],
            "summary": "none of the supplied candidates fit",
        },
    ]

    for payload in payloads:
        client = CodexDrawingResolverClient(
            _config(),
            http_client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda request, payload=payload: httpx.Response(
                        200, json=_response_text(payload)
                    )
                )
            ),
        )
        decision = client.resolve(source, (candidate,))
        assert decision.verdict == payload["verdict"]
        assert decision.candidate_id is None


def test_client_retries_once_after_malformed_output_then_succeeds(tmp_path):
    source = _source(tmp_path)
    candidate = _candidate(tmp_path)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "id": "resp-bad",
                    "model": "gpt-5.3-codex",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "not-json"}],
                        }
                    ],
                },
            )
        return httpx.Response(200, json=_response_text(_valid_payload(candidate)))

    client = CodexDrawingResolverClient(
        _config(), http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    decision = client.resolve(source, (candidate,))
    assert decision.verdict == "match"
    assert calls == 2


def test_client_retries_once_after_transport_error_then_succeeds(tmp_path):
    source = _source(tmp_path)
    candidate = _candidate(tmp_path)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary", request=request)
        return httpx.Response(200, json=_response_text(_valid_payload(candidate)))

    client = CodexDrawingResolverClient(
        _config(), http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    decision = client.resolve(source, (candidate,))
    assert decision.verdict == "match"
    assert calls == 2


def test_client_raises_typed_error_after_two_malformed_responses(tmp_path):
    source = _source(tmp_path)
    candidate = _candidate(tmp_path)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "id": f"resp-{calls}",
                "model": "gpt-5.3-codex",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "{"}]}
                ],
            },
        )

    client = CodexDrawingResolverClient(
        _config(), http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(CodexDrawingDecisionError):
        client.resolve(source, (candidate,))
    assert calls == 2
