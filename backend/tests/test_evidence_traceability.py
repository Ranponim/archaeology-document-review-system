from typing import Any
import pytest

from app.domain.review_models import (
    DOCUMENT_BOUND_KINDS,
    CorrectionCandidate,
    CorrectionCandidateData,
    Evidence,
    EvidenceData,
)
from app.graph.review_repository import ReviewRepository


class FakeNeo4jRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class FakeNeo4jDriver:
    def __init__(self, records_to_return: list[dict[str, Any]] | None = None):
        self.queries: list[dict[str, Any]] = []
        self.records_to_return = [FakeNeo4jRecord(r) for r in (records_to_return or [])]

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        return self.records_to_return, None, None


# -----------------------------------------------------------------------------
# 1. Evidence Schema & Validation Tests
# -----------------------------------------------------------------------------

def test_evidence_schema_valid_document_evidence():
    ev = Evidence(
        id="ev_001",
        kind="text_claim",
        source_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        document_version_id="ver_sannori_1cha",
        page_id="ver_sannori_1cha_p105",
        region_id="reg_1",
        bbox=(10.0, 20.0, 150.0, 80.0),
        method="vlm_observation",
        analysis_run_id="run_001",
        value={"claim": "2호 토광묘", "observed": "1지점 2호 토광묘"},
        rationale="Discrepancy detected in feature heading",
        confidence=0.95,
    )

    assert ev.id == "ev_001"
    assert ev.kind == "text_claim"
    assert ev.source_sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert ev.document_version_id == "ver_sannori_1cha"
    assert ev.page_id == "ver_sannori_1cha_p105"
    assert ev.bbox == (10.0, 20.0, 150.0, 80.0)
    assert ev.method == "vlm_observation"
    assert ev.confidence == 0.95
    assert ev.value == {"claim": "2호 토광묘", "observed": "1지점 2호 토광묘"}


@pytest.mark.parametrize("kind", list(DOCUMENT_BOUND_KINDS))
def test_evidence_validation_fails_when_source_sha256_missing(kind: str):
    with pytest.raises(ValueError, match="source_sha256 is required"):
        Evidence(
            id="ev_invalid_1",
            kind=kind,
            source_sha256="",
            document_version_id="ver_1",
            page_id="ver_1_p10",
            method="rule",
            value="sample text",
        )


@pytest.mark.parametrize("kind", list(DOCUMENT_BOUND_KINDS))
def test_evidence_validation_fails_when_document_version_id_missing(kind: str):
    with pytest.raises(ValueError, match="document_version_id is required"):
        Evidence(
            id="ev_invalid_2",
            kind=kind,
            source_sha256="sha256_dummy_hash",
            document_version_id="",
            page_id="ver_1_p10",
            method="rule",
            value="sample text",
        )


@pytest.mark.parametrize("kind", list(DOCUMENT_BOUND_KINDS))
def test_evidence_validation_fails_when_page_id_missing(kind: str):
    with pytest.raises(ValueError, match="page_id is required"):
        Evidence(
            id="ev_invalid_3",
            kind=kind,
            source_sha256="sha256_dummy_hash",
            document_version_id="ver_1",
            page_id="",
            method="rule",
            value="sample text",
        )


def test_evidence_validation_invalid_confidence():
    with pytest.raises(ValueError, match="confidence"):
        Evidence(
            id="ev_conf_low",
            kind="text_claim",
            source_sha256="sha256_dummy_hash",
            document_version_id="ver_1",
            page_id="ver_1_p10",
            confidence=-0.1,
        )

    with pytest.raises(ValueError, match="confidence"):
        Evidence(
            id="ev_conf_high",
            kind="text_claim",
            source_sha256="sha256_dummy_hash",
            document_version_id="ver_1",
            page_id="ver_1_p10",
            confidence=1.5,
        )


