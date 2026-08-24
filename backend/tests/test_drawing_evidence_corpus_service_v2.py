from pathlib import Path

from app.services.drawing_evidence_corpus_service import EvidenceGraphReferenceCorpusService
from app.services.drawing_evidence_graph_resolver_v2 import DrawingEvidenceGraphResolverV2


def test_service_selects_v2_only_when_explicitly_requested():
    service = object.__new__(EvidenceGraphReferenceCorpusService)
    resolver = service._build_drawing_evidence_resolver("v2")
    assert isinstance(resolver, DrawingEvidenceGraphResolverV2)
    assert resolver.resolver_version == "drawing-evidence-v2"


def test_service_default_resolver_remains_v1_until_local_acceptance():
    service = object.__new__(EvidenceGraphReferenceCorpusService)
    resolver = service._build_drawing_evidence_resolver("v1")
    assert resolver.resolver_version == "drawing-evidence-v1"


def test_v2_context_mode_is_selected_from_resolver_version():
    service = object.__new__(EvidenceGraphReferenceCorpusService)
    service._drawing_evidence_resolver = service._build_drawing_evidence_resolver("v2")
    assert service._body_context_mode() == "v2"


def test_unknown_resolver_version_is_rejected():
    service = object.__new__(EvidenceGraphReferenceCorpusService)
    try:
        service._build_drawing_evidence_resolver("v3")
    except ValueError as error:
        assert "resolver version" in str(error).lower()
    else:
        raise AssertionError("unknown resolver version must fail closed")
