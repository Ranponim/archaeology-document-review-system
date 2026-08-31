from app.domain.drawing_evidence_v3 import (
    CodexDrawingDecision,
    DrawingCandidatePacket,
    DrawingV3Evidence,
    DrawingV3Resolution,
    DrawingV3SourceResult,
)
from app.graph.drawing_evidence_repository_v3 import DrawingEvidenceRepositoryV3


class CaptureDriver:
    def __init__(self):
        self.calls = []

    def execute_query(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return ([], None, None)


def candidate(candidate_id: str, number: str, *, evidence_id: str) -> DrawingCandidatePacket:
    return DrawingCandidatePacket(
        candidate_id=candidate_id,
        publication_kind="drawing",
        number=number,
        raw_texts=(f"도면 {number}",),
        facts=(),
        visual_regions=(),
        local_score=12.5,
        evidence=(
            DrawingV3Evidence(
                id=evidence_id,
                family="archaeology_signature",
                method="exact_feature_pair",
                value="1호:토광묘",
                supports=True,
                weak=False,
            ),
        ),
        hard_contradiction=False,
        strong_contradiction_ids=(),
    )


def decision(run_id: str, candidate_id: str, evidence_id: str) -> CodexDrawingDecision:
    return CodexDrawingDecision(
        run_id=run_id,
        model="gpt-5.3-codex",
        verdict="match",
        candidate_id=candidate_id,
        confidence=0.98,
        cited_support_ids=(evidence_id,),
        cited_contradiction_ids=(),
        reason_codes=("feature_pair_exact",),
        summary="candidate is consistent with the supplied evidence",
    )


def resolution() -> DrawingV3Resolution:
    c52 = candidate("candidate:source-a:drawing:52", "52", evidence_id="ev-a")
    c53 = candidate("candidate:source-b:drawing:53", "53", evidence_id="ev-b")
    c54 = candidate("candidate:source-c:drawing:54", "54", evidence_id="ev-c")
    return DrawingV3Resolution(
        source_results=(
            DrawingV3SourceResult(
                source_asset_id="source-a",
                status="AUTO_VERIFIED",
                candidates=(c52,),
                decision=decision("run-a", c52.candidate_id, "ev-a"),
                selected_candidate_id=c52.candidate_id,
                diagnostics={"resolver_version": "drawing-evidence-v3"},
            ),
            DrawingV3SourceResult(
                source_asset_id="source-b",
                status="REVIEW_REQUIRED",
                candidates=(c53,),
                decision=decision("run-b", c53.candidate_id, "ev-b"),
                selected_candidate_id=c53.candidate_id,
                diagnostics={"resolver_version": "drawing-evidence-v3"},
            ),
            DrawingV3SourceResult(
                source_asset_id="source-c",
                status="UNRESOLVED",
                candidates=(c54,),
                decision=CodexDrawingDecision(
                    run_id="run-c",
                    model="gpt-5.3-codex",
                    verdict="none",
                    candidate_id=None,
                    confidence=0.91,
                    cited_support_ids=(),
                    cited_contradiction_ids=(),
                    reason_codes=("no_supported_candidate",),
                    summary="none of the submitted candidates is supported",
                ),
                selected_candidate_id=None,
                diagnostics={"resolver_version": "drawing-evidence-v3"},
            ),
        ),
        diagnostics={"resolver_version": "drawing-evidence-v3"},
    )


def test_v3_shadow_persists_candidates_evidence_and_codex_decisions_without_targets():
    driver = CaptureDriver()
    repo = DrawingEvidenceRepositoryV3(driver)

    repo.save_v3_resolution("project-1", "corpus-1", resolution(), auto_promote=False)

    joined = "\n".join(query for query, _ in driver.calls)
    assert "DRAWING_V3_CANDIDATES" in joined
    assert "DRAWING_V3_EVIDENCE" in joined
    assert "DRAWING_V3_CODEX_DECISIONS" in joined
    assert "DRAWING_V3_TARGETS" not in joined

    decision_call = next(kwargs for query, kwargs in driver.calls if "DRAWING_V3_CODEX_DECISIONS" in query)
    rows = decision_call["decisions"]
    assert [(row["run_id"], row["final_status"]) for row in rows] == [
        ("run-a", "AUTO_VERIFIED"),
        ("run-b", "REVIEW_REQUIRED"),
        ("run-c", "UNRESOLVED"),
    ]
    assert rows[0]["model"] == "gpt-5.3-codex"
    assert rows[0]["cited_support_ids"] == ["ev-a"]
    assert rows[0]["reason_codes"] == ["feature_pair_exact"]


def test_v3_auto_promote_creates_target_only_for_auto_verified_match():
    driver = CaptureDriver()
    repo = DrawingEvidenceRepositoryV3(driver)

    repo.save_v3_resolution("project-1", "corpus-1", resolution(), auto_promote=True)

    target_call = next(kwargs for query, kwargs in driver.calls if "DRAWING_V3_TARGETS" in query)
    assert target_call["targets"] == [
        {
            "candidate_id": "candidate:source-a:drawing:52",
            "source_asset_id": "source-a",
            "publication_kind": "drawing",
            "number": "52",
            "decision_run_id": "run-a",
        }
    ]
