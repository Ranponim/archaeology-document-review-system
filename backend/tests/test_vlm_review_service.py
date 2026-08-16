import json
import sys
import pytest
from app.services.image_processor import ImageProcessor
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


def test_image_processor_prepare_for_vlm_returns_bytes():
    raw_data = b"MOCK_IMAGE_DATA_12345"
    result = ImageProcessor.prepare_for_vlm(raw_data)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_image_processor_prepare_for_vlm_empty():
    assert ImageProcessor.prepare_for_vlm(b"") == b""


def test_image_processor_prepare_for_vlm_without_pillow(monkeypatch):
    # Simulate Pillow not installed
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)

    raw_data = b"FALLBACK_IMAGE_DATA_NO_PIL"
    result = ImageProcessor.prepare_for_vlm(raw_data)
    assert isinstance(result, bytes)
    assert result == raw_data


def test_image_processor_prepare_for_vlm_with_pillow_if_available():
    try:
        import io
        from PIL import Image

        # Create a sample large RGBA image in memory
        img = Image.new("RGBA", (1200, 800), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Process image
        processed = ImageProcessor.prepare_for_vlm(png_bytes, max_dimension=768, quality=75)
        assert isinstance(processed, bytes)

        # Verify resized output
        with Image.open(io.BytesIO(processed)) as res_img:
            assert res_img.format == "JPEG"
            assert res_img.mode == "RGB"
            assert max(res_img.size) <= 768
            assert res_img.size[0] == 768
            assert res_img.size[1] == 512
    except ImportError:
        pytest.skip("Pillow is not installed in the test environment")


@pytest.mark.anyio
async def test_vlm_review_service_default_expected_site_empty_string(tmp_path):
    import inspect
    sig = inspect.signature(VLMReviewService.verify_plate_photo)
    assert sig.parameters['expected_site'].default == ''

    cache = AssetHashCache(cache_dir=tmp_path)
    mock_response = {
        'choices': [
            {
                'message': {
                    'content': json.dumps({
                        'label_detected': '논산 산노리 2지점 2호 토광묘',
                        'feature_number': '2',
                        'site_point': '2지점',
                        'compass_north': 'N-74-E',
                        'match_confidence': 0.98,
                        'rationale': 'Feature matched'
                    })
                }
            }
        ],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 50}
    }
    mock_client = MockOpenRouterMultimodalClient(mock_response)
    service = VLMReviewService(client=mock_client, cache=cache)
    
    # Call without specifying expected_site (default empty string)
    res = await service.verify_plate_photo(
        image_bytes=b'SAMPLE_IMAGE',
        expected_feature='2호 토광묘'
    )
    assert res.is_match is True
    assert res.feature_number == '2'

@pytest.mark.anyio
async def test_vlm_review_service_handles_markdown_wrapped_json(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path)
    inner_json = json.dumps({
        "label_detected": "논산 산노리 2지점 2호 토광묘",
        "feature_number": "2",
        "site_point": "2지점",
        "compass_north": "N-74-E",
        "match_confidence": 0.98,
        "rationale": "표찰 텍스트 및 방위표가 본문 서술과 일치함"
    })
    wrapped_content = """```json
""" + inner_json + """
```"""

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": wrapped_content
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

    res = await service.verify_plate_photo(
        image_bytes=b"RAW_IMAGE_DATA_SAMPLE_PLATE_85_MD",
        expected_feature="2호 토광묘",
        expected_site="2지점"
    )
    assert isinstance(res, VLMReviewResult)
    assert res.feature_number == "2"
    assert res.site_point == "2지점"
    assert res.is_match is True


@pytest.mark.anyio
async def test_vlm_review_service_structured_observation_output(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path)
    mock_payload = {
        "status": "SUPPORTED",
        "observations": {
            "site_label": "논산 산노리 2지점 2호 토광묘",
            "feature_number": "2",
            "object_type": "토광묘",
            "investigation_stage": "완굴",
            "soil_layer": "풍화암반층",
            "orientation": "N-74-E",
            "scale": "1:20"
        },
        "supported_claims": ["2지점 2호 토광묘 사진", "완굴 상태"],
        "contradicted_claims": [],
        "unobservable_claims": [],
        "confidence": 0.96,
        "rationale": "표찰 및 유구 구조 일치"
    }
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(mock_payload)
                }
            }
        ],
        "usage": {
            "prompt_tokens": 500,
            "completion_tokens": 100
        }
    }
    mock_client = MockOpenRouterMultimodalClient(mock_response)
    service = VLMReviewService(client=mock_client, cache=cache, model="openai/gpt-5.6-luna")

    res = await service.verify_plate_photo(
        image_bytes=b"SAMPLE_IMAGE_STRUCTURED",
        expected_feature="2호 토광묘",
        expected_site="2지점",
        claims=["2지점 2호 토광묘 사진", "완굴 상태"]
    )

    assert isinstance(res, VLMReviewResult)
    assert res.status == "SUPPORTED"
    assert res.is_match is True
    assert res.observations["site_label"] == "논산 산노리 2지점 2호 토광묘"
    assert res.observations["feature_number"] == "2"
    assert res.observations["object_type"] == "토광묘"
    assert res.observations["investigation_stage"] == "완굴"
    assert res.observations["soil_layer"] == "풍화암반층"
    assert res.observations["orientation"] == "N-74-E"
    assert res.observations["scale"] == "1:20"
    assert res.supported_claims == ["2지점 2호 토광묘 사진", "완굴 상태"]
    assert res.contradicted_claims == []
    assert res.unobservable_claims == []
    assert res.confidence == 0.96
    assert res.rationale == "표찰 및 유구 구조 일치"
    assert res.prompt_tokens == 500
    assert res.completion_tokens == 100
    assert res.cost_usd > 0
    assert res.cost_krw > 0
    assert res.is_cached is False


