from app.domain.review_models import CorrectionCandidateData
from app.graph.strict_review_repository import StrictReviewRepository


class FakeRecord(dict):
    pass


class FakeDriver:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.queries = []

    def execute_query(self, query, **kwargs):
        self.queries.append((query, kwargs))
        rows = self.responses.pop(0) if self.responses else []
        return [FakeRecord(r) for r in rows], None, None


def test_save_candidates_persists_project_scope_severity_fingerprint_and_run_link():
    driver = FakeDriver()
    repo = StrictReviewRepository(driver)
    candidate = CorrectionCandidateData(
        candidate_id="cand_run_1_abc",
        rule_category="numeric_value",
        severity="high",
        finding_fingerprint="fp_abc",
        analysis_run_id="run_1",
    )
    repo.save_candidates("p1", [candidate], analysis_run_id="run_1")

    save_query, save_kwargs = driver.queries[0]
    assert "MATCH (proj:Project {id: $project_id})" in save_query
    assert "cand.severity = c.severity" in save_query
    assert "cand.findingFingerprint = c.finding_fingerprint" in save_query
    assert save_kwargs["candidates"][0]["severity"] == "high"
    assert save_kwargs["candidates"][0]["finding_fingerprint"] == "fp_abc"

    run_query, _ = driver.queries[1]
    assert "(proj)-[:HAS_RUN]->(run:AnalysisRun" in run_query
    assert "(proj)-[:HAS_CANDIDATE]->(cand:CorrectionCandidate" in run_query


def test_get_candidate_is_project_scoped():
    driver = FakeDriver(responses=[[]])
    repo = StrictReviewRepository(driver)
    assert repo.get_candidate("p1", "c1") is None
    query, kwargs = driver.queries[0]
    assert "(proj:Project {id: $project_id})-[:HAS_CANDIDATE]->" in query
    assert kwargs["project_id"] == "p1"
    assert kwargs["candidate_id"] == "c1"


def test_create_analysis_run_links_review_round_and_claim_returns_it():
    driver = FakeDriver(
        responses=[
            [{"id": "run_1"}],
            [{"projectId": "p1", "run": {"reviewRoundId": "round_2", "bodyVersionId": "b2"}}],
        ]
    )
    repo = StrictReviewRepository(driver)
    repo.create_analysis_run(
        "p1",
        "run_1",
        review_round_id="round_2",
        body_version_id="b2",
    )
    create_query, create_kwargs = driver.queries[0]
    assert "HAS_REVIEW_ROUND" in create_query
    assert "FOR_ROUND" in create_query
    assert create_kwargs["review_round_id"] == "round_2"

    claimed = repo.claim_analysis("run_1")
    assert claimed["review_round_id"] == "round_2"


def test_metrics_use_persisted_severity_values():
    repo = StrictReviewRepository(None)
    metrics = repo.compute_metrics_for_candidates(
        "p1",
        [
            {"severity": "high", "status": "pending_review", "rule_category": "numeric_value", "decisions": []},
            {"severity": "low", "status": "pending_review", "rule_category": "site_or_area_name", "decisions": []},
        ],
    )
    assert metrics["by_severity"] == {"high": 1, "low": 1}
