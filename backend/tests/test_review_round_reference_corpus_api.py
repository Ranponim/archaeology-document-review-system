from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.reviews import router
from app.domain.models import VersionInput
from app.domain.review_round import ReviewRound


class FakeProjectRepository:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_project(self, project_id: str):
        return {"project": object()}

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

    def create_review_round(
        self,
        project_id: str,
        body_version_id: str | None = None,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        notes: str | None = None,
        reference_corpus_id: str | None = None,
    ):
        self.calls.append(
            (
                project_id,
                body_version_id,
                plate_version_id,
                drawing_version_id,
                notes,
                reference_corpus_id,
            )
        )
        return ReviewRound(
            id="round-1",
            project_id=project_id,
            sequence=1,
            body_version_id=body_version_id,
            reference_corpus_id=reference_corpus_id,
            plate_version_id=plate_version_id,
            drawing_version_id=drawing_version_id,
        )


def _client(repository: FakeProjectRepository) -> TestClient:
    app = FastAPI()
    app.state.project_repository = repository
    app.state.review_repository = None
    app.include_router(router)
    return TestClient(app)


def test_create_round_accepts_body_plus_reference_corpus():
    repository = FakeProjectRepository()
    client = _client(repository)

    response = client.post(
        "/api/v1/projects/p1/rounds",
        json={
            "bodyVersionId": "body-v1",
            "referenceCorpusId": "corpus-1",
            "notes": "new mode",
        },
    )

    assert response.status_code == 201
    assert response.json()["bodyVersionId"] == "body-v1"
    assert response.json()["referenceCorpusId"] == "corpus-1"
    assert response.json()["plateVersionId"] is None
    assert response.json()["drawingVersionId"] is None
    assert repository.calls == [
        ("p1", "body-v1", None, None, "new mode", "corpus-1")
    ]


def test_create_round_rejects_mixed_corpus_and_legacy_visual_ids_before_repository():
    repository = FakeProjectRepository()
    client = _client(repository)

    response = client.post(
        "/api/v1/projects/p1/rounds",
        json={
            "bodyVersionId": "body-v1",
            "referenceCorpusId": "corpus-1",
            "plateVersionId": "legacy-plate-v1",
        },
    )

    assert response.status_code == 422
    assert repository.calls == []
