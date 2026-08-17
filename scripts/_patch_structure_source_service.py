from pathlib import Path

p = Path('backend/app/services/project_structure_service.py')
s = p.read_text(encoding='utf-8')


def replace(old: str, new: str) -> None:
    global s
    if old not in s:
        raise SystemExit('service patch guard failed: ' + old[:80])
    s = s.replace(old, new, 1)


replace(
'''KIND_LABELS = {\n    "report_body": "본문",\n    "plate_book": "도판 / 사진",\n    "drawing_book": "도면",\n}\n''',
'''KIND_LABELS = {\n    "report_body": "본문",\n    "plate_book": "도판 / 사진",\n    "drawing_book": "도면",\n}\n\nSOURCE_KIND_LABELS = {\n    "body_source": "본문 원본",\n    "drawing_source": "도면 원본",\n    "layout_source": "조판 원본",\n    "linked_photo": "원천 사진",\n    "other_source": "기타 원천",\n    "provenance_manifest": "연결 명세",\n}\n\nPROVENANCE_STATUS_LABELS = {\n    "unlinked": "canonical 미연결",\n    "declared": "연결 선언",\n    "verified": "연결 검증",\n    "ambiguous": "연결 모호",\n    "missing_target": "대상 없음",\n    "conflict": "연결 충돌",\n}\n''')

replace(
'''            child_count=5,\n            badges=[\n                f"검수 세트 {summary.get('review_round_count', 0)}",\n                f"고고학 객체 {summary.get('object_count', 0)}",\n            ],\n''',
'''            child_count=6,\n            badges=[\n                f"원천 자료 {summary.get('original_asset_count', 0)}",\n                f"검수 세트 {summary.get('review_round_count', 0)}",\n                f"고고학 객체 {summary.get('object_count', 0)}",\n            ],\n''')

replace(
'''        groups.append(\n            self._group(\n                "review-rounds",\n                ProjectStructureNodeType.review_round_group,\n''',
'''        source_count = int(summary.get("original_asset_count") or 0)\n        groups.append(\n            self._group(\n                "source-assets",\n                ProjectStructureNodeType.source_asset_group,\n                "원천 자료",\n                source_count,\n                [f"원천 파일 {source_count}"],\n                {"scope": "project-owned OriginalAsset"},\n            )\n        )\n        groups.append(\n            self._group(\n                "review-rounds",\n                ProjectStructureNodeType.review_round_group,\n''')

replace(
'''        if row.get("node_type"):\n            node_type = ProjectStructureNodeType(row["node_type"])\n            return self._group(\n''',
'''        if row.get("node_type") == ProjectStructureNodeType.original_asset.value:\n            return self._original_asset_node(row)\n        if row.get("node_type"):\n            node_type = ProjectStructureNodeType(row["node_type"])\n            return self._group(\n''')

replace(
'''        if node_type in {\n            ProjectStructureNodeType.material_group,\n            ProjectStructureNodeType.review_round_group,\n            ProjectStructureNodeType.archaeology_object_group,\n        }:\n''',
'''        if node_type in {\n            ProjectStructureNodeType.material_group,\n            ProjectStructureNodeType.source_asset_group,\n            ProjectStructureNodeType.review_round_group,\n            ProjectStructureNodeType.archaeology_object_group,\n        }:\n''')

replace(
'''            ProjectStructureNodeType.region_group,\n        }:\n''',
'''            ProjectStructureNodeType.region_group,\n            ProjectStructureNodeType.source_kind_group,\n        }:\n''')

replace(
'''                "plate_group": "표준 도판", "panel_group": "패널", "drawing_group": "표준 도면", "region_group": "영역",\n            }[node_type.value]\n''',
'''                "plate_group": "표준 도판", "panel_group": "패널", "drawing_group": "표준 도면", "region_group": "영역",\n                "source_kind_group": SOURCE_KIND_LABELS.get(node_id.removeprefix("source-kind:"), "기타 원천"),\n            }[node_type.value]\n''')

replace(
'''        if node_type == ProjectStructureNodeType.review_round:\n            relationships = []\n''',
'''        if node_type == ProjectStructureNodeType.original_asset:\n            node = self._original_asset_node(detail)\n            relationships: list[ProjectStructureRelationship] = []\n            for relation in detail.get("relationships") or []:\n                if relation and relation.get("id") and relation.get("label"):\n                    relationships.append(ProjectStructureRelationship(\n                        type="DERIVED_FROM", direction="in",\n                        target=ProjectStructureRelationshipTarget(\n                            id=str(relation["id"]),\n                            node_type=self._node_type_for_label(str(relation["label"])),\n                            label=self._canonical_label(str(relation["label"]), relation),\n                        ),\n                    ))\n            return node.model_copy(update={"relationships": relationships})\n        if node_type == ProjectStructureNodeType.review_round:\n            relationships = []\n''')

marker = '''    def _version_node(self, row: dict[str, Any]) -> ProjectStructureNode:\n'''
insert = '''    def _original_asset_node(self, row: dict[str, Any]) -> ProjectStructureNode:\n        kind = str(row.get("asset_kind") or "other_source")\n        provenance = str(row.get("provenance_status") or "unlinked")\n        parse_status = str(row.get("parse_status") or "stored")\n        original_name = str(row.get("original_name") or "원천 자료")\n        kind_label = SOURCE_KIND_LABELS.get(kind, SOURCE_KIND_LABELS["other_source"])\n        provenance_label = PROVENANCE_STATUS_LABELS.get(provenance, provenance)\n        storage = self.file_store.inspect(str(row.get("uri") or "")) if row.get("uri") else "unknown"\n        storage_label = {"present": "파일 존재", "missing": "파일 누락", "unknown": "파일 상태 미확인"}[storage]\n        return ProjectStructureNode(\n            id=str(row["id"]),\n            node_type=ProjectStructureNodeType.original_asset,\n            label=f"[{kind_label}] {original_name} · {provenance_label}",\n            subtitle="OriginalAsset · 원천 자료",\n            source_system="neo4j",\n            status=provenance,\n            expandable=False,\n            child_count=0,\n            badges=[storage_label, f"parse {parse_status}", provenance_label],\n            details={\n                "neo4jLabel": "OriginalAsset",\n                "storageSystem": "FileStore",\n                "storageStatus": storage,\n                "storageUri": row.get("uri"),\n                "sha256": row.get("sha256"),\n                "mimeType": row.get("mime_type"),\n                "sizeBytes": row.get("size_bytes"),\n                "relativePath": row.get("relative_path"),\n                "assetKind": kind,\n                "parseStatus": parse_status,\n                "provenanceStatus": provenance,\n                "originalName": original_name,\n            },\n        )\n\n'''
if marker not in s:
    raise SystemExit('service method marker missing')
s = s.replace(marker, insert + marker, 1)

p.write_text(s, encoding='utf-8')
