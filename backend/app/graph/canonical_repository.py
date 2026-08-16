import re
from dataclasses import dataclass
from typing import Any
from neo4j import Driver

from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    DrawingRegionData,
    PlateData,
    PlatePanelData,
    ReferenceData,
)
from app.domain.document_structure import make_reference_id


@dataclass(frozen=True, slots=True)
class DepictsLink:
    asset_label: str
    asset_id: str
    object_id: str


def _normalize_identifier(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _object_strong_identifiers(obj: ArchaeologyObjectData) -> list[str]:
    """High-confidence identifiers: canonical name and 지점+유구/유물 combination."""
    ids: list[str] = []
    canonical = _normalize_identifier(obj.canonical_name)
    if canonical:
        ids.append(canonical)
    point = _normalize_identifier(obj.point)
    number = _normalize_identifier(obj.number)
    type_ = _normalize_identifier(obj.type)
    if point and number and type_:
        ids.append(f"{point}{number}{type_}")
    return ids


def _object_weak_identifier(obj: ArchaeologyObjectData) -> str:
    number = _normalize_identifier(obj.number)
    type_ = _normalize_identifier(obj.type)
    if number and type_:
        return f"{number}{type_}"
    return ""


def compute_depicts_links(
    plates: list[PlateData] | None = None,
    panels: list[PlatePanelData] | None = None,
    drawings: list[DrawingData] | None = None,
    regions: list[DrawingRegionData] | None = None,
    objects: list[ArchaeologyObjectData] | None = None,
) -> tuple[list[DepictsLink], list[tuple[str, str]]]:
    """Deterministically match visual assets to ArchaeologyObjects.

    Returns (links, ambiguous_assets): links are (label, asset_id, object_id)
    triples; ambiguous_assets are (label, asset_id) pairs that matched more
    than one object and must remain in semantic review. Assets whose text
    merely contains a number never match.
    """
    objects = objects or []
    if not objects:
        return [], []

    assets: list[tuple[str, str, str]] = []
    for p in plates or []:
        assets.append(("Plate", p.plate_id, _normalize_identifier(p.title)))
        for pan in p.panels:
            assets.append(("PlatePanel", pan.panel_id, _normalize_identifier(pan.caption)))
    for pan in panels or []:
        assets.append(("PlatePanel", pan.panel_id, _normalize_identifier(pan.caption)))
    for d in drawings or []:
        assets.append(("Drawing", d.drawing_id, _normalize_identifier(d.title)))
        for reg in d.regions:
            assets.append(("DrawingRegion", reg.region_id, _normalize_identifier(reg.title)))
    for reg in regions or []:
        assets.append(("DrawingRegion", reg.region_id, _normalize_identifier(reg.title)))

    links: list[DepictsLink] = []
    ambiguous: list[tuple[str, str]] = []

    for label, asset_id, asset_text in assets:
        if not asset_text:
            continue
        strong_candidates = [
            o.object_id
            for o in objects
            if any(i and i in asset_text for i in _object_strong_identifiers(o))
        ]
        if len(strong_candidates) == 1:
            links.append(DepictsLink(label, asset_id, strong_candidates[0]))
            continue
        if len(strong_candidates) > 1:
            ambiguous.append((label, asset_id))
            continue
        weak_candidates = [
            o.object_id
            for o in objects
            if (weak := _object_weak_identifier(o)) and weak in asset_text
        ]
        if len(weak_candidates) == 1:
            links.append(DepictsLink(label, asset_id, weak_candidates[0]))
        elif len(weak_candidates) > 1:
            ambiguous.append((label, asset_id))

    return links, ambiguous


class CanonicalRepository:
    ALLOWED_TARGET_LABELS = {
        "Plate",
        "Drawing",
        "PlatePanel",
        "DrawingRegion",
        "ArchaeologyObject",
        "OriginalAsset",
    }

    def __init__(self, driver: Driver | None, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    def _query_config(self) -> dict[str, Any]:
        return {"database_": self._database} if self._database is not None else {}

    def _reference_id(self, ref: ReferenceData) -> str:
        if hasattr(ref, "id") and getattr(ref, "id", None):
            return getattr(ref, "id")
        if ref.source_block_id:
            return make_reference_id(ref.source_block_id, str(ref.ref_type), ref.number)
        clean_num = (
            ref.number.strip()
            .replace(" ", "_")
            .replace("·", "_")
            .replace("ㆍ", "_")
            .replace("~", "_")
        )
        return f"ref_{ref.ref_type}_{clean_num}"

    def _reference_to_param(self, ref: ReferenceData) -> dict[str, Any]:
        return {
            "id": self._reference_id(ref),
            "ref_type": ref.ref_type,
            "number": ref.number,
            "source_block_id": ref.source_block_id,
            "raw_text": ref.raw_text,
            "source_sha256": ref.source_sha256,
            "bbox": list(ref.bbox) if ref.bbox is not None else None,
            "physical_page": ref.physical_page,
        }

    def _panel_to_param(self, panel: PlatePanelData) -> dict[str, Any]:
        return {
            "id": panel.panel_id,
            "plate_id": panel.plate_id,
            "panel_index": panel.panel_index,
            "caption": panel.caption,
            "bbox": list(panel.bbox) if panel.bbox is not None else None,
            "physical_page": panel.physical_page,
            "render_uri": panel.render_uri,
            "source_sha256": panel.source_sha256,
        }

    def _plate_to_param(self, plate: PlateData) -> dict[str, Any]:
        return {
            "id": plate.plate_id,
            "number": plate.number,
            "physical_page": plate.physical_page,
            "title": plate.title,
            "bbox": list(plate.bbox) if plate.bbox is not None else None,
            "source_sha256": plate.source_sha256,
            "document_version_id": plate.document_version_id,
            "raw_identifier": plate.raw_identifier,
            "source_kind": plate.source_kind,
        }

    def _region_to_param(self, region: DrawingRegionData) -> dict[str, Any]:
        return {
            "id": region.region_id,
            "drawing_id": region.drawing_id,
            "number": region.number,
            "title": region.title,
            "bbox": list(region.bbox) if region.bbox is not None else None,
            "physical_page": region.physical_page,
            "render_uri": region.render_uri,
            "source_sha256": region.source_sha256,
        }

    def _drawing_to_param(self, drawing: DrawingData) -> dict[str, Any]:
        return {
            "id": drawing.drawing_id,
            "number": drawing.number,
            "physical_page": drawing.physical_page,
            "title": drawing.title,
            "bbox": list(drawing.bbox) if drawing.bbox is not None else None,
            "source_sha256": drawing.source_sha256,
            "document_version_id": drawing.document_version_id,
            "raw_identifier": drawing.raw_identifier,
            "source_kind": drawing.source_kind,
        }

    def _archaeology_object_to_param(
        self, obj: ArchaeologyObjectData
    ) -> dict[str, Any]:
        return {
            "id": obj.object_id,
            "site": obj.site,
            "point": obj.point,
            "period": obj.period,
            "type": obj.type,
            "number": obj.number,
            "canonical_name": obj.canonical_name,
            "source_block_ids": obj.source_block_ids,
            "source_sha256": obj.source_sha256,
        }

    def save_references(self, references: list[ReferenceData]) -> None:
        if self._driver is None or not references:
            return

        ref_params = [self._reference_to_param(r) for r in references]
        cypher = """
        UNWIND $references AS r
        MERGE (ref:Reference {id: r.id})
        SET ref.ref_type = r.ref_type,
            ref.number = r.number,
            ref.raw_text = r.raw_text,
            ref.source_block_id = r.source_block_id,
            ref.source_sha256 = r.source_sha256,
            ref.bbox = r.bbox,
            ref.physical_page = r.physical_page
        WITH ref, r
        WHERE r.source_block_id IS NOT NULL
        OPTIONAL MATCH (b:TextBlock {id: r.source_block_id})
        OPTIONAL MATCH (c:Caption {id: r.source_block_id})
        FOREACH (_ IN CASE WHEN b IS NOT NULL THEN [1] ELSE [] END |
            MERGE (b)-[:REFERENCES]->(ref)
        )
        FOREACH (_ IN CASE WHEN c IS NOT NULL THEN [1] ELSE [] END |
            MERGE (c)-[:REFERENCES]->(ref)
        )
        """
        self._driver.execute_query(
            cypher,
            references=ref_params,
            **self._query_config(),
        )

    def save_plates(
        self,
        plates: list[PlateData],
        panels: list[PlatePanelData] | None = None,
    ) -> None:
        if self._driver is None or not plates:
            return

        plate_params = [self._plate_to_param(p) for p in plates]
        all_panels: list[PlatePanelData] = []
        for p in plates:
            if p.panels:
                all_panels.extend(p.panels)
        if panels:
            all_panels.extend(panels)

        plate_cypher = """
        UNWIND $plates AS p
        MERGE (plate:Plate {id: p.id})
        SET plate.number = p.number,
            plate.physical_page = p.physical_page,
            plate.title = p.title,
            plate.bbox = p.bbox,
            plate.source_sha256 = p.source_sha256,
            plate.document_version_id = p.document_version_id,
            plate.raw_identifier = p.raw_identifier,
            plate.source_kind = p.source_kind
        WITH plate, p
        WHERE p.document_version_id IS NOT NULL
        OPTIONAL MATCH (v:DocumentVersion {id: p.document_version_id})
        FOREACH (_ IN CASE WHEN v IS NOT NULL THEN [1] ELSE [] END |
            MERGE (v)-[:HAS_PLATE]->(plate)
        )
        """
        self._driver.execute_query(
            plate_cypher,
            plates=plate_params,
            **self._query_config(),
        )

        if all_panels:
            panel_params = [self._panel_to_param(pan) for pan in all_panels]
            panel_cypher = """
            UNWIND $panels AS pan
            MERGE (panel:PlatePanel {id: pan.id})
            SET panel.plate_id = pan.plate_id,
                panel.panel_index = pan.panel_index,
                panel.caption = pan.caption,
                panel.bbox = pan.bbox,
                panel.physical_page = pan.physical_page,
                panel.render_uri = pan.render_uri,
                panel.source_sha256 = pan.source_sha256
            WITH panel, pan
            MATCH (plate:Plate {id: pan.plate_id})
            MERGE (plate)-[:HAS_PANEL]->(panel)
            """
            self._driver.execute_query(
                panel_cypher,
                panels=panel_params,
                **self._query_config(),
            )

    def save_drawings(
        self,
        drawings: list[DrawingData],
        regions: list[DrawingRegionData] | None = None,
    ) -> None:
        if self._driver is None or not drawings:
            return

        drawing_params = [self._drawing_to_param(d) for d in drawings]
        all_regions: list[DrawingRegionData] = []
        for d in drawings:
            if d.regions:
                all_regions.extend(d.regions)
        if regions:
            all_regions.extend(regions)

        drawing_cypher = """
        UNWIND $drawings AS d
        MERGE (drawing:Drawing {id: d.id})
        SET drawing.number = d.number,
            drawing.physical_page = d.physical_page,
            drawing.title = d.title,
            drawing.bbox = d.bbox,
            drawing.source_sha256 = d.source_sha256,
            drawing.document_version_id = d.document_version_id,
            drawing.raw_identifier = d.raw_identifier,
            drawing.source_kind = d.source_kind
        WITH drawing, d
        WHERE d.document_version_id IS NOT NULL
        OPTIONAL MATCH (v:DocumentVersion {id: d.document_version_id})
        FOREACH (_ IN CASE WHEN v IS NOT NULL THEN [1] ELSE [] END |
            MERGE (v)-[:HAS_DRAWING]->(drawing)
        )
        """
        self._driver.execute_query(
            drawing_cypher,
            drawings=drawing_params,
            **self._query_config(),
        )

        if all_regions:
            region_params = [self._region_to_param(reg) for reg in all_regions]
            region_cypher = """
            UNWIND $regions AS reg
            MERGE (region:DrawingRegion {id: reg.id})
            SET region.drawing_id = reg.drawing_id,
                region.number = reg.number,
                region.title = reg.title,
                region.bbox = reg.bbox,
                region.physical_page = reg.physical_page,
                region.render_uri = reg.render_uri,
                region.source_sha256 = reg.source_sha256
            WITH region, reg
            MATCH (drawing:Drawing {id: reg.drawing_id})
            MERGE (drawing)-[:HAS_REGION]->(region)
            """
            self._driver.execute_query(
                region_cypher,
                regions=region_params,
                **self._query_config(),
            )

    def link_reference_to_target(
        self, reference_id: str, target_label: str, target_id: str
    ) -> None:
        if self._driver is None:
            return

        if target_label not in self.ALLOWED_TARGET_LABELS:
            raise ValueError(f"Invalid target label: {target_label}")

        cypher = f"""
        MATCH (ref:Reference {{id: $reference_id}})
        MATCH (target:{target_label} {{id: $target_id}})
        MERGE (ref)-[:RESOLVES_TO]->(target)
        """
        self._driver.execute_query(
            cypher,
            reference_id=reference_id,
            target_id=target_id,
            **self._query_config(),
        )

    def save_archaeology_objects(
        self, objects: list[ArchaeologyObjectData]
    ) -> None:
        if self._driver is None or not objects:
            return

        obj_params = [self._archaeology_object_to_param(o) for o in objects]
        cypher = """
        UNWIND $objects AS o
        MERGE (obj:ArchaeologyObject {id: o.id})
        SET obj.site = o.site,
            obj.point = o.point,
            obj.period = o.period,
            obj.type = o.type,
            obj.number = o.number,
            obj.canonical_name = o.canonical_name,
            obj.source_sha256 = o.source_sha256,
            obj.source_block_ids = o.source_block_ids
        WITH obj, o
        UNWIND o.source_block_ids AS block_id
        OPTIONAL MATCH (b:TextBlock {id: block_id})
        OPTIONAL MATCH (c:Caption {id: block_id})
        FOREACH (_ IN CASE WHEN b IS NOT NULL THEN [1] ELSE [] END |
            MERGE (b)-[:MENTIONS]->(obj)
        )
        FOREACH (_ IN CASE WHEN c IS NOT NULL THEN [1] ELSE [] END |
            MERGE (c)-[:MENTIONS]->(obj)
        )
        """
        self._driver.execute_query(
            cypher,
            objects=obj_params,
            **self._query_config(),
        )

    def link_visual_assets_to_objects(
        self,
        plates: list[PlateData] | None = None,
        panels: list[PlatePanelData] | None = None,
        drawings: list[DrawingData] | None = None,
        regions: list[DrawingRegionData] | None = None,
        objects: list[ArchaeologyObjectData] | None = None,
    ) -> None:
        """MERGE (asset)-[:DEPICTS]->(obj) for deterministic asset/object matches.

        Assets and objects must already be persisted (save_plates /
        save_drawings / save_archaeology_objects run earlier in the pipeline).
        Ambiguous assets are flagged depicts_status='semantic_review' and get
        no edge.
        """
        if self._driver is None:
            return

        links, ambiguous = compute_depicts_links(
            plates=plates,
            panels=panels,
            drawings=drawings,
            regions=regions,
            objects=objects,
        )
        if not links and not ambiguous:
            return

        for label in ("Plate", "PlatePanel", "Drawing", "DrawingRegion"):
            label_links = [l for l in links if l.asset_label == label]
            if label_links:
                self._merge_depicts(label, label_links)
            label_ambiguous = [(a, i) for (a, i) in ambiguous if a == label]
            if label_ambiguous:
                self._mark_depicts_ambiguous(label, label_ambiguous)

    def _merge_depicts(self, label: str, links: list[DepictsLink]) -> None:
        if label not in self.ALLOWED_TARGET_LABELS:
            raise ValueError(f"Invalid target label: {label}")
        params = [{"asset_id": l.asset_id, "object_id": l.object_id} for l in links]
        cypher = f"""
        UNWIND $links AS l
        MATCH (asset:{label} {{id: l.asset_id}})
        MATCH (obj:ArchaeologyObject {{id: l.object_id}})
        MERGE (asset)-[:DEPICTS]->(obj)
        SET asset.depicts_status = 'linked'
        """
        self._driver.execute_query(cypher, links=params, **self._query_config())

    def _mark_depicts_ambiguous(self, label: str, assets: list[tuple[str, str]]) -> None:
        if label not in self.ALLOWED_TARGET_LABELS:
            raise ValueError(f"Invalid target label: {label}")
        params = [{"asset_id": asset_id} for _, asset_id in assets]
        cypher = f"""
        UNWIND $assets AS a
        MATCH (asset:{label} {{id: a.asset_id}})
        SET asset.depicts_status = 'semantic_review'
        """
        self._driver.execute_query(cypher, assets=params, **self._query_config())

    def get_canonical_evidence_path(self, reference_id: str) -> dict[str, Any]:
        if self._driver is None:
            return {}

        cypher = """
        MATCH (ref:Reference {id: $reference_id})
        OPTIONAL MATCH (source)-[:REFERENCES]->(ref)
        OPTIONAL MATCH (page:Page)-[:HAS_BLOCK|HAS_CAPTION]->(source)
        OPTIONAL MATCH (ref)-[:RESOLVES_TO]->(target)
        OPTIONAL MATCH (target)-[:HAS_PANEL]->(panel:PlatePanel)
        OPTIONAL MATCH (target)-[:HAS_REGION]->(region:DrawingRegion)
        OPTIONAL MATCH (target)-[:DEPICTS|ABOUT]-(target_obj:ArchaeologyObject)
        OPTIONAL MATCH (source)-[:MENTIONS]->(source_obj:ArchaeologyObject)
        RETURN properties(ref) AS ref_props,
               head(labels(target)) AS target_label,
               properties(target) AS target_props,
               properties(source) AS source_props,
               properties(page) AS page_props,
               [p IN collect(DISTINCT panel) WHERE p IS NOT NULL | properties(p)] AS panels,
               [r IN collect(DISTINCT region) WHERE r IS NOT NULL | properties(r)] AS regions,
               [o IN (collect(DISTINCT target_obj) + collect(DISTINCT source_obj)) WHERE o IS NOT NULL | properties(o)] AS objects
        """
        records, _, _ = self._driver.execute_query(
            cypher,
            reference_id=reference_id,
            **self._query_config(),
        )
        if not records:
            return {}

        row = records[0]
        ref_props = dict(row["ref_props"]) if row.get("ref_props") else None
        if not ref_props:
            return {}

        target_label = row.get("target_label")
        target_props = dict(row["target_props"]) if row.get("target_props") else None
        source_props = dict(row["source_props"]) if row.get("source_props") else None
        page_props = dict(row["page_props"]) if row.get("page_props") else None
        panels = [dict(p) for p in (row.get("panels") or [])]
        regions = [dict(r) for r in (row.get("regions") or [])]
        objects = [dict(o) for o in (row.get("objects") or [])]

        target = None
        if target_props or target_label:
            target = {
                "label": target_label,
                "properties": target_props or {},
            }

        return {
            "reference": ref_props,
            "source": source_props,
            "page": page_props,
            "target": target,
            "panels": panels,
            "regions": regions,
            "objects": objects,
        }
