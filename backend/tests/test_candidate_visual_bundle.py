"""Unit and integration tests for candidate visual bundle Cypher query and service resolution.

Review 3 / Phase P0-D:
Validates that AssetRepository.get_candidate_visual_bundle uses sequential WITH clauses
without nested collect aggregations, and that VisualAssetService correctly bundles
provenance metadata for both text-only claims and visual-evidence candidates.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.graph.asset_repository import AssetRepository
from app.services.visual_asset_service import VisualAssetService


def _png_bytes(size: tuple[int, int] = (100, 100), rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    import io
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="PNG")
    return buf.getvalue()


class MockDriver:
    def __init__(self, query_results=None):
        self.query_results = query_results or []
        self.executed_queries = []

    def execute_query(self, query: str, **params):
        self.executed_queries.append((query, params))
        return self.query_results, None, None


# =============================================================================
# 1. AssetRepository Cypher Query Structure & Execution
# =============================================================================


def test_asset_repository_get_candidate_visual_bundle_query_structure():
    """Verify that the Cypher query uses sequential WITH clauses instead of nested collect()."""
    mock_driver = MockDriver(query_results=[])
    repo = AssetRepository(driver=mock_driver)

    repo.get_candidate_visual_bundle("cand_123")

    assert len(mock_driver.executed_queries) == 1
    query, params = mock_driver.executed_queries[0]
    assert params["candidate_id"] == "cand_123"

    # Must NOT have nested collect(DISTINCT child) inside collect(DISTINCT { ... })
    assert "[c IN collect(" not in query, "Query must not nest collect inside another collect"

    # Must use separate WITH clauses
    assert "WITH cand," in query
    assert "collect(DISTINCT properties(child)) AS child_props" in query
    assert "children: [c IN child_props WHERE c IS NOT NULL]" in query
    assert "RETURN properties(cand) AS candidate," in query


def test_asset_repository_get_candidate_visual_bundle_record_parsing():
    """Verify that record dict conversion works accurately."""
    mock_record = {
        "candidate": {"id": "cand_1", "status": "detected"},
        "evidence_chain": [
            {
                "evidence": {"id": "ev_1", "page_id": "p_1"},
                "page": {"id": "p_1", "physical_page": 5},
                "version": {"id": "v_1", "uri": "doc.pdf", "sha256": "abc"},
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

    mock_driver = MockDriver(query_results=[mock_record])
    repo = AssetRepository(driver=mock_driver)
    res = repo.get_candidate_visual_bundle("cand_1")

    assert res is not None
    assert res["candidate"]["id"] == "cand_1"
    assert len(res["evidence_chain"]) == 1
    assert res["evidence_chain"][0]["evidence"]["id"] == "ev_1"
    assert len(res["canonical_assets"]) == 1
    assert res["canonical_assets"][0]["props"]["id"] == "pl_1"
    assert res["canonical_assets"][0]["children"][0]["id"] == "pan_1"


def test_asset_repository_returns_none_when_no_driver_or_no_candidate():
    repo_no_driver = AssetRepository(driver=None)
    assert repo_no_driver.get_candidate_visual_bundle("cand_1") is None

    mock_driver = MockDriver(query_results=[])
    repo = AssetRepository(driver=mock_driver)
    assert repo.get_candidate_visual_bundle("cand_1") is None


# =============================================================================
# 2. VisualAssetService candidate bundle resolution
# =============================================================================


class StubAssetRepository:
    def __init__(self, bundle_data: dict | None):
        self.bundle_data = bundle_data

    def get_candidate_visual_bundle(self, candidate_id: str):
        return self.bundle_data


def test_visual_asset_service_returns_none_for_missing_candidate(tmp_path):
    repo = StubAssetRepository(None)
    svc = VisualAssetService(asset_repo=repo, data_root=tmp_path)
    bundle = svc.get_candidate_visual_bundle("nonexistent")
    assert bundle is None


def test_visual_asset_service_text_claim_only(tmp_path):
    """Candidate with text claim on page but no canonical visual asset (canonical is None)."""
    # Create fake body pdf render
    body_dir = tmp_path / "derived" / "body_renders" / "ver_1"
    body_dir.mkdir(parents=True, exist_ok=True)
    (body_dir / "p005.png").write_bytes(_png_bytes((1200, 1600)))

    bundle_data = {
        "candidate": {"id": "cand_text_1", "type": "typo"},
        "evidence_chain": [
            {
                "evidence": {
                    "id": "ev_1",
                    "page_id": "page_5",
                    "bbox": [10.0, 20.0, 100.0, 200.0],
                    "document_version_id": "ver_1",
                    "source_sha256": "sha_v1",
                },
                "page": {"id": "page_5", "physical_page": 5, "printed_page": 3},
                "version": {"id": "ver_1", "uri": "doc.pdf", "sha256": "sha_v1"},
            }
        ],
        "canonical_assets": [],
    }

    repo = StubAssetRepository(bundle_data)
    svc = VisualAssetService(asset_repo=repo, data_root=tmp_path)
    bundle = svc.get_candidate_visual_bundle("cand_text_1")

    assert bundle is not None
    assert bundle["candidate_id"] == "cand_text_1"
    assert bundle["canonical"] is None

    source = bundle["source"]
    assert source is not None
    assert source["asset_type"] == "page"
    assert source["region_id"] == "page_5"
    assert source["physical_page"] == 5
    assert source["printed_identifier"] == "3"
    assert source["render_width"] == 1200
    assert source["render_height"] == 1600


def test_visual_asset_service_plate_with_children_render(tmp_path):
    """Candidate depicting an ArchaeologyObject that maps to a Plate with child panels."""
    panel_file = tmp_path / "derived" / "panel_1.png"
    panel_file.parent.mkdir(parents=True, exist_ok=True)
    panel_file.write_bytes(_png_bytes((800, 600)))

    bundle_data = {
        "candidate": {"id": "cand_vis_1"},
        "evidence_chain": [],
        "canonical_assets": [
            {
                "label": "Plate",
                "props": {
                    "id": "plate_10",
                    "raw_identifier": "【도판 10】",
                    "title": "청동검",
                    "document_version_id": "ver_pl",
                    "source_sha256": "sha_pl",
                    "physical_page": 15,
                },
                "parent": None,
                "children": [
                    {
                        "id": "panel_10_1",
                        "render_uri": str(panel_file),
                        "bbox": [0.1, 0.1, 0.9, 0.9],
                    }
                ],
            }
        ],
    }

    repo = StubAssetRepository(bundle_data)
    svc = VisualAssetService(asset_repo=repo, data_root=tmp_path)
    bundle = svc.get_candidate_visual_bundle("cand_vis_1")

    assert bundle is not None
    assert bundle["source"] is None

    canonical = bundle["canonical"]
    assert canonical is not None
    assert canonical["asset_type"] == "plate"
    assert canonical["region_id"] == "plate_10"
    assert canonical["printed_identifier"] == "【도판 10】"
    assert canonical["caption"] == "청동검"
    assert canonical["render_width"] == 800
    assert canonical["render_height"] == 600


def test_visual_asset_service_drawing_region_crop(tmp_path):
    """Candidate depicting an ArchaeologyObject that maps directly to a DrawingRegion."""
    draw_file = tmp_path / "derived" / "draw_1.png"
    draw_file.parent.mkdir(parents=True, exist_ok=True)
    draw_file.write_bytes(_png_bytes((1000, 1000)))

    bundle_data = {
        "candidate": {"id": "cand_draw_1"},
        "evidence_chain": [],
        "canonical_assets": [
            {
                "label": "DrawingRegion",
                "props": {
                    "id": "dr_region_1",
                    "drawing_id": "dr_1",
                    "title": "유구 단면도",
                    "render_uri": str(draw_file),
                    "bbox": [0.2, 0.2, 0.8, 0.8],
                    "document_version_id": "ver_dr",
                    "source_sha256": "sha_dr",
                    "physical_page": 3,
                },
                "parent": {
                    "id": "dr_1",
                    "raw_identifier": "【도면 1】",
                    "document_version_id": "ver_dr",
                },
                "children": [],
            }
        ],
    }

    repo = StubAssetRepository(bundle_data)
    svc = VisualAssetService(asset_repo=repo, data_root=tmp_path)
    bundle = svc.get_candidate_visual_bundle("cand_draw_1")

    assert bundle is not None
    canonical = bundle["canonical"]
    assert canonical is not None
    assert canonical["asset_type"] == "drawing_region"
    assert canonical["region_id"] == "dr_region_1"
    assert canonical["printed_identifier"] == "【도면 1】"
    assert canonical["caption"] == "유구 단면도"
    assert canonical["content_type"] == "image/jpeg"
    assert canonical["render_width"] == 1000
    assert canonical["render_height"] == 1000


def test_visual_asset_service_handles_unresolvable_renders_gracefully(tmp_path):
    """When renders cannot be resolved, candidate bundle still builds without raising."""
    bundle_data = {
        "candidate": {"id": "cand_incomplete"},
        "evidence_chain": [
            {
                "evidence": {"id": "ev_1", "page_id": "p_1"},
                "page": {"id": "p_1", "physical_page": 20},
                "version": {"id": "v_1", "uri": "missing.pdf", "sha256": "sha_missing"},
            }
        ],
        "canonical_assets": [
            {
                "label": "Plate",
                "props": {"id": "pl_incomplete", "physical_page": 30},
                "parent": None,
                "children": [],
            }
        ],
    }

    repo = StubAssetRepository(bundle_data)
    svc = VisualAssetService(asset_repo=repo, data_root=tmp_path)
    bundle = svc.get_candidate_visual_bundle("cand_incomplete")

    assert bundle is not None
    assert bundle["source"] is not None
    assert bundle["source"]["render_width"] is None
    assert bundle["canonical"] is not None
    assert bundle["canonical"]["render_width"] is None
