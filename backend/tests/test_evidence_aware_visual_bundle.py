from app.services.strict_visual_asset_service import StrictVisualAssetService


class StubRepo:
    def __init__(self, bundle):
        self.bundle = bundle

    def get_candidate_visual_bundle(self, candidate_id, project_id):
        return self.bundle


def _body_evidence(version_id: str, page_id: str, physical_page: int, text: str):
    return {
        "evidence": {
            "id": f"ev_{version_id}",
            "kind": "text_claim",
            "document_version_id": version_id,
            "page_id": page_id,
            "value": text,
            "source_sha256": f"sha_{version_id}",
        },
        "page": {"id": page_id, "physical_page": physical_page},
        "version": {
            "id": version_id,
            "uri": f"missing/{version_id}.pdf",
            "sha256": f"sha_{version_id}",
        },
    }


def test_version_change_uses_round_body_pair_not_plate_placeholder(tmp_path):
    data = {
        "candidate": {
            "id": "cand_numeric",
            "original_text": "길이 220cm",
            "proposed_text": "길이 210cm",
        },
        "evidence_chain": [
            _body_evidence("body_v2", "page_v2", 10, "길이 220cm"),
            _body_evidence("body_v3", "page_v3", 10, "길이 210cm"),
        ],
        "round_context": {
            "previous_body_version_id": "body_v2",
            "current_body_version_id": "body_v3",
        },
        "canonical_assets": [],
    }
    result = StrictVisualAssetService(StubRepo(data), data_root=tmp_path).get_candidate_visual_bundle(
        "cand_numeric", "p1"
    )

    assert result["comparison_type"] == "version_change"
    assert result["source"]["document_version_id"] == "body_v2"
    assert result["comparison"]["document_version_id"] == "body_v3"
    assert result["canonical"] is None
    assert result["reference"] is None
    assert result["render_status"] == "missing_render"


def test_exact_plate_reference_reports_plate_mode_and_reference_metadata(tmp_path):
    data = {
        "candidate": {"id": "cand_plate", "original_text": "본문 도판 45 확인"},
        "evidence_chain": [_body_evidence("body_v3", "page_v3", 1, "본문 도판 45 확인")],
        "round_context": {
            "previous_body_version_id": "body_v2",
            "current_body_version_id": "body_v3",
        },
        "canonical_assets": [
            {
                "ref": {"id": "ref_45", "ref_type": "plate", "number": "45"},
                "label": "Plate",
                "props": {
                    "id": "plate_45",
                    "raw_identifier": "【도판 45】",
                    "physical_page": 3,
                },
                "parent": None,
                "children": [],
                "document_version": {
                    "id": "plate_v1",
                    "uri": "missing/plate.pdf",
                    "sha256": "platesha",
                },
            }
        ],
    }
    result = StrictVisualAssetService(StubRepo(data), data_root=tmp_path).get_candidate_visual_bundle(
        "cand_plate", "p1"
    )

    assert result["comparison_type"] == "plate_reference"
    assert result["reference"] == {
        "type": "plate",
        "number": "45",
        "reference_id": "ref_45",
        "target_id": "plate_45",
    }
    assert result["canonical"]["region_id"] == "plate_45"
    assert result["render_status"] == "missing_render"
    assert result["unresolved_reason"] == "render_unavailable"


def test_exact_drawing_reference_reports_drawing_mode(tmp_path):
    data = {
        "candidate": {"id": "cand_drawing", "original_text": "본문 도면 30 확인"},
        "evidence_chain": [_body_evidence("body_v3", "page_v3", 1, "본문 도면 30 확인")],
        "round_context": {
            "previous_body_version_id": "body_v2",
            "current_body_version_id": "body_v3",
        },
        "canonical_assets": [
            {
                "ref": {"id": "ref_30", "ref_type": "drawing", "number": "30"},
                "label": "Drawing",
                "props": {"id": "drawing_30", "raw_identifier": "【도면 30】", "physical_page": 4},
                "parent": None,
                "children": [],
                "document_version": {
                    "id": "drawing_v1",
                    "uri": "missing/drawing.pdf",
                    "sha256": "drawsha",
                },
            }
        ],
    }
    result = StrictVisualAssetService(StubRepo(data), data_root=tmp_path).get_candidate_visual_bundle(
        "cand_drawing", "p1"
    )

    assert result["comparison_type"] == "drawing_reference"
    assert result["reference"]["target_id"] == "drawing_30"
    assert result["render_status"] == "missing_render"


def test_plain_rule_finding_is_text_evidence_not_empty_visual(tmp_path):
    data = {
        "candidate": {"id": "cand_text", "original_text": "오탈자"},
        "evidence_chain": [_body_evidence("body_v3", "page_v3", 1, "오탈자")],
        "round_context": {
            "previous_body_version_id": None,
            "current_body_version_id": "body_v3",
        },
        "canonical_assets": [],
    }
    result = StrictVisualAssetService(StubRepo(data), data_root=tmp_path).get_candidate_visual_bundle(
        "cand_text", "p1"
    )

    assert result["comparison_type"] == "text_evidence"
    assert result["canonical"] is None
    assert result["comparison"] is None
    assert result["render_status"] == "not_applicable"
    assert result["unresolved_reason"] is None
