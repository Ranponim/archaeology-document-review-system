from app.domain.reference_corpus import ReferenceCorpusFailureCode, ReferenceCorpusStatus, compute_build_identity


def test_ready_is_terminal_immutable_state():
    assert ReferenceCorpusStatus.READY.is_terminal is True
    assert ReferenceCorpusStatus.STAGING.is_terminal is False


def test_build_identity_changes_when_canonicalizer_changes():
    first = compute_build_identity("sources", "adobe-1", "manifest-1", "canon-1")
    second = compute_build_identity("sources", "adobe-1", "manifest-1", "canon-2")
    assert first != second


def test_reference_corpus_failure_codes_cover_fail_closed_identity_errors():
    assert ReferenceCorpusFailureCode.LINK_MISSING.value == "LINK_MISSING"
    assert ReferenceCorpusFailureCode.AMBIGUOUS_IDENTIFIER.value == "AMBIGUOUS_IDENTIFIER"
    assert ReferenceCorpusFailureCode.DUPLICATE_CANONICAL_IDENTIFIER.value == "DUPLICATE_CANONICAL_IDENTIFIER"
    assert ReferenceCorpusFailureCode.PROVENANCE_INCOMPLETE.value == "PROVENANCE_INCOMPLETE"
