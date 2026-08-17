"""Visual asset delivery service (review §10 / Phase P0-D).

Resolves renderable image bytes for graph nodes (Page / Plate / PlatePanel /
Drawing / DrawingRegion) and builds the metadata contract. Body pages that were
never rendered are rendered on demand from the stored DocumentVersion PDF
(PyMuPDF) and cached under the derived dir. Render routes serve bytes; metadata
routes return a relative `imageUrl` API path — never a server filesystem path
(anti-pattern #15). A node with no render/asset fails closed with
VisualAssetIncompleteError (404 / evidence_incomplete).
"""
from pathlib import Path

from PIL import Image

from app.config import DATA_ROOT
from app.services.image_processor import ImageProcessor

try:
    import pymupdf  # type: ignore
    HAS_PYMUPDF = True
except ImportError:
    try:
        import fitz as pymupdf  # type: ignore
        HAS_PYMUPDF = True
    except ImportError:
        HAS_PYMUPDF = False

PAGE_RENDER_ZOOM = 2.0
PAGE_RENDER_MIN_WIDTH = 1191.0

_ASSET_TYPE_TO_ROUTE = {
    "page": "pages",
    "plate": "plates",
    "plate_panel": "plate-panels",
    "drawing": "drawings",
    "drawing_region": "drawing-regions",
}

_LABEL_TO_ASSET_TYPE = {
    "Page": "page",
    "Plate": "plate",
    "PlatePanel": "plate_panel",
    "Drawing": "drawing",
    "DrawingRegion": "drawing_region",
}

_CROP_ASSET_TYPES = frozenset({"plate_panel", "drawing_region"})


class VisualAssetNotFoundError(RuntimeError):
    """The graph node does not exist (404 / input_error)."""


class VisualAssetIncompleteError(RuntimeError):
    """The node exists but has no renderable asset (404 / evidence_incomplete)."""


def render_page_png(pdf_path: str | Path, physical_page: int, zoom: float | None = None) -> bytes:
    """Render one physical page of a PDF at >=2x (~1191px wide) as PNG bytes."""
    if not HAS_PYMUPDF:
        return b""
    doc = pymupdf.open(str(pdf_path))
    try:
        if physical_page < 1 or physical_page > len(doc):
            return b""
        page = doc[physical_page - 1]
        if zoom is None:
            zoom = max(PAGE_RENDER_ZOOM, PAGE_RENDER_MIN_WIDTH / page.rect.width)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


