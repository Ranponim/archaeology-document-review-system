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

@pytest.mark.anyio
async def test_ai_review_service_handles_markdown_wrapped_json():
    inner_json = json.dumps({
        "candidates": [
            {
                "category": "numeric_value",
                "original_text": "해발 45.2m",
                "proposed_text": "해발 45.5m",
                "change_type": "modified",
                "rationale": "도면 수치와 불일치"
            }
        ]
    })
    wrapped_content = """```json
""" + inner_json + """
```"""

    mock_llm_response = {
        "choices": [
            {
                "message": {
                    "content": wrapped_content
                }
            }
        ],
        "usage": {
            "prompt_tokens": 200,
            "completion_tokens": 50,
            "total_tokens": 250
        }
    }

    mock_client = MockOpenRouterClient(mock_llm_response)
    service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")

    page = ParsedPage(
        physical_page=10,
        printed_page=8,
        header="보고서 | 8",
        raw_text="표고 해발 45.2m...",
        normalized_text="표고 해발 45.2m...",
        text_blocks=[
            TextBlockData(block_id="p10_b1", text="표고 해발 45.2m...", normalized_text="표고 해발 45.2m...", order=1)
        ],
        captions=[]
    )

    result = await service.analyze_page(project_id="p1", version_stage="1차", page=page)

    assert isinstance(result, AIReviewResult)
    assert len(result.candidates) == 1
    cand = result.candidates[0]
    assert cand.rule_category == "numeric_value"
    assert cand.proposed_text == "해발 45.5m"
    assert cand.original_text == "해발 45.2m"


@pytest.mark.anyio
async def test_review_object_evidence_generates_grounded_candidates_with_evidence_links():
    from app.domain.canonical_models import ArchaeologyObjectData, ReferenceData
    from app.domain.review_models import EvidenceData

    obj = ArchaeologyObjectData(
        object_id="obj_cist_2",
        site="2지점",
        point="2지점",
        period="조선시대",
        type="토광묘",
        number="2호",
        canonical_name="2지점 2호 토광묘",
    )

    ev1 = EvidenceData(
        id="ev_dim_101",
        value="길이 210cm, 너비 85cm, 잔존깊이 32cm",
        rationale="본문 유구 설명 실측치",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        source_sha256="sha256_hash1",
        kind="text_claim",
        physical_page_from=105,
        printed_page_from=101,
    )
    ev2 = EvidenceData(
        id="ev_dim_102",
        value="길이 2.1m, 너비 0.95m, 잔존깊이 0.32m",
        rationale="도면 설명 실측치",
        document_version_id="ver_1",
        page_id="ver_1_p106",
        source_sha256="sha256_hash2",
        kind="text_claim",
        physical_page_from=106,
        printed_page_from=102,
    )

    mock_llm_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "candidates": [
                            {
                                "category": "numeric_value",
                                "original_text": "너비 85cm",
                                "proposed_text": "너비 95cm",
                                "change_type": "modified",
                                "rationale": "도면 실측치(너비 0.95m)와 본문(너비 85cm) 간 너비 수치 불일치",
                                "cited_evidence_ids": ["ev_dim_101", "ev_dim_102"],
                                "confidence": 0.92,
                            }
                        ]
                    })
                }
            }
        ],
        "usage": {
            "prompt_tokens": 400,
            "completion_tokens": 150,
            "total_tokens": 550,
        },
    }

    mock_client = MockOpenRouterClient(mock_llm_response)
    service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")

    candidates = await service.review_object_evidence(
        archaeology_object=obj,
        evidences=[ev1, ev2],
        project_id="p1",
        version_stage="1차",
    )

    assert len(candidates) == 1
    cand = candidates[0]
    assert isinstance(cand, CorrectionCandidateData)
    assert cand.rule_category == "numeric_value"
    assert cand.change_type == "modified"
    assert cand.status == "pending_review"
    assert cand.original_text == "너비 85cm"
    assert cand.proposed_text == "너비 95cm"
    assert cand.archaeology_object_id == "obj_cist_2"
    assert cand.confidence == 0.92
    assert cand.evidence is not None
    assert cand.evidence.id in ["ev_dim_101", "ev_dim_102"]
    assert len(cand.evidences) == 2
    assert {e.id for e in cand.evidences} == {"ev_dim_101", "ev_dim_102"}

    # Verify prompt context grounded in graph evidence
    assert mock_client.last_context is not None
    assert mock_client.last_context["archaeology_object"]["object_id"] == "obj_cist_2"
    assert len(mock_client.last_context["evidences"]) == 2
    assert mock_client.last_context["evidences"][0]["evidence_id"] == "ev_dim_101"


