"""Phase P0-D tests: evidence visual asset delivery API.

Review source: docs/superpowers/reviews/2026-08-17-neo4j-frontend-mvp-code-review.md
Phase P0-D (§13), §10 Required Asset/Evidence API, §9 Real Split View,
Mandatory Test D, anti-pattern #15, Definition of Done "Frontend" +
"Photo/Plate" + "Drawing".

Covered:
1. §10 — metadata endpoints return the full contract
   (assetType / imageUrl / documentVersionId / sourceSha256 / physicalPage /
   printedIdentifier / regionId / bbox / caption / renderWidth / renderHeight)
   for a body page, plate, plate panel, drawing, and drawing region.
2. §10 — render endpoints serve actual decodable image bytes (Pillow open OK)
   with the correct content-type; body page render is on-demand from the
   version PDF and is cached under the derived dir.
3. Mandatory Test D — one candidate exposes source body page + source bbox +
   source sha256 + canonical plate/drawing + canonical visual bbox + canonical
   visual sha256 together in a single visual-bundle response.
4. Anti-pattern #15 — no visual route response contains a `/data/` or absolute
   filesystem path; render routes serve bytes, metadata routes return relative
   `imageUrl` API paths.
5. Fail-closed — a node with no render/asset returns a structured 404
   (`evidence_incomplete`), never a guessed/empty image; a missing node returns
   404 `input_error`.
6. Real Neo4j (optional): create a page/panel/region, render, assert render
   bytes decodable + provenance; scoped p0d_test_* ids with cleanup.
"""
import hashlib
import io
import os
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.graph.project_repository import ProjectNotFoundError
from app.main import create_app
from app.services.image_processor import ImageProcessor
from app.services.visual_asset_service import VisualAssetService

try:
    import pymupdf  # type: ignore
    HAS_PYMUPDF = True
except ImportError:
    try:
        import fitz as pymupdf  # type: ignore
        HAS_PYMUPDF = True
    except ImportError:
        HAS_PYMUPDF = False


def _png_bytes(size: tuple[int, int], rgb: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="PNG")
    return buf.getvalue()


