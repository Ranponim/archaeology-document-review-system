import pytest

from app.graph.project_repository import DocumentVersionNotFoundError
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


def _version_row(version_id: str, document_id: str, kind: str, stage: str = "source"):
    return {
        "version_id": version_id,
        "document_id": document_id,
        "project_id": "p1",
        "kind": kind,
        "stage": stage,
        "uri": f"{version_id}.pdf",
        "sha256": f"sha-{version_id}",
        "mime_type": "application/pdf",
    }


def _body_v4_row():
    return _version_row("body_4", "doc_body", "report_body", "4차")


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


def test_review_round_rejects_version_that_is_not_in_project_and_expected_kind():
    # body resolves correctly; plate lookup is empty because the id belongs to
    # another project or a non-plate Document. The round CREATE must never run.
    driver = FakeDriver(responses=[
        [[_version_row("body_v1", "doc_body", "report_body")][0]],
        [],
    ])
    repo = ReviewProjectRepository(driver)

    with pytest.raises(DocumentVersionNotFoundError, match="plate_book"):
        repo.create_review_round(
            "p1",
            body_version_id="body_v1",
            plate_version_id="foreign_or_wrong_kind_plate",
            drawing_version_id="drawing_v1",
        )

    assert len(driver.queries) == 2
    assert "CREATE (round:ReviewRound" not in "\n".join(query for query, _ in driver.queries)
    assert driver.queries[0][1]["kind"] == "report_body"
    assert driver.queries[1][1]["kind"] == "plate_book"


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
