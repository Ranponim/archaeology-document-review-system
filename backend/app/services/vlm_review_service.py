import base64
from dataclasses import dataclass
import json
import os
from typing import Any
import httpx
from app.jobs.ingest import ApiError, RateLimitedError
from app.services.asset_cache import AssetHashCache
from app.services.image_processor import ImageProcessor
from app.services.json_utils import strip_markdown_json
from app.services.openrouter_client import OpenRouterConfig


@dataclass(frozen=True, slots=True)
class VLMReviewResult:
    label_detected: str
    feature_number: str
    site_point: str
    compass_north: str | None
    is_match: bool
    match_confidence: float
    rationale: str
    is_cached: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0


class VLMReviewService:
    DEFAULT_MODEL = "openai/gpt-5.6-luna"

    def __init__(
        self,
        client: Any | None = None,
        cache: AssetHashCache | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or os.environ.get("OPENROUTER_MODEL", self.DEFAULT_MODEL)
        self._cache = cache or AssetHashCache()
        self._client = client

    def _build_multimodal_payload(
        self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
    ) -> dict[str, Any]:
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        image_data_uri = f"data:{mime_type};base64,{b64_image}"

        system_instruction = (
            "당신은 고고학 발굴보고서 시각 검수 VLM 전문가입니다. 사진 속의 표찰 텍스트, "
            "유구 번호판, 스케일바(축척), 방위표(북향 화살표)를 정밀 판독하고 "
            "본문 유구 서술과의 일치 여부를 JSON 형식으로 출력합니다."
        )

        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_uri, "detail": "low"},
                        },
                    ],
                },
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

    async def _call_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is not None and hasattr(self._client, "analyze_multimodal"):
            return await self._client.analyze_multimodal(
                prompt=payload["messages"][1]["content"][0]["text"],
                image_bytes=b"",
                mime_type="image/jpeg",
            )

        config = OpenRouterConfig.from_env()
        if not config.api_key:
            raise ApiError("OPENROUTER_API_KEY is not configured in .env")

        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Ranponim/archaeology-document-review-system",
            "X-Title": "Archaeology Document Review System VLM",
        }
        endpoint = config.base_url
        if not endpoint.endswith("/chat/completions") and not endpoint.endswith("/responses"):
            endpoint = endpoint.rstrip("/") + "/chat/completions"

        async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
            try:
                response = await client.post(endpoint, json=payload, headers=headers)
                if response.status_code == 429:
                    raise RateLimitedError("OpenRouter rate limit exceeded")
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise RateLimitedError("OpenRouter rate limit exceeded")
                raise ApiError(f"VLM API request failed with status {e.response.status_code}")
            except httpx.RequestError as e:
                raise ApiError(f"VLM connection error: {e.__class__.__name__}")

    async def verify_plate_photo(
        self,
        image_bytes: bytes,
        expected_feature: str,
        expected_site: str = "",
        mime_type: str = "image/jpeg",
    ) -> VLMReviewResult:
        processed_bytes = ImageProcessor.prepare_for_vlm(image_bytes)
        image_hash = self._cache.compute_bytes_hash(processed_bytes)
        prompt_text = (
            f"이 발굴 사진의 표찰을 판독하여 유적 지점(예: '{expected_site}') 및 "
            f"유구 번호(예: '{expected_feature}')와 일치하는지 판별하십시오.\n"
            f"JSON 형식: {{\"label_detected\": \"...\", \"feature_number\": \"...\", \"site_point\": \"...\", \"compass_north\": \"...\", \"match_confidence\": 0.95, \"rationale\": \"...\"}}"
        )

        # 1. Check SHA-256 Cache
        cached_data = self._cache.get_cached_result(image_hash, prompt_text)
        if cached_data is not None:
            is_match = (
                (bool(expected_site) and expected_site in cached_data.get("site_point", ""))
                or (bool(expected_feature) and expected_feature in cached_data.get("label_detected", ""))
            ) or bool(cached_data.get("is_match", False))
            return VLMReviewResult(
                label_detected=cached_data.get("label_detected", ""),
                feature_number=cached_data.get("feature_number", ""),
                site_point=cached_data.get("site_point", ""),
                compass_north=cached_data.get("compass_north"),
                is_match=is_match,
                match_confidence=cached_data.get("match_confidence", 1.0),
                rationale=cached_data.get("rationale", "Loaded from cache (0 API cost)"),
                is_cached=True,
                prompt_tokens=0,
                completion_tokens=0,
            )

        # 2. Call VLM API (Cache Miss)
        payload = self._build_multimodal_payload(prompt_text, processed_bytes, mime_type)
        response = await self._call_api(payload)

        prompt_tokens = response.get("usage", {}).get("prompt_tokens", 0)
        completion_tokens = response.get("usage", {}).get("completion_tokens", 0)

        data = {}
        choices = response.get("choices", [])
        if choices:
            msg_str = choices[0].get("message", {}).get("content", "{}")
            try:
                data = json.loads(strip_markdown_json(msg_str))
            except json.JSONDecodeError:
                data = {}

        # 3. Store result in SHA-256 Cache for future reuse
        self._cache.store_result(image_hash, prompt_text, data)

        is_match = (
            (bool(expected_site) and expected_site in data.get("site_point", ""))
            or (bool(expected_feature) and expected_feature in data.get("label_detected", ""))
        ) or bool(data.get("is_match", False))

        return VLMReviewResult(
            label_detected=data.get("label_detected", ""),
            feature_number=data.get("feature_number", ""),
            site_point=data.get("site_point", ""),
            compass_north=data.get("compass_north"),
            is_match=is_match,
            match_confidence=data.get("match_confidence", 0.0),
            rationale=data.get("rationale", ""),
            is_cached=False,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
