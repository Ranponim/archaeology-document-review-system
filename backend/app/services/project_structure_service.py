from __future__ import annotations

from typing import Any

from app.api.project_structure_contract import (
    ProjectStructureChildrenResponse,
    ProjectStructureNode,
    ProjectStructureNodeType,
    ProjectStructureRelationship,
    ProjectStructureRelationshipTarget,
    ProjectStructureRootResponse,
)
from app.graph.project_structure_repository import ProjectStructureRepository
from app.services.file_store import FileStore


KIND_LABELS = {
    "report_body": "본문",
    "plate_book": "도판 / 사진",
    "drawing_book": "도면",
}


class StructureNodeNotFoundError(LookupError):
    pass


class ProjectStructureService:
    def __init__(self, repository: ProjectStructureRepository, file_store: FileStore) -> None:
        self.repository = repository
        self.file_store = file_store

    @staticmethod
    def _group(
        node_id: str,
        node_type: ProjectStructureNodeType,
        label: str,
        child_count: int,
        badges: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> ProjectStructureNode:
        return ProjectStructureNode(
            id=node_id,
            node_type=node_type,
            label=label,
            source_system="derived_group",
            expandable=child_count > 0,
            child_count=child_count,
            badges=badges or [],
            details=details or {},
        )

    def get_root(self, project_id: str) -> ProjectStructureRootResponse:
        summary = self.repository.project_summary(project_id)
        root = ProjectStructureNode(
            id=summary["id"],
            node_type=ProjectStructureNodeType.project,
            label=summary.get("name") or summary["id"],
            subtitle="프로젝트 전체 자료 구조",
            source_system="neo4j",
            expandable=True,
            child_count=5,
            badges=[
                f"검수 세트 {summary.get('review_round_count', 0)}",
                f"고고학 객체 {summary.get('object_count', 0)}",
            ],
            details={
                "neo4jLabel": "Project",
                "internalCode": summary.get("internal_code"),
            },
        )
        material_map = {row["kind"]: row for row in summary.get("materials", [])}
        groups: list[ProjectStructureNode] = []
        for kind in ("report_body", "plate_book", "drawing_book"):
            row = material_map.get(kind, {})
            versions = int(row.get("version_count") or 0)
            completed = int(row.get("completed_count") or 0)
            badges = [f"파일 {versions}"]
            if versions:
                badges.append(f"ingest 완료 {completed}/{versions}")
            if kind == "report_body":
                badges.append(f"페이지 {int(row.get('page_count') or 0)}")
            elif kind == "plate_book":
                badges.extend([
                    f"도판 {int(row.get('plate_count') or 0)}",
                    f"패널 {int(row.get('panel_count') or 0)}",
                ])
            else:
                badges.extend([
                    f"도면 {int(row.get('drawing_count') or 0)}",
                    f"영역 {int(row.get('region_count') or 0)}",
                ])
            groups.append(
                self._group(
                    f"material:{kind}",
                    ProjectStructureNodeType.material_group,
                    KIND_LABELS[kind],
                    int(row.get("document_count") or 0),
                    badges,
                    {"kind": kind, "versionCount": versions},
                )
            )
        groups.append(
            self._group(
                "review-rounds",
                ProjectStructureNodeType.review_round_group,
                "검수 세트",
                int(summary.get("review_round_count") or 0),
                [f"ReviewRound {int(summary.get('review_round_count') or 0)}"],
            )
        )
        groups.append(
            self._group(
                "archaeology-objects",
                ProjectStructureNodeType.archaeology_object_group,
                "고고학 객체",
                int(summary.get("object_count") or 0),
                [f"객체 {int(summary.get('object_count') or 0)}"],
            )
        )
        return ProjectStructureRootResponse(project_id=project_id, root=root, groups=groups)

    def get_children(
        self,
        project_id: str,
        node_type: ProjectStructureNodeType,
        node_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> ProjectStructureChildrenResponse:
        rows, total = self.repository.list_children(
            project_id, node_type, node_id, offset, limit
        )
        items = [self._row_to_node(node_type, row) for row in rows]
        return ProjectStructureChildrenResponse(
            items=items, offset=offset, limit=limit, total=total
        )

    def _row_to_node(
        self,
        parent_type: ProjectStructureNodeType,
        row: dict[str, Any],
    ) -> ProjectStructureNode:
        if row.get("node_type"):
            node_type = ProjectStructureNodeType(row["node_type"])
            return self._group(
                row["id"],
                node_type,
                row.get("label") or row["id"],
                int(row.get("child_count") or 0),
                details={k: v for k, v in row.items() if k not in {"id", "node_type", "label", "child_count"}},
            )

        if parent_type == ProjectStructureNodeType.material_group:
            return ProjectStructureNode(
                id=row["id"], node_type="document", label=row.get("label") or row["id"],
                subtitle=f"{KIND_LABELS.get(row.get('kind'), row.get('kind', '문서'))} · Document",
                source_system="neo4j", expandable=int(row.get("child_count") or 0) > 0,
                child_count=int(row.get("child_count") or 0), badges=[f"버전 {int(row.get('child_count') or 0)}"],
                details={"neo4jLabel": "Document", "kind": row.get("kind")},
            )
        if parent_type == ProjectStructureNodeType.document:
            return self._version_node(row)
        if parent_type == ProjectStructureNodeType.page_group:
            physical = row.get("physical_page")
            printed = row.get("printed_page")
            child_groups = sum(1 for key in ("block_count", "caption_count", "reference_count") if int(row.get(key) or 0) > 0)
            badges = []
            if printed not in (None, ""):
                badges.append(f"인쇄면 {printed}")
            badges.extend([
                f"본문 {int(row.get('block_count') or 0)}",
                f"캡션 {int(row.get('caption_count') or 0)}",
                f"참조 {int(row.get('reference_count') or 0)}",
            ])
            return ProjectStructureNode(
                id=row["id"], node_type="page", label=f"Page {physical}", subtitle=row.get("header"),
                source_system="neo4j", expandable=child_groups > 0, child_count=child_groups,
                badges=badges, details={"physicalPage": physical, "printedPage": printed, "neo4jLabel": "Page"},
            )
        if parent_type == ProjectStructureNodeType.textblock_group:
            text = row.get("text") or row.get("normalized_text") or "본문 블록"
            return ProjectStructureNode(
                id=row["id"], node_type="text_block", label=str(text)[:90], subtitle="TextBlock",
                source_system="neo4j", details={**row, "neo4jLabel": "TextBlock"},
            )
        if parent_type == ProjectStructureNodeType.caption_group:
            text = row.get("text") or "캡션"
            return ProjectStructureNode(
                id=row["id"], node_type="caption", label=str(text)[:90], subtitle="Caption",
                source_system="neo4j", details={**row, "neo4jLabel": "Caption"},
            )
        if parent_type == ProjectStructureNodeType.reference_group:
            ref_type = row.get("ref_type") or "reference"
            number = row.get("number") or ""
            return ProjectStructureNode(
                id=row["id"], node_type="reference", label=f"{self._ref_label(ref_type)} {number}".strip(),
                subtitle="Reference", source_system="neo4j", expandable=False,
                details={**row, "neo4jLabel": "Reference"},
            )
        if parent_type in {ProjectStructureNodeType.plate_group}:
            number = row.get("number") or ""
            raw = row.get("raw_identifier") or (f"【도판 {number}】" if number else row["id"])
            return ProjectStructureNode(
                id=row["id"], node_type="plate", label=str(raw), subtitle=row.get("title") or "Plate",
                source_system="neo4j", expandable=int(row.get("child_count") or 0) > 0,
                child_count=int(row.get("child_count") or 0), badges=[f"PDF p.{row.get('physical_page')}" ] if row.get("physical_page") else [],
                details={**row, "neo4jLabel": "Plate"},
            )
        if parent_type in {ProjectStructureNodeType.plate, ProjectStructureNodeType.panel_group}:
            idx = row.get("panel_index")
            return ProjectStructureNode(
                id=row["id"], node_type="plate_panel", label=f"패널 {idx}" if idx is not None else row["id"],
                subtitle=row.get("caption") or "PlatePanel", source_system="neo4j",
                details={**row, "neo4jLabel": "PlatePanel"},
            )
        if parent_type == ProjectStructureNodeType.drawing_group:
            number = row.get("number") or ""
            raw = row.get("raw_identifier") or (f"【도면 {number}】" if number else row["id"])
            return ProjectStructureNode(
                id=row["id"], node_type="drawing", label=str(raw), subtitle=row.get("title") or "Drawing",
                source_system="neo4j", expandable=int(row.get("child_count") or 0) > 0,
                child_count=int(row.get("child_count") or 0), badges=[f"PDF p.{row.get('physical_page')}" ] if row.get("physical_page") else [],
                details={**row, "neo4jLabel": "Drawing"},
            )
        if parent_type in {ProjectStructureNodeType.drawing, ProjectStructureNodeType.region_group}:
            number = row.get("number") or ""
            return ProjectStructureNode(
                id=row["id"], node_type="drawing_region", label=f"영역 {number}" if number else row["id"],
                subtitle=row.get("title") or "DrawingRegion", source_system="neo4j",
                details={**row, "neo4jLabel": "DrawingRegion"},
            )
        if parent_type == ProjectStructureNodeType.review_round_group:
            seq = row.get("sequence")
            badges = [str(row.get("status") or "draft")]
            if row.get("previous_round_id"):
                badges.append("이전 라운드 연결")
            return ProjectStructureNode(
                id=row["id"], node_type="review_round", label=f"검수 #{seq}", subtitle="ReviewRound",
                source_system="neo4j", status=row.get("status"), expandable=True, child_count=3,
                badges=badges, details={**row, "neo4jLabel": "ReviewRound"},
            )
        if parent_type == ProjectStructureNodeType.review_round:
            return ProjectStructureNode(
                id=row["id"], node_type="version_reference", label=row.get("label") or row["id"],
                subtitle="DocumentVersion 바로가기", source_system="neo4j",
                details={**row, "neo4jLabel": "DocumentVersion"},
            )
        if parent_type == ProjectStructureNodeType.archaeology_object_group:
            label = row.get("canonical_name") or self._object_label(row) or row["id"]
            return ProjectStructureNode(
                id=row["id"], node_type="archaeology_object", label=str(label), subtitle="ArchaeologyObject",
                source_system="neo4j", details={**row, "neo4jLabel": "ArchaeologyObject"},
            )
        raise ValueError(f"Unsupported structure parent type: {parent_type}")

    def _version_node(self, row: dict[str, Any]) -> ProjectStructureNode:
        storage = self.file_store.inspect(str(row.get("uri") or "")) if row.get("uri") else "unknown"
        ingest = row.get("ingest_status") or "unknown"
        groups = sum(1 for key in ("page_count", "plate_count", "drawing_count") if int(row.get(key) or 0) > 0)
        storage_label = {"present": "파일 존재", "missing": "파일 누락", "unknown": "파일 상태 미확인"}[storage]
        badges = [storage_label, f"ingest {ingest}", f"Page {int(row.get('page_count') or 0)}"]
        if int(row.get("plate_count") or 0):
            badges.append(f"Plate {int(row['plate_count'])}")
        if int(row.get("drawing_count") or 0):
            badges.append(f"Drawing {int(row['drawing_count'])}")
        return ProjectStructureNode(
            id=row["id"], node_type="document_version", label=row.get("label") or row["id"],
            subtitle=f"{KIND_LABELS.get(row.get('kind'), row.get('kind', '문서'))} · DocumentVersion",
            source_system="neo4j", status=str(ingest), expandable=groups > 0, child_count=groups,
            badges=badges,
            details={
                "neo4jLabel": "DocumentVersion", "storageSystem": "FileStore", "storageStatus": storage,
                "storageUri": row.get("uri"), "sha256": row.get("sha256"), "sizeBytes": row.get("size_bytes"),
                "mimeType": row.get("mime_type"), "stage": row.get("stage"), "ingestStatus": ingest,
                "pageCount": int(row.get("page_count") or 0), "plateCount": int(row.get("plate_count") or 0),
                "drawingCount": int(row.get("drawing_count") or 0),
            },
        )

    def get_node(
        self,
        project_id: str,
        node_type: ProjectStructureNodeType,
        node_id: str,
    ) -> ProjectStructureNode:
        if node_type in {
            ProjectStructureNodeType.material_group,
            ProjectStructureNodeType.review_round_group,
            ProjectStructureNodeType.archaeology_object_group,
        }:
            root = self.get_root(project_id)
            found = next((group for group in root.groups if group.id == node_id), None)
            if found is None:
                raise StructureNodeNotFoundError(node_id)
            return found
        if node_type in {
            ProjectStructureNodeType.page_group,
            ProjectStructureNodeType.textblock_group,
            ProjectStructureNodeType.caption_group,
            ProjectStructureNodeType.reference_group,
            ProjectStructureNodeType.plate_group,
            ProjectStructureNodeType.panel_group,
            ProjectStructureNodeType.drawing_group,
            ProjectStructureNodeType.region_group,
        }:
            # A derived group is authorized by successfully listing its first page.
            _items = self.get_children(project_id, node_type, node_id, 0, 1)
            label = {
                "page_group": "페이지", "textblock_group": "본문 블록", "caption_group": "캡션", "reference_group": "참조",
                "plate_group": "표준 도판", "panel_group": "패널", "drawing_group": "표준 도면", "region_group": "영역",
            }[node_type.value]
            return self._group(node_id, node_type, label, _items.total, [f"항목 {_items.total}"])

        detail = self.repository.get_detail(project_id, node_type, node_id)
        if detail is None:
            raise StructureNodeNotFoundError(node_id)
        return self._detail_node(node_type, detail)

    def _detail_node(self, node_type: ProjectStructureNodeType, detail: dict[str, Any]) -> ProjectStructureNode:
        if node_type == ProjectStructureNodeType.document:
            return ProjectStructureNode(
                id=detail["id"], node_type=node_type, label=detail.get("label") or detail["id"], subtitle="Document",
                source_system="neo4j", expandable=int(detail.get("child_count") or 0) > 0,
                child_count=int(detail.get("child_count") or 0), badges=[f"버전 {int(detail.get('child_count') or 0)}"],
                details={**detail, "neo4jLabel": "Document"},
            )
        if node_type in {ProjectStructureNodeType.document_version, ProjectStructureNodeType.version_reference}:
            return self._version_node(detail)
        if node_type == ProjectStructureNodeType.page:
            return ProjectStructureNode(
                id=detail["id"], node_type=node_type, label=f"Page {detail.get('physical_page')}", subtitle=detail.get("header"),
                source_system="neo4j", details={**detail, "neo4jLabel": "Page"},
            )
        if node_type == ProjectStructureNodeType.reference:
            relationships = []
            if detail.get("target_id") and detail.get("target_label"):
                relationships.append(ProjectStructureRelationship(
                    type="RESOLVES_TO", direction="out",
                    target=ProjectStructureRelationshipTarget(
                        id=str(detail["target_id"]), node_type=self._node_type_for_label(str(detail["target_label"])),
                        label=self._canonical_label(str(detail["target_label"]), detail.get("target_properties") or {}),
                    ),
                ))
            return ProjectStructureNode(
                id=detail["id"], node_type=node_type,
                label=f"{self._ref_label(detail.get('ref_type'))} {detail.get('number') or ''}".strip(),
                subtitle="Reference", source_system="neo4j",
                badges=["해결됨" if relationships else "미해결"],
                details={
                    "neo4jLabel": "Reference", "refType": detail.get("ref_type"), "number": detail.get("number"),
                    "rawText": detail.get("raw_text"), "physicalPage": detail.get("physical_page"), "pageId": detail.get("page_id"),
                }, relationships=relationships,
            )
        if node_type in {ProjectStructureNodeType.plate, ProjectStructureNodeType.plate_panel, ProjectStructureNodeType.drawing, ProjectStructureNodeType.drawing_region}:
            props = dict(detail.get("properties") or {})
            label_name = {
                ProjectStructureNodeType.plate: "Plate", ProjectStructureNodeType.plate_panel: "PlatePanel",
                ProjectStructureNodeType.drawing: "Drawing", ProjectStructureNodeType.drawing_region: "DrawingRegion",
            }[node_type]
            relationships: list[ProjectStructureRelationship] = []
            for ref in detail.get("references") or []:
                if ref and ref.get("id"):
                    relationships.append(ProjectStructureRelationship(
                        type="RESOLVES_TO", direction="in",
                        target=ProjectStructureRelationshipTarget(
                            id=str(ref["id"]), node_type="reference",
                            label=f"{self._ref_label(ref.get('ref_type'))} {ref.get('number') or ''}".strip(),
                        ),
                    ))
            for obj in detail.get("objects") or []:
                if obj and obj.get("id"):
                    relationships.append(ProjectStructureRelationship(
                        type="DEPICTS", direction="out",
                        target=ProjectStructureRelationshipTarget(
                            id=str(obj["id"]), node_type="archaeology_object", label=str(obj.get("canonical_name") or obj["id"]),
                        ),
                    ))
            return ProjectStructureNode(
                id=detail["id"], node_type=node_type, label=self._canonical_label(label_name, props), subtitle=label_name,
                source_system="neo4j", details={**props, "neo4jLabel": label_name, "documentVersionId": detail.get("document_version_id")},
                relationships=relationships,
            )
        if node_type == ProjectStructureNodeType.review_round:
            relationships = []
            if detail.get("previous_round_id"):
                relationships.append(ProjectStructureRelationship(
                    type="PRECEDES", direction="in",
                    target=ProjectStructureRelationshipTarget(id=str(detail["previous_round_id"]), node_type="review_round", label=f"이전 검수 {detail['previous_round_id']}"),
                ))
            for rel_type, key, name_key, role in (
                ("USES_BODY_VERSION", "body_id", "body_name", "본문"),
                ("USES_PLATE_VERSION", "plate_id", "plate_name", "도판 / 사진"),
                ("USES_DRAWING_VERSION", "drawing_id", "drawing_name", "도면"),
            ):
                if detail.get(key):
                    relationships.append(ProjectStructureRelationship(
                        type=rel_type, direction="out",
                        target=ProjectStructureRelationshipTarget(id=str(detail[key]), node_type="document_version", label=f"{role}: {detail.get(name_key) or detail[key]}"),
                    ))
            return ProjectStructureNode(
                id=detail["id"], node_type=node_type, label=f"검수 #{detail.get('sequence')}", subtitle="ReviewRound",
                source_system="neo4j", status=detail.get("status"), expandable=True, child_count=3,
                badges=[str(detail.get("status") or "draft")], details={**detail, "neo4jLabel": "ReviewRound"}, relationships=relationships,
            )
        if node_type == ProjectStructureNodeType.archaeology_object:
            props = dict(detail.get("properties") or {})
            relationships = []
            for source in detail.get("mention_sources") or []:
                if source and source.get("id") and source.get("label") in {"TextBlock", "Caption"}:
                    relationships.append(ProjectStructureRelationship(
                        type="MENTIONS", direction="in",
                        target=ProjectStructureRelationshipTarget(id=str(source["id"]), node_type="text_block" if source["label"] == "TextBlock" else "caption", label=f"{source['label']} {source['id']}"),
                    ))
            for asset in detail.get("depicted_by") or []:
                if asset and asset.get("id") and asset.get("label"):
                    relationships.append(ProjectStructureRelationship(
                        type="DEPICTS", direction="in",
                        target=ProjectStructureRelationshipTarget(id=str(asset["id"]), node_type=self._node_type_for_label(str(asset["label"])), label=f"{asset['label']} {asset['id']}"),
                    ))
            return ProjectStructureNode(
                id=detail["id"], node_type=node_type, label=str(props.get("canonical_name") or self._object_label(props) or detail["id"]),
                subtitle="ArchaeologyObject", source_system="neo4j", details={**props, "neo4jLabel": "ArchaeologyObject"}, relationships=relationships,
            )
        raise StructureNodeNotFoundError(detail.get("id", "unknown"))

    @staticmethod
    def _ref_label(ref_type: Any) -> str:
        return {"plate": "도판", "drawing": "도면", "figure": "그림", "photo": "사진"}.get(str(ref_type), str(ref_type or "참조"))

    @staticmethod
    def _object_label(row: dict[str, Any]) -> str:
        return " ".join(str(row.get(k)) for k in ("site", "period", "number", "type") if row.get(k))

    @staticmethod
    def _node_type_for_label(label: str) -> ProjectStructureNodeType:
        mapping = {
            "Plate": ProjectStructureNodeType.plate,
            "PlatePanel": ProjectStructureNodeType.plate_panel,
            "Drawing": ProjectStructureNodeType.drawing,
            "DrawingRegion": ProjectStructureNodeType.drawing_region,
            "ArchaeologyObject": ProjectStructureNodeType.archaeology_object,
            "Reference": ProjectStructureNodeType.reference,
            "TextBlock": ProjectStructureNodeType.text_block,
            "Caption": ProjectStructureNodeType.caption,
            "DocumentVersion": ProjectStructureNodeType.document_version,
        }
        return mapping.get(label, ProjectStructureNodeType.archaeology_object)

    @staticmethod
    def _canonical_label(label: str, props: dict[str, Any]) -> str:
        raw = props.get("raw_identifier") or props.get("rawIdentifier")
        if raw:
            return str(raw)
        number = props.get("number")
        if label in {"Plate", "PlatePanel"} and number not in (None, ""):
            return f"【도판 {number}】"
        if label in {"Drawing", "DrawingRegion"} and number not in (None, ""):
            return f"【도면 {number}】"
        return str(props.get("canonical_name") or props.get("title") or props.get("id") or label)
