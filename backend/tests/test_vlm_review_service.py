import json
import pytest
from app.services.vlm_review_service import VLMReviewService, VLMReviewResult
from app.services.asset_cache import AssetHashCache


class MockOpenRouterMultimodalClient:
    def __init__(self, mock_response: dict):
        self.mock_response = mock_response
        self.call_count = 0

    async def analyze_multimodal(self, prompt: str, image_bytes: bytes, mime_type: str) -> dict:
        self.call_count += 1
        return self.mock_response


@pytest.mark.anyio
async def test_vlm_review_service_with_caching(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path)
    
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "label_detected": "논산 산노리 2지점 2호 토광묘",
                        "feature_number": "2",
                        "site_point": "2지점",
                        "compass_north": "N-74-E",
                        "match_confidence": 0.98,
                        "rationale": "표찰 텍스트 및 방위표가 본문 서술과 일치함"
                    })
                }
            }
        ],
        "usage": {
            "prompt_tokens": 400,
            "completion_tokens": 80,
            "total_tokens": 480
        }
    }
    
    mock_client = MockOpenRouterMultimodalClient(mock_response)
    service = VLMReviewService(client=mock_client, cache=cache, model="openai/gpt-5.6-luna")
    
    sample_image = b"RAW_IMAGE_DATA_SAMPLE_PLATE_85"
    
    # First call: Cache miss -> API called
    res1 = await service.verify_plate_photo(
        image_bytes=sample_image,
        expected_feature="2호 토광묘",
        expected_site="2지점"
    )
    assert isinstance(res1, VLMReviewResult)
    assert res1.is_cached is False
    assert res1.feature_number == "2"
    assert res1.is_match is True
    assert mock_client.call_count == 1
    
    # Second call: Cache HIT! -> ZERO API calls
    res2 = await service.verify_plate_photo(
        image_bytes=sample_image,
        expected_feature="2호 토광묘",
        expected_site="2지점"
    )
    assert isinstance(res2, VLMReviewResult)
    assert res2.is_cached is True
    assert res2.feature_number == "2"
    assert mock_client.call_count == 1  # Still 1! 0 API cost!