def test_evidence_legacy_or_non_document_bound_kind_without_document_fields():
    # Legacy initialization or kind=None should remain supported without error
    legacy_ev = EvidenceData(
        version_from="1차",
        version_to="2차",
        physical_page_from=105,
        physical_page_to=111,
        printed_page_from=101,
        printed_page_to=102,
        rule_name="figure_plate_table_photo_ref",
        rationale="Filled blank drawing reference",
    )
    assert legacy_ev.version_from == "1차"
    assert legacy_ev.physical_page_from == 105


# -----------------------------------------------------------------------------
# 2. CorrectionCandidate Integrity Tests
# -----------------------------------------------------------------------------

def test_candidate_defaults_to_pending_review():
    cand = CorrectionCandidate(
        candidate_id="cand_default_status",
        rule_category="figure_plate_table_photo_ref",
    )
    assert cand.status == "pending_review"


def test_candidate_preserves_explicit_status_and_links_archaeology_object():
    ev = Evidence(
        id="ev_cand_1",
        kind="reference",
        source_sha256="sha_abc123",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        method="rule",
        value="도면 : 57",
    )
    cand = CorrectionCandidate(
        candidate_id="cand_explicit",
        rule_category="feature_or_artifact_id",
        change_type="modified",
        status="manual_review",
        original_text="도면 : ",
        proposed_text="도면 : 57",
        evidence=ev,
        archaeology_object_id="obj_site1_pit_2",
        confidence=0.88,
    )
    assert cand.candidate_id == "cand_explicit"
    assert cand.status == "manual_review"
    assert cand.archaeology_object_id == "obj_site1_pit_2"
    assert cand.evidence == ev
    assert cand.confidence == 0.88


# -----------------------------------------------------------------------------
# 3. Full Traceability Traversal Tests
# -----------------------------------------------------------------------------

def test_save_candidates_builds_provenance_and_archaeology_links():
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="arch_test")

    ev1 = Evidence(
        id="ev_link_1",
        kind="reference",
        source_sha256="hash_ver1",
        document_version_id="ver_1",
        page_id="ver_1_p105",
        bbox=(10.0, 20.0, 100.0, 30.0),
        method="rule_matcher",
        analysis_run_id="run_999",
        value="도판 : 45",
        rationale="Missing plate reference resolved",
        confidence=0.92,
    )

    cand = CorrectionCandidate(
        candidate_id="cand_link_1",
        rule_category="figure_plate_table_photo_ref",
        change_type="modified",
        status="pending_review",
        original_text="도판 : ",
        proposed_text="도판 : 45",
        evidence=ev1,
        archaeology_object_id="obj_cist_6",
    )

    repo.save_candidates(
        project_id="proj_sannori",
        candidates=[cand],
        analysis_run_id="run_999",
    )

    assert len(driver.queries) >= 1
    cypher_queries = " ".join(q["query"] for q in driver.queries)

    # Check key relationships in Cypher
    assert "CorrectionCandidate" in cypher_queries
    assert "[:SUPPORTED_BY]->" in cypher_queries
    assert "[:EXTRACTED_FROM]->" in cypher_queries or "Page" in cypher_queries
    assert "[:FROM_VERSION]->" in cypher_queries or "DocumentVersion" in cypher_queries
    assert "[:ABOUT]->" in cypher_queries or "ArchaeologyObject" in cypher_queries


