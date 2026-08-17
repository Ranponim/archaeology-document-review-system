from typing import Any
import pytest
from fastapi.testclient import TestClient

from app.domain.canonical_models import ArchaeologyObjectData
from app.domain.models import Document, DocumentVersion, Project, VersionInput
from app.domain.review_models import (
    CorrectionCandidateData,
    EvidenceData,
)
from app.graph.project_repository import ProjectNotFoundError
from app.main import create_app
from app.services.proofreading_orchestrator import (
    OrchestratorResult,
    ProofreadingOrchestrator,
)



class FakeProjectRepository:
    def __init__(self):
        self.projects = {
            "p1": Project(id="p1", name="산노리 유적", internal_code="NONSAN-001")
        }
        self.documents = {
            "p1": [
                Document(id="doc_body_1", project_id="p1", kind="report_body", title="본문"),
                Document(id="doc_plate_1", project_id="p1", kind="plate_pdf", title="도판"),
            ]
        }
        self.versions = {
            "p1": [
                DocumentVersion(
                    id="ver_body_01",
                    document_id="doc_body_1",
                    analysis_run_id="run_1",
                    uri="incoming/p1/sha_b/body.pdf",
                    sha256="sha256_body_hash",
                    size_bytes=10000,
                    mime_type="application/pdf",
                    original_name="body.pdf",
                    stage="1차",
                ),
                DocumentVersion(
                    id="ver_plate_01",
                    document_id="doc_plate_1",
                    analysis_run_id="run_2",
                    uri="incoming/p1/sha_p/plate.pdf",
                    sha256="sha256_plate_hash",
                    size_bytes=20000,
                    mime_type="application/pdf",
                    original_name="plate.pdf",
                    stage="1차",
                ),
                DocumentVersion(
                    id="ver_body_03",
                    document_id="doc_body_1",
                    analysis_run_id="run_3",
                    uri="incoming/p1/sha_b3/body3.pdf",
                    sha256="sha256_body_3rd_hash",
                    size_bytes=12000,
                    mime_type="application/pdf",
                    original_name="body-3차.pdf",
                    stage="3차",
                ),
            ]
        }

    def get_project(self, project_id: str) -> dict:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        return {
            "project": self.projects[project_id],
            "id": project_id,
            "name": self.projects[project_id].name,
            "internal_code": self.projects[project_id].internal_code,
            "documents": self.documents.get(project_id, []),
            "document_versions": self.versions.get(project_id, []),
            "analysis_runs": [],
        }

    def get_document_version_by_id(self, version_id: str) -> DocumentVersion | None:
        for v_list in self.versions.values():
            for v in v_list:
                if v.id == version_id:
                    return v
        return None

    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ) -> VersionInput | None:
        if project_id not in self.projects:
            return None
        v_list = self.versions.get(project_id, [])
        doc_map = {d.id: d for d in self.documents.get(project_id, [])}
        for v in v_list:
            doc = doc_map.get(v.document_id)
            doc_kind = doc.kind if doc else "report_body"
            if doc_kind != kind:
                continue
            if stage is not None and v.stage != stage:
                continue
            if version_id is not None and v.id != version_id:
                continue
            return VersionInput(
                version_id=v.id,
                document_id=v.document_id,
                project_id=project_id,
                kind=doc_kind,
                stage=v.stage,
                uri=v.uri,
                sha256=v.sha256,
                mime_type=v.mime_type,
            )
        return None



