from __future__ import annotations

import json

import pytest

from app.config import CodexDrawingResolverConfig
from app.domain.drawing_evidence_v3 import (
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
    DrawingVisualRegion,
    drawing_visual_support_id,
)
from app.services.codex_drawing_resolver_openai_client import (
    CodexDrawingDecisionError,
    CodexDrawingResolverClient,
    _DECISION_SCHEMA,
)


def _source() -> DrawingSourceEvidencePacket:
    return DrawingSourceEvidencePacket(
        source_asset_id="asset-1",
        source_sha256="source-sha",
        original_name="source.ai",
        source_path="site/source.ai",
        raw_text="",
        publication_kind="drawing",
        internal_numbers=(),
        facts=(),
        visual_regions=(
            DrawingVisualRegion(
                region_id="source:asset-1",
                image_path="/tmp/source.png",
                page=1,
                bbox=None,
                confidence=1.0,
                source_sha256="source-sha",
            ),
        ),
        evidence=(),
    )


def _candidate(number: str) -> DrawingCandidatePacket:
    weak = DrawingV3Evidence(
        id=f"ev:filename:{number}",
        family="weak_filename_semantic",
        method="filename_semantic",
        value=f"drawing:{number}",
        supports=True,
        weak=True,
    )
    return DrawingCandidatePacket(
        candidate_id=f"candidate:asset-1:drawing:{number}",
        publication_kind="drawing",
        number=number,
        raw_texts=(f"도면 {number}",),
        facts=(),
        visual_regions=(
            DrawingVisualRegion(
                region_id=f"body:drawing:{number}",
                image_path=f"/tmp/body-{number}.png",
                page=12,
                bbox=(1.0, 1.0, 10.0, 10.0),
                confidence=1.0,
                source_sha256="body-sha",
            ),
        ),
        local_score=10.0,
        evidence=(weak,),
        hard_contradiction=False,
        strong_contradiction_ids=(),
    )


def _client() -> CodexDrawingResolverClient:
    config = CodexDrawingResolverConfig(
        api_key="test-key",
        model="gpt-5.6-luna",
        timeout_seconds=3.0,
        auto_confidence=0.95,
        max_candidates=10,
        max_expansions=1,
    )
    return CodexDrawingResolverClient(config, openai_client=object())


def _response(payload: dict) -> dict:
    return {
        "id": "turn-1",
        "model": "gpt-5.6-luna",
        "output_text": json.dumps(payload, ensure_ascii=False),
    }


def _payload(candidate: DrawingCandidatePacket, visual_ids: list[str]) -> dict:
    return {
        "verdict": "match",
        "candidate_id": candidate.candidate_id,
        "confidence": 0.97,
        "cited_support_ids": [candidate.evidence[0].id],
        "cited_visual_support_ids": visual_ids,
        "cited_contradiction_ids": [],
        "reason_codes": ["visual_match"],
        "summary": "material visual agreement",
    }


def test_prompt_and_schema_publish_closed_world_visual_support_options():
    source = _source()
    candidate = _candidate("35")
    visual_id = drawing_visual_support_id(
        source.source_asset_id,
        source.visual_regions[0].region_id,
        candidate.candidate_id,
        candidate.visual_regions[0].region_id,
    )

    prompt = _client()._prompt(source, (candidate,))

    assert "visual_support_options" in prompt
    assert visual_id in prompt
    assert '"source_region_id":"source:asset-1"' in prompt
    assert '"candidate_region_id":"body:drawing:35"' in prompt
    assert '"attachment_index":1' in prompt
    assert '"attachment_index":2' in prompt
    assert "cited_visual_support_ids" in _DECISION_SCHEMA["properties"]
    assert "cited_visual_support_ids" in _DECISION_SCHEMA["required"]


def test_parser_accepts_only_submitted_visual_pair_for_selected_candidate():
    source = _source()
    selected = _candidate("35")
    other = _candidate("36")
    valid_visual_id = drawing_visual_support_id(
        source.source_asset_id,
        source.visual_regions[0].region_id,
        selected.candidate_id,
        selected.visual_regions[0].region_id,
    )

    decision = _client()._parse_decision(
        _response(_payload(selected, [valid_visual_id])),
        candidates=(selected, other),
        source=source,
    )

    assert decision.cited_visual_support_ids == (valid_visual_id,)


def test_parser_rejects_invented_visual_support_id():
    source = _source()
    selected = _candidate("35")

    with pytest.raises(CodexDrawingDecisionError, match="visual"):
        _client()._parse_decision(
            _response(
                _payload(selected, ["drawing-v3-visual-support:invented"])
            ),
            candidates=(selected,),
            source=source,
        )


def test_parser_rejects_visual_pair_belonging_to_unselected_candidate():
    source = _source()
    selected = _candidate("35")
    other = _candidate("36")
    other_visual_id = drawing_visual_support_id(
        source.source_asset_id,
        source.visual_regions[0].region_id,
        other.candidate_id,
        other.visual_regions[0].region_id,
    )

    with pytest.raises(CodexDrawingDecisionError, match="visual"):
        _client()._parse_decision(
            _response(_payload(selected, [other_visual_id])),
            candidates=(selected, other),
            source=source,
        )
