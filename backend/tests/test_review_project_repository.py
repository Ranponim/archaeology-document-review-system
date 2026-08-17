from app.graph.review_project_repository import ReviewProjectRepository


class FakeRecord(dict):
    pass


class FakeDriver:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.queries = []

    def execute_query(self, query, **kwargs):
        self.queries.append((query, kwargs))
        rows = self.responses.pop(0) if self.responses else []
        return [FakeRecord(row) for row in rows], None, None


def test_exact_version_resolution_ignores_legacy_stage_filter():
    driver = FakeDriver(responses=[[{
        "version_id": "body_4",
        "document_id": "doc_body",
        "project_id": "p1",
        "kind": "report_body",
        "stage": "4차",
        "uri": "b4.pdf",
        "sha256": "sha",
        "mime_type": "application/pdf",
    }]])
    repo = ReviewProjectRepository(driver)
    version = repo.resolve_version_input("p1", "report_body", "1차", "body_4")
    assert version.version_id == "body_4"
    _, kwargs = driver.queries[0]
    assert kwargs["stage"] is None


def test_approve_round_preserves_first_approved_timestamp():
    driver = FakeDriver(responses=[[{
        "id": "round_1",
        "project_id": "p1",
        "sequence": 1,
        "status": "approved",
        "notes": None,
        "created_at": "created",
        "approved_at": "first-approved",
        "body_version_id": "b1",
        "plate_version_id": "p1v",
        "drawing_version_id": "d1",
    }]])
    repo = ReviewProjectRepository(driver)
    result = repo.approve_review_round("p1", "round_1")
    query, _ = driver.queries[0]
    assert "coalesce(round.approvedAt, datetime())" in query
    assert result.approved_at == "first-approved"
