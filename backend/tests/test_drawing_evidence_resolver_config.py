import pytest

from app.config import (
    CodexDrawingResolverConfig,
    get_drawing_evidence_resolver_version,
    get_drawing_evidence_v3_auto_promote,
)


def test_drawing_evidence_resolver_defaults_to_v1(monkeypatch):
    monkeypatch.delenv("DRAWING_EVIDENCE_RESOLVER_VERSION", raising=False)
    assert get_drawing_evidence_resolver_version() == "v1"


def test_drawing_evidence_resolver_can_explicitly_select_v2(monkeypatch):
    monkeypatch.setenv("DRAWING_EVIDENCE_RESOLVER_VERSION", "v2")
    assert get_drawing_evidence_resolver_version() == "v2"


@pytest.mark.parametrize("value", ["v3", "drawing-evidence-v3"])
def test_drawing_evidence_resolver_can_explicitly_select_v3(monkeypatch, value):
    monkeypatch.setenv("DRAWING_EVIDENCE_RESOLVER_VERSION", value)
    assert get_drawing_evidence_resolver_version() == "v3"


def test_v3_auto_promote_defaults_false(monkeypatch):
    monkeypatch.delenv("DRAWING_EVIDENCE_V3_AUTO_PROMOTE", raising=False)
    assert get_drawing_evidence_v3_auto_promote() is False


def test_v3_auto_promote_requires_explicit_true(monkeypatch):
    monkeypatch.setenv("DRAWING_EVIDENCE_V3_AUTO_PROMOTE", "true")
    assert get_drawing_evidence_v3_auto_promote() is True


def test_unknown_drawing_evidence_resolver_version_fails_closed(monkeypatch):
    monkeypatch.setenv("DRAWING_EVIDENCE_RESOLVER_VERSION", "latest")
    with pytest.raises(ValueError, match="DRAWING_EVIDENCE_RESOLVER_VERSION"):
        get_drawing_evidence_resolver_version()


def test_codex_drawing_resolver_config_loads_explicit_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "key-123")
    monkeypatch.setenv("DRAWING_CODEX_MODEL", "gpt-5.3-codex")
    monkeypatch.setenv("DRAWING_CODEX_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("DRAWING_CODEX_AUTO_CONFIDENCE", "0.97")
    monkeypatch.setenv("DRAWING_CODEX_MAX_CANDIDATES", "12")
    monkeypatch.setenv("DRAWING_CODEX_MAX_EXPANSIONS", "1")

    config = CodexDrawingResolverConfig.from_env()

    assert config.api_key == "key-123"
    assert config.model == "gpt-5.3-codex"
    assert config.timeout_seconds == 45.0
    assert config.auto_confidence == 0.97
    assert config.max_candidates == 12
    assert config.max_expansions == 1


def test_codex_drawing_resolver_config_allows_sdk_auth_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = CodexDrawingResolverConfig.from_env()

    assert config.api_key == ""
    assert config.model == "gpt-5.3-codex"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DRAWING_CODEX_TIMEOUT_SECONDS", "0"),
        ("DRAWING_CODEX_AUTO_CONFIDENCE", "1.5"),
        ("DRAWING_CODEX_MAX_CANDIDATES", "0"),
        ("DRAWING_CODEX_MAX_EXPANSIONS", "-1"),
    ],
)
def test_codex_drawing_resolver_config_rejects_unsafe_values(monkeypatch, name, value):
    monkeypatch.setenv("OPENAI_API_KEY", "key-123")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        CodexDrawingResolverConfig.from_env()