def test_save_evidences_batch():
    driver = FakeNeo4jDriver()
    repo = ReviewRepository(driver=driver, database="arch_test")

    evidences = [
        Evidence(
            id="ev_batch_1",
            kind="vlm_observation",
            source_sha256="hash_v1",
            document_version_id="ver_1",
            page_id="ver_1_p10",
            bbox=(5.0, 10.0, 80.0, 40.0),
            method="vlm_ocr",
            value="출토유물",
            confidence=0.98,
        ),
        Evidence(
            id="ev_batch_2",
            kind="plate_caption",
            source_sha256="hash_v2",
            document_version_id="ver_2",
            page_id="ver_2_p15",
            bbox=(12.0, 18.0, 120.0, 50.0),
            method="caption_parser",
            value="도판 15",
            confidence=1.0,
        ),
    ]

    repo.save_evidences(evidences)

    assert len(driver.queries) == 1
    q = driver.queries[0]
    assert "MERGE (ev:Evidence {id: e.id})" in q["query"]
    assert "[:EXTRACTED_FROM]->" in q["query"]
    assert "[:FROM_VERSION]->" in q["query"]
    assert len(q["kwargs"]["evidences"]) == 2
    assert q["kwargs"]["evidences"][0]["id"] == "ev_batch_1"
    assert q["kwargs"]["evidences"][0]["kind"] == "vlm_observation"
    assert q["kwargs"]["evidences"][0]["source_sha256"] == "hash_v1"
    assert q["kwargs"]["evidences"][0]["bbox"] == [5.0, 10.0, 80.0, 40.0]


def test_get_candidate_traceability_traversal():
    fake_record = {
        "candidate_props": {
            "id": "cand_trace_1",
            "rule_category": "figure_plate_table_photo_ref",
            "change_type": "modified",
            "status": "pending_review",
            "original_text": "도면 : ",
            "proposed_text": "도면 : 57",
            "confidence": 0.95,
        },
        "object_props": {
            "id": "obj_site1_cist_6",
            "canonical_name": "1지점 청동기시대 6호 석관묘",
            "site": "1지점",
            "period": "청동기시대",
        },
        "evidence_chain": [
            {
                "evidence": {
                    "id": "ev_trace_1",
                    "kind": "reference",
                    "source_sha256": "sha256_ver1_full",
                    "document_version_id": "ver_1",
                    "page_id": "ver_1_p105",
                    "bbox": [15.0, 25.0, 110.0, 35.0],
                    "method": "reference_aligner",
                    "value": "도면 : 57",
                    "rationale": "Matched drawing 57 caption on page 111",
                    "confidence": 0.95,
                },
                "page": {
                    "id": "ver_1_p105",
                    "physical_page": 105,
                    "printed_page": 101,
                    "header": "백제문화유산연구원 | 101",
                },
                "document_version": {
                    "id": "ver_1",
                    "sha256": "sha256_ver1_full",
                    "stage": "1차",
                },
            }
        ],
        "decisions": [
            {
                "id": "dec_1",
                "decision_status": "accepted",
                "note": "Verified by researcher",
                "reviewer": "archaeologist_kim",
            }
        ],
    }

    driver = FakeNeo4jDriver(records_to_return=[fake_record])
    repo = ReviewRepository(driver=driver, database="arch_test")

    trace = repo.get_candidate_traceability(candidate_id="cand_trace_1")

    assert len(driver.queries) == 1
    cypher = driver.queries[0]["query"]
    assert "MATCH (cand:CorrectionCandidate {id: $candidate_id})" in cypher
    assert "[:SUPPORTED_BY]->" in cypher
    assert "[:EXTRACTED_FROM]->" in cypher
    assert "[:FROM_VERSION]->" in cypher

    assert trace["candidate"]["id"] == "cand_trace_1"
    assert trace["candidate"]["status"] == "pending_review"
    assert trace["archaeology_object"]["id"] == "obj_site1_cist_6"
    assert trace["archaeology_object"]["canonical_name"] == "1지점 청동기시대 6호 석관묘"

    assert len(trace["evidence"]) == 1
    ev_entry = trace["evidence"][0]
    assert ev_entry["id"] == "ev_trace_1"
    assert ev_entry["kind"] == "reference"
    assert ev_entry["source_sha256"] == "sha256_ver1_full"
    assert ev_entry["document_version_id"] == "ver_1"
    assert ev_entry["page_id"] == "ver_1_p105"
    assert ev_entry["bbox"] == [15.0, 25.0, 110.0, 35.0]
    assert ev_entry["page"]["physical_page"] == 105
    assert ev_entry["document_version"]["stage"] == "1차"
    assert len(trace["decisions"]) == 1
    assert trace["decisions"][0]["reviewer"] == "archaeologist_kim"
