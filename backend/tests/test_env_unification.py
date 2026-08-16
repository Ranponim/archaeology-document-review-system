"""Task 11 env unification tests: OPENROUTER_API_KEY is the canonical OpenRouter
key; the legacy AI_API_KEY is honored only as an optional alias with a
deprecation warning.
"""
import pytest

from app.config import get_openrouter_api_key
from app.services.openrouter_client import OpenRouterConfig


def test_config_reads_openrouter_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter")
    monkeypatch.delenv("AI_API_KEY", raising=False)

    assert get_openrouter_api_key() == "sk-openrouter"


def test_config_legacy_ai_api_key_alias_warns(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("AI_API_KEY", "sk-legacy")

    with pytest.warns(DeprecationWarning):
        assert get_openrouter_api_key() == "sk-legacy"


def test_config_returns_empty_when_no_key_configured(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)

    assert get_openrouter_api_key() == ""


def test_openrouter_config_from_env_uses_unified_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-unified")
    monkeypatch.delenv("AI_API_KEY", raising=False)

    config = OpenRouterConfig.from_env()

    assert config.api_key == "sk-unified"


def test_openrouter_config_from_env_honors_legacy_alias(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("AI_API_KEY", "sk-legacy")

    with pytest.warns(DeprecationWarning):
        config = OpenRouterConfig.from_env()

    assert config.api_key == "sk-legacy"