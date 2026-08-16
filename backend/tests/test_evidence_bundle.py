"""Task 7 tests: ObjectEvidenceBundle contract and graph-row evidence reconstruction.

The bundle is the graph-derived input contract that RuleEngine consumes (plan
§2, Task 7). Reconstructed EvidenceData must preserve document-bound provenance
(source_sha256 / document_version_id / page_id) exactly as stored, and must
never fabricate provenance or mine rationale text as source values.
"""
from typing import Any

import pytest

from app.domain.evidence_bundle import ObjectEvidenceBundle, evidence_from_row_props
from app.domain.review_models import EvidenceData


def _doc_bound_evidence(
    ev_id: str,
    text: str,
    kind: str = "text_claim",
    sha: str = "sha256_body",
    version_id: str = "ver_1",
    page_id: str = "ver_1_p1",
    **kwargs: Any,
) -> EvidenceData:
    props: dict[str, Any] = dict(
        id=ev_id,
        kind=kind,
        source_sha256=sha,
        document_version_id=version_id,
        page_id=page_id,
        value=text,
        method="graph_mention",
        confidence=1.0,
    )
    props.update(kwargs)
    return EvidenceData(**props)


def test_bundle_contract_fields_default_to_empty():
    bundle = ObjectEvidenceBundle(
        object_id="obj_6", canonical_name="1지점 청동기시대 6호 석관묘"
    )
    assert bundle.object_id == "obj_6"
    assert bundle.canonical_name == "1지점 청동기시대 6호 석관묘"
    assert bundle.text_claims == []
    assert bundle.references == []
    assert bundle.plate_claims == []
    assert bundle.drawing_claims == []
    assert bundle.visual_observations == []
    assert bundle.version_claims == []
    assert bundle.evidences == []
    assert bundle.has_graph_evidence() is False


def test_bundle_evidences_flattens_and_dedupes_by_id():
    a1 = _doc_bound_evidence("db_claim_a", "길이 275cm")
    a2 = _doc_bound_evidence("db_claim_a", "길이 275cm")
    b = _doc_bound_evidence("db_claim_b", "길이 2.45m")
    c = _doc_bound_evidence("db_target", "도판 : 45", kind="reference")
    d = _doc_bound_evidence("db_vlm", "visual", kind="vlm_observation")

    bundle = ObjectEvidenceBundle(
        object_id="obj_1",
        canonical_name="1지점 청동기시대 1호 주거지",
        text_claims=[a1, b],
        references=[c],
        drawing_claims=[a2],
        visual_observations=[d],
    )

    flat = bundle.evidences
    assert len(flat) == 4
    assert {ev.id for ev in flat} == {
        "db_claim_a",
        "db_claim_b",
        "db_target",
        "db_vlm",
    }
    assert bundle.has_graph_evidence() is True


def test_bundle_evidences_keeps_non_duplicate_same_id_rows():
    """Two rows sharing an id with different payloads keep only the first."""
    first = _doc_bound_evidence("dup_id", "길이 100cm")
    second = _doc_bound_evidence("dup_id", "길이 200cm")
    bundle = ObjectEvidenceBundle(
        object_id="obj_1",
        canonical_name="obj",
        text_claims=[first, second],
    )
    flat = bundle.evidences
    assert len(flat) == 1
    assert flat[0].value == "길이 100cm"


def test_evidence_from_row_props_preserves_document_binding_and_value_shape():
    row = {
        "id": "ev_ref_obj1_p105_b1",
        "kind": "reference",
        "source_sha256": "sha256_body_sample",
        "document_version_id": "ver_body_1",
        "page_id": "ver_body_1_p105",
        "region_id": "p105_b1",
        "bbox": [10.0, 20.0, 100.0, 30.0],
        "method": "pdf_parser",
        "analysis_run_id": "run_1",
        "value": '{"ref_type": "plate", "number": "45", "raw_text": "도판 : 45"}',
        "rationale": "Reference associated with object",
        "confidence": 1.0,
        "version_from": "1차",
        "version_to": "1차",
        "physical_page_from": 105,
        "printed_page_from": 101,
        "rule_name": "reference_evidence",
    }
    ev = evidence_from_row_props(row)
    assert ev.id == "ev_ref_obj1_p105_b1"
    assert ev.kind == "reference"
    assert ev.source_sha256 == "sha256_body_sample"
    assert ev.document_version_id == "ver_body_1"
    assert ev.page_id == "ver_body_1_p105"
    assert ev.region_id == "p105_b1"
    assert ev.bbox == (10.0, 20.0, 100.0, 30.0)
    assert ev.value == {"ref_type": "plate", "number": "45", "raw_text": "도판 : 45"}
    assert ev.rationale == "Reference associated with object"
    assert ev.version_from == "1차"
    assert ev.confidence == 1.0


def test_evidence_from_row_props_keeps_plain_string_values_untouched():
    row = {
        "id": "ev_claim_x",
        "kind": "text_claim",
        "source_sha256": "sha256_body_1",
        "document_version_id": "ver_1",
        "page_id": "ver_1_p1",
        "value": "길이 275cm",
    }
    ev = evidence_from_row_props(row)
    assert ev.value == "길이 275cm"


def test_evidence_from_row_props_raises_when_document_bound_provenance_missing():
    """Never fabricate provenance: a document-bound kind without its required
    source_sha256/document_version_id/page_id must raise (evidence invariant)."""
    row = {
        "id": "ev_bad",
        "kind": "text_claim",
        "page_id": "ver_1_p1",
        "value": "길이 275cm",
    }
    with pytest.raises(ValueError, match="source_sha256 is required"):
        evidence_from_row_props(row)

    row2 = {
        "id": "ev_bad2",
        "kind": "reference",
        "source_sha256": "sha",
        "document_version_id": "ver_1",
        "value": '{"ref_type": "plate", "number": "45"}',
    }
    with pytest.raises(ValueError, match="page_id is required"):
        evidence_from_row_props(row2)