class FakeReviewRepository:
    def __init__(self):
        self.candidates: dict[str, dict[str, Any]] = {}
        self.decisions: list[dict[str, Any]] = []
        self.runs: dict[str, dict[str, Any]] = {}

    def create_analysis_run(
        self,
        project_id: str,
        run_id: str,
        *,
        body_version_id: str,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        body_pdf_path: str | None = None,
        plate_pdf_path: str | None = None,
        drawing_pdf_path: str | None = None,
        enable_vlm: bool = True,
        enable_ai_review: bool = True,
        version_stage: str = "1차",
    ) -> None:
        self.runs[run_id] = {
            "project_id": project_id,
            "status": "queued",
            "step": "queued",
            "body_version_id": body_version_id,
            "plate_version_id": plate_version_id,
            "drawing_version_id": drawing_version_id,
            "body_pdf_path": body_pdf_path,
            "plate_pdf_path": plate_pdf_path,
            "drawing_pdf_path": drawing_pdf_path,
            "enable_vlm": enable_vlm,
            "enable_ai_review": enable_ai_review,
            "version_stage": version_stage,
        }

    def save_analysis_run(
        self,
        project_id: str,
        run_id: str,
        status: str = "pending",
        model: str | None = None,
        step: str | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        run = self.runs.setdefault(run_id, {"project_id": project_id})
        run["status"] = status
        if step is not None:
            run["step"] = step
        if error_code is not None:
            run["error_code"] = error_code
        if retryable is not None:
            run["retryable"] = retryable

    def seed_candidate(
        self,
        project_id: str,
        cand_id: str,
        rule_category: str,
        status: str = "pending_review",
        original_text: str = "30cm",
        proposed_text: str = "30m",
        archaeology_object_id: str | None = None,
        confidence: float = 0.95,
        evidence: dict[str, Any] | None = None,
        evidences: list[dict[str, Any]] | None = None,
    ):
        ev_list = evidences or ([evidence] if evidence else [])
        self.candidates[cand_id] = {
            "id": cand_id,
            "candidate_id": cand_id,
            "project_id": project_id,
            "rule_category": rule_category,
            "category": rule_category,
            "change_type": "modified",
            "status": status,
            "original_text": original_text,
            "proposed_text": proposed_text,
            "archaeology_object_id": archaeology_object_id,
            "confidence": confidence,
            "evidence": ev_list[0] if ev_list else None,
            "evidences": ev_list,
            "decisions": [],
            "latest_decision": None,
        }

    def get_candidates(
        self,
        project_id: str,
        status: str | None = None,
        rule_category: str | None = None,
        archaeology_object_id: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        results = []
        for c in self.candidates.values():
            if c.get("project_id") != project_id:
                continue
            if status is not None and c.get("status") != status:
                continue
            if rule_category is not None and c.get("rule_category") != rule_category:
                continue
            if (
                archaeology_object_id is not None
                and c.get("archaeology_object_id") != archaeology_object_id
            ):
                continue
            results.append(dict(c))
        return results

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        return self.candidates.get(candidate_id)

    def save_review_decision(
        self,
        decision_id: str,
        candidate_id: str,
        decision_status: str,
        note: str = "",
        reviewer: str = "",
        previous_decision_id: str | None = None,
        modified_text: str | None = None,
    ) -> None:
        cand = self.candidates.get(candidate_id)
        if not cand:
            raise KeyError(f"Candidate {candidate_id} not found")

        if decision_status not in ("accepted", "rejected", "modified", "deferred"):
            raise ValueError(f"decision_status must be one of accepted|rejected|modified|deferred")

        prev_id = previous_decision_id
        if prev_id is None and cand["decisions"]:
            prev_id = cand["decisions"][-1]["id"]

        decision_record = {
            "id": decision_id,
            "candidate_id": candidate_id,
            "decision_status": decision_status,
            "decision": decision_status,
            "note": note,
            "rationale": note,
            "reviewer": reviewer,
            "modified_text": modified_text,
            "previous_decision_id": prev_id,
            "created_at": f"2026-08-17T00:00:0{len(cand['decisions'])}Z",
        }
        self.decisions.append(decision_record)
        cand["decisions"].append(decision_record)
        if modified_text is not None:
            cand["proposed_text"] = modified_text

        latest = max(
            cand["decisions"],
            key=lambda d: str(d.get("created_at") or "") or str(d.get("id") or ""),
        )
        cand["latest_decision"] = latest

    def get_candidate_traceability(self, candidate_id: str) -> dict[str, Any]:
        cand = self.candidates.get(candidate_id)
        if not cand:
            return {}

        ev_list = cand.get("evidences", [])
        evidence_chain = []
        for ev in ev_list:
            ev_entry = {
                "evidence": ev,
                "page": {
                    "id": ev.get("page_id", "p1"),
                    "physical_page": ev.get("physical_page_from", 1),
                    "printed_page": ev.get("printed_page_from", 1),
                },
                "document_version": {
                    "id": ev.get("document_version_id", "v1"),
                    "source_sha256": ev.get("source_sha256", "sha256_dummy"),
                },
            }
            evidence_chain.append(ev_entry)

        obj_props = None
        if cand.get("archaeology_object_id"):
            obj_props = {
                "id": cand["archaeology_object_id"],
                "object_type": "pit_tomb",
                "object_number": "2호 토광묘",
            }

        return {
            "candidate": cand,
            "archaeology_object": obj_props,
            "evidence": ev_list,
            "evidence_chain": evidence_chain,
            "decisions": cand.get("decisions", []),
        }

    def get_metrics(self, project_id: str) -> dict[str, Any]:
        cands = [c for c in self.candidates.values() if c.get("project_id") == project_id]
        total = len(cands)
        accepted = rejected = modified = deferred = 0
        by_cat: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for c in cands:
            latest = c.get("latest_decision")
            outcome = latest.get("decision_status") if latest else None
            if outcome == "accepted":
                accepted += 1
            elif outcome == "rejected":
                rejected += 1
            elif outcome == "modified":
                modified += 1
            elif outcome == "deferred":
                deferred += 1
            cat = c.get("rule_category", "unknown")
            by_cat[cat] = by_cat.get(cat, 0) + 1
            st = c.get("status", "unknown")
            by_status[st] = by_status.get(st, 0) + 1

        resolved = accepted + rejected + modified + deferred
        pending = total - resolved
        accuracy_denom = accepted + rejected + modified
        accuracy = accepted / accuracy_denom if accuracy_denom > 0 else 0.0

        return {
            "project_id": project_id,
            "total_candidates": total,
            "pending_candidates": pending,
            "accepted_candidates": accepted,
            "rejected_candidates": rejected,
            "modified_candidates": modified,
            "deferred_candidates": deferred,
            "by_category": by_cat,
            "by_status": by_status,
            "by_severity": {"high": 0, "medium": total, "low": 0},
            "completion_rate": resolved / total if total > 0 else 0.0,
            "accuracy_rate": accuracy,
        }


class FakeOrchestrator:
    async def run_proofreading(
        self,
        project_id: str,
        body_version_id: str,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        **kwargs,
    ) -> OrchestratorResult:
        cand = CorrectionCandidateData(
            candidate_id="cand_orch_1",
            rule_category="numeric_value",
            change_type="modified",
            status="pending_review",
            original_text="12.5cm",
            proposed_text="12.5m",
            confidence=0.98,
        )
        return OrchestratorResult(
            project_id=project_id,
            analysis_run_id="run_test_001",
            status="completed",
            pages_parsed=15,
            objects_resolved=8,
            references_resolved=22,
            candidates=[cand],
            evidences=[],
            objects=[ArchaeologyObjectData(object_id="obj_tomb_1", site="산노리", type="pit_tomb", number="1호")],
            plates=[],
            drawings=[],
            summary={"numeric_value": {"mismatches": 1}},
            errors=[],
        )


@pytest.fixture
def api_client():
    proj_repo = FakeProjectRepository()
    rev_repo = FakeReviewRepository()
    orch = FakeOrchestrator()
    orch.calls = []
    recorder = []

    def recording_enqueuer(analysis_run_id: str) -> str:
        recorder.append(analysis_run_id)
        return f"proofreading-{analysis_run_id}"

    rev_repo.seed_candidate(
        project_id="p1",
        cand_id="cand_1",
        rule_category="numeric_value",
        status="pending_review",
        original_text="30cm",
        proposed_text="30m",
        archaeology_object_id="obj_1",
        confidence=0.92,
        evidence={
            "id": "ev_1",
            "kind": "text_claim",
            "source_sha256": "sha256_dummy_hash_1",
            "document_version_id": "v1",
            "page_id": "v1_p10",
            "physical_page_from": 10,
            "printed_page_from": 10,
            "bbox": [10.0, 20.0, 100.0, 40.0],
            "method": "rule",
            "value": {"claim": "30cm", "standard": "30m"},
            "rationale": "Unit mismatch detected",
            "confidence": 0.92,
        },
    )
    rev_repo.seed_candidate(
        project_id="p1",
        cand_id="cand_2",
        rule_category="feature_or_artifact_id",
        status="pending_review",
        original_text="1호 토광묘",
        proposed_text="2호 토광묘",
        archaeology_object_id="obj_2",
        confidence=0.88,
        evidence={
            "id": "ev_2",
            "kind": "reference",
            "source_sha256": "sha256_dummy_hash_2",
            "document_version_id": "v1",
            "page_id": "v1_p25",
            "physical_page_from": 25,
            "printed_page_from": 25,
            "bbox": [50.0, 60.0, 150.0, 80.0],
            "method": "vlm_observation",
            "value": "2호 토광묘",
            "rationale": "Plate caption mismatch",
            "confidence": 0.88,
        },
    )

    app = create_app(
        project_repository=proj_repo,
        review_repository=rev_repo,
        orchestrator=orch,
        run_enqueuer=recording_enqueuer,
    )
    app.state._enqueued = recorder
    return TestClient(app), rev_repo


# =============================================================================
# 1. POST /api/v1/projects/{project_id}/runs — strict ReviewRound contract
# =============================================================================

@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"bodyVersionId": "ver_body_01"},
        {"plateVersionId": "ver_plate_01"},
        {"versionStage": "1차"},
        {"bodyPdfPath": "/tmp/body.pdf"},
        {"reviewRoundId": "round-1", "bodyVersionId": "ver_body_01"},
        {"reviewRoundId": "round-1", "versionStage": "1차"},
    ],
)
def test_trigger_proofreading_run_rejects_missing_round_or_legacy_fields(api_client, payload):
    client, rev_repo = api_client
    resp = client.post("/api/v1/projects/p1/runs", json=payload)
    assert resp.status_code == 422
    assert resp.json()["code"] == "input_error"
    assert client.app.state._enqueued == []
    assert rev_repo.runs == {}


