import os
import pytest
from app.services.openrouter_client import OpenRouterClient, OpenRouterConfig


def test_openrouter_config_reads_env_and_defaults(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-testkey123")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/responses")
    
    config = OpenRouterConfig.from_env()
    assert config.api_key == "sk-or-v1-testkey123"
    assert config.base_url == "https://openrouter.ai/api/v1/responses"
    assert config.model != ""


def test_openrouter_config_mask_secret(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-testkey123")
    config = OpenRouterConfig.from_env()
    rep = repr(config)
    assert "sk-or-v1-testkey123" not in rep
    assert "***" in rep


@pytest.mark.anyio
async def test_openrouter_client_builds_payload_correctly():
    config = OpenRouterConfig(
        api_key="sk-or-test",
        base_url="https://openrouter.ai/api/v1/responses",
        model="google/gemini-2.0-flash-001"
    )
    client = OpenRouterClient(config)
    
    prompt = "다음 고고학 보고서 문단의 오탈자 및 문맥 오류를 검토하시오."
    context = {"feature_id": "2호 토광묘", "original_text": "풍화암반토(생토) 포함여부"}
    
    payload = client._build_payload(prompt, context)
    assert payload["model"] == "google/gemini-2.0-flash-001"
    assert len(payload["messages"]) >= 2
    assert "2호 토광묘" in payload["messages"][-1]["content"]
