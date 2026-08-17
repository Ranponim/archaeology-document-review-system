from dataclasses import dataclass

import pytest

from app.graph.project_repository import DocumentVersionNotFoundError, ReviewRoundNotFoundError
from app.services.review_round_execution import resolve_review_round_inputs


@dataclass
class FakeRound:
    id: str
    sequence: int
    body_version_id: str | None
    plate_version_id: str | None
    drawing_version_id: str | None
    status: str = "reviewing"


@dataclass
class FakeVersion:
    version_id: str
    kind: str
    stage: str = "legacy-stage"


class FakeProjectRepository:
    def __init__(self):
        self.round = FakeRound("round_2", 2, "body_2", "plate_1", "drawing_1")
        self.versions = {
            ("report_body", "body_2"): FakeVersion("body_2", "report_body"),
            ("plate_book", "plate_1"): FakeVersion("plate_1", "plate_book"),
            ("drawing_book", "drawing_1"): FakeVersion("drawing_1", "drawing_book"),
        }

    def get_review_round(self, project_id, round_id):
        if project_id == "p1" and round_id == self.round.id:
            return self.round
        return None

    def resolve_version_input(self, project_id, kind, stage=None, version_id=None):
        assert project_id == "p1"
        assert stage is None
        return self.versions.get((kind, version_id))


def test_round_is_authoritative_for_all_three_version_inputs():
    repo = FakeProjectRepository()
    resolved = resolve_review_round_inputs(repo, "p1", "round_2")
    assert resolved.review_round.id == "round_2"
    assert resolved.body.version_id == "body_2"
    assert resolved.plate.version_id == "plate_1"
    assert resolved.drawing.version_id == "drawing_1"
    assert resolved.compatibility_stage == "2차"


def test_missing_round_fails_closed():
    repo = FakeProjectRepository()
    with pytest.raises(ReviewRoundNotFoundError):
        resolve_review_round_inputs(repo, "p1", "missing")


def test_wrong_project_or_kind_version_fails_closed():
    repo = FakeProjectRepository()
    repo.versions.pop(("plate_book", "plate_1"))
    with pytest.raises(DocumentVersionNotFoundError):
        resolve_review_round_inputs(repo, "p1", "round_2")


def test_body_version_is_required_for_a_review_round():
    repo = FakeProjectRepository()
    repo.round.body_version_id = None
    with pytest.raises(DocumentVersionNotFoundError):
        resolve_review_round_inputs(repo, "p1", "round_2")
