from app.graph.review_project_repository import ReviewProjectRepository


class FakeRecord(dict):
    pass


class FakeDriver:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute_query(self, query, **kwargs):
        self.queries.append((query, kwargs))
        return [FakeRecord(row) for row in self.rows], None, None


def test_get_previous_review_round_uses_precedes_and_project_scope():
    driver = FakeDriver([
        {
            "id": "round_3",
            "project_id": "p1",
            "sequence": 3,
            "status": "approved",
            "notes": None,
            "created_at": "2026-08-17T10:00:00Z",
            "approved_at": "2026-08-17T11:00:00Z",
            "body_version_id": "body_v2",
            "plate_version_id": "plate_v1",
            "drawing_version_id": "drawing_v1",
        }
    ])
    repo = ReviewProjectRepository(driver)

    previous = repo.get_previous_review_round("p1", "round_4")

    assert previous is not None
    assert previous.id == "round_3"
    assert previous.sequence == 3
    assert previous.body_version_id == "body_v2"

    query, kwargs = driver.queries[0]
    assert "(previous:ReviewRound)-[:PRECEDES]->(current:ReviewRound" in query
    assert "HAS_REVIEW_ROUND" in query
    assert "USES_BODY_VERSION" in query
    assert "version.stage" not in query
    assert kwargs["project_id"] == "p1"
    assert kwargs["round_id"] == "round_4"


def test_get_previous_review_round_returns_none_for_first_round():
    driver = FakeDriver([
        {
            "id": None,
            "project_id": None,
            "sequence": None,
            "status": None,
            "notes": None,
            "created_at": None,
            "approved_at": None,
            "body_version_id": None,
            "plate_version_id": None,
            "drawing_version_id": None,
        }
    ])
    repo = ReviewProjectRepository(driver)

    assert repo.get_previous_review_round("p1", "round_1") is None