def test_trigger_proofreading_run_rejects_legacy_payload_before_project_lookup(api_client):
    client, _ = api_client
    resp = client.post(
        "/api/v1/projects/nonexistent/runs",
        json={"bodyVersionId": "legacy-direct-version"},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "input_error"
    assert client.app.state._enqueued == []


# =============================================================================
# 2. GET /api/v1/projects/{project_id}/candidates
# =============================================================================

def test_list_candidates_all(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/p1/candidates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["projectId"] == "p1"
    assert data["total"] == 2
    assert len(data["candidates"]) == 2


def test_list_candidates_filter_by_status(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/p1/candidates?status=pending_review")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(c["status"] == "pending_review" for c in data["candidates"])


def test_list_candidates_filter_by_rule_category(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/p1/candidates?rule_category=feature_or_artifact_id")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["candidates"][0]["id"] == "cand_2"


def test_list_candidates_filter_by_archaeology_object_id(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/p1/candidates?archaeology_object_id=obj_1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["candidates"][0]["id"] == "cand_1"


def test_list_candidates_missing_project_returns_404(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/nonexistent/candidates")
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


# =============================================================================
# 3. POST /api/v1/projects/{project_id}/candidates/{candidate_id}/decision
# =============================================================================

def test_record_accept_decision(api_client):
    client, rev_repo = api_client
    payload = {
        "decision": "accepted",
        "reviewer": "김고고",
        "rationale": "도면 실측값 대조 결과 30m가 맞음",
    }
    resp = client.post("/api/v1/projects/p1/candidates/cand_1/decision", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidateId"] == "cand_1"
    assert data["decisionStatus"] == "accepted"
    assert data["reviewer"] == "김고고"

    # Candidate generation status is untouched; the decision appends instead
    cand = rev_repo.get_candidate("cand_1")
    assert cand["status"] == "pending_review"
    assert cand["latest_decision"]["decision_status"] == "accepted"
    assert len(cand["decisions"]) == 1


def test_record_reject_decision(api_client):
    client, rev_repo = api_client
    payload = {
        "decision": "rejected",
        "reviewer": "박전문가",
        "rationale": "본문 서술이 정확함",
    }
    resp = client.post("/api/v1/projects/p1/candidates/cand_1/decision", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidateId"] == "cand_1"
    assert data["decisionStatus"] == "rejected"

    cand = rev_repo.get_candidate("cand_1")
    assert cand["status"] == "pending_review"
    assert cand["latest_decision"]["decision_status"] == "rejected"


def test_record_decision_rejects_layout_noise_as_decision_value(api_client):
    """layout_noise is a rule classification only — never an expert decision
    (anti-pattern #11); confirmed is not a decision value either (Gate F)."""
    client, _ = api_client
    for bad in ("layout_noise", "confirmed"):
        resp = client.post(
            "/api/v1/projects/p1/candidates/cand_1/decision",
            json={"decision": bad, "reviewer": "박전문가"},
        )
        assert resp.status_code == 422, f"{bad} must be rejected as a decision value"


def test_record_defer_decision(api_client):
    client, rev_repo = api_client
    resp = client.post(
        "/api/v1/projects/p1/candidates/cand_1/decision",
        json={"decision": "deferred", "reviewer": "연구원C", "rationale": "추가 자료 확인 필요"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decisionStatus"] == "deferred"
    assert rev_repo.get_candidate("cand_1")["latest_decision"]["decision_status"] == "deferred"


def test_record_modify_decision_and_audit_trail_supersedes(api_client):
    client, rev_repo = api_client
    client.post(
        "/api/v1/projects/p1/candidates/cand_1/decision",
        json={"decision": "accepted", "reviewer": "연구원A", "rationale": "1차 수용"},
    )
    first_dec_id = rev_repo.get_candidate("cand_1")["decisions"][0]["id"]

    payload = {
        "decision": "modified",
        "reviewer": "책임연구원B",
        "rationale": "실제 도면 재확인 결과 35m로 최종 수정",
        "modifiedText": "35m",
    }
    resp = client.post("/api/v1/projects/p1/candidates/cand_1/decision", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["decisionStatus"] == "modified"
    assert data["modifiedText"] == "35m"
    assert data["previousDecisionId"] == first_dec_id

    cand = rev_repo.get_candidate("cand_1")
    assert cand["proposed_text"] == "35m"
    assert len(cand["decisions"]) == 2
    assert cand["decisions"][1]["previous_decision_id"] == first_dec_id
    assert cand["latest_decision"]["decision_status"] == "modified"
    assert cand["status"] == "pending_review"


def test_record_decision_missing_candidate_returns_404(api_client):
    client, _ = api_client
    resp = client.post(
        "/api/v1/projects/p1/candidates/nonexistent_cand/decision",
        json={"decision": "accepted", "reviewer": "김고고"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


# =============================================================================
# 4. GET /api/v1/projects/{project_id}/candidates/{candidate_id}/traceability
# =============================================================================

def test_get_candidate_traceability(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/p1/candidates/cand_1/traceability")
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidateId"] == "cand_1"
    assert "evidenceChain" in data or "evidence" in data
    assert "documentVersionId" in data or "evidence" in data
    assert data["candidate"]["id"] == "cand_1"
    assert data["archaeologyObject"]["id"] == "obj_1"


def test_get_candidate_traceability_missing_candidate_returns_404(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/p1/candidates/nonexistent/traceability")
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


# =============================================================================
# 5. GET /api/v1/projects/{project_id}/metrics
# =============================================================================

def test_get_review_metrics_uses_latest_decision(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/p1/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["projectId"] == "p1"
    assert data["totalCandidates"] == 2
    assert data["pendingCandidates"] == 2
    assert data["acceptedCandidates"] == 0
    assert data["deferredCandidates"] == 0
    assert "byCategory" in data
    assert "completionRate" in data
    assert "accuracyRate" in data

    client.post(
        "/api/v1/projects/p1/candidates/cand_1/decision",
        json={"decision": "accepted", "reviewer": "김고고"},
    )
    resp = client.get("/api/v1/projects/p1/metrics")
    data = resp.json()
    assert data["acceptedCandidates"] == 1
    assert data["pendingCandidates"] == 1


def test_get_review_metrics_missing_project_returns_404(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/nonexistent/metrics")
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"