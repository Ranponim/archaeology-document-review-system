from __future__ import annotations

from app.graph.graph_review_repository import GraphReviewRepository


class FakeDriver:
    def __init__(self):
        self.queries: list[tuple[str, dict]] = []

    def execute_query(self, query: str, **kwargs):
        self.queries.append((query, kwargs))
        corpus_id = kwargs.get("corpus_id")
        if "RETURN corpus.status AS status" in query:
            status = "ready" if corpus_id in {"c1", "c2"} else "failed"
            return ([{"status": status}] if corpus_id != "missing" else []), None, None
        if "AS visual_count" in query:
            return [{"visual_count": 2 if corpus_id == "c1" else 1}], None, None
        if "AS artifact_count" in query:
            return [{"artifact_count": 1}], None, None
        if "AS provenance_gap_count" in query:
            return [{"provenance_gap_count": 0}], None, None
        if "AS cross_project_count" in query:
            return [{"cross_project_count": 0}], None, None
        if "duplicate_number" in query:
            return [], None, None
        if "RETURN 'Plate' AS label" in query:
            return ([{"label": "Plate", "id": f"plate:{corpus_id}:45", "number": "45", "title": "6호 석관묘"}] if corpus_id else []), None, None
        if "RETURN ref.id AS id" in query and "REFERENCES" in query:
            return [{"id": "ref-45", "ref_type": "plate", "number": "45", "raw_text": "【도판 45】", "source_block_id": "b1"}], None, None
        return [], None, None


def test_validate_corpus_integrity_returns_structured_report():
    repository = GraphReviewRepository(FakeDriver())

    report = repository.validate_corpus_integrity("p1", "c1")

    assert report.ok is True
    assert report.visual_count == 2
    assert report.artifact_count == 1
    assert report.errors == ()


def test_validate_corpus_integrity_reports_non_ready_as_hard_error():
    repository = GraphReviewRepository(FakeDriver())

    report = repository.validate_corpus_integrity("p1", "foreign")

    assert report.ok is False
    assert "CORPUS_NOT_READY" in report.errors


def test_visuals_for_object_is_selected_corpus_scoped():
    repository = GraphReviewRepository(FakeDriver())

    v1 = repository.visuals_for_object("p1", "c1", "obj-6")
    v2 = repository.visuals_for_object("p1", "c2", "obj-6")

    assert [item.id for item in v1] == ["plate:c1:45"]
    assert [item.id for item in v2] == ["plate:c2:45"]
    assert all(item.reference_corpus_id == "c1" for item in v1)
    assert all(item.reference_corpus_id == "c2" for item in v2)


def test_references_for_object_is_project_scoped():
    driver = FakeDriver()
    repository = GraphReviewRepository(driver)

    refs = repository.references_for_object("p1", "obj-6")

    assert [(item.id, item.reference_type, item.number) for item in refs] == [
        ("ref-45", "plate", "45")
    ]
    ref_queries = [kwargs for query, kwargs in driver.queries if "REFERENCES" in query]
    assert ref_queries and ref_queries[-1]["project_id"] == "p1"
