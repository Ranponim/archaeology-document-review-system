import os
import json
from dataclasses import dataclass
from typing import Any
import httpx
from app.jobs.ingest import ApiError, RateLimitedError


@dataclass(frozen=True, slots=True)
class OpenRouterConfig:
    api_key: str
    base_url: str = "https://openrouter.ai/api/v1/responses"
    model: str = "google/gemini-2.0-flash-001"
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "OpenRouterConfig":
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        base_url = os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/responses"
        )
        model = os.environ.get(
            "OPENROUTER_MODEL", "google/gemini-2.0-flash-001"
        )
        return cls(api_key=api_key, base_url=base_url, model=model)

    def __repr__(self) -> str:
        masked_key = "***" if self.api_key else "(none)"
        return (
            f"OpenRouterConfig(api_key='{masked_key}', base_url='{self.base_url}', "
            f"model='{self.model}', timeout={self.timeout_seconds}s)"
        )


class OpenRouterClient:
    def __init__(self, config: OpenRouterConfig | None = None) -> None:
        self._config = config or OpenRouterConfig.from_env()

    def _build_payload(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        system_instruction = (
            "당신은 고고학 보고서 검수 전문가입니다. 문맥 모순, 고고학 전문용어 오기, "
            "도면/도판/사진 번호 불일치를 엄격하게 검증합니다. 원본을 자동 수정하지 않고 "
            "JSON 형식의 교정 후보와 명확한 근거만을 제시해야 합니다."
        )
        user_content = f"{prompt}\n\n[검토 컨텍스트]:\n{json.dumps(context, ensure_ascii=False, indent=2)}"

        return {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

    async def analyze_text_discrepancy(
        self, prompt: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        if not self._config.api_key:
            raise ApiError("OPENROUTER_API_KEY is not configured in .env")

        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Ranponim/archaeology-document-review-system",
            "X-Title": "Archaeology Document Review System",
        }
        payload = self._build_payload(prompt, context)

        # Handle either base url or full endpoint path
        endpoint = self._config.base_url
        if not endpoint.endswith("/chat/completions") and not endpoint.endswith("/responses"):
            endpoint = endpoint.rstrip("/") + "/chat/completions"

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            try:
                response = await client.post(endpoint, json=payload, headers=headers)
                if response.status_code == 429:
                    raise RateLimitedError("OpenRouter rate limit exceeded")
                response.raise_for_status()
                data = response.json()
                return data
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise RateLimitedError("OpenRouter rate limit exceeded")
                raise ApiError(f"OpenRouter API request failed with status {e.response.status_code}")
            except httpx.RequestError as e:
                raise ApiError(f"OpenRouter network connection error: {e.__class__.__name__}")
