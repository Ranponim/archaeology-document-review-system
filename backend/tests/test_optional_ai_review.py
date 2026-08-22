from __future__ import annotations

import pytest

from app.api.review_run_contract import ReviewRoundRunTriggerRequest
from app.domain.ai_review_finding import AIReviewFindingData
from app.services.graph_rules import GraphRuleFinding
from app.services.optional_graph_review import OptionalGraphReviewDispatcher


def _deterministic() -> GraphRuleFinding:
    return GraphRuleFinding(
        rule_code="VISUAL_REFERENCE_MISSING",
        severity="high",
        source_block_id="b1",
        archaeology_object_id="obj-6",
        reference_corpus_id="c1",
        canonical_target_ids=("plate:c1:45",),
        original_text="6호 석관묘",
        proposed_text="(도판 45)",
        rationale="graph proof",
        evidence_ids=("ev-graph",),
        requires_ai=False,
    )


def _semantic() -> GraphRuleFinding:
    return GraphRuleFinding(
        rule_code="SEMANTIC_REVIEW_REQUIRED",
        severity="medium",
        source_block_id="b2",
        archaeology_object_id="obj-6",
        reference_corpus_id="c1",
        canonical_target_ids=("region:c1:30",),
        original_text="북쪽 단면 방향이 일치한다.",
        proposed_text=None,
        rationale="orientation requires visual/context review",
        evidence_ids=("ev-semantic",),
        requires_ai=True,
    )


class FakeReviewer:
    def __init__(self, source: str, *, fail: bool = False):
        self.source = source
        self.fail = fail
        self.calls = []
        self._model = f"fake-{source}-model"

    async def review_graph_finding(self, *, finding, context):
        self.calls.append((finding.rule_code, context["analysis_run_id"]))
        if self.fail:
            raise TimeoutError(f"{self.source} timeout")
        return {
            "verdict": "SUPPORTED" if self.source == "vlm" else "REVIEWED",
            "confidence": 0.82,
            "rationale": f"{self.source} bounded review",
            "proposed_text": None,
        }


def test_strict_run_flags_default_off():
    payload = ReviewRoundRunTriggerRequest(reviewRoundId="r1")
    assert payload.enable_ai_review is False
    assert payload.enable_vlm is False


@pytest.mark.anyio
async def test_disabled_optional_review_never_calls_models():
    ai = FakeReviewer("ai")
    vlm = FakeReviewer("vlm")
    dispatcher = OptionalGraphReviewDispatcher(ai_reviewer=ai, vlm_reviewer=vlm)

    outcome = await dispatcher.review(
        findings=[_deterministic(), _semantic()],
        enable_ai_review=False,
        enable_vlm=False,
        context_by_finding={
            "SEMANTIC_REVIEW_REQUIRED:b2": {"analysis_run_id": "run-1"}
        },
    )

    assert ai.calls == []
    assert vlm.calls == []
    assert outcome.findings == []
    assert outcome.warnings == []


@pytest.mark.anyio
async def test_only_semantic_findings_are_dispatched_when_enabled():
    ai = FakeReviewer("ai")
    vlm = FakeReviewer("vlm")
    dispatcher = OptionalGraphReviewDispatcher(ai_reviewer=ai, vlm_reviewer=vlm)

    outcome = await dispatcher.review(
        findings=[_deterministic(), _semantic()],
        enable_ai_review=True,
        enable_vlm=True,
        context_by_finding={
            "SEMANTIC_REVIEW_REQUIRED:b2": {
                "analysis_run_id": "run-1",
                "candidate_id": "cand-semantic",
                "evidence_ids": ["ev-semantic"],
            }
        },
    )

    assert ai.calls == [("SEMANTIC_REVIEW_REQUIRED", "run-1")]
    assert vlm.calls == [("SEMANTIC_REVIEW_REQUIRED", "run-1")]
    assert len(outcome.findings) == 2
    assert all(isinstance(item, AIReviewFindingData) for item in outcome.findings)
    assert {item.source for item in outcome.findings} == {"ai", "vlm"}
    assert all(item.reference_corpus_id == "c1" for item in outcome.findings)
    assert all(item.analysis_run_id == "run-1" for item in outcome.findings)
    assert all(item.input_hash for item in outcome.findings)


@pytest.mark.anyio
async def test_optional_timeout_is_warning_not_core_failure():
    ai = FakeReviewer("ai", fail=True)
    dispatcher = OptionalGraphReviewDispatcher(ai_reviewer=ai, vlm_reviewer=None)

    outcome = await dispatcher.review(
        findings=[_deterministic(), _semantic()],
        enable_ai_review=True,
        enable_vlm=False,
        context_by_finding={
            "SEMANTIC_REVIEW_REQUIRED:b2": {"analysis_run_id": "run-1"}
        },
    )

    assert ai.calls == [("SEMANTIC_REVIEW_REQUIRED", "run-1")]
    assert outcome.findings == []
    assert len(outcome.warnings) == 1
    assert "ai" in outcome.warnings[0].lower()
    assert "timeout" in outcome.warnings[0].lower()
