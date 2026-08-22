from __future__ import annotations

from typing import Any

import pytest

from app.domain.models import VersionInput
from app.graph.review_project_repository import ReviewProjectRepository


class FakeRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str):
        return self._data[key]

    def get(self, key: str, default=None):
        return self._data.get(key, default)


class FakeDriver:
    def __init__(self, responses: list[list[dict[str, Any]]]):
        self.responses = list(responses)
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def execute_query(self, query: str, **kwargs):
        self.queries.append((query, kwargs))
        response = self.responses.pop(0) if self.responses else []
        return [FakeRecord(item) for item in response], None, None


class BodyResolvedRepository(ReviewProjectRepository):
    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ):
        if project_id == "p1" and kind == "report_body" and version_id == "body-v1":
            return VersionInput(
                version_id="body-v1",
                document_id="body-doc",
                project_id="p1",
                kind="report_body",
                stage="source",
                uri="incoming/p1/body.pdf",
                sha256="body-sha",
                mime_type="application/pdf",
            )
        return None


def _created_round_record() -> dict[str, Any]:
    return {
        "id": "round-1",
        "project_id": "p1",
        "sequence": 1,
        "status": "reviewing",
        "notes": None,
        "created_at": "2026-08-23T00:00:00Z",
        "approved_at": None,
        "body_version_id": "body-v1",
        "reference_corpus_id": "corpus-1",
        "plate_version_id": None,
        "drawing_version_id": None,
    }


def test_new_round_accepts_body_plus_ready_same_project_corpus():
    driver = FakeDriver(
        [
            [{"id": "corpus-1", "status": "ready", "project_id": "p1"}],
            [_created_round_record()],
        ]
    )
    repository = BodyResolvedRepository(driver)

    round_ = repository.create_review_round(
        project_id="p1",
        body_version_id="body-v1",
        reference_corpus_id="corpus-1",
    )

    assert round_.body_version_id == "body-v1"
    assert round_.reference_corpus_id == "corpus-1"
    assert round_.plate_version_id is None
    assert round_.drawing_version_id is None
    create_query = driver.queries[-1][0]
    assert "USES_REFERENCE_CORPUS" in create_query
    assert "USES_PLATE_VERSION" not in create_query
    assert "USES_DRAWING_VERSION" not in create_query


def test_new_round_rejects_mixed_corpus_and_legacy_visual_versions():
    repository = BodyResolvedRepository(FakeDriver([]))

    with pytest.raises(ValueError, match="mixed"):
        repository.create_review_round(
            project_id="p1",
            body_version_id="body-v1",
            reference_corpus_id="corpus-1",
            plate_version_id="plate-v1",
        )


def test_new_round_rejects_non_ready_corpus():
    driver = FakeDriver(
        [[{"id": "corpus-1", "status": "staging", "project_id": "p1"}]]
    )
    repository = BodyResolvedRepository(driver)

    with pytest.raises(ValueError, match="READY"):
        repository.create_review_round(
            project_id="p1",
            body_version_id="body-v1",
            reference_corpus_id="corpus-1",
        )


def test_new_round_rejects_cross_project_or_missing_corpus():
    repository = BodyResolvedRepository(FakeDriver([[]]))

    with pytest.raises(ValueError, match="corpus"):
        repository.create_review_round(
            project_id="p1",
            body_version_id="body-v1",
            reference_corpus_id="foreign-corpus",
        )