@pytest.mark.anyio
async def test_vlm_review_service_site_same_feature_different_negative_safety(tmp_path):
    """Safety test: If expected feature is 2호 but photo shows 25호 (same 2지점),

    status must be CONTRADICTED or PARTIAL, NEVER SUPPORTED.
    """
    cache = AssetHashCache(cache_dir=tmp_path)
    mock_payload = {
        "status": "SUPPORTED",  # VLM might hallucinate match based on site label
        "observations": {
            "site_label": "논산 산노리 2지점 25호 토광묘",
            "feature_number": "25",
            "object_type": "토광묘",
            "investigation_stage": "완굴",
            "soil_layer": "풍화암반층",
            "orientation": "N-10-W",
            "scale": "1:20"
        },
        "supported_claims": ["2지점 사진"],
        "contradicted_claims": ["유구 번호 불일치 (기대: 2호 vs 관측: 25호)"],
        "unobservable_claims": [],
        "confidence": 0.90,
        "rationale": "2지점은 일치하나 2호가 아닌 25호 토광묘 표찰이 확인됨"
    }
    mock_response = {
        "choices": [{"message": {"content": json.dumps(mock_payload)}}],
        "usage": {"prompt_tokens": 450, "completion_tokens": 90}
    }
    mock_client = MockOpenRouterMultimodalClient(mock_response)
    service = VLMReviewService(client=mock_client, cache=cache)

    res = await service.verify_plate_photo(
        image_bytes=b"SAMPLE_IMAGE_DIFFERENT_FEATURE",
        expected_feature="2호 토광묘",
        expected_site="2지점"
    )

    assert res.status in ("CONTRADICTED", "PARTIAL")
    assert res.status != "SUPPORTED"
    assert res.is_match is False
    assert res.observations["feature_number"] == "25"


@pytest.mark.anyio
async def test_vlm_review_service_unobservable_claim_tracking(tmp_path):
    """When a claim cannot be verified from a single photo (e.g. backside retouch),

    it must be tracked in unobservable_claims and status downgraded to PARTIAL or INSUFFICIENT_EVIDENCE.
    """
    cache = AssetHashCache(cache_dir=tmp_path)
    mock_payload = {
        "status": "SUPPORTED",  # If model initially returned supported
        "observations": {
            "site_label": "논산 산노리 2지점 2호 토광묘",
            "feature_number": "2",
            "object_type": "토광묘",
            "investigation_stage": "완굴",
            "soil_layer": "풍화암반층",
            "orientation": "N-74-E",
            "scale": "1:20"
        },
        "supported_claims": ["2지점 2호 토광묘 전경"],
        "contradicted_claims": [],
        "unobservable_claims": ["유물 배면 잔손질 여부 (정면 단일 사진으로 확인 불가)"],
        "confidence": 0.75,
        "rationale": "전경은 확인되나 배면 잔손질은 관측 불가"
    }
    mock_response = {
        "choices": [{"message": {"content": json.dumps(mock_payload)}}],
        "usage": {"prompt_tokens": 400, "completion_tokens": 80}
    }
    mock_client = MockOpenRouterMultimodalClient(mock_response)
    service = VLMReviewService(client=mock_client, cache=cache)

    res = await service.verify_plate_photo(
        image_bytes=b"SAMPLE_IMAGE_FRONT_ONLY",
        expected_feature="2호 토광묘",
        expected_site="2지점",
        claims=["2지점 2호 토광묘 전경", "유물 배면 잔손질 여부"]
    )

    # Status must be downgraded to PARTIAL due to unobservable claim
    assert res.status in ("PARTIAL", "INSUFFICIENT_EVIDENCE")
    assert len(res.unobservable_claims) > 0
    assert "배면 잔손질" in res.unobservable_claims[0]


