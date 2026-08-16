import base64
from dataclasses import dataclass, field
import json
import os
import re
from typing import Any
import httpx
from app.jobs.ingest import ApiError, RateLimitedError
from app.services.asset_cache import AssetHashCache
from app.services.image_processor import ImageProcessor
from app.services.json_utils import strip_markdown_json
from app.services.openrouter_client import OpenRouterConfig


@dataclass(frozen=True, slots=True)
class VLMReviewResult:
    status: str  # "SUPPORTED", "PARTIAL", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"
    observations: dict[str, Any] = field(default_factory=dict)
    supported_claims: list[str] = field(default_factory=list)
    contradicted_claims: list[str] = field(default_factory=list)
    unobservable_claims: list[str] = field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""
    cost_usd: float = 0.0
    cost_krw: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    is_cached: bool = False

    @property
    def is_match(self) -> bool:
        return self.status == "SUPPORTED"

    @property
    def label_detected(self) -> str:
        return str(
            self.observations.get("site_label")
            or self.observations.get("label_detected")
            or ""
        )

    @property
    def feature_number(self) -> str:
        return str(self.observations.get("feature_number", ""))

    @property
    def site_point(self) -> str:
        return str(
            self.observations.get("site_point")
            or self.observations.get("site_label")
            or ""
        )

    @property
    def compass_north(self) -> str | None:
        return self.observations.get("orientation") or self.observations.get(
            "compass_north"
        )

    @property
    def match_confidence(self) -> float:
        return self.confidence


