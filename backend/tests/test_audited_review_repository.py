from app.domain.review_models import CorrectionCandidateData
from app.graph.audited_review_repository import AuditedReviewRepository


class FakeRecord(dict):
    pass


class FakeDriver:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.queries = []

    def execute_query(self, query, **kwargs):
        self.queries.append((query, kwargs))
        rows = self.responses.pop(0) if self.responses else []
        return [FakeRecord(row) for row in rows], None, None


def test_same_finding_is_materialized_as_distinct_candidate_per_run():
    driver = FakeDriver()
    repo = AuditedReviewRepository(driver)
    finding1 = CorrectionCandidateData(
        candidate_id="legacy",
        rule_category="numeric_value",
        original_text="210cm",
        proposed_text="220cm",
        analysis_run_id="run_1",
    )
    finding2 = CorrectionCandidateData(
        candidate_id="legacy",
        rule_category="numeric_value",
        original_text="210cm",
        proposed_text="220cm",
        analysis_run_id="run_2",
    )
    repo.save_candidates("p1", [finding1], analysis_run_id="run_1")
    first_id = driver.queries[0][1]["candidates"][0]["candidate_id"]
    repo.save_candidates("p1", [finding2], analysis_run_id="run_2")
    second_id = driver.queries[2][1]["candidates"][0]["candidate_id"]
    assert first_id != second_id
    assert first_id.startswith("cand_run_1_")
    assert second_id.startswith("cand_run_2_")


def test_run_summary_is_persisted_and_project_scoped_readable():
    driver = FakeDriver(
        responses=[
            [],
            [{"run": {"id": "run_1", "reviewSummary": '{"selected_candidates":10}'}}],
        ]
    )
    repo = AuditedReviewRepository(driver)
    repo.save_run_summary("run_1", {"selected_candidates": 10})
    save_query, _ = driver.queries[0]
    assert "run.reviewSummary" in save_query
    data = repo.get_analysis_run("p1", "run_1")
    query, kwargs = driver.queries[1]
    assert "(proj:Project {id: $project_id})-[:HAS_RUN]->" in query
    assert kwargs["project_id"] == "p1"
    assert data["summary"]["selected_candidates"] == 10
