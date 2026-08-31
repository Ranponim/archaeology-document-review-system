from __future__ import annotations

import pytest

from app.graph.drawing_evidence_repository_v3 import (
    DrawingEvidenceRepositoryV3,
    DrawingReviewConflictError,
)


class ReviewDriver:
    def __init__(self):
        self.calls = []

    def execute_query(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if "DRAWING_V3_REVIEW_CASES" in query:
            return (
                [
                    {
                        "source_asset_id": "source-a",
                        "source_name": "source-a.ai",
                        "source_text": "2지점 1호 토광묘",
                        "source_visual_id": "review-visual:source-a",
                        "decision_id": "decision-a",
                        "codex_candidate_id": "candidate:52",
                        "codex_confidence": 0.91,
                        "codex_summary": "52와 53을 추가 확인해야 함",
                        "candidate_id": "candidate:53",
                        "publication_kind": "drawing",
                        "number": "53",
                        "caption": "도면 53. 2지점 2호 토광묘",
                        "local_score": 19.0,
                        "candidate_visual_id": "review-visual:53",
                        "evidence_summary": ["2지점 일치"],
                        "contradiction_summary": ["호수 확인 필요"],
                    },
                    {
                        "source_asset_id": "source-a",
                        "source_name": "source-a.ai",
                        "source_text": "2지점 1호 토광묘",
                        "source_visual_id": "review-visual:source-a",
                        "decision_id": "decision-a",
                        "codex_candidate_id": "candidate:52",
                        "codex_confidence": 0.91,
                        "codex_summary": "52와 53을 추가 확인해야 함",
                        "candidate_id": "candidate:52",
                        "publication_kind": "drawing",
                        "number": "52",
                        "caption": "도면 52. 2지점 1호 토광묘",
                        "local_score": 18.0,
                        "candidate_visual_id": "review-visual:52",
                        "evidence_summary": ["2지점 일치", "1호 토광묘 일치"],
                        "contradiction_summary": [],
                    },
                ],
                None,
                None,
            )
        if "DRAWING_V3_REVIEW_RESOLVE_LOOKUP" in query:
            return (
                [
                    {
                        "source_asset_id": "source-a",
                        "corpus_id": "corpus-1",
                        "decision_id": "decision-a",
                        "codex_candidate_id": "candidate:52",
                        "codex_run_id": "run-a",
                        "codex_model": "gpt-5.3-codex",
                        "candidate_ids": ["candidate:52", "candidate:53", "candidate:61"],
                        "candidates": [
                            {"id": "candidate:52", "publication_kind": "drawing", "number": "52"},
                            {"id": "candidate:53", "publication_kind": "drawing", "number": "53"},
                            {"id": "candidate:61", "publication_kind": "drawing", "number": "61"},
                        ],
                    }
                ],
                None,
                None,
            )
        if "DRAWING_V3_HUMAN_RESOLUTION" in query:
            return ([{"saved": 1}], None, None)
        return ([], None, None)


def test_pending_review_cases_put_codex_selection_first_then_local_score():
    repo = DrawingEvidenceRepositoryV3(ReviewDriver())

    rows = repo.list_v3_review_cases("project-1")

    assert len(rows) == 1
    case = rows[0]
    assert case["source_asset_id"] == "source-a"
    assert case["source_image_url"].endswith("review-visual%3Asource-a/render")
    assert case["codex_candidate_id"] == "candidate:52"
    assert [candidate["candidate_id"] for candidate in case["candidates"]] == [
        "candidate:52",
        "candidate:53",
    ]
    assert case["candidates"][0]["image_url"].endswith("review-visual%3A52/render")


def test_choose_persists_human_verified_target_and_rejects_alternatives():
    driver = ReviewDriver()
    repo = DrawingEvidenceRepositoryV3(driver)

    result = repo.resolve_v3_review(
        "project-1",
        "source-a",
        "choose",
        "candidate:53",
        "reviewer-1",
    )

    assert result == {
        "source_asset_id": "source-a",
        "action": "choose",
        "candidate_id": "candidate:53",
        "final_status": "HUMAN_VERIFIED",
    }
    mutation = next(
        kwargs for query, kwargs in driver.calls if "DRAWING_V3_HUMAN_RESOLUTION" in query
    )
    assert mutation["candidate_id"] == "candidate:53"
    assert set(mutation["rejected_candidate_ids"]) == {"candidate:52", "candidate:61"}
    assert mutation["final_status"] == "HUMAN_VERIFIED"
    assert mutation["drawing_id"] == "drawing:corpus-1:drawing:53"


def test_approve_only_accepts_codex_selected_candidate():
    repo = DrawingEvidenceRepositoryV3(ReviewDriver())
    with pytest.raises(DrawingReviewConflictError):
        repo.resolve_v3_review(
            "project-1", "source-a", "approve", "candidate:53", "human"
        )


def test_unknown_candidate_fails_closed():
    repo = DrawingEvidenceRepositoryV3(ReviewDriver())
    with pytest.raises(DrawingReviewConflictError):
        repo.resolve_v3_review(
            "project-1", "source-a", "choose", "candidate:999", "human"
        )


def test_none_records_all_candidates_rejected_and_creates_no_target():
    driver = ReviewDriver()
    repo = DrawingEvidenceRepositoryV3(driver)

    result = repo.resolve_v3_review(
        "project-1", "source-a", "none", None, "reviewer-1"
    )

    assert result["final_status"] == "HUMAN_UNRESOLVED"
    mutation = next(
        kwargs for query, kwargs in driver.calls if "DRAWING_V3_HUMAN_RESOLUTION" in query
    )
    assert mutation["candidate_id"] is None
    assert mutation["drawing_id"] is None
    assert set(mutation["rejected_candidate_ids"]) == {
        "candidate:52",
        "candidate:53",
        "candidate:61",
    }