def build_synthetic_body_pdf(dest_dir: Path) -> Path:
    """Create a 12-page body-style PDF with deterministic text pages."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(1, 13):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 60), f"본문 {i}쪽 테스트", fontname="korea", fontsize=12)
    pdf_path = dest_dir / "body.pdf"
    doc.save(pdf_path)
    doc.close()
    return pdf_path


class FakeProjectRepository:
    def get_project(self, project_id: str) -> dict:
        if project_id != "p1":
            raise ProjectNotFoundError(project_id)
        return {
            "project": {"id": "p1", "name": "테스트", "internal_code": None},
            "id": "p1",
            "name": "테스트",
            "internal_code": None,
            "documents": [],
            "document_versions": [],
            "analysis_runs": [],
        }


class FakeAssetRepository:
    """In-memory asset repository returning pre-shaped graph rows."""

    def __init__(self) -> None:
        self.pages: dict[str, dict] = {}
        self.plates: dict[str, dict] = {}
        self.panels: dict[str, dict] = {}
        self.drawings: dict[str, dict] = {}
        self.regions: dict[str, dict] = {}
        self.bundles: dict[str, dict] = {}

    def get_page_asset(self, page_id: str) -> dict | None:
        return self.pages.get(page_id)

    def get_plate_asset(self, plate_id: str) -> dict | None:
        return self.plates.get(plate_id)

    def get_plate_panel_asset(self, panel_id: str) -> dict | None:
        return self.panels.get(panel_id)

    def get_drawing_asset(self, drawing_id: str) -> dict | None:
        return self.drawings.get(drawing_id)

    def get_drawing_region_asset(self, region_id: str) -> dict | None:
        return self.regions.get(region_id)

    def get_candidate_visual_bundle(self, candidate_id: str) -> dict | None:
        return self.bundles.get(candidate_id)


@pytest.fixture
def visual_env(tmp_path):
    """App wired with a fake asset repository + real render files + a real body
    PDF so render endpoints return decodable bytes and page render is on-demand."""
    body_pdf = build_synthetic_body_pdf(tmp_path / "incoming" / "p1" / "sha")

    plate_render = tmp_path / "derived" / "plate_renders" / "ver_plate" / "p047.png"
    plate_render.parent.mkdir(parents=True, exist_ok=True)
    plate_render.write_bytes(_png_bytes((1191, 1684), (200, 30, 30)))

    drawing_render = tmp_path / "derived" / "drawing_renders" / "ver_draw" / "p001.png"
    drawing_render.parent.mkdir(parents=True, exist_ok=True)
    drawing_render.write_bytes(_png_bytes((1191, 1684), (30, 30, 200)))

    repo = FakeAssetRepository()
    repo.pages["ver_body_p10"] = {
        "page": {"id": "ver_body_p10", "physical_page": 10, "printed_page": 10, "header": ""},
        "version": {
            "id": "ver_body",
            "uri": "incoming/p1/sha/body.pdf",
            "sha256": "sha256_body",
            "stage": "1차",
        },
    }
    repo.plates["plate_45"] = {
        "plate": {
            "id": "plate_45",
            "number": "45",
            "physical_page": 47,
            "title": "테스트",
            "source_sha256": "sha256_plate",
            "document_version_id": "ver_plate",
            "raw_identifier": "【도판 45】",
        },
        "version": {"id": "ver_plate", "uri": "incoming/p1/sha/plate.pdf", "sha256": "sha256_plate"},
        "panels": [
            {"id": "plate_45_panel_1", "render_uri": str(plate_render), "bbox": [0.1, 0.1, 0.5, 0.5]}
        ],
    }
    repo.panels["plate_45_panel_1"] = {
        "panel": {
            "id": "plate_45_panel_1",
            "plate_id": "plate_45",
            "panel_index": 1,
            "caption": "조사 전",
            "bbox": [0.1, 0.1, 0.5, 0.5],
            "bbox_status": "segmented",
            "physical_page": 47,
            "render_uri": str(plate_render),
            "source_sha256": "sha256_plate",
        },
        "plate": {
            "id": "plate_45",
            "number": "45",
            "raw_identifier": "【도판 45】",
            "document_version_id": "ver_plate",
        },
        "version": {"id": "ver_plate", "uri": "incoming/p1/sha/plate.pdf", "sha256": "sha256_plate"},
    }
    repo.drawings["drawing_30"] = {
        "drawing": {
            "id": "drawing_30",
            "number": "30",
            "physical_page": 1,
            "title": "테스트",
            "source_sha256": "sha256_draw",
            "document_version_id": "ver_draw",
            "raw_identifier": "【도면 30】",
        },
        "version": {"id": "ver_draw", "uri": "incoming/p1/sha/draw.pdf", "sha256": "sha256_draw"},
        "regions": [
            {"id": "drawing_30_region_1", "render_uri": str(drawing_render), "bbox": [0.1, 0.1, 0.5, 0.5]}
        ],
    }
    repo.regions["drawing_30_region_1"] = {
        "region": {
            "id": "drawing_30_region_1",
            "drawing_id": "drawing_30",
            "number": "1",
            "title": "평면도",
            "bbox": [0.1, 0.1, 0.5, 0.5],
            "bbox_status": "segmented",
            "physical_page": 1,
            "render_uri": str(drawing_render),
            "source_sha256": "sha256_draw",
        },
        "drawing": {
            "id": "drawing_30",
            "number": "30",
            "raw_identifier": "【도면 30】",
            "document_version_id": "ver_draw",
        },
        "version": {"id": "ver_draw", "uri": "incoming/p1/sha/draw.pdf", "sha256": "sha256_draw"},
    }
    repo.bundles["cand_1"] = {
        "candidate": {"id": "cand_1"},
        "evidence_chain": [
            {
                "evidence": {
                    "id": "ev_1",
                    "page_id": "ver_body_p10",
                    "bbox": [59.5, 84.2, 297.5, 168.4],
                    "source_sha256": "sha256_body",
                    "document_version_id": "ver_body",
                },
                "page": {"id": "ver_body_p10", "physical_page": 10, "printed_page": 10},
                "version": {"id": "ver_body", "uri": "incoming/p1/sha/body.pdf", "sha256": "sha256_body"},
            }
        ],
        "canonical_assets": [
            {
                "label": "PlatePanel",
                "props": {
                    "id": "plate_45_panel_1",
                    "plate_id": "plate_45",
                    "caption": "조사 전",
                    "bbox": [0.1, 0.1, 0.5, 0.5],
                    "physical_page": 47,
                    "render_uri": str(plate_render),
                    "source_sha256": "sha256_plate",
                    "document_version_id": "ver_plate",
                },
                "parent": {
                    "id": "plate_45",
                    "number": "45",
                    "raw_identifier": "【도판 45】",
                    "document_version_id": "ver_plate",
                },
                "children": [],
            }
        ],
    }

    svc = VisualAssetService(asset_repo=repo, data_root=tmp_path)
    app = create_app(
        project_repository=FakeProjectRepository(),
        visual_asset_service=svc,
    )
    return TestClient(app), repo, tmp_path


def _assert_no_filesystem_path(data, url: str) -> None:
    if isinstance(data, dict):
        for value in data.values():
            _assert_no_filesystem_path(value, url)
    elif isinstance(data, list):
        for value in data:
            _assert_no_filesystem_path(value, url)
    elif isinstance(data, str):
        assert "/data/" not in data, f"{url} leaked a /data/ path: {data!r}"
        for prefix in ("/Users/", "/tmp/", "/var/", "/private/", "file://"):
            assert not data.startswith(prefix), f"{url} leaked an absolute path: {data!r}"


# =============================================================================
# 1. Metadata contract
# =============================================================================


def test_page_metadata_returns_contract_fields(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/assets/pages/ver_body_p10/metadata")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assetType"] == "page"
    assert data["imageUrl"] == "/api/v1/assets/pages/ver_body_p10/render"
    assert data["documentVersionId"] == "ver_body"
    assert data["sourceSha256"] == "sha256_body"
    assert data["physicalPage"] == 10
    assert data["printedIdentifier"] == "10"
    assert data["regionId"] == "ver_body_p10"
    assert data["renderWidth"] is not None
    assert data["renderHeight"] is not None
    assert data["contentType"] == "image/png"


def test_plate_metadata_returns_contract_fields(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/assets/plates/plate_45/metadata")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assetType"] == "plate"
    assert data["imageUrl"] == "/api/v1/assets/plates/plate_45/render"
    assert data["documentVersionId"] == "ver_plate"
    assert data["sourceSha256"] == "sha256_plate"
    assert data["physicalPage"] == 47
    assert data["printedIdentifier"] == "【도판 45】"
    assert data["renderWidth"] == 1191
    assert data["renderHeight"] == 1684


def test_plate_panel_metadata_returns_contract_fields(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/assets/plate-panels/plate_45_panel_1/metadata")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assetType"] == "plate_panel"
    assert data["imageUrl"] == "/api/v1/assets/plate-panels/plate_45_panel_1/render"
    assert data["documentVersionId"] == "ver_plate"
    assert data["sourceSha256"] == "sha256_plate"
    assert data["physicalPage"] == 47
    assert data["printedIdentifier"] == "【도판 45】"
    assert data["regionId"] == "plate_45_panel_1"
    assert data["bbox"] == [0.1, 0.1, 0.5, 0.5]
    assert data["caption"] == "조사 전"
    assert data["renderWidth"] == 1191
    assert data["renderHeight"] == 1684
    assert data["contentType"] == "image/jpeg"


def test_drawing_metadata_returns_contract_fields(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/assets/drawings/drawing_30/metadata")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assetType"] == "drawing"
    assert data["printedIdentifier"] == "【도면 30】"
    assert data["documentVersionId"] == "ver_draw"
    assert data["sourceSha256"] == "sha256_draw"
    assert data["renderWidth"] == 1191
    assert data["renderHeight"] == 1684


def test_drawing_region_metadata_returns_contract_fields(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/assets/drawing-regions/drawing_30_region_1/metadata")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assetType"] == "drawing_region"
    assert data["imageUrl"] == "/api/v1/assets/drawing-regions/drawing_30_region_1/render"
    assert data["printedIdentifier"] == "【도면 30】"
    assert data["regionId"] == "drawing_30_region_1"
    assert data["bbox"] == [0.1, 0.1, 0.5, 0.5]
    assert data["caption"] == "평면도"
    assert data["contentType"] == "image/jpeg"


# =============================================================================
# 2. Render endpoints serve real bytes
# =============================================================================


def test_page_render_returns_decodable_bytes_and_caches(visual_env):
    client, _, tmp_path = visual_env
    resp = client.get("/api/v1/assets/pages/ver_body_p10/render")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(resp.content)) as img:
        assert img.width >= 1191
        assert img.height > 1600
    cache = tmp_path / "derived" / "body_renders" / "ver_body" / "p010.png"
    assert cache.is_file(), "on-demand page render must be cached under the derived dir"
    assert cache.stat().st_size > 0
    assert ImageProcessor.is_valid_image(cache.read_bytes())


def test_plate_render_returns_page_bytes(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/assets/plates/plate_45/render")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(resp.content)) as img:
        assert img.width == 1191
        assert img.height == 1684


def test_plate_panel_render_returns_cropped_bytes(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/assets/plate-panels/plate_45_panel_1/render")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(resp.content)) as img:
        assert img.width > 0 and img.height > 0


def test_drawing_render_returns_page_bytes(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/assets/drawings/drawing_30/render")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(resp.content)) as img:
        assert img.width == 1191
        assert img.height == 1684


def test_drawing_region_render_returns_cropped_bytes(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/assets/drawing-regions/drawing_30_region_1/render")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(resp.content)) as img:
        assert img.width > 0 and img.height > 0


# =============================================================================
# 3. Mandatory Test D — provenance visual bundle
# =============================================================================


def test_visual_bundle_contains_source_and_canonical_provenance(visual_env):
    """Mandatory Test D: one candidate exposes source body page + source bbox +
    source sha256 + canonical plate/drawing + canonical visual bbox + canonical
    visual sha256 together so the frontend can render both images and highlight
    both bboxes."""
    client, _, _ = visual_env
    resp = client.get("/api/v1/projects/p1/candidates/cand_1/visual-bundle")
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidateId"] == "cand_1"

    source = data["source"]
    assert source["assetType"] == "page"
    assert source["imageUrl"].startswith("/api/v1/assets/pages/")
    assert source["documentVersionId"] == "ver_body"
    assert source["sourceSha256"] == "sha256_body"
    assert source["physicalPage"] == 10
    assert source["bbox"] is not None, "source bbox must be present (normalized)"
    assert source["renderWidth"] is not None
    assert source["renderHeight"] is not None

    canonical = data["canonical"]
    assert canonical["assetType"] == "plate_panel"
    assert canonical["imageUrl"].startswith("/api/v1/assets/plate-panels/")
    assert canonical["documentVersionId"] == "ver_plate"
    assert canonical["sourceSha256"] == "sha256_plate"
    assert canonical["bbox"] == [0.1, 0.1, 0.5, 0.5]
    assert canonical["printedIdentifier"] == "【도판 45】"
    assert canonical["caption"] == "조사 전"
    assert canonical["renderWidth"] == 1191
    assert canonical["renderHeight"] == 1684


def test_visual_bundle_missing_candidate_returns_404(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/projects/p1/candidates/nonexistent/visual-bundle")
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


# =============================================================================
# 4. Anti-pattern #15 — no filesystem paths to the browser
# =============================================================================


def test_no_route_response_contains_filesystem_path(visual_env):
    """Anti-pattern #15: no visual route returns an arbitrary server filesystem
    path. Metadata responses return relative imageUrl API paths; render routes
    serve image bytes."""
    client, _, _ = visual_env
    metadata_urls = [
        "/api/v1/assets/pages/ver_body_p10/metadata",
        "/api/v1/assets/plates/plate_45/metadata",
        "/api/v1/assets/plate-panels/plate_45_panel_1/metadata",
        "/api/v1/assets/drawings/drawing_30/metadata",
        "/api/v1/assets/drawing-regions/drawing_30_region_1/metadata",
        "/api/v1/projects/p1/candidates/cand_1/visual-bundle",
    ]
    for url in metadata_urls:
        resp = client.get(url)
        assert resp.status_code == 200, url
        _assert_no_filesystem_path(resp.json(), url)

    render_urls = [
        "/api/v1/assets/pages/ver_body_p10/render",
        "/api/v1/assets/plates/plate_45/render",
        "/api/v1/assets/plate-panels/plate_45_panel_1/render",
        "/api/v1/assets/drawings/drawing_30/render",
        "/api/v1/assets/drawing-regions/drawing_30_region_1/render",
    ]
    for url in render_urls:
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert resp.headers["content-type"].startswith("image/"), url
        assert ImageProcessor.is_valid_image(resp.content), url


# =============================================================================
# 5. Fail-closed
# =============================================================================


def test_missing_render_fails_closed_404_evidence_incomplete(visual_env):
    """A node with no render/asset returns a structured 404 (evidence_incomplete),
    never a guessed/empty image."""
    client, repo, _ = visual_env
    repo.panels["plate_99_panel_1"] = {
        "panel": {
            "id": "plate_99_panel_1",
            "plate_id": "plate_99",
            "panel_index": 1,
            "caption": "없음",
            "bbox": None,
            "bbox_status": "insufficient",
            "physical_page": 99,
            "render_uri": None,
            "source_sha256": "sha256_plate",
        },
        "plate": {"id": "plate_99", "number": "99", "raw_identifier": "【도판 99】", "document_version_id": "ver_plate"},
        "version": {"id": "ver_plate", "uri": "incoming/p1/sha/plate.pdf", "sha256": "sha256_plate"},
    }
    resp = client.get("/api/v1/assets/plate-panels/plate_99_panel_1/render")
    assert resp.status_code == 404
    assert resp.json()["code"] == "evidence_incomplete"
    assert resp.content != b"", "fail-closed must not return an empty image body"

    resp = client.get("/api/v1/assets/plate-panels/plate_99_panel_1/metadata")
    assert resp.status_code == 404
    assert resp.json()["code"] == "evidence_incomplete"


def test_missing_node_returns_404(visual_env):
    client, _, _ = visual_env
    resp = client.get("/api/v1/assets/plate-panels/nonexistent/render")
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"

    resp = client.get("/api/v1/assets/pages/nonexistent/metadata")
    assert resp.status_code == 404
    assert resp.json()["code"] == "input_error"


# =============================================================================
# 6. Real Neo4j (optional) — page/panel/region render + provenance
# =============================================================================


def test_real_neo4j_page_panel_region_render_and_provenance(tmp_path):
    """Real Neo4j (optional): create a page/panel/region, render, assert render
    bytes decodable + provenance. Scoped p0d_test_* ids with cleanup."""
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
    except Exception:
        pytest.skip("Real Neo4j unavailable (set NEO4J_PASSWORD to enable)")

    from app.graph.asset_repository import AssetRepository

    scope = f"p0d_test_{uuid.uuid4().hex[:8]}"
    version_id = f"{scope}_ver"
    page_id = f"{scope}_p10"
    plate_id = f"{scope}_plate_45"
    panel_id = f"{scope}_plate_45_panel_1"
    try:
        data_root = tmp_path
        build_synthetic_body_pdf(data_root / "incoming" / scope)
        version_uri = f"incoming/{scope}/body.pdf"
        render_file = data_root / "derived" / "plate_renders" / version_id / "p047.png"
        render_file.parent.mkdir(parents=True, exist_ok=True)
        render_file.write_bytes(_png_bytes((1191, 1684), (200, 30, 30)))

        driver.execute_query(
            "CREATE (v:DocumentVersion {id: $version_id, uri: $uri, sha256: 'sha256_body', stage: '1차'})",
            version_id=version_id,
            uri=version_uri,
        )
        driver.execute_query(
            "CREATE (p:Page {id: $page_id, physical_page: 10, printed_page: 10})",
            page_id=page_id,
        )
        driver.execute_query(
            "MATCH (v:DocumentVersion {id: $version_id}) MATCH (p:Page {id: $page_id}) "
            "MERGE (v)-[:HAS_PAGE]->(p)",
            version_id=version_id,
            page_id=page_id,
        )
        driver.execute_query(
            "CREATE (pl:Plate {id: $plate_id, number: '45', physical_page: 47, "
            "raw_identifier: '【도판 45】', document_version_id: $version_id, source_sha256: 'sha256_plate'})",
            plate_id=plate_id,
            version_id=version_id,
        )
        driver.execute_query(
            "CREATE (pan:PlatePanel {id: $panel_id, plate_id: $plate_id, panel_index: 1, "
            "caption: '조사 전', bbox: [0.1, 0.1, 0.5, 0.5], bbox_status: 'segmented', "
            "physical_page: 47, render_uri: $render_uri, source_sha256: 'sha256_plate'})",
            panel_id=panel_id,
            plate_id=plate_id,
            render_uri=str(render_file),
        )
        driver.execute_query(
            "MATCH (pl:Plate {id: $plate_id}) MATCH (pan:PlatePanel {id: $panel_id}) "
            "MERGE (pl)-[:HAS_PANEL]->(pan)",
            plate_id=plate_id,
            panel_id=panel_id,
        )

        repo = AssetRepository(driver=driver)
        svc = VisualAssetService(asset_repo=repo, data_root=data_root)

        page_render = svc.get_page_render(page_id)
        assert ImageProcessor.is_valid_image(page_render["bytes"])
        assert page_render["content_type"] == "image/png"

        page_meta = svc.get_page_metadata(page_id)
        assert page_meta["source_sha256"] == "sha256_body"
        assert page_meta["physical_page"] == 10
        assert page_meta["render_width"] is not None

        panel_render = svc.get_plate_panel_render(panel_id)
        assert ImageProcessor.is_valid_image(panel_render["bytes"])
        assert panel_render["content_type"] == "image/jpeg"

        panel_meta = svc.get_plate_panel_metadata(panel_id)
        assert panel_meta["printed_identifier"] == "【도판 45】"
        assert panel_meta["bbox"] == [0.1, 0.1, 0.5, 0.5]
        assert panel_meta["source_sha256"] == "sha256_plate"
        assert panel_meta["render_width"] == 1191
        assert panel_meta["render_height"] == 1684
    finally:
        driver.execute_query(
            "MATCH (n) WHERE n.id STARTS WITH $scope DETACH DELETE n",
            scope=scope,
        )
        driver.close()
