from typing import Any
import pytest

from app.domain.review_round import ReviewRound
from app.graph.project_repository import (
    ProjectNotFoundError,
    ProjectRepository,
    ReviewRoundNotFoundError,
)
from app.graph.schema import CONSTRAINTS


class FakeNeo4jRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class FakeNeo4jDriver:
    def __init__(self, responses: list[list[dict[str, Any]]] | None = None):
        self.queries: list[dict[str, Any]] = []
        self._responses = responses or []
        self._response_idx = 0

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        if self._response_idx < len(self._responses):
            records = [FakeNeo4jRecord(r) for r in self._responses[self._response_idx]]
            self._response_idx += 1
            return records, None, None
        return [], None, None


def test_review_round_domain_dataclass_instantiation():
    rr = ReviewRound(
        id="round_1",
        project_id="proj_1",
        sequence=1,
        status="reviewing",
        body_version_id="body_v1",
        plate_version_id="plate_v1",
        drawing_version_id="drawing_v1",
        created_at="2026-08-17T15:00:00Z",
        approved_at=None,
        notes="First round review",
    )
    assert rr.id == "round_1"
    assert rr.project_id == "proj_1"
    assert rr.sequence == 1
    assert rr.status == "reviewing"
    assert rr.body_version_id == "body_v1"
    assert rr.plate_version_id == "plate_v1"
    assert rr.drawing_version_id == "drawing_v1"
    assert rr.notes == "First round review"
    assert rr.approved_at is None


def test_schema_declares_review_round_constraint():
    labels = [label for _, label in CONSTRAINTS]
    assert "ReviewRound" in labels


def test_create_review_round_first_sequence():
    driver = FakeNeo4jDriver(
        responses=[
            [
                {
                    "id": "round_1",
                    "project_id": "proj_1",
                    "sequence": 1,
                    "status": "reviewing",
                    "notes": "Round 1",
                    "created_at": "2026-08-17T15:00:00Z",
                    "approved_at": None,
                    "body_version_id": "ver_body_1",
                    "plate_version_id": "ver_plate_1",
                    "drawing_version_id": "ver_drawing_1",
                }
            ]
        ]
    )
    repo = ProjectRepository(driver=driver, database="test_db")

    round_result = repo.create_review_round(
        project_id="proj_1",
        body_version_id="ver_body_1",
        plate_version_id="ver_plate_1",
        drawing_version_id="ver_drawing_1",
        notes="Round 1",
    )

    assert round_result.sequence == 1
    assert round_result.status == "reviewing"
    assert round_result.body_version_id == "ver_body_1"
    assert round_result.plate_version_id == "ver_plate_1"
    assert round_result.drawing_version_id == "ver_drawing_1"

    assert len(driver.queries) == 1
    q = driver.queries[0]
    cypher = q["query"]
    assert "HAS_REVIEW_ROUND" in cypher
    assert "USES_BODY_VERSION" in cypher
    assert "USES_PLATE_VERSION" in cypher
    assert "USES_DRAWING_VERSION" in cypher
    assert "PRECEDES" in cypher


def test_create_review_round_asset_reuse_and_precedes_chain():
    """Round 2 reuses plate_version_id from Round 1, updates body_version_id."""
    driver = FakeNeo4jDriver(
        responses=[
            [
                {
                    "id": "round_2",
                    "project_id": "proj_1",
                    "sequence": 2,
                    "status": "reviewing",
                    "notes": "Round 2 with reused plates",
                    "created_at": "2026-08-17T16:00:00Z",
                    "approved_at": None,
                    "body_version_id": "ver_body_2",
                    "plate_version_id": "ver_plate_1",  # reused from Round 1
                    "drawing_version_id": "ver_drawing_2",
                }
            ]
        ]
    )
    repo = ProjectRepository(driver=driver, database="test_db")

    round_result = repo.create_review_round(
        project_id="proj_1",
        body_version_id="ver_body_2",
        plate_version_id="ver_plate_1",
        drawing_version_id="ver_drawing_2",
        notes="Round 2 with reused plates",
    )

    assert round_result.sequence == 2
    assert round_result.body_version_id == "ver_body_2"
    assert round_result.plate_version_id == "ver_plate_1"
    assert round_result.drawing_version_id == "ver_drawing_2"

    q = driver.queries[0]
    assert q["kwargs"]["body_version_id"] == "ver_body_2"
    assert q["kwargs"]["plate_version_id"] == "ver_plate_1"
    assert q["kwargs"]["drawing_version_id"] == "ver_drawing_2"


