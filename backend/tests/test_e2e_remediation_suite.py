"""End-to-End Remediation Integration Suite.

Validates the full set of remediation capabilities across:
- Review 1: Multi-Round Review Lifecycle, Precedes Relationship & Version Reuse
- Review 2: Project-Scoped Graph Identity, Evidence Version Isolation, Morphology Guards, Candidate Budget & Status Invariants
- Review 3: Non-Nested Cypher Aggregation, Provenance Visual Bundles & Render Resilience
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    PlateData,
    PlatePanelData,
)
from app.domain.document_structure import ParsedPage, TextBlockData
from app.domain.models import Document, DocumentVersion, Project
from app.domain.review_models import CorrectionCandidateData, EvidenceData
from app.domain.review_round import ReviewRound
from app.graph.asset_repository import AssetRepository
from app.graph.canonical_repository import CanonicalRepository
from app.graph.project_repository import (
    ProjectNotFoundError,
    ProjectRepository,
    ReviewRoundNotFoundError,
)
from app.graph.schema import CONSTRAINTS
from app.main import create_app
from app.services.drawing_parser import DrawingIndex
from app.services.object_resolver import ObjectResolver
from app.services.plate_parser import PlateIndex
from app.services.proofreading_orchestrator import ProofreadingOrchestrator
from app.services.rule_engine import RuleEngine, prioritize_and_cap_candidates
from app.services.visual_asset_service import VisualAssetService


# =============================================================================
# Helper Utilities & Fake Drivers
# =============================================================================


def _make_png_bytes(
    size: tuple[int, int] = (120, 120),
    rgb: tuple[int, int, int] = (100, 150, 200),
) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="PNG")
    return buf.getvalue()


class FakeNeo4jRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class FakeNeo4jDriver:
    def __init__(
        self,
        responses: list[list[dict[str, Any]]] | None = None,
        records_by_query_marker: list[tuple[str, list[dict[str, Any]]]] | None = None,
    ):
        self.queries: list[dict[str, Any]] = []
        self._responses = responses or []
        self._response_idx = 0
        self._records_map = records_by_query_marker or []

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})

        # Match by query marker if provided
        if self._records_map:
            for marker, records in self._records_map:
                if marker in query:
                    return [FakeNeo4jRecord(r) for r in records], None, None
            return [], None, None

        # Otherwise consume sequential responses
        if self._response_idx < len(self._responses):
            records = [FakeNeo4jRecord(r) for r in self._responses[self._response_idx]]
            self._response_idx += 1
            return records, None, None
        return [], None, None


class FakeProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[str, Project] = {
            "proj_e2e": Project(id="proj_e2e", name="산노리 유적", internal_code="NONSAN-E2E")
        }
        self.documents: dict[str, list[Document]] = {"proj_e2e": []}
        self.versions: dict[str, list[DocumentVersion]] = {"proj_e2e": []}
        self.rounds: dict[str, list[ReviewRound]] = {"proj_e2e": []}

    def get_project(self, project_id: str) -> dict[str, Any]:
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

    def create_review_round(
        self,
        project_id: str,
        body_version_id: str | None = None,
        plate_version_id: str | None = None,
        drawing_version_id: str | None = None,
        notes: str | None = None,
    ) -> ReviewRound:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        rounds = self.rounds.setdefault(project_id, [])
        next_seq = len(rounds) + 1
        round_obj = ReviewRound(
            id=f"round_{project_id}_{next_seq}",
            project_id=project_id,
            sequence=next_seq,
            status="reviewing",
            body_version_id=body_version_id,
            plate_version_id=plate_version_id,
            drawing_version_id=drawing_version_id,
            created_at="2026-08-17T15:00:00Z",
            approved_at=None,
            notes=notes,
        )
        rounds.append(round_obj)
        return round_obj

    def list_review_rounds(self, project_id: str) -> list[ReviewRound]:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        return list(self.rounds.get(project_id, []))

    def get_review_round(
        self, project_id: str, round_id: str
    ) -> ReviewRound | None:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        for r in self.rounds.get(project_id, []):
            if r.id == round_id:
                return r
        return None

    def approve_review_round(
        self, project_id: str, round_id: str
    ) -> ReviewRound:
        if project_id not in self.projects:
            raise ProjectNotFoundError(project_id)
        rounds = self.rounds.get(project_id, [])
        for i, r in enumerate(rounds):
            if r.id == round_id:
                approved = ReviewRound(
                    id=r.id,
                    project_id=r.project_id,
                    sequence=r.sequence,
                    status="approved",
                    body_version_id=r.body_version_id,
                    plate_version_id=r.plate_version_id,
                    drawing_version_id=r.drawing_version_id,
                    created_at=r.created_at,
                    approved_at="2026-08-17T15:30:00Z",
                    notes=r.notes,
                )
                rounds[i] = approved
                return approved
        raise ReviewRoundNotFoundError(
            f"Review round {round_id} not found in project {project_id}"
        )


# =============================================================================
# Section 1: Review 1 E2E Multi-Round Lifecycle & Asset Reuse Tests
# =============================================================================


def test_review_1_multi_round_lifecycle_graph_queries():
    """Verify Round 1 creation -> approval -> Round 2 creation reusing assets.

    Verifies that the graph layer generates correct PRECEDES relationships,
    proper sequence numbers, and version links.
    """
    labels = [label for _, label in CONSTRAINTS]
    assert "ReviewRound" in labels, "Schema constraint for ReviewRound must exist"

    # 1. Create Round 1
    driver_r1 = FakeNeo4jDriver(
        responses=[
            [
                {
                    "id": "round_1",
                    "project_id": "proj_1",
                    "sequence": 1,
                    "status": "reviewing",
                    "notes": "1차 검수 시작",
                    "created_at": "2026-08-17T15:00:00Z",
                    "approved_at": None,
                    "body_version_id": "ver_body_1",
                    "plate_version_id": "ver_plate_1",
                    "drawing_version_id": "ver_drawing_1",
                }
            ]
        ]
    )
    repo_r1 = ProjectRepository(driver=driver_r1, database="test_db")
    r1 = repo_r1.create_review_round(
        project_id="proj_1",
        body_version_id="ver_body_1",
        plate_version_id="ver_plate_1",
        drawing_version_id="ver_drawing_1",
        notes="1차 검수 시작",
    )

    assert r1.sequence == 1
    assert r1.status == "reviewing"
    assert r1.body_version_id == "ver_body_1"
    assert r1.plate_version_id == "ver_plate_1"
    assert r1.drawing_version_id == "ver_drawing_1"

    query_r1 = driver_r1.queries[0]["query"]
    assert "HAS_REVIEW_ROUND" in query_r1
    assert "USES_BODY_VERSION" in query_r1
    assert "USES_PLATE_VERSION" in query_r1
    assert "USES_DRAWING_VERSION" in query_r1
    assert "PRECEDES" in query_r1

    # 2. Approve Round 1
    driver_app = FakeNeo4jDriver(
        responses=[
            [
                {
                    "id": "round_1",
                    "project_id": "proj_1",
                    "sequence": 1,
                    "status": "approved",
                    "notes": "1차 검수 시작",
                    "created_at": "2026-08-17T15:00:00Z",
                    "approved_at": "2026-08-17T15:30:00Z",
                    "body_version_id": "ver_body_1",
                    "plate_version_id": "ver_plate_1",
                    "drawing_version_id": "ver_drawing_1",
                }
            ]
        ]
    )
    repo_app = ProjectRepository(driver=driver_app, database="test_db")
    r1_approved = repo_app.approve_review_round(project_id="proj_1", round_id="round_1")
    assert r1_approved.status == "approved"
    assert r1_approved.approved_at == "2026-08-17T15:30:00Z"

    # 3. Create Round 2 (reuse plate_version_id and drawing_version_id from Round 1, update body_version_id)
    driver_r2 = FakeNeo4jDriver(
        responses=[
            [
                {
                    "id": "round_2",
                    "project_id": "proj_1",
                    "sequence": 2,
                    "status": "reviewing",
                    "notes": "2차 검수 (도판/도면 v1 재사용)",
                    "created_at": "2026-08-17T16:00:00Z",
                    "approved_at": None,
                    "body_version_id": "ver_body_2",
                    "plate_version_id": "ver_plate_1",
                    "drawing_version_id": "ver_drawing_1",
                }
            ]
        ]
    )
    repo_r2 = ProjectRepository(driver=driver_r2, database="test_db")
    r2 = repo_r2.create_review_round(
        project_id="proj_1",
        body_version_id="ver_body_2",
        plate_version_id="ver_plate_1",
        drawing_version_id="ver_drawing_1",
        notes="2차 검수 (도판/도면 v1 재사용)",
    )

    assert r2.sequence == 2
    assert r2.body_version_id == "ver_body_2"
    assert r2.plate_version_id == "ver_plate_1"
    assert r2.drawing_version_id == "ver_drawing_1"

    kwargs_r2 = driver_r2.queries[0]["kwargs"]
    assert kwargs_r2["body_version_id"] == "ver_body_2"
    assert kwargs_r2["plate_version_id"] == "ver_plate_1"
    assert kwargs_r2["drawing_version_id"] == "ver_drawing_1"


def test_review_1_api_multi_round_e2e_journey():
    """Verify complete API round progression: create r1 -> approve r1 -> create r2 -> list."""
    repo = FakeProjectRepository()
    app = create_app(project_repository=repo)
    client = TestClient(app)

    # 1. Create Round 1
    res1 = client.post(
        "/api/v1/projects/proj_e2e/rounds",
        json={
            "bodyVersionId": "ver_b1",
            "plateVersionId": "ver_p1",
            "drawingVersionId": "ver_d1",
            "notes": "Initial Round 1",
        },
    )
    assert res1.status_code == 201
    r1_data = res1.json()
    assert r1_data["sequence"] == 1
    assert r1_data["status"] == "reviewing"
    assert r1_data["bodyVersionId"] == "ver_b1"
    assert r1_data["plateVersionId"] == "ver_p1"
    round_1_id = r1_data["id"]

    # 2. Approve Round 1
    res_app = client.post(f"/api/v1/projects/proj_e2e/rounds/{round_1_id}/approve")
    assert res_app.status_code == 200
    assert res_app.json()["status"] == "approved"
    assert res_app.json()["approvedAt"] is not None

    # 3. Create Round 2 reusing plates & drawings
    res2 = client.post(
        "/api/v1/projects/proj_e2e/rounds",
        json={
            "bodyVersionId": "ver_b2",
            "plateVersionId": "ver_p1",
            "drawingVersionId": "ver_d1",
            "notes": "Round 2 with updated body text",
        },
    )
    assert res2.status_code == 201
    r2_data = res2.json()
    assert r2_data["sequence"] == 2
    assert r2_data["status"] == "reviewing"
    assert r2_data["bodyVersionId"] == "ver_b2"
    assert r2_data["plateVersionId"] == "ver_p1"

    # 4. List rounds and check sequence order
    list_res = client.get("/api/v1/projects/proj_e2e/rounds")
    assert list_res.status_code == 200
    rounds = list_res.json()["items"]
    assert len(rounds) == 2
    assert rounds[0]["sequence"] == 1
    assert rounds[0]["status"] == "approved"
    assert rounds[1]["sequence"] == 2
    assert rounds[1]["status"] == "reviewing"


# =============================================================================
# Section 2: Review 2 Graph Identity, Evidence Isolation & Guards
# =============================================================================


def test_review_2_archaeology_object_project_scoping_identity():
    """Verify ArchaeologyObject ID generation and mention resolution are project-scoped."""
    resolver = ObjectResolver()
    site = "논산 산노리 산17-1번지"
    canonical_name = "1지점 청동기시대 6호 석관묘"

    # Same site + name in two different projects produce distinct IDs
    id_proj_1 = resolver.generate_object_id("proj_alpha", site, canonical_name)
    id_proj_2 = resolver.generate_object_id("proj_beta", site, canonical_name)
    assert id_proj_1 != id_proj_2
    assert id_proj_1.startswith("obj_")
    assert id_proj_2.startswith("obj_")

    # Mention resolution sets object_data.project_id
    blocks = [
        TextBlockData(
            block_id="b101",
            text="1지점 청동기시대 6호 석관묘 완형이 확인됨.",
            normalized_text="1지점 청동기시대 6호 석관묘 완형이 확인됨.",
            order=1,
        )
    ]
    resolved_alpha = resolver.resolve_mentions(blocks, project_id="proj_alpha", site=site)
    resolved_beta = resolver.resolve_mentions(blocks, project_id="proj_beta", site=site)

    assert len(resolved_alpha) == 1
    assert len(resolved_beta) == 1
    assert resolved_alpha[0].object_data.project_id == "proj_alpha"
    assert resolved_beta[0].object_data.project_id == "proj_beta"
    assert resolved_alpha[0].object_data.object_id == id_proj_1
    assert resolved_beta[0].object_data.object_id == id_proj_2


def test_review_2_canonical_repo_evidence_bundle_version_isolation():
    """Verify CanonicalRepository.get_object_evidence_bundle strictly isolates evidence to version IDs."""
    identity_records = [
        {"obj": {"id": "obj_scoped_1", "canonical_name": "1지점 청동기시대 6호 석관묘", "projectId": "proj_1"}}
    ]
    text_claims_records = [
        {
            "source": {"id": "b1", "text": "v1 토광묘 기술", "source_sha256": "sha_v1"},
            "page": {"id": "v1_p1", "physical_page": 1, "printed_page": 1},
            "version": {"id": "ver_v1", "sha256": "sha_v1", "stage": "1차"},
        },
        {
            "source": {"id": "b2", "text": "v2 석곽묘 오염 기술", "source_sha256": "sha_v2"},
            "page": {"id": "v2_p1", "physical_page": 1, "printed_page": 1},
            "version": {"id": "ver_v2", "sha256": "sha_v2", "stage": "2차"},
        },
    ]
    ref_records = [
        {
            "source": {"id": "b1"},
            "ref": {"id": "ref_pl_1", "ref_type": "plate", "number": "1", "raw_text": "도판 1", "physical_page": 1},
            "page": {"id": "v1_p1", "physical_page": 1},
            "version": {"id": "ver_v1", "sha256": "sha_v1", "stage": "1차"},
        }
    ]
    visual_records = [
        {
            "asset_label": "Plate",
            "asset": {"id": "pl_1", "number": "1", "title": "도판 1", "document_version_id": "ver_v1", "physical_page": 5},
            "ref": {"id": "ref_pl_1"},
            "page": {"id": "v1_p5"},
            "version": {"id": "ver_v1", "sha256": "sha_v1", "stage": "1차"},
        }
    ]

    driver = FakeNeo4jDriver(
        records_by_query_marker=[
            ("RETURN properties(obj) AS obj", identity_records),
            ("-[:REFERENCES]->(ref:Reference)", ref_records),
            ("-[:MENTIONS]->(obj:ArchaeologyObject", text_claims_records),
            ("-[:DEPICTS]->(obj:ArchaeologyObject", visual_records),
            ("CorrectionCandidate", []),
        ]
    )
    repo = CanonicalRepository(driver=driver, database="test_db")

    bundle = repo.get_object_evidence_bundle(
        object_id="obj_scoped_1",
        analysis_run_id="run_e2e_001",
        document_version_ids=["ver_v1"],
    )

    assert bundle is not None
    assert bundle.object_id == "obj_scoped_1"
    # Verify version filtering applied to returned domain records
    assert len(bundle.text_claims) == 1
    assert bundle.text_claims[0].document_version_id == "ver_v1"
    assert bundle.text_claims[0].analysis_run_id == "run_e2e_001"
    assert len(bundle.references) == 1
    assert bundle.references[0].document_version_id == "ver_v1"
    assert len(bundle.plate_claims) == 1
    assert bundle.plate_claims[0].document_version_id == "ver_v1"


def test_review_2_rule_engine_morphology_false_positive_suppression():
    """Verify morphology vocabulary guards prevent false positives between distinct features."""
    engine = RuleEngine()

    # 1. 토광묘 entity with nearby 수혈 context mention -> no false conflict
    obj_togwang = ArchaeologyObjectData(
        object_id="obj_togwang_1",
        site="1지점",
        type="토광묘",
        number="1호",
        canonical_name="1지점 1호 토광묘",
    )
    ev_context = EvidenceData(
        id="ev_t1",
        value="1호 토광묘는 구릉 상부에 위치하며 주변에 수혈 2기가 분포한다.",
        document_version_id="ver_1",
        page_id="p1",
        source_sha256="s1",
        kind="text_claim",
    )
    cands_togwang = engine.check_object_consistency(
        archaeology_object=obj_togwang,
        evidences=[ev_context],
    )
    type_conflicts = [c for c in cands_togwang if c.rule_category == "feature_or_artifact_id"]
    assert len(type_conflicts) == 0

    # 2. 주거지 vs 수혈주거지 compatible terms -> no conflict
    obj_dwelling = ArchaeologyObjectData(
        object_id="obj_dw_1",
        site="1지점",
        type="수혈주거지",
        number="1호",
        canonical_name="1지점 1호 수혈주거지",
    )
    ev_dw1 = EvidenceData(
        id="ev_dw1",
        value="1호 수혈주거지 바닥면 정리 상태 양호.",
        document_version_id="ver_1",
        page_id="p2",
        source_sha256="s1",
        kind="text_claim",
    )
    ev_dw2 = EvidenceData(
        id="ev_dw2",
        value="1호 주거지 내부에서 노지가 노출됨.",
        document_version_id="ver_1",
        page_id="p3",
        source_sha256="s1",
        kind="text_claim",
    )
    cands_dwelling = engine.check_object_consistency(
        archaeology_object=obj_dwelling,
        evidences=[ev_dw1, ev_dw2],
    )
    assert len([c for c in cands_dwelling if c.rule_category == "feature_or_artifact_id"]) == 0

    # 3. Direct contradiction on same entity (석관묘 vs 석곽묘) -> must detect
    obj_cist = ArchaeologyObjectData(
        object_id="obj_cist_6",
        site="1지점",
        type="석관묘",
        number="6호",
        canonical_name="1지점 6호 석관묘",
    )
    ev_cist1 = EvidenceData(
        id="ev_c1",
        value="6호 석관묘는 주축이 동서방향이다.",
        document_version_id="ver_1",
        page_id="p4",
        source_sha256="s1",
        kind="text_claim",
    )
    ev_cist2 = EvidenceData(
        id="ev_c2",
        value="6호 석곽묘는 주축이 남북방향이다.",
        document_version_id="ver_1",
        page_id="p5",
        source_sha256="s1",
        kind="text_claim",
    )
    cands_cist = engine.check_object_consistency(
        archaeology_object=obj_cist,
        evidences=[ev_cist1, ev_cist2],
    )
    cist_conflicts = [c for c in cands_cist if c.rule_category == "feature_or_artifact_id"]
    assert len(cist_conflicts) >= 1
    assert "석곽묘" in (cist_conflicts[0].proposed_text or "") or "석곽묘" in (cist_conflicts[0].original_text or "")


@pytest.mark.anyio
async def test_review_2_candidate_budget_and_pending_review_status_invariant():
    """Verify ProofreadingOrchestrator enforces candidate budget <= 10 and status == 'pending_review'."""
    # 1. Budget Prioritization
    pool = [
        CorrectionCandidateData(
            candidate_id=f"cand_low_{i}",
            rule_category="annotation_resolution",
            confidence=0.99,
            severity="low",
            status="pending_review",
        )
        for i in range(5)
    ] + [
        CorrectionCandidateData(
            candidate_id=f"cand_high_{i}",
            rule_category="numeric_value",
            confidence=0.90 + (i * 0.01),
            severity="high",
            status="pending_review",
        )
        for i in range(5)
    ] + [
        CorrectionCandidateData(
            candidate_id=f"cand_crit_{i}",
            rule_category="feature_or_artifact_id",
            confidence=0.95,
            severity="critical",
            status="pending_review",
        )
        for i in range(3)
    ]
    # Total 13 candidates: 3 crit, 5 high, 5 low
    capped = prioritize_and_cap_candidates(pool, max_candidates=10)
    assert len(capped) == 10
    # Must preserve all critical (3) and all high (5), with remaining 2 low
    assert len([c for c in capped if c.severity == "critical"]) == 3
    assert len([c for c in capped if c.severity == "high"]) == 5
    assert len([c for c in capped if c.severity == "low"]) == 2

    # 2. Orchestrator Run with budget & status verification
    orchestrator = ProofreadingOrchestrator(allow_degraded_mode=True, max_candidates=10)
    page = ParsedPage(
        physical_page=1,
        printed_page=1,
        header="",
        raw_text="",
        normalized_text="",
        text_blocks=[
            TextBlockData(
                block_id=f"b_{i}",
                text=f"{i}호 토광묘 길이 {100 + i}cm (도면 : , 도판 : )",
                normalized_text=f"{i}호 토광묘 길이 {100 + i}cm (도면 : , 도판 : )",
                order=i,
            )
            for i in range(1, 15)
        ],
    )

    res = await orchestrator.run_proofreading(
        project_id="proj_budget_test",
        body_version_id="ver_body_budget",
        body_pages=[page],
        enable_vlm=False,
        enable_ai_review=False,
        max_candidates=10,
    )

    assert len(res.candidates) <= 10
    assert res.summary["total_candidates"] <= 10

    # Invariant: Every candidate must strictly have status == "pending_review"
    for cand in res.candidates:
        assert cand.status == "pending_review", f"Candidate {cand.candidate_id} status is not pending_review"


# =============================================================================
# Section 3: Review 3 Visual Bundles, Cypher Aggregation & Error Resilience
# =============================================================================


def test_review_3_candidate_visual_bundle_cypher_aggregation():
    """Verify AssetRepository.get_candidate_visual_bundle uses sequential WITH without nested collect()."""
    mock_driver = FakeNeo4jDriver(
        responses=[
            [
                {
                    "candidate": {"id": "cand_e2e_1", "status": "pending_review"},
                    "evidence_chain": [
                        {
                            "evidence": {"id": "ev_1", "page_id": "p_1"},
                            "page": {"id": "p_1", "physical_page": 3},
                            "version": {"id": "ver_1", "uri": "doc.pdf", "sha256": "sha1"},
                        }
                    ],
                    "canonical_assets": [
                        {
                            "label": "Plate",
                            "props": {"id": "pl_1", "raw_identifier": "【도판 1】"},
                            "parent": None,
                            "children": [{"id": "pan_1", "render_uri": "pan_1.png"}],
                        }
                    ],
                }
            ]
        ]
    )
    repo = AssetRepository(driver=mock_driver)
    bundle = repo.get_candidate_visual_bundle("cand_e2e_1")

    assert bundle is not None
    assert bundle["candidate"]["id"] == "cand_e2e_1"
    assert len(bundle["evidence_chain"]) == 1
    assert len(bundle["canonical_assets"]) == 1

    # Check Cypher structure
    cypher = mock_driver.queries[0]["query"]
    assert "[c IN collect(" not in cypher, "Must avoid nested collect() aggregation"
    assert "WITH cand," in cypher
    assert "collect(DISTINCT properties(child)) AS child_props" in cypher


def test_review_3_visual_asset_service_provenance_and_resilience(tmp_path: Path):
    """Verify VisualAssetService builds full provenance bundles and handles missing renders gracefully."""
    # 1. Setup sample render files
    body_dir = tmp_path / "derived" / "body_renders" / "ver_1"
    body_dir.mkdir(parents=True, exist_ok=True)
    (body_dir / "p003.png").write_bytes(_make_png_bytes((1200, 1600)))

    panel_file = tmp_path / "derived" / "panel_1.png"
    panel_file.write_bytes(_make_png_bytes((800, 600)))

    bundle_data_valid = {
        "candidate": {"id": "cand_vis_e2e"},
        "evidence_chain": [
            {
                "evidence": {
                    "id": "ev_text_1",
                    "page_id": "p_3",
                    "bbox": [10.0, 10.0, 100.0, 100.0],
                    "document_version_id": "ver_1",
                    "source_sha256": "sha_v1",
                },
                "page": {"id": "p_3", "physical_page": 3, "printed_page": 1},
                "version": {"id": "ver_1", "uri": "doc.pdf", "sha256": "sha_v1"},
            }
        ],
        "canonical_assets": [
            {
                "label": "Plate",
                "props": {
                    "id": "pl_1",
                    "raw_identifier": "【도판 1】",
                    "title": "청동검",
                    "document_version_id": "ver_pl",
                    "source_sha256": "sha_pl",
                    "physical_page": 10,
                },
                "parent": None,
                "children": [
                    {
                        "id": "pan_1",
                        "render_uri": str(panel_file),
                        "bbox": [0.1, 0.1, 0.9, 0.9],
                    }
                ],
            }
        ],
    }

    mock_repo = MagicMock()
    mock_repo.get_candidate_visual_bundle.return_value = bundle_data_valid
    svc = VisualAssetService(asset_repo=mock_repo, data_root=tmp_path)

    bundle = svc.get_candidate_visual_bundle("cand_vis_e2e")
    assert bundle is not None
    assert bundle["candidate_id"] == "cand_vis_e2e"

    # Source provenance
    assert bundle["source"] is not None
    assert bundle["source"]["physical_page"] == 3
    assert bundle["source"]["render_width"] == 1200
    assert bundle["source"]["render_height"] == 1600

    # Canonical visual asset provenance
    assert bundle["canonical"] is not None
    assert bundle["canonical"]["asset_type"] == "plate"
    assert bundle["canonical"]["printed_identifier"] == "【도판 1】"
    assert bundle["canonical"]["render_width"] == 800
    assert bundle["canonical"]["render_height"] == 600

    # 2. Resilience test: missing renders must not throw unhandled exception
    bundle_data_missing = {
        "candidate": {"id": "cand_missing_renders"},
        "evidence_chain": [
            {
                "evidence": {"id": "ev_m1", "page_id": "p_99"},
                "page": {"id": "p_99", "physical_page": 99},
                "version": {"id": "ver_missing", "uri": "missing.pdf", "sha256": "sha_m"},
            }
        ],
        "canonical_assets": [
            {
                "label": "Plate",
                "props": {"id": "pl_missing", "physical_page": 999},
                "parent": None,
                "children": [],
            }
        ],
    }
    mock_repo.get_candidate_visual_bundle.return_value = bundle_data_missing
    bundle_resilient = svc.get_candidate_visual_bundle("cand_missing_renders")

    assert bundle_resilient is not None
    assert bundle_resilient["source"] is not None
    assert bundle_resilient["source"]["render_width"] is None
    assert bundle_resilient["canonical"] is not None
    assert bundle_resilient["canonical"]["render_width"] is None
