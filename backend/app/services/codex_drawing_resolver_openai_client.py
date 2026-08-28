from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Iterable

import httpx
from openai import OpenAI, OpenAIError

from app.config import CodexDrawingResolverConfig
from app.domain.drawing_evidence_v3 import (
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingSourceEvidencePacket,
    DrawingV3Evidence,
    DrawingVisualRegion,
    drawing_visual_support_id,
)


class CodexDrawingDecisionError(RuntimeError):
    """Typed, fail-closed error for transport, format, or closed-world failures."""


_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["match", "ambiguous", "none"]},
        "candidate_id": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "cited_support_ids": {"type": "array", "items": {"type": "string"}},
        "cited_visual_support_ids": {"type": "array", "items": {"type": "string"}},
        "cited_contradiction_ids": {"type": "array", "items": {"type": "string"}},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": [
        "verdict",
        "candidate_id",
        "confidence",
        "cited_support_ids",
        "cited_visual_support_ids",
        "cited_contradiction_ids",
        "reason_codes",
        "summary",
    ],
    "additionalProperties": False,
}


class CodexDrawingResolverClient:
    def __init__(
        self,
        config: CodexDrawingResolverConfig,
        *,
        http_client: httpx.Client | None = None,
        openai_client: Any | None = None,
    ) -> None:
        self._config = config
        if openai_client is not None and http_client is not None:
            raise ValueError("provide openai_client or http_client, not both")
        self._openai = openai_client or OpenAI(
            api_key=config.api_key,
            base_url=self._sdk_base_url(config.base_url),
            timeout=config.timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )

    @staticmethod
    def _sdk_base_url(endpoint: str) -> str:
        value = endpoint.rstrip("/")
        if value.endswith("/responses"):
            return value[: -len("/responses")]
        return value

    @staticmethod
    def _mime_type(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".webp":
            return "image/webp"
        if suffix == ".gif":
            return "image/gif"
        return "image/png"

    @classmethod
    def _image_data_url(cls, region: DrawingVisualRegion) -> str:
        path = Path(region.image_path)
        if not path.is_file():
            raise CodexDrawingDecisionError(
                f"visual region file is missing: {region.region_id}"
            )
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{cls._mime_type(path)};base64,{encoded}"

    @staticmethod
    def _evidence_rows(evidence: Iterable[DrawingV3Evidence]) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "family": item.family,
                "method": item.method,
                "value": item.value,
                "supports": item.supports,
                "weak": item.weak,
            }
            for item in evidence
        ]

    @staticmethod
    def _visual_support_options(
        source: DrawingSourceEvidencePacket,
        candidate: DrawingCandidatePacket,
    ) -> list[dict[str, str]]:
        return [
            {
                "id": drawing_visual_support_id(
                    source.source_asset_id,
                    source_region.region_id,
                    candidate.candidate_id,
                    candidate_region.region_id,
                ),
                "source_region_id": source_region.region_id,
                "candidate_region_id": candidate_region.region_id,
            }
            for source_region in source.visual_regions
            for candidate_region in candidate.visual_regions
        ]

    @staticmethod
    def _image_order(
        source: DrawingSourceEvidencePacket,
        candidates: tuple[DrawingCandidatePacket, ...],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        attachment_index = 1
        for region in source.visual_regions:
            rows.append(
                {
                    "attachment_index": attachment_index,
                    "role": "source",
                    "source_region_id": region.region_id,
                }
            )
            attachment_index += 1
        for candidate in candidates:
            for region in candidate.visual_regions:
                rows.append(
                    {
                        "attachment_index": attachment_index,
                        "role": "candidate",
                        "candidate_id": candidate.candidate_id,
                        "candidate_region_id": region.region_id,
                    }
                )
                attachment_index += 1
        return rows

    def _prompt(
        self,
        source: DrawingSourceEvidencePacket,
        candidates: tuple[DrawingCandidatePacket, ...],
    ) -> str:
        packet = {
            "task": "Choose only among the supplied drawing candidates.",
            "rules": [
                "Return match only when one submitted candidate is sufficiently supported.",
                "Return ambiguous when multiple submitted candidates remain plausible.",
                "Return none when no submitted candidate is supported.",
                "Never invent candidate IDs, evidence IDs, or visual support IDs.",
                "Filename/path/sequence evidence is weak and cannot be sole identity authority.",
                "cited_visual_support_ids may contain only supplied visual_support_options for the selected candidate.",
                "Cite visual support only after inspecting both referenced submitted images and finding material agreement in geometry, layout, or depicted content; image presence alone is not support.",
                "For ambiguous or none, cited_visual_support_ids must be empty.",
            ],
            "image_order": self._image_order(source, candidates),
            "source": {
                "source_asset_id": source.source_asset_id,
                "publication_kind": source.publication_kind,
                "raw_text": source.raw_text,
                "visual_region_ids": [
                    region.region_id for region in source.visual_regions
                ],
                "facts": [
                    {
                        "kind": fact.kind,
                        "value": fact.value,
                        "normalized_value": fact.normalized_value,
                    }
                    for fact in source.facts
                ],
                "evidence": self._evidence_rows(source.evidence),
            },
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "publication_kind": candidate.publication_kind,
                    "number": candidate.number,
                    "captions": list(candidate.raw_texts),
                    "local_rank_score": candidate.local_score,
                    "visual_region_ids": [
                        region.region_id for region in candidate.visual_regions
                    ],
                    "visual_support_options": self._visual_support_options(
                        source, candidate
                    ),
                    "facts": [
                        {
                            "kind": fact.kind,
                            "value": fact.value,
                            "normalized_value": fact.normalized_value,
                        }
                        for fact in candidate.facts
                    ],
                    "evidence": self._evidence_rows(candidate.evidence),
                    "strong_contradiction_ids": list(
                        candidate.strong_contradiction_ids
                    ),
                }
                for candidate in candidates
            ],
        }
        return (
            "You are resolving archaeology drawing identity from a closed candidate set. "
            "Use only the supplied packet and images. Output only the requested schema.\n"
            + json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
        )

    def _request_payload(
        self,
        source: DrawingSourceEvidencePacket,
        candidates: tuple[DrawingCandidatePacket, ...],
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": self._prompt(source, candidates)}
        ]
        for region in source.visual_regions:
            content.append(
                {
                    "type": "input_image",
                    "image_url": self._image_data_url(region),
                    "detail": "auto",
                }
            )
        for candidate in candidates:
            for region in candidate.visual_regions:
                content.append(
                    {
                        "type": "input_image",
                        "image_url": self._image_data_url(region),
                        "detail": "auto",
                    }
                )
        return {
            "model": self._config.model,
            "store": False,
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "drawing_identity_decision",
                    "strict": True,
                    "schema": _DECISION_SCHEMA,
                }
            },
        }

    @staticmethod
    def _output_text(response_payload: dict[str, Any]) -> str:
        direct = response_payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        for item in response_payload.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if (
                    isinstance(content, dict)
                    and content.get("type") == "output_text"
                    and isinstance(content.get("text"), str)
                ):
                    return content["text"]
        raise CodexDrawingDecisionError("Responses API returned no output_text")

    @staticmethod
    def _string_tuple(payload: dict[str, Any], key: str) -> tuple[str, ...]:
        value = payload.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise CodexDrawingDecisionError(f"invalid {key}")
        return tuple(value)

    def _parse_decision(
        self,
        response_payload: dict[str, Any],
        *,
        candidates: tuple[DrawingCandidatePacket, ...],
        source: DrawingSourceEvidencePacket,
    ) -> CodexDrawingDecision:
        try:
            parsed = json.loads(self._output_text(response_payload))
        except json.JSONDecodeError as exc:
            raise CodexDrawingDecisionError("malformed decision JSON") from exc
        if not isinstance(parsed, dict):
            raise CodexDrawingDecisionError("decision JSON must be an object")

        verdict = parsed.get("verdict")
        if verdict not in {"match", "ambiguous", "none"}:
            raise CodexDrawingDecisionError("invalid verdict")
        candidate_id = parsed.get("candidate_id")
        submitted_candidate_ids = {candidate.candidate_id for candidate in candidates}
        selected_candidate: DrawingCandidatePacket | None = None
        if verdict == "match":
            if not isinstance(candidate_id, str) or candidate_id not in submitted_candidate_ids:
                raise CodexDrawingDecisionError("invented or invalid candidate id")
            selected_candidate = next(
                candidate for candidate in candidates if candidate.candidate_id == candidate_id
            )
        elif candidate_id is not None:
            raise CodexDrawingDecisionError(
                "ambiguous/none decision must not select a candidate"
            )

        confidence = parsed.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise CodexDrawingDecisionError("invalid confidence")
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise CodexDrawingDecisionError("invalid confidence")

        support_ids = self._string_tuple(parsed, "cited_support_ids")
        visual_value = parsed.get("cited_visual_support_ids", [])
        if not isinstance(visual_value, list) or not all(
            isinstance(item, str) for item in visual_value
        ):
            raise CodexDrawingDecisionError("invalid cited_visual_support_ids")
        visual_support_ids = tuple(visual_value)
        contradiction_ids = self._string_tuple(parsed, "cited_contradiction_ids")
        reason_codes = self._string_tuple(parsed, "reason_codes")
        submitted_evidence_ids = {
            item.id
            for item in source.evidence
        } | {
            item.id
            for candidate in candidates
            for item in candidate.evidence
        }
        if not set(support_ids) <= submitted_evidence_ids:
            raise CodexDrawingDecisionError("invented support evidence id")
        if not set(contradiction_ids) <= submitted_evidence_ids:
            raise CodexDrawingDecisionError("invented contradiction evidence id")

        if verdict != "match":
            if visual_support_ids:
                raise CodexDrawingDecisionError(
                    "ambiguous/none decision must not cite visual support"
                )
        elif selected_candidate is not None:
            allowed_visual_ids = {
                row["id"]
                for row in self._visual_support_options(source, selected_candidate)
            }
            if not set(visual_support_ids) <= allowed_visual_ids:
                raise CodexDrawingDecisionError(
                    "invented or invalid visual support id"
                )

        summary = parsed.get("summary")
        if not isinstance(summary, str):
            raise CodexDrawingDecisionError("invalid summary")
        run_id = response_payload.get("id")
        model = response_payload.get("model") or self._config.model
        if not isinstance(run_id, str) or not run_id:
            raise CodexDrawingDecisionError("Responses API returned no response id")
        if not isinstance(model, str) or not model:
            raise CodexDrawingDecisionError("Responses API returned no model")

        return CodexDrawingDecision(
            run_id=run_id,
            model=model,
            verdict=verdict,
            candidate_id=candidate_id,
            confidence=confidence,
            cited_support_ids=support_ids,
            cited_contradiction_ids=contradiction_ids,
            reason_codes=reason_codes,
            summary=summary,
            cited_visual_support_ids=visual_support_ids,
        )

    @staticmethod
    def _response_payload(response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        model_dump = getattr(response, "model_dump", None)
        if callable(model_dump):
            payload = model_dump()
            if isinstance(payload, dict):
                return payload
        to_dict = getattr(response, "to_dict", None)
        if callable(to_dict):
            payload = to_dict()
            if isinstance(payload, dict):
                return payload
        raise CodexDrawingDecisionError("Responses API payload must be an object")

    def resolve(
        self,
        source: DrawingSourceEvidencePacket,
        candidates: tuple[DrawingCandidatePacket, ...],
    ) -> CodexDrawingDecision:
        payload = self._request_payload(source, candidates)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = self._openai.responses.create(**payload)
                response_payload = self._response_payload(response)
                return self._parse_decision(
                    response_payload,
                    candidates=candidates,
                    source=source,
                )
            except (OpenAIError, ValueError, CodexDrawingDecisionError) as exc:
                last_error = exc
                if attempt == 0:
                    continue
                if isinstance(exc, CodexDrawingDecisionError):
                    raise exc
                raise CodexDrawingDecisionError(str(exc)) from exc
        raise CodexDrawingDecisionError(str(last_error or "Codex decision failed"))