def test_create_review_round_raises_when_project_not_found():
    driver = FakeNeo4jDriver(responses=[[]])
    repo = ProjectRepository(driver=driver)

    with pytest.raises(ProjectNotFoundError):
        repo.create_review_round(
            project_id="non_existent_proj",
            body_version_id="body_1",
        )


def test_list_review_rounds():
    driver = FakeNeo4jDriver(
        responses=[
            [
                {
                    "id": "round_1",
                    "project_id": "proj_1",
                    "sequence": 1,
                    "status": "approved",
                    "notes": "Round 1 done",
                    "created_at": "2026-08-17T14:00:00Z",
                    "approved_at": "2026-08-17T14:30:00Z",
                    "body_version_id": "ver_body_1",
                    "plate_version_id": "ver_plate_1",
                    "drawing_version_id": None,
                },
                {
                    "id": "round_2",
                    "project_id": "proj_1",
                    "sequence": 2,
                    "status": "reviewing",
                    "notes": "Round 2 in progress",
                    "created_at": "2026-08-17T15:00:00Z",
                    "approved_at": None,
                    "body_version_id": "ver_body_2",
                    "plate_version_id": "ver_plate_1",
                    "drawing_version_id": "ver_drawing_2",
                },
            ]
        ]
    )
    repo = ProjectRepository(driver=driver, database="test_db")
    rounds = repo.list_review_rounds(project_id="proj_1")

    assert len(rounds) == 2
    assert rounds[0].sequence == 1
    assert rounds[0].status == "approved"
    assert rounds[1].sequence == 2
    assert rounds[1].status == "reviewing"
    assert rounds[1].plate_version_id == "ver_plate_1"


def test_get_review_round_found_and_not_found():
    driver = FakeNeo4jDriver(
        responses=[
            [
                {
                    "id": "round_1",
                    "project_id": "proj_1",
                    "sequence": 1,
                    "status": "reviewing",
                    "notes": "Notes",
                    "created_at": "2026-08-17T15:00:00Z",
                    "approved_at": None,
                    "body_version_id": "ver_body_1",
                    "plate_version_id": "ver_plate_1",
                    "drawing_version_id": "ver_drawing_1",
                }
            ],
            [],
        ]
    )
    repo = ProjectRepository(driver=driver)

    round_found = repo.get_review_round(project_id="proj_1", round_id="round_1")
    assert round_found is not None
    assert round_found.id == "round_1"
    assert round_found.body_version_id == "ver_body_1"

    round_missing = repo.get_review_round(project_id="proj_1", round_id="missing_round")
    assert round_missing is None


def test_approve_review_round_success_and_not_found():
    driver = FakeNeo4jDriver(
        responses=[
            [
                {
                    "id": "round_1",
                    "project_id": "proj_1",
                    "sequence": 1,
                    "status": "approved",
                    "notes": "Notes",
                    "created_at": "2026-08-17T15:00:00Z",
                    "approved_at": "2026-08-17T15:30:00Z",
                    "body_version_id": "ver_body_1",
                    "plate_version_id": "ver_plate_1",
                    "drawing_version_id": "ver_drawing_1",
                }
            ],
            [],
        ]
    )
    repo = ProjectRepository(driver=driver)

    approved = repo.approve_review_round(project_id="proj_1", round_id="round_1")
    assert approved.status == "approved"
    assert approved.approved_at == "2026-08-17T15:30:00Z"

    with pytest.raises(ReviewRoundNotFoundError):
        repo.approve_review_round(project_id="proj_1", round_id="missing_round")