class VisualAssetService:
    def __init__(
        self,
        asset_repo,
        data_root: str | Path = DATA_ROOT,
        render_dir: str | Path | None = None,
    ) -> None:
        self._asset_repo = asset_repo
        self._data_root = Path(data_root)
        self._render_dir = (
            Path(render_dir) if render_dir is not None else self._data_root / "derived" / "body_renders"
        )

    # ------------------------------------------------------------------
    # Public API: metadata + render per asset type
    # ------------------------------------------------------------------

    def get_page_metadata(self, page_id: str) -> dict:
        asset = self._require_asset(self._asset_repo.get_page_asset(page_id), page_id)
        page = asset.get("page") or {}
        version = asset.get("version") or {}
        physical_page = page.get("physical_page")
        if physical_page is None:
            raise VisualAssetIncompleteError(page_id)
        render_path = self._resolve_page_render(
            version.get("uri"), version.get("id"), physical_page
        )
        return self._build_metadata(
            "page",
            page_id,
            document_version_id=version.get("id"),
            source_sha256=version.get("sha256"),
            physical_page=physical_page,
            printed_identifier=(
                str(page.get("printed_page")) if page.get("printed_page") is not None else None
            ),
            region_id=page_id,
            render_path=render_path,
            content_type="image/png",
        )

    def get_page_render(self, page_id: str) -> dict:
        asset = self._require_asset(self._asset_repo.get_page_asset(page_id), page_id)
        page = asset.get("page") or {}
        version = asset.get("version") or {}
        physical_page = page.get("physical_page")
        if physical_page is None:
            raise VisualAssetIncompleteError(page_id)
        render_path = self._resolve_page_render(
            version.get("uri"), version.get("id"), physical_page
        )
        return {"bytes": render_path.read_bytes(), "content_type": "image/png"}

    def get_plate_metadata(self, plate_id: str) -> dict:
        asset = self._require_asset(self._asset_repo.get_plate_asset(plate_id), plate_id)
        plate = asset.get("plate") or {}
        version = asset.get("version") or {}
        render_path = self._resolve_asset_page_render(
            plate_id,
            plate.get("physical_page"),
            version,
            asset.get("panels") or [],
            "render_uri",
        )
        return self._build_metadata(
            "plate",
            plate_id,
            document_version_id=plate.get("document_version_id") or version.get("id"),
            source_sha256=plate.get("source_sha256"),
            physical_page=plate.get("physical_page"),
            printed_identifier=plate.get("raw_identifier"),
            region_id=plate_id,
            bbox=plate.get("bbox"),
            caption=plate.get("title"),
            render_path=render_path,
            content_type="image/png",
        )

    def get_plate_render(self, plate_id: str) -> dict:
        asset = self._require_asset(self._asset_repo.get_plate_asset(plate_id), plate_id)
        plate = asset.get("plate") or {}
        version = asset.get("version") or {}
        render_path = self._resolve_asset_page_render(
            plate_id,
            plate.get("physical_page"),
            version,
            asset.get("panels") or [],
            "render_uri",
        )
        return {"bytes": render_path.read_bytes(), "content_type": "image/png"}

    def get_plate_panel_metadata(self, panel_id: str) -> dict:
        asset = self._require_asset(self._asset_repo.get_plate_panel_asset(panel_id), panel_id)
        panel = asset.get("panel") or {}
        plate = asset.get("plate") or {}
        version = asset.get("version") or {}
        render_path = self._resolve_render_path(panel.get("render_uri"))
        if render_path is None or not render_path.is_file():
            raise VisualAssetIncompleteError(panel_id)
        return self._build_metadata(
            "plate_panel",
            panel_id,
            document_version_id=plate.get("document_version_id") or version.get("id"),
            source_sha256=panel.get("source_sha256"),
            physical_page=panel.get("physical_page"),
            printed_identifier=plate.get("raw_identifier"),
            region_id=panel_id,
            bbox=panel.get("bbox"),
            caption=panel.get("caption"),
            render_path=render_path,
            content_type="image/jpeg",
        )

    def get_plate_panel_render(self, panel_id: str) -> dict:
        asset = self._require_asset(self._asset_repo.get_plate_panel_asset(panel_id), panel_id)
        panel = asset.get("panel") or {}
        return self._crop_render(panel_id, panel.get("render_uri"), panel.get("bbox"))

    def get_drawing_metadata(self, drawing_id: str) -> dict:
        asset = self._require_asset(self._asset_repo.get_drawing_asset(drawing_id), drawing_id)
        drawing = asset.get("drawing") or {}
        version = asset.get("version") or {}
        render_path = self._resolve_asset_page_render(
            drawing_id,
            drawing.get("physical_page"),
            version,
            asset.get("regions") or [],
            "render_uri",
        )
        return self._build_metadata(
            "drawing",
            drawing_id,
            document_version_id=drawing.get("document_version_id") or version.get("id"),
            source_sha256=drawing.get("source_sha256"),
            physical_page=drawing.get("physical_page"),
            printed_identifier=drawing.get("raw_identifier"),
            region_id=drawing_id,
            bbox=drawing.get("bbox"),
            caption=drawing.get("title"),
            render_path=render_path,
            content_type="image/png",
        )

    def get_drawing_render(self, drawing_id: str) -> dict:
        asset = self._require_asset(self._asset_repo.get_drawing_asset(drawing_id), drawing_id)
        drawing = asset.get("drawing") or {}
        version = asset.get("version") or {}
        render_path = self._resolve_asset_page_render(
            drawing_id,
            drawing.get("physical_page"),
            version,
            asset.get("regions") or [],
            "render_uri",
        )
        return {"bytes": render_path.read_bytes(), "content_type": "image/png"}

    def get_drawing_region_metadata(self, region_id: str) -> dict:
        asset = self._require_asset(self._asset_repo.get_drawing_region_asset(region_id), region_id)
        region = asset.get("region") or {}
        drawing = asset.get("drawing") or {}
        version = asset.get("version") or {}
        render_path = self._resolve_render_path(region.get("render_uri"))
        if render_path is None or not render_path.is_file():
            raise VisualAssetIncompleteError(region_id)
        return self._build_metadata(
            "drawing_region",
            region_id,
            document_version_id=drawing.get("document_version_id") or version.get("id"),
            source_sha256=region.get("source_sha256"),
            physical_page=region.get("physical_page"),
            printed_identifier=drawing.get("raw_identifier"),
            region_id=region_id,
            bbox=region.get("bbox"),
            caption=region.get("title"),
            render_path=render_path,
            content_type="image/jpeg",
        )

    def get_drawing_region_render(self, region_id: str) -> dict:
        asset = self._require_asset(self._asset_repo.get_drawing_region_asset(region_id), region_id)
        region = asset.get("region") or {}
        return self._crop_render(region_id, region.get("render_uri"), region.get("bbox"))

    # ------------------------------------------------------------------
    # Mandatory Test D — provenance visual bundle
    # ------------------------------------------------------------------

    def get_candidate_visual_bundle(self, candidate_id: str) -> dict | None:
        data = self._asset_repo.get_candidate_visual_bundle(candidate_id)
        if not data or not data.get("candidate"):
            return None
        bundle: dict = {"candidate_id": candidate_id, "source": None, "canonical": None}
        for entry in data.get("evidence_chain") or []:
            evidence = entry.get("evidence") or {}
            page = entry.get("page") or {}
            version = entry.get("version") or {}
            page_id = evidence.get("page_id") or page.get("id")
            physical_page = page.get("physical_page")
            if not page_id or physical_page is None:
                continue
            render_path = self._resolve_page_render(
                version.get("uri"), version.get("id"), physical_page
            )
            bundle["source"] = self._build_metadata(
                "page",
                page_id,
                document_version_id=evidence.get("document_version_id") or version.get("id"),
                source_sha256=evidence.get("source_sha256") or version.get("sha256"),
                physical_page=physical_page,
                printed_identifier=(
                    str(page.get("printed_page")) if page.get("printed_page") is not None else None
                ),
                region_id=page_id,
                bbox=self._normalize_bbox(
                    evidence.get("bbox"), version.get("uri"), physical_page
                ),
                render_path=render_path,
                content_type="image/png",
            )
            break
        for entry in data.get("canonical_assets") or []:
            asset_type = _LABEL_TO_ASSET_TYPE.get(entry.get("label"))
            props = entry.get("props") or {}
            parent = entry.get("parent") or {}
            asset_id = props.get("id")
            if not asset_type or not asset_id:
                continue
            render_path = None
            content_type = "image/png"
            if asset_type in _CROP_ASSET_TYPES:
                render_path = self._resolve_render_path(props.get("render_uri"))
                content_type = "image/jpeg"
            else:
                render_path = self._resolve_asset_page_render(
                    asset_id,
                    props.get("physical_page"),
                    entry.get("version") or {},
                    entry.get("children") or [],
                    "render_uri",
                )
            bundle["canonical"] = self._build_metadata(
                asset_type,
                asset_id,
                document_version_id=props.get("document_version_id")
                or parent.get("document_version_id"),
                source_sha256=props.get("source_sha256"),
                physical_page=props.get("physical_page"),
                printed_identifier=props.get("raw_identifier") or parent.get("raw_identifier"),
                region_id=asset_id,
                bbox=props.get("bbox"),
                caption=props.get("caption") or props.get("title"),
                render_path=render_path,
                content_type=content_type,
            )
            break
        return bundle

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _require_asset(asset: dict | None, node_id: str) -> dict:
        if not asset:
            raise VisualAssetNotFoundError(node_id)
        return asset

    def _build_metadata(
        self,
        asset_type: str,
        node_id: str,
        *,
        document_version_id=None,
        source_sha256=None,
        physical_page=None,
        printed_identifier=None,
        region_id=None,
        bbox=None,
        caption=None,
        render_path: Path | None = None,
        content_type: str = "image/png",
    ) -> dict:
        render_width = render_height = None
        if render_path is not None and render_path.is_file():
            try:
                with Image.open(render_path) as img:
                    render_width, render_height = img.size
            except Exception:
                pass
        return {
            "asset_type": asset_type,
            "image_url": f"/api/v1/assets/{_ASSET_TYPE_TO_ROUTE[asset_type]}/{node_id}/render",
            "document_version_id": document_version_id,
            "source_sha256": source_sha256,
            "physical_page": physical_page,
            "printed_identifier": printed_identifier,
            "region_id": region_id,
            "bbox": list(bbox) if bbox is not None else None,
            "caption": caption,
            "render_width": render_width,
            "render_height": render_height,
            "content_type": content_type,
        }

    def _resolve_page_render(self, version_uri, version_id, physical_page: int) -> Path:
        """Render a body page on demand from the version PDF and cache it."""
        pdf_path = self._resolve_pdf_path(version_uri)
        if pdf_path is None:
            raise VisualAssetIncompleteError(f"page {physical_page} of version {version_id}")
        cache_dir = self._render_dir / str(version_id)
        cache_path = cache_dir / f"p{int(physical_page):03d}.png"
        if cache_path.is_file() and cache_path.stat().st_size > 0:
            return cache_path
        cache_dir.mkdir(parents=True, exist_ok=True)
        rendered = render_page_png(pdf_path, int(physical_page))
        if not rendered:
            raise VisualAssetIncompleteError(f"page {physical_page} of version {version_id}")
        cache_path.write_bytes(rendered)
        return cache_path

    def _resolve_asset_page_render(
        self,
        node_id: str,
        physical_page,
        version: dict,
        children: list[dict],
        render_key: str,
    ) -> Path:
        """Resolve the full-page render for a Plate/Drawing: prefer a child
        (panel/region) render_uri, else render on demand from the version PDF."""
        for child in children:
            path = self._resolve_render_path(child.get(render_key))
            if path is not None and path.is_file():
                return path
        if physical_page is None:
            raise VisualAssetIncompleteError(node_id)
        return self._resolve_page_render(version.get("uri"), version.get("id"), physical_page)

    def _crop_render(self, node_id: str, render_uri, bbox) -> dict:
        render_path = self._resolve_render_path(render_uri)
        if render_path is None or not render_path.is_file():
            raise VisualAssetIncompleteError(node_id)
        if not bbox:
            raise VisualAssetIncompleteError(node_id)
        cropped = ImageProcessor.crop_region_full(render_path.read_bytes(), bbox)
        if not cropped:
            raise VisualAssetIncompleteError(node_id)
        return {"bytes": cropped, "content_type": "image/jpeg"}

    def _resolve_render_path(self, render_uri) -> Path | None:
        if not render_uri:
            return None
        uri = render_uri
        if uri.startswith("file://"):
            uri = uri[len("file://"):]
        path = Path(uri)
        if path.is_absolute():
            return path
        return self._data_root / path

    def _resolve_pdf_path(self, version_uri) -> Path | None:
        if not version_uri:
            return None
        candidate = self._data_root / version_uri
        if candidate.is_file():
            return candidate
        if Path(version_uri).is_file():
            return Path(version_uri)
        return None

    def _normalize_bbox(self, bbox, version_uri, physical_page) -> list[float] | None:
        """Normalize an absolute PDF-point bbox to 0..1 page coordinates so the
        frontend can overlay it on the rendered page using renderWidth/Height."""
        if not bbox or len(bbox) != 4:
            return None
        pdf_path = self._resolve_pdf_path(version_uri)
        if pdf_path is None or not HAS_PYMUPDF:
            return list(bbox)
        try:
            doc = pymupdf.open(str(pdf_path))
            try:
                if physical_page < 1 or physical_page > len(doc):
                    return list(bbox)
                page = doc[physical_page - 1]
                width, height = page.rect.width, page.rect.height
                if width <= 0 or height <= 0:
                    return list(bbox)
                return [
                    float(bbox[0]) / width,
                    float(bbox[1]) / height,
                    float(bbox[2]) / width,
                    float(bbox[3]) / height,
                ]
            finally:
                doc.close()
        except Exception:
            return list(bbox)
