from __future__ import annotations

from app.graph.graph_review_repository import GraphReviewRepository


class FakeDriver:
    def __init__(self):
        self.queries: list[tuple[str, dict]] = []

    def execute_query(self, query: str, **kwargs):
        self.queries.append((query, kwargs))
        corpus_id = kwargs.get("corpus_id")
        if "RETURN corpus.status AS status" in query:
            return ([{"status": "ready"}] if corpus_id in {"c1", "c2"} else []), None, None
        if "MATCH (corpus)-[:HAS_PLATE]" in query:
            if corpus_id == "c1":
                return [{"id": "plate:c1:45"}], None, None
            if corpus_id == "c2":
                return [{"id": "plate:c2:45"}], None, None
            return [], None, None
        if "MATCH (corpus)-[:HAS_DRAWING]" in query:
            return [], None, None
        if "ResolutionEvidence" in query:
            return [{"id": kwargs["evidence_id"]}], None, None
        return [], None, None


def test_resolution_is_corpus_scoped():
    repository = GraphReviewRepository(FakeDriver())

    v1 = repository.resolve_reference("p1", "c1", "plate", "45")
    v2 = repository.resolve_reference("p1", "c2", "plate", "45")

    assert v1.status == "RESOLVED"
    assert v2.status == "RESOLVED"
    assert v1.target_ids == ("plate:c1:45",)
    assert v2.target_ids == ("plate:c2:45",)


def test_missing_and_invalid_reference_statuses_are_explicit():
    repository = GraphReviewRepository(FakeDriver())

    missing = repository.resolve_reference("p1", "c1", "drawing", "999")
    invalid = repository.resolve_reference("p1", "c1", "unknown", "45")

    assert missing.status == "MISSING"
    assert missing.target_ids == ()
    assert invalid.status == "INVALID"
    assert invalid.target_ids == ()


def test_ambiguous_target_fails_closed():
    driver = FakeDriver()

    def execute(query: str, **kwargs):
        driver.queries.append((query, kwargs))
        if "RETURN corpus.status AS status" in query:
            return [{"status": "ready"}], None, None
        if "MATCH (corpus)-[:HAS_PLATE]" in query:
            return [{"id": "plate:c1:45:a"}, {"id": "plate:c1:45:b"}], None, None
        return [], None, None

    driver.execute_query = execute
    repository = GraphReviewRepository(driver)
    result = repository.resolve_reference("p1", "c1", "plate", "45")

    assert result.status == "AMBIGUOUS"
    assert result.target_ids == ("plate:c1:45:a", "plate:c1:45:b")


def test_cross_project_or_missing_corpus_is_rejected_before_resolution():
    repository = GraphReviewRepository(FakeDriver())

    try:
        repository.resolve_reference("p1", "foreign-corpus", "plate", "45")
    except ValueError as error:
        assert "corpus" in str(error).lower()
    else:
        raise AssertionError("cross-project corpus must fail closed")


def test_resolution_evidence_identity_includes_run_and_corpus():
    driver = FakeDriver()
    repository = GraphReviewRepository(driver)
    resolution = repository.resolve_reference("p1", "c1", "plate", "45")

    e1 = repository.save_resolution_evidence(
        "p1", "c1", "run-1", "ref-45", resolution
    )
    e2 = repository.save_resolution_evidence(
        "p1", "c2", "run-1", "ref-45", repository.resolve_reference("p1", "c2", "plate", "45")
    )
    e3 = repository.save_resolution_evidence(
        "p1", "c1", "run-2", "ref-45", resolution
    )

    assert len({e1, e2, e3}) == 3
    writes = [kwargs for query, kwargs in driver.queries if "ResolutionEvidence" in query]
    assert {item["corpus_id"] for item in writes} == {"c1", "c2"}
    assert {item["analysis_run_id"] for item in writes} == {"run-1", "run-2"}
