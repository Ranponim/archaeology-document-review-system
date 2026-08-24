import pytest

from app.config import get_drawing_evidence_resolver_version


def test_drawing_evidence_resolver_defaults_to_v1(monkeypatch):
    monkeypatch.delenv("DRAWING_EVIDENCE_RESOLVER_VERSION", raising=False)
    assert get_drawing_evidence_resolver_version() == "v1"


def test_drawing_evidence_resolver_can_explicitly_select_v2(monkeypatch):
    monkeypatch.setenv("DRAWING_EVIDENCE_RESOLVER_VERSION", "v2")
    assert get_drawing_evidence_resolver_version() == "v2"


def test_unknown_drawing_evidence_resolver_version_fails_closed(monkeypatch):
    monkeypatch.setenv("DRAWING_EVIDENCE_RESOLVER_VERSION", "latest")
    with pytest.raises(ValueError, match="DRAWING_EVIDENCE_RESOLVER_VERSION"):
        get_drawing_evidence_resolver_version()
