from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from typing import Any

import httpx

from app.jobs.ingest import ApiError, RateLimitedError
from app.services.json_utils import strip_markdown_json
from app.services.openrouter_client import OpenRouterConfig


@dataclass(frozen=True, slots=True)
class PanelProvenanceVLMResult:
    verdict: str
    confidence: float
    matching_features: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()

    @property
    def is_same_source(self) -> bool:
        return self.verdict == "SAME_SOURCE"


class PanelProvenanceVLMResolver:
    """Closed-world visual adjudicator for one panel and one JPG candidate.

    The public API intentionally accepts only image bytes and MIME types. File
    metadata, textual labels, and corpus identifiers cannot enter the prompt,
    so they cannot become provenance evidence accidentally.
    """

    DEFAULT_MODEL = "openai/gpt-5.6-luna"
    _VERDICTS = frozenset(
        {"SAME_SOURCE", "DIFFERENT_SOURCE", "INSUFFICIENT_EVIDENCE"}
    )

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        self._client = client
        self._model = model or os.environ.get(
            "PANEL_PROVENANCE_VLM_MODEL", self.DEFAULT_MODEL
        )

    @staticmethod
    def _image_part(image_bytes: bytes, mime_type: str) -> dict[str, Any]:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{encoded}",
                "detail": "low",
            },
        }

    def _build_payload(
        self,
        panel_bytes: bytes,
        candidate_bytes: bytes,
        panel_mime_type: str,
        candidate_mime_type: str,
    ) -> dict[str, Any]:
        system_instruction = (
            "You are a conservative visual provenance adjudicator. Compare exactly "
            "two supplied images using pixels only. Decide whether they depict the "
            "same underlying photograph despite crop, resize, recompression, border, "
            "or minor publication edits. Do not infer identity when visual evidence "
            "is weak or contradictory. Return only JSON with verdict, confidence, "
            "matching_features, and contradictions. verdict must be SAME_SOURCE, "
            "DIFFERENT_SOURCE, or INSUFFICIENT_EVIDENCE."
        )
        user_text = (
            "Compare Image A (the publication panel) with Image B (one retrieved "
            "candidate). Use visual content only. If decisive evidence is absent, "
            "return INSUFFICIENT_EVIDENCE."
        )
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        self._image_part(panel_bytes, panel_mime_type),
                        self._image_part(candidate_bytes, candidate_mime_type),
                    ],
                },
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }

    async def _call_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is not None and hasattr(
            self._client, "analyze_panel_provenance"
        ):
            return await self._client.analyze_panel_provenance(payload=payload)

        config = OpenRouterConfig.from_env()
        if not config.api_key:
            raise ApiError("OPENROUTER_API_KEY is not configured in .env")

        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Ranponim/archaeology-document-review-system",
            "X-Title": "Archaeology Panel Provenance VLM",
        }
        endpoint = config.base_url
        if not endpoint.endswith("/chat/completions") and not endpoint.endswith(
            "/responses"
        ):
            endpoint = endpoint.rstrip("/") + "/chat/completions"

        async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
            try:
                response = await client.post(endpoint, json=payload, headers=headers)
                if response.status_code == 429:
                    raise RateLimitedError("OpenRouter rate limit exceeded")
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 429:
                    raise RateLimitedError("OpenRouter rate limit exceeded")
                raise ApiError(
                    f"Panel provenance VLM request failed with status {error.response.status_code}"
                ) from error
            except httpx.RequestError as error:
                raise ApiError(
                    f"Panel provenance VLM connection error: {error.__class__.__name__}"
                ) from error

    @staticmethod
    def _response_text(response: dict[str, Any]) -> str:
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            content = choices[0].get("message", {}).get("content", "")
            if isinstance(content, str):
                return content

        output_text = response.get("output_text")
        if isinstance(output_text, str):
            return output_text

        output = response.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content_items = item.get("content")
                if not isinstance(content_items, list):
                    continue
                for content_item in content_items:
                    if not isinstance(content_item, dict):
                        continue
                    text = content_item.get("text")
                    if isinstance(text, str):
                        return text
        return ""

    @classmethod
    def _normalize_result(cls, raw_data: dict[str, Any]) -> PanelProvenanceVLMResult:
        verdict = str(raw_data.get("verdict") or "").strip().upper()
        if verdict not in cls._VERDICTS:
            verdict = "INSUFFICIENT_EVIDENCE"

        try:
            confidence = float(raw_data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))

        matching_raw = raw_data.get("matching_features")
        contradiction_raw = raw_data.get("contradictions")
        matching_features = (
            tuple(str(value) for value in matching_raw)
            if isinstance(matching_raw, list)
            else ()
        )
        contradictions = (
            tuple(str(value) for value in contradiction_raw)
            if isinstance(contradiction_raw, list)
            else ()
        )
        return PanelProvenanceVLMResult(
            verdict=verdict,
            confidence=confidence,
            matching_features=matching_features,
            contradictions=contradictions,
        )

    async def compare(
        self,
        *,
        panel_bytes: bytes,
        candidate_bytes: bytes,
        panel_mime_type: str = "image/jpeg",
        candidate_mime_type: str = "image/jpeg",
    ) -> PanelProvenanceVLMResult:
        payload = self._build_payload(
            panel_bytes,
            candidate_bytes,
            panel_mime_type,
            candidate_mime_type,
        )
        response = await self._call_api(payload)
        text = self._response_text(response)
        data: dict[str, Any] = {}
        if text:
            try:
                parsed = json.loads(strip_markdown_json(text))
                if isinstance(parsed, dict):
                    data = parsed
            except (TypeError, ValueError, json.JSONDecodeError):
                data = {}
        return self._normalize_result(data)