class VLMReviewService:
    DEFAULT_MODEL = "openai/gpt-5.6-luna"
    USD_PER_PROMPT_TOKEN: float = 2.50 / 1_000_000
    USD_PER_COMPLETION_TOKEN: float = 10.00 / 1_000_000
    DEFAULT_KRW_EXCHANGE_RATE: float = 1400.0

    def __init__(
        self,
        client: Any | None = None,
        cache: AssetHashCache | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or os.environ.get("OPENROUTER_MODEL", self.DEFAULT_MODEL)
        self._cache = cache or AssetHashCache()
        self._client = client

    @staticmethod
    def _extract_feature_number(text: str) -> str | None:
        if not text:
            return None
        match = re.search(r"(\d+)\s*호", text)
        if match:
            return match.group(1)
        digits = re.findall(r"\d+", text)
        if digits:
            return digits[0]
        return None

    def _build_multimodal_payload(
        self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg"
    ) -> dict[str, Any]:
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        image_data_uri = f"data:{mime_type};base64,{b64_image}"

        system_instruction = (
            "당신은 고고학 발굴보고서 시각 검수 VLM 전문가입니다.\n"
            "사진 속의 표찰 텍스트(site_label), 유구 번호(feature_number), 유구/유물 종류(object_type), "
            "조사 단계(investigation_stage), 토층 상태(soil_layer), 방위(orientation), 스케일(scale)을 정밀 판독하고 "
            "주어진 주장(claims) 및 유구 정보와의 일치 여부를 아래 JSON 형식으로 출력하십시오.\n\n"
            "JSON 형식:\n"
            "{\n"
            '  "status": "SUPPORTED" | "PARTIAL" | "CONTRADICTED" | "INSUFFICIENT_EVIDENCE",\n'
            '  "observations": {\n'
            '    "site_label": "판독된 전체 표찰 문자열",\n'
            '    "feature_number": "판독된 유구 번호 (예: 2)",\n'
            '    "object_type": "유구/유물 유형 (예: 토광묘, 석곽묘, 주거지)",\n'
            '    "investigation_stage": "조사 단계 (예: 완굴, 토층조사, 노출)",\n'
            '    "soil_layer": "토층 정보",\n'
            '    "orientation": "방위 (예: N-74-E)",\n'
            '    "scale": "스케일/축척 (예: 1:20)"\n'
            "  },\n"
            '  "supported_claims": ["관측으로 뒷받침되는 주장 목록"],\n'
            '  "contradicted_claims": ["관측과 명백히 불일치하는 주장 목록"],\n'
            '  "unobservable_claims": ["단일 사진 각도/해상도로는 확인 불가한 주장 목록 (예: 배면 잔손질, 내부 토색 등)"],\n'
            '  "confidence": 0.95,\n'
            '  "rationale": "판독 및 검증 근거 설명"\n'
            "}"
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

    def _normalize_result(
        self,
        raw_data: dict[str, Any],
        expected_feature: str,
        expected_site: str,
        claims: list[str] | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        is_cached: bool = False,
    ) -> VLMReviewResult:
        obs_raw = raw_data.get("observations")
        if isinstance(obs_raw, dict):
            observations = dict(obs_raw)
        else:
            observations = {}

        # Backwards-compatible fallback for observation keys
        if "site_label" not in observations:
            if "label_detected" in raw_data:
                observations["site_label"] = raw_data["label_detected"]
            elif "site_point" in raw_data:
                observations["site_label"] = raw_data["site_point"]
        if "feature_number" not in observations and "feature_number" in raw_data:
            observations["feature_number"] = raw_data["feature_number"]
        if "site_point" not in observations and "site_point" in raw_data:
            observations["site_point"] = raw_data["site_point"]
        if "orientation" not in observations and "compass_north" in raw_data:
            observations["orientation"] = raw_data["compass_north"]

        supported_claims = [str(c) for c in raw_data.get("supported_claims", [])]
        contradicted_claims = [str(c) for c in raw_data.get("contradicted_claims", [])]
        unobservable_claims = [str(c) for c in raw_data.get("unobservable_claims", [])]
        confidence = float(raw_data.get("confidence") or raw_data.get("match_confidence") or 0.0)
        rationale = str(raw_data.get("rationale") or "")
        status = str(raw_data.get("status") or "").upper()

        # Site-same / Feature-different safety check
        expected_num = self._extract_feature_number(expected_feature)
        observed_num = self._extract_feature_number(str(observations.get("feature_number", "")))
        if not observed_num:
            observed_num = self._extract_feature_number(str(observations.get("site_label", "")))

        if expected_num and observed_num and expected_num != observed_num:
            contradiction_msg = f"유구 번호 불일치 (기대: {expected_feature} vs 관측: {observed_num}호)"
            if not any(
                "유구 번호 불일치" in c or (expected_num in c and observed_num in c)
                for c in contradicted_claims
            ):
                contradicted_claims.append(contradiction_msg)
            supported_claims = [
                c for c in supported_claims if expected_feature not in c and contradiction_msg not in c
            ]
            status = "CONTRADICTED"

        # Contradictions dictate status
        if contradicted_claims:
            if status not in ("CONTRADICTED", "PARTIAL"):
                status = "CONTRADICTED"

        # Unobservable claims downgrade status if no contradictions
        if unobservable_claims and not contradicted_claims:
            if status == "SUPPORTED":
                if supported_claims:
                    status = "PARTIAL"
                else:
                    status = "INSUFFICIENT_EVIDENCE"

        # Default / fallback resolution for status
        if status not in {"SUPPORTED", "PARTIAL", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"}:
            if contradicted_claims:
                status = "CONTRADICTED"
            elif unobservable_claims and supported_claims:
                status = "PARTIAL"
            elif unobservable_claims and not supported_claims:
                status = "INSUFFICIENT_EVIDENCE"
            elif (
                raw_data.get("is_match") is True
                or (expected_num and observed_num and expected_num == observed_num)
                or (expected_feature and expected_feature in observations.get("site_label", ""))
            ):
                status = "SUPPORTED"
                if not supported_claims and expected_feature:
                    supported_claims.append(f"{expected_feature} 확인")
            else:
                status = "INSUFFICIENT_EVIDENCE"

        if confidence <= 0.0:
            if status == "SUPPORTED":
                confidence = 0.95
            elif status == "PARTIAL":
                confidence = 0.70
            elif status == "CONTRADICTED":
                confidence = 0.90
            else:
                confidence = 0.0

        if is_cached:
            cost_usd = 0.0
            cost_krw = 0.0
            p_tokens = 0
            c_tokens = 0
        else:
            p_tokens = prompt_tokens
            c_tokens = completion_tokens
            cost_usd = (p_tokens * self.USD_PER_PROMPT_TOKEN) + (c_tokens * self.USD_PER_COMPLETION_TOKEN)
            cost_krw = cost_usd * self.DEFAULT_KRW_EXCHANGE_RATE

        return VLMReviewResult(
            status=status,
            observations=observations,
            supported_claims=supported_claims,
            contradicted_claims=contradicted_claims,
            unobservable_claims=unobservable_claims,
            confidence=confidence,
            rationale=rationale,
            cost_usd=cost_usd,
            cost_krw=cost_krw,
            prompt_tokens=p_tokens,
            completion_tokens=c_tokens,
            is_cached=is_cached,
        )

    async def verify_plate_photo(
        self,
        image_bytes: bytes,
        expected_feature: str,
        expected_site: str = "",
        claims: list[str] | None = None,
        mime_type: str = "image/jpeg",
    ) -> VLMReviewResult:
        processed_bytes = ImageProcessor.prepare_for_vlm(image_bytes)
        image_hash = self._cache.compute_bytes_hash(processed_bytes)

        claims_prompt = ""
        if claims:
            claims_formatted = "\n".join(f"- {c}" for c in claims)
            claims_prompt = f"\n[검증 대상 주장 목록 (Claims)]:\n{claims_formatted}\n"

        prompt_text = (
            f"이 발굴 사진의 표찰 및 시각 정보를 판독하여 유적 지점(예: '{expected_site}') 및 "
            f"유구 번호(예: '{expected_feature}')와 일치하는지 분석하십시오.{claims_prompt}\n"
            f"JSON 규격에 맞추어 observations, supported_claims, contradicted_claims, unobservable_claims, status, confidence, rationale을 응답하십시오."
        )

        preprocessor_ver = getattr(ImageProcessor, "PREPROCESSOR_VERSION", "v1")

        # 1. Check SHA-256 Composite Cache
        cached_data = self._cache.get_cached_result(
            image_hash=image_hash,
            prompt=prompt_text,
            model=self._model,
            preprocessor_version=preprocessor_ver,
        )
        if cached_data is not None:
            return self._normalize_result(
                raw_data=cached_data,
                expected_feature=expected_feature,
                expected_site=expected_site,
                claims=claims,
                is_cached=True,
            )

        # 2. Call VLM API (Cache Miss)
        payload = self._build_multimodal_payload(prompt_text, processed_bytes, mime_type)
        response = await self._call_api(payload)

        prompt_tokens = response.get("usage", {}).get("prompt_tokens", 0)
        completion_tokens = response.get("usage", {}).get("completion_tokens", 0)

        data: dict[str, Any] = {}
        choices = response.get("choices", [])
        if choices:
            msg_str = choices[0].get("message", {}).get("content", "{}")
            try:
                data = json.loads(strip_markdown_json(msg_str))
            except json.JSONDecodeError:
                data = {}

        result = self._normalize_result(
            raw_data=data,
            expected_feature=expected_feature,
            expected_site=expected_site,
            claims=claims,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            is_cached=False,
        )

        # 3. Store structured result in Cache for future reuse
        cache_data_to_store = {
            "status": result.status,
            "observations": result.observations,
            "supported_claims": result.supported_claims,
            "contradicted_claims": result.contradicted_claims,
            "unobservable_claims": result.unobservable_claims,
            "confidence": result.confidence,
            "rationale": result.rationale,
            "is_match": result.is_match,
            "label_detected": result.label_detected,
            "feature_number": result.feature_number,
            "site_point": result.site_point,
            "compass_north": result.compass_north,
            "match_confidence": result.match_confidence,
        }
        self._cache.store_result(
            image_hash=image_hash,
            prompt=prompt_text,
            result=cache_data_to_store,
            model=self._model,
            preprocessor_version=preprocessor_ver,
        )

        return result
