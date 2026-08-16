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

        # Determine previous decision ID if not explicitly provided
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
        }
        self.decisions.append(decision_record)
        cand["decisions"].append(decision_record)

        # Update candidate status according to verdict
        if decision_status in ("accept", "accepted", "confirmed"):
            cand["status"] = "confirmed"
        elif decision_status in ("reject", "rejected", "layout_noise"):
            cand["status"] = "layout_noise"
        elif decision_status in ("modify", "modified"):
            cand["status"] = "confirmed"
            if modified_text is not None:
                cand["proposed_text"] = modified_text

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
        pending = sum(1 for c in cands if c.get("status") in ("pending_review", "unresolved"))
        confirmed = sum(1 for c in cands if c.get("status") == "confirmed")
        rejected = sum(1 for c in cands if c.get("status") == "layout_noise")
        modified = sum(
            1 for c in cands if any(d.get("decision_status") in ("modify", "modified") for d in c.get("decisions", []))
        )

        by_cat: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for c in cands:
            cat = c.get("rule_category", "unknown")
            by_cat[cat] = by_cat.get(cat, 0) + 1
            st = c.get("status", "unknown")
            by_status[st] = by_status.get(st, 0) + 1

        resolved = confirmed + rejected + modified
        completion = resolved / total if total > 0 else 0.0
        accuracy = confirmed / resolved if resolved > 0 else 0.0

        return {
            "project_id": project_id,
            "total_candidates": total,
            "pending_candidates": pending,
            "accepted_candidates": confirmed,
            "rejected_candidates": rejected,
            "modified_candidates": modified,
            "by_category": by_cat,
            "by_status": by_status,
            "by_severity": {"high": 0, "medium": total, "low": 0},
            "completion_rate": completion,
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

    # Seed sample candidates
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
        status="confirmed",
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
    )
    return TestClient(app), rev_repo


# =============================================================================
# 1. POST /api/v1/projects/{project_id}/runs
# =============================================================================

def test_trigger_proofreading_run_success(api_client):
    client, _ = api_client
    payload = {
        "bodyVersionId": "ver_body_01",
        "plateVersionId": "ver_plate_01",
        "enableVlm": True,
        "enableAiReview": True,
        "versionStage": "1차",
    }
    resp = client.post("/api/v1/projects/p1/runs", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["runId"] == "run_test_001"
    assert data["projectId"] == "p1"
    assert data["status"] == "completed"
    assert data["pagesParsed"] == 15
    assert data["objectsResolved"] == 8
    assert data["referencesResolved"] == 22
    assert data["candidatesCount"] == 1


def test_trigger_proofreading_run_missing_project_returns_404(api_client):
    client, _ = api_client
    resp = client.post("/api/v1/projects/nonexistent/runs", json={"bodyVersionId": "v1"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


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
    assert data["total"] == 1
    assert data["candidates"][0]["id"] == "cand_1"
    assert data["candidates"][0]["status"] == "pending_review"


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
        "decision": "accept",
        "reviewer": "김고고",
        "rationale": "도면 실측값 대조 결과 30m가 맞음",
    }
    resp = client.post("/api/v1/projects/p1/candidates/cand_1/decision", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidateId"] == "cand_1"
    assert data["decisionStatus"] in ("accept", "accepted", "confirmed")
    assert data["reviewer"] == "김고고"

    # Verify candidate status updated
    cand = rev_repo.get_candidate("cand_1")
    assert cand["status"] == "confirmed"
    assert len(cand["decisions"]) == 1


def test_record_reject_decision(api_client):
    client, rev_repo = api_client
    payload = {
        "decision": "reject",
        "reviewer": "박전문가",
        "rationale": "본문 서술이 정확함, 노이즈 판정",
    }
    resp = client.post("/api/v1/projects/p1/candidates/cand_1/decision", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidateId"] == "cand_1"
    assert data["decisionStatus"] in ("reject", "rejected", "layout_noise")

    cand = rev_repo.get_candidate("cand_1")
    assert cand["status"] == "layout_noise"


def test_record_modify_decision_and_audit_trail_supersedes(api_client):
    client, rev_repo = api_client
    # First decision: accept
    client.post(
        "/api/v1/projects/p1/candidates/cand_1/decision",
        json={"decision": "accept", "reviewer": "연구원A", "rationale": "1차 수용"},
    )
    first_dec_id = rev_repo.get_candidate("cand_1")["decisions"][0]["id"]

    # Second decision: modify (overrides first decision)
    payload = {
        "decision": "modify",
        "reviewer": "책임연구원B",
        "rationale": "실제 도면 재확인 결과 35m로 최종 수정",
        "modifiedText": "35m",
    }
    resp = client.post("/api/v1/projects/p1/candidates/cand_1/decision", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["decisionStatus"] in ("modify", "modified", "confirmed")
    assert data["modifiedText"] == "35m"
    assert data["previousDecisionId"] == first_dec_id

    cand = rev_repo.get_candidate("cand_1")
    assert cand["proposed_text"] == "35m"
    assert len(cand["decisions"]) == 2
    assert cand["decisions"][1]["previous_decision_id"] == first_dec_id


def test_record_decision_missing_candidate_returns_404(api_client):
    client, _ = api_client
    resp = client.post(
        "/api/v1/projects/p1/candidates/nonexistent_cand/decision",
        json={"decision": "accept", "reviewer": "김고고"},
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

def test_get_review_metrics(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/p1/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["projectId"] == "p1"
    assert data["totalCandidates"] == 2
    assert data["pendingCandidates"] == 1
    assert data["acceptedCandidates"] == 1
    assert "byCategory" in data
    assert "completionRate" in data
    assert "accuracyRate" in data


def test_get_review_metrics_missing_project_returns_404(api_client):
    client, _ = api_client
    resp = client.get("/api/v1/projects/nonexistent/metrics")
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"