@pytest.mark.anyio
async def test_review_object_evidence_refusal_when_no_evidence_or_insufficient():
    from app.domain.canonical_models import ArchaeologyObjectData
    from app.domain.review_models import EvidenceData

    mock_client = MockOpenRouterClient({})
    service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")

    obj = ArchaeologyObjectData(
        object_id="obj_cist_3",
        site="1지점",
        canonical_name="1지점 3호 석관묘",
    )

    # 1. Empty evidence list -> Refusal safety: return empty list immediately without LLM call
    res_empty = await service.review_object_evidence(archaeology_object=obj, evidences=[])
    assert res_empty == []
    assert mock_client.last_prompt is None

    # 2. None evidence list -> Refusal safety
    res_none = await service.review_object_evidence(archaeology_object=obj, evidences=None)
    assert res_none == []
    assert mock_client.last_prompt is None

    # 3. None archaeology object -> Refusal safety
    res_no_obj = await service.review_object_evidence(archaeology_object=None, evidences=[])
    assert res_no_obj == []
    assert mock_client.last_prompt is None

    # 4. Insufficient empty-valued evidences -> Refusal safety
    empty_ev = EvidenceData(id="ev_empty", value="")
    res_blank = await service.review_object_evidence(archaeology_object=obj, evidences=[empty_ev])
    assert res_blank == []
    assert mock_client.last_prompt is None


@pytest.mark.anyio
async def test_review_object_evidence_filters_out_hallucinated_evidence_ids():
    from app.domain.canonical_models import ArchaeologyObjectData
    from app.domain.review_models import EvidenceData

    obj = ArchaeologyObjectData(
        object_id="obj_4",
        site="3지점",
        canonical_name="3지점 4호 주거지",
    )

    ev_real = EvidenceData(
        id="ev_real_1",
        value="평면형태는 장방형",
        document_version_id="ver_1",
        page_id="ver_1_p20",
        source_sha256="sha256_hash",
        kind="text_claim",
    )

    mock_llm_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "candidates": [
                            {
                                "category": "feature_or_artifact_id",
                                "original_text": "원삼국시대 주거지",
                                "proposed_text": "삼국시대 주거지",
                                "change_type": "modified",
                                "rationale": "근거 없는 추정 제안",
                                "cited_evidence_ids": ["ev_hallucinated_999"],  # Hallucinated ID not in evidences
                                "confidence": 0.8,
                            },
                            {
                                "category": "annotation_resolution",
                                "original_text": "장방형",
                                "proposed_text": "말각장방형",
                                "change_type": "modified",
                                "rationale": "실측 도면과 일치",
                                "cited_evidence_ids": ["ev_real_1"],
                                "confidence": 0.9,
                            }
                        ]
                    })
                }
            }
        ]
    }

    mock_client = MockOpenRouterClient(mock_llm_response)
    service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")

    candidates = await service.review_object_evidence(
        archaeology_object=obj,
        evidences=[ev_real],
    )

    # Hallucinated candidate without real evidence backing is rejected
    assert len(candidates) == 1
    assert candidates[0].proposed_text == "말각장방형"
    assert candidates[0].evidence is not None
    assert candidates[0].evidence.id == "ev_real_1"


@pytest.mark.anyio
async def test_review_object_evidence_strictly_enforces_pending_review_status():
    from app.domain.canonical_models import ArchaeologyObjectData
    from app.domain.review_models import EvidenceData

    obj = ArchaeologyObjectData(
        object_id="obj_5",
        site="1지점",
        canonical_name="1지점 5호 토광묘",
    )
    ev = EvidenceData(
        id="ev_5",
        value="해발 63.4m",
        document_version_id="ver_1",
        page_id="ver_1_p50",
        source_sha256="sha256_hash",
        kind="text_claim",
    )

    # LLM returns status='confirmed' or other non-pending status
    mock_llm_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "candidates": [
                            {
                                "category": "numeric_value",
                                "original_text": "해발 63.4m",
                                "proposed_text": "해발 63.8m",
                                "status": "confirmed",  # Should be overridden to pending_review
                                "change_type": "modified",
                                "rationale": "등고선 고도 불일치",
                                "cited_evidence_ids": ["ev_5"],
                            }
                        ]
                    })
                }
            }
        ]
    }

    mock_client = MockOpenRouterClient(mock_llm_response)
    service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")

    candidates = await service.review_object_evidence(
        archaeology_object=obj,
        evidences=[ev],
    )

    assert len(candidates) == 1
    assert candidates[0].status == "pending_review"


