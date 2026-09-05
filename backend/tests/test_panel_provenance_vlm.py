from __future__ import annotations

import json

import pytest

from app.services.panel_provenance_vlm import PanelProvenanceVLMResolver


class _FakePanelClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.payloads: list[dict] = []

    async def analyze_panel_provenance(self, *, payload: dict) -> dict:
        self.payloads.append(payload)
        return self.response


def _chat_response(data: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(data, ensure_ascii=False),
                }
            }
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_verdict", "expected"),
    [
        ("SAME_SOURCE", "SAME_SOURCE"),
        ("different_source", "DIFFERENT_SOURCE"),
        ("INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE"),
        ("looks_similar", "INSUFFICIENT_EVIDENCE"),
    ],
)
async def test_panel_provenance_vlm_normalizes_verdicts(raw_verdict, expected):
    fake = _FakePanelClient(
        _chat_response(
            {
                "verdict": raw_verdict,
                "confidence": 0.91,
                "matching_features": ["same crop geometry"],
                "contradictions": [],
            }
        )
    )
    resolver = PanelProvenanceVLMResolver(client=fake)

    result = await resolver.compare(
        panel_bytes=b"panel-image",
        candidate_bytes=b"candidate-image",
    )

    assert result.verdict == expected
    assert result.confidence == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_panel_provenance_vlm_payload_has_exactly_two_images_and_no_metadata_hints():
    fake = _FakePanelClient(
        _chat_response(
            {
                "verdict": "INSUFFICIENT_EVIDENCE",
                "confidence": 0.2,
                "matching_features": [],
                "contradictions": [],
            }
        )
    )
    resolver = PanelProvenanceVLMResolver(client=fake)

    await resolver.compare(
        panel_bytes=b"first-secret-bytes",
        candidate_bytes=b"second-secret-bytes",
    )

    assert len(fake.payloads) == 1
    payload = fake.payloads[0]
    user_content = payload["messages"][1]["content"]
    image_parts = [part for part in user_content if part.get("type") == "image_url"]
    assert len(image_parts) == 2

    prompt_text = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in (
        "filename",
        "file name",
        "filepath",
        "file path",
        "caption",
        "sequence number",
        "source_asset_id",
    ):
        assert forbidden not in prompt_text


@pytest.mark.asyncio
async def test_panel_provenance_vlm_malformed_response_fails_closed():
    fake = _FakePanelClient({"choices": [{"message": {"content": "not-json"}}]})
    resolver = PanelProvenanceVLMResolver(client=fake)

    result = await resolver.compare(
        panel_bytes=b"panel-image",
        candidate_bytes=b"candidate-image",
    )

    assert result.verdict == "INSUFFICIENT_EVIDENCE"
    assert result.confidence == 0.0
    assert result.matching_features == ()
    assert result.contradictions == ()
