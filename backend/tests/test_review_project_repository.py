import pytest

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


def _body_v4_row():
    return {
        "version_id": "body_4",
        "document_id": "doc_body",
        "project_id": "p1",
        "kind": "report_body",
        "stage": "4차",
        "uri": "b4.pdf",
        "sha256": "sha",
        "mime_type": "application/pdf",
    }


def test_review_round_exact_version_resolution_uses_no_stage_filter():
    driver = FakeDriver(responses=[[_body_v4_row()]])
    repo = ReviewProjectRepository(driver)
    version = repo.resolve_version_input("p1", "report_body", None, "body_4")
    assert version.version_id == "body_4"
    _, kwargs = driver.queries[0]
    assert kwargs["stage"] is None


def test_exact_version_id_wins_over_stale_legacy_stage_metadata():
    driver = FakeDriver(responses=[[_body_v4_row()]])
    repo = ReviewProjectRepository(driver)
    version = repo.resolve_version_input("p1", "report_body", "1차", "body_4")
    assert version.version_id == "body_4"
    _, kwargs = driver.queries[0]
    assert kwargs["stage"] is None


def test_stage_only_legacy_lookup_still_uses_stage():
    driver = FakeDriver(responses=[])
    repo = ReviewProjectRepository(driver)
    assert repo.resolve_version_input("p1", "report_body", "4차", None) is None
    _, kwargs = driver.queries[0]
    assert kwargs["stage"] == "4차"


def test_review_round_rejects_incomplete_canonical_input_set():
    repo = ReviewProjectRepository(FakeDriver())
    with pytest.raises(ValueError, match="complete canonical input set"):
        repo.create_review_round(
            "p1",
            body_version_id="body_v1",
            plate_version_id=None,
            drawing_version_id="drawing_v1",
        )


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