@pytest.mark.anyio
async def test_review_object_evidence_with_references_drawings_and_plates():
    from app.domain.canonical_models import (
        ArchaeologyObjectData,
        ReferenceData,
        PlateData,
        DrawingData,
    )
    from app.domain.review_models import EvidenceData

    obj = ArchaeologyObjectData(
        object_id="obj_cist_7",
        site="2지점",
        canonical_name="2지점 7호 석관묘",
    )
    ev = EvidenceData(
        id="ev_7",
        value="도면 12, 도판 34 참조",
        document_version_id="ver_1",
        page_id="ver_1_p70",
        source_sha256="sha256_hash",
        kind="text_claim",
    )
    ref = ReferenceData(ref_type="plate", number="34", raw_text="도판 34", physical_page=70)
    plate = PlateData(plate_id="plate_34", number="34", physical_page=120, title="2지점 7호 석관묘 전경")
    drawing = DrawingData(drawing_id="dwg_12", number="12", physical_page=80, title="2지점 7호 석관묘 평·단면도")

    mock_llm_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "candidates": []
                    })
                }
            }
        ]
    }

    mock_client = MockOpenRouterClient(mock_llm_response)
    service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")

    candidates = await service.review_object_evidence(
        archaeology_object=obj,
        evidences=[ev],
        references=[ref],
        plates=[plate],
        drawings=[drawing],
    )

    assert candidates == []
    context = mock_client.last_context
    assert context is not None
    assert len(context["references"]) == 1
    assert context["references"][0]["ref_type"] == "plate"
    assert context["references"][0]["number"] == "34"
    assert len(context["plates"]) == 1
    assert context["plates"][0]["plate_id"] == "plate_34"
    assert len(context["drawings"]) == 1
    assert context["drawings"][0]["drawing_id"] == "dwg_12"


@pytest.mark.anyio
async def test_review_object_evidence_handles_markdown_wrapped_and_malformed_json():
    from app.domain.canonical_models import ArchaeologyObjectData
    from app.domain.review_models import EvidenceData

    obj = ArchaeologyObjectData(
        object_id="obj_8",
        site="1지점",
        canonical_name="1지점 8호 수혈",
    )
    ev = EvidenceData(
        id="ev_8",
        value="동서 340cm, 남북 210cm",
        document_version_id="ver_1",
        page_id="ver_1_p90",
        source_sha256="sha256_hash",
        kind="text_claim",
    )

    # 1. Markdown-wrapped JSON
    wrapped_json = """```json
    {
      "candidates": [
        {
          "category": "unknown_invalid_category",
          "change_type": "unknown_change_type",
          "original_text": "동서 340cm",
          "proposed_text": "남북 340cm",
          "rationale": "방향 기술 전도 오류",
          "cited_evidence_ids": ["ev_8"],
          "confidence": 1.5
        }
      ]
    }
    ```"""
    mock_client = MockOpenRouterClient({
        "choices": [{"message": {"content": wrapped_json}}]
    })
    service = AIReviewService(client=mock_client, model="openai/gpt-5.6-luna")

    candidates = await service.review_object_evidence(
        archaeology_object=obj,
        evidences=[ev],
    )

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.rule_category == "annotation_resolution"  # normalized from invalid
    assert cand.change_type == "modified"  # normalized from invalid
    assert cand.status == "pending_review"
    assert cand.confidence == 1.0  # clamped from 1.5
    assert cand.evidence is not None
    assert cand.evidence.id == "ev_8"

    # 2. Corrupt / non-JSON content
    corrupt_client = MockOpenRouterClient({
        "choices": [{"message": {"content": "This is plain text and not json."}}]
    })
    service_corrupt = AIReviewService(client=corrupt_client, model="openai/gpt-5.6-luna")
    candidates_corrupt = await service_corrupt.review_object_evidence(
        archaeology_object=obj,
        evidences=[ev],
    )
    assert candidates_corrupt == []


