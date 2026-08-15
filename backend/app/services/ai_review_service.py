from dataclasses import dataclass, field
import json
import os
from typing import Any
from app.domain.document_structure import ParsedPage
from app.domain.review_models import (
    CorrectionCandidateData,
    EvidenceData,
    RuleCategory,
    ChangeType,
    ReviewStatus,
)
from app.services.openrouter_client import OpenRouterClient, OpenRouterConfig


@dataclass(frozen=True, slots=True)
class AIReviewResult:
    candidates: list[CorrectionCandidateData]
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AIReviewService:
    DEFAULT_MODEL = "openai/gpt-5.6-luna"

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or os.environ.get("OPENROUTER_MODEL", self.DEFAULT_MODEL)
        config = OpenRouterConfig.from_env()
        # Ensure config uses model
        object.__setattr__(config, "model", self._model)
        self._client = client or OpenRouterClient(config)

    async def analyze_page(
        self,
        project_id: str,
        version_stage: str,
        page: ParsedPage,
    ) -> AIReviewResult:
        prompt = (
            "고고학 발굴보고서의 본문 단락과 캡션을 검토하여 다음 오류를 찾아내고 "
            "JSON 형식으로 교정 후보를 출력하십시오:\n"
            "1. 고고학 전문용어 표기 및 맞춤법/띄어쓰기 오류 (annotation_resolution)\n"
            "2. 도면/도판 번호 누락 및 불일치 (figure_plate_table_photo_ref)\n"
            "3. 유구/유물 식별자 번호 및 명칭 모순 (feature_or_artifact_id)\n"
            "4. 수치/치수/고도 모순 (numeric_value)\n\n"
            "반드시 JSON 형식 `{\"candidates\": [{\"category\": \"...\", \"original_text\": \"...\", \"proposed_text\": \"...\", \"change_type\": \"...\", \"rationale\": \"...\"}]}` 으로만 응답하십시오."
        )

        context = {
            "physical_page": page.physical_page,
            "printed_page": page.printed_page,
            "header": page.header,
            "text_blocks": [b.text for b in page.text_blocks],
            "captions": [c.raw_text for c in page.captions],
        }

        response = await self._client.analyze_text_discrepancy(prompt, context)

        candidates: list[CorrectionCandidateData] = []
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        usage = response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        choices = response.get("choices", [])
        if choices:
            msg_content = choices[0].get("message", {}).get("content", "{}")
            try:
                data = json.loads(msg_content)
                raw_cands = data.get("candidates", [])
                for idx, c in enumerate(raw_cands):
                    cat = c.get("category", "annotation_resolution")
                    if cat not in [
                        "figure_plate_table_photo_ref",
                        "annotation_resolution",
                        "feature_or_artifact_id",
                        "numeric_value",
                        "site_or_area_name",
                        "direction_period_term",
                    ]:
                        cat = "annotation_resolution"

                    ch_type = c.get("change_type", "modified")
                    if ch_type not in ["added", "deleted", "modified", "moved"]:
                        ch_type = "modified"

                    status: ReviewStatus = "pending_review"

                    evidence = EvidenceData(
                        version_from=version_stage,
                        version_to=version_stage,
                        physical_page_from=page.physical_page,
                        physical_page_to=page.physical_page,
                        printed_page_from=page.printed_page,
                        printed_page_to=page.printed_page,
                        rule_name=f"ai_{self._model}",
                        rationale=c.get("rationale", "AI review candidate proposal"),
                    )

                    cand = CorrectionCandidateData(
                        candidate_id=f"cand_ai_p{page.physical_page}_{idx+1}",
                        rule_category=cat,
                        change_type=ch_type,
                        status=status,
                        original_text=c.get("original_text"),
                        proposed_text=c.get("proposed_text"),
                        evidence=evidence,
                    )
                    candidates.append(cand)
            except json.JSONDecodeError:
                pass

        return AIReviewResult(
            candidates=candidates,
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