@pytest.mark.anyio
async def test_vlm_review_service_composite_cache_keys(tmp_path):
    """Cache key must incorporate image_hash + model + prompt_hash + preprocessor_version."""
    cache = AssetHashCache(cache_dir=tmp_path)
    mock_payload_1 = {
        "status": "SUPPORTED",
        "observations": {"feature_number": "2"},
        "supported_claims": ["2호 토광묘"],
        "contradicted_claims": [],
        "unobservable_claims": [],
        "confidence": 0.95,
        "rationale": "Model 1 analysis"
    }
    mock_payload_2 = {
        "status": "SUPPORTED",
        "observations": {"feature_number": "2"},
        "supported_claims": ["2호 토광묘"],
        "contradicted_claims": [],
        "unobservable_claims": [],
        "confidence": 0.99,
        "rationale": "Model 2 analysis"
    }

    mock_client_1 = MockOpenRouterMultimodalClient({
        "choices": [{"message": {"content": json.dumps(mock_payload_1)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50}
    })
    mock_client_2 = MockOpenRouterMultimodalClient({
        "choices": [{"message": {"content": json.dumps(mock_payload_2)}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 60}
    })

    service_model_a = VLMReviewService(client=mock_client_1, cache=cache, model="openai/gpt-5.6-luna")
    service_model_b = VLMReviewService(client=mock_client_2, cache=cache, model="anthropic/claude-3.7-sonnet")

    sample_image = b"RAW_IMAGE_IDENTICAL_BYTES"

    # Call with Model A
    res_a1 = await service_model_a.verify_plate_photo(sample_image, expected_feature="2호 토광묘")
    assert res_a1.is_cached is False
    assert res_a1.rationale == "Model 1 analysis"
    assert mock_client_1.call_count == 1

    # Call with Model A again -> CACHED
    res_a2 = await service_model_a.verify_plate_photo(sample_image, expected_feature="2호 토광묘")
    assert res_a2.is_cached is True
    assert mock_client_1.call_count == 1

    # Call with Model B -> Cache MISS because model changed in composite key!
    res_b1 = await service_model_b.verify_plate_photo(sample_image, expected_feature="2호 토광묘")
    assert res_b1.is_cached is False
    assert res_b1.rationale == "Model 2 analysis"
    assert mock_client_2.call_count == 1


@pytest.mark.anyio
async def test_vlm_review_service_insufficient_evidence_when_all_unobservable(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path)
    mock_payload = {
        "status": "SUPPORTED",
        "observations": {},
        "supported_claims": [],
        "contradicted_claims": [],
        "unobservable_claims": ["토층 심도 1.5m 여부 (스케일바 부재)", "내부 토색 10YR 3/2 여부"],
        "confidence": 0.2,
        "rationale": "사진만으로는 토색 및 깊이 확인 불가"
    }
    mock_client = MockOpenRouterMultimodalClient({
        "choices": [{"message": {"content": json.dumps(mock_payload)}}],
        "usage": {"prompt_tokens": 300, "completion_tokens": 50}
    })
    service = VLMReviewService(client=mock_client, cache=cache)

    res = await service.verify_plate_photo(
        image_bytes=b"BLURRY_IMAGE",
        expected_feature="1호 수혈유구",
        claims=["토층 심도 1.5m 여부", "내부 토색 10YR 3/2 여부"]
    )
    assert res.status == "INSUFFICIENT_EVIDENCE"
    assert res.is_match is False
    assert len(res.unobservable_claims) == 2


@pytest.mark.anyio
async def test_vlm_review_service_cost_calculation_math(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path)
    mock_payload = {
        "status": "SUPPORTED",
        "observations": {"feature_number": "1"},
        "supported_claims": ["1호 주거지"],
        "contradicted_claims": [],
        "unobservable_claims": [],
        "confidence": 0.95,
        "rationale": "일치"
    }
    mock_client = MockOpenRouterMultimodalClient({
        "choices": [{"message": {"content": json.dumps(mock_payload)}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500}
    })
    service = VLMReviewService(client=mock_client, cache=cache)

    res = await service.verify_plate_photo(
        image_bytes=b"COST_TEST_IMAGE",
        expected_feature="1호 주거지"
    )
    # 1000 prompt tokens * $2.50/1M = 0.0025 USD
    # 500 completion tokens * $10.00/1M = 0.0050 USD
    # Total = 0.0075 USD
    assert pytest.approx(res.cost_usd, rel=1e-5) == 0.0075
    # Total KRW = 0.0075 * 1400 = 10.5 KRW
    assert pytest.approx(res.cost_krw, rel=1e-5) == 10.5


@pytest.mark.anyio
async def test_vlm_review_service_corrupt_json_fallback(tmp_path):
    cache = AssetHashCache(cache_dir=tmp_path)
    mock_client = MockOpenRouterMultimodalClient({
        "choices": [{"message": {"content": "INVALID_NON_JSON_CONTENT"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20}
    })
    service = VLMReviewService(client=mock_client, cache=cache)

    res = await service.verify_plate_photo(
        image_bytes=b"CORRUPT_JSON_IMAGE",
        expected_feature="1호 주거지"
    )
    assert res.status == "INSUFFICIENT_EVIDENCE"
    assert res.is_match is False


