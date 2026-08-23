from __future__ import annotations

from typing import Any

import pytest

from app.api.projects import _run_repository
from app.domain.models import VersionInput
from app.graph.review_project_repository import ReviewProjectRepository
from app.services.review_round_execution import resolve_review_round_inputs


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


def _body_only_round_record() -> dict[str, Any]:
    return {
        "id": "round-1",
        "project_id": "p1",
        "sequence": 1,
        "status": "reviewing",
        "notes": "1차 본문 단독 교정",
        "created_at": "2026-08-23T00:00:00Z",
        "approved_at": None,
        "body_version_id": "body-v1",
        "reference_corpus_id": None,
        "plate_version_id": None,
        "drawing_version_id": None,
    }


def test_production_repository_accepts_body_only_review_round():
    driver = FakeDriver([[_body_only_round_record()]])
    repository = BodyResolvedRepository(driver)

    round_ = repository.create_review_round(
        project_id="p1",
        body_version_id="body-v1",
        notes="1차 본문 단독 교정",
    )

    assert round_.body_version_id == "body-v1"
    assert round_.reference_corpus_id is None
    assert round_.plate_version_id is None
    assert round_.drawing_version_id is None
    create_query = driver.queries[-1][0]
    assert "USES_BODY_VERSION" in create_query
    assert "USES_REFERENCE_CORPUS" not in create_query


def test_body_only_round_resolves_as_explicit_body_only_mode():
    repository = BodyResolvedRepository(FakeDriver([]))
    repository.get_review_round = lambda project_id, round_id: type(
        "Round",
        (),
        {
            "id": "round-1",
            "sequence": 1,
            "body_version_id": "body-v1",
            "reference_corpus_id": None,
            "plate_version_id": None,
            "drawing_version_id": None,
        },
    )()

    resolved = resolve_review_round_inputs(repository, "p1", "round-1")

    assert resolved.mode == "body_only"
    assert resolved.body.version_id == "body-v1"
    assert resolved.plate is None
    assert resolved.drawing is None
    assert resolved.reference_corpus is None


@pytest.mark.anyio
async def test_repository_value_error_stays_client_input_error_instead_of_500():
    def invalid_operation():
        raise ValueError("invalid review inputs")

    with pytest.raises(ValueError, match="invalid review inputs"):
        await _run_repository(invalid_operation)
