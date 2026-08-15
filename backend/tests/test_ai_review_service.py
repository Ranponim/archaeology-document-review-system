import json
import pytest
from app.services.openrouter_client import OpenRouterConfig
from app.services.ai_review_service import AIReviewService, AIReviewResult
from app.domain.document_structure import ParsedPage, TextBlockData, CaptionData
from app.domain.review_models import CorrectionCandidateData


class MockOpenRouterClient:
    def __init__(self, mock_response: dict):
        self.mock_response = mock_response
        self.last_prompt = None
        self.last_context = None

    async def analyze_text_discrepancy(self, prompt: str, context: dict) -> dict:
        self.last_prompt = prompt
        self.last_context = context
        return self.mock_response


@pytest.mark.anyio
async def test_ai_review_service_generates_candidates_from_llm_response():
    mock_llm_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "candidates": [
                            {
                                "category": "annotation_resolution",
                                "original_text": "풍화암반토(생토) 포함여부",
                                "proposed_text": "풍화암반토(생토) 포함 여부",
                                "change_type": "modified",
                                "rationale": "'포함여부'는 표준 맞춤법상 '포함 여부'로 띄어 쓰는 것이 적절합니다."
                            },
                            {
                                "category": "figure_plate_table_photo_ref",
                                "original_text": "① 유구(도면 : , 도판 : )",
                                "proposed_text": "① 유구(도면 : 57, 도판 : 85)",
                                "change_type": "modified",
                                "rationale": "2지점 2호 토광묘 도면 및 도판 번호 보완"
                            }
                        ]
                    })
                }
            }
        ],
        "usage": {
            "prompt_tokens": 350,
            "completion_tokens": 120,
            "total_tokens": 470
        }
    }
    
    mock_client = MockOpenRouterClient(mock_llm_response)
    service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")
    
    page = ParsedPage(
        physical_page=105,
        printed_page=101,
        header="백제문화유산연구원 | 101",
        raw_text="2호 토광묘...",
        normalized_text="2호 토광묘...",
        text_blocks=[
            TextBlockData(block_id="p105_b1", text="풍화암반토(생토) 포함여부", normalized_text="풍화암반토(생토) 포함여부", order=1)
        ],
        captions=[
            CaptionData(caption_id="p105_c1", raw_text="① 유구(도면 : , 도판 : )", is_blank_reference=True)
        ]
    )
    
    result = await service.analyze_page(project_id="p1", version_stage="1차", page=page)
    
    assert isinstance(result, AIReviewResult)
    assert len(result.candidates) == 2
    assert result.model == "openai/gpt-5.6-luna"
    assert result.prompt_tokens == 350
    assert result.completion_tokens == 120
    
    cand1 = result.candidates[0]
    assert isinstance(cand1, CorrectionCandidateData)
    assert cand1.rule_category == "annotation_resolution"
    assert cand1.proposed_text == "풍화암반토(생토) 포함 여부"
    assert cand1.evidence.version_from == "1차"
    assert cand1.evidence.physical_page_from == 105
