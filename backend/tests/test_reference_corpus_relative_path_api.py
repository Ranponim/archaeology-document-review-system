from __future__ import annotations

from uuid import uuid4

from tests.test_reference_corpora_api import _client


def test_reference_corpus_upload_forwards_and_returns_relative_path(tmp_path):
    client, service = _client(tmp_path)
    project_id = str(uuid4())
    assert client.post(f"/api/projects/{project_id}/reference-corpora").status_code == 201

    captured: dict[str, str | None] = {}
    original = service.stage_stored_source

    def capture(project_id_arg, corpus_id, stored, role, *, relative_path=None):
        captured["relative_path"] = relative_path
        return original(
            project_id_arg,
            corpus_id,
            stored,
            role,
            relative_path=relative_path,
        )

    service.stage_stored_source = capture
    response = client.post(
        f"/api/projects/{project_id}/reference-corpora/corpus-1/sources"
        "?role=plate_link&relativePath=Job%2FLinks%2Fphoto.jpg",
        files={"file": ("photo.jpg", b"jpeg", "image/jpeg")},
    )

    assert response.status_code == 202
    assert captured["relative_path"] == "Job/Links/photo.jpg"
    assert response.json()["relativePath"] == "Job/Links/photo.jpg"
