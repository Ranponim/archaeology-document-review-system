from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.domain.reference_corpus import ReferenceCorpusData, ReferenceCorpusStatus
from app.services.review_round_execution import resolve_review_round_inputs


@dataclass
class FakeRound:
    id: str = "round-1"
    sequence: int = 1
    body_version_id: str | None = "body-v1"
    reference_corpus_id: str | None = "corpus-1"
    plate_version_id: str | None = None
    drawing_version_id: str | None = None


@dataclass
class FakeVersion:
    version_id: str = "body-v1"
    kind: str = "report_body"


class FakeRepository:
    def __init__(self, corpus_status=ReferenceCorpusStatus.READY):
        self.round = FakeRound()
        self.corpus = ReferenceCorpusData(
            id="corpus-1",
            project_id="p1",
            revision=1,
            status=corpus_status,
        )
        self.version_calls: list[tuple[str, str | None]] = []

    def get_review_round(self, project_id: str, round_id: str):
        if project_id == "p1" and round_id == "round-1":
            return self.round
        return None

    def resolve_version_input(self, project_id, kind, stage=None, version_id=None):
        self.version_calls.append((kind, version_id))
        if project_id == "p1" and kind == "report_body" and version_id == "body-v1":
            return FakeVersion()
        return None

    def get_reference_corpus(self, project_id: str, corpus_id: str):
        if project_id == "p1" and corpus_id == "corpus-1":
            return self.corpus
        return None


def test_corpus_round_resolves_body_and_ready_corpus_without_legacy_visual_versions():
    repository = FakeRepository()

    resolved = resolve_review_round_inputs(repository, "p1", "round-1")

    assert resolved.mode == "reference_corpus"
    assert resolved.body.version_id == "body-v1"
    assert resolved.reference_corpus.id == "corpus-1"
    assert resolved.plate is None
    assert resolved.drawing is None
    assert repository.version_calls == [("report_body", "body-v1")]


def test_corpus_round_fails_closed_if_selected_corpus_is_no_longer_ready():
    repository = FakeRepository(ReferenceCorpusStatus.FAILED)

    with pytest.raises(ValueError, match="READY"):
        resolve_review_round_inputs(repository, "p1", "round-1")


def test_corpus_round_fails_closed_if_corpus_is_missing_or_cross_project():
    repository = FakeRepository()
    repository.get_reference_corpus = lambda project_id, corpus_id: None

    with pytest.raises(ValueError, match="corpus"):
        resolve_review_round_inputs(repository, "p1", "round-1")
