from pathlib import Path
p=Path('backend/app/graph/project_structure_repository.py'); s=p.read_text(encoding='utf-8')
def r(o,n):
 global s
 if o not in s: raise SystemExit('guard '+o[:50])
 s=s.replace(o,n,1)
r('''        counts = count_rows[0] if count_rows else {"review_round_count": 0, "object_count": 0}\n        return {\n''','''        counts = count_rows[0] if count_rows else {"review_round_count": 0, "object_count": 0}\n        asset_rows = self._records(\n            "MATCH (:Project {id: $project_id})-[:HAS_ORIGINAL_ASSET]->(asset:OriginalAsset) RETURN count(asset) AS total",\n            project_id=project_id,\n        )\n        return {\n''')
r('''            "object_count": int(counts.get("object_count") or 0),\n        }\n''','''            "object_count": int(counts.get("object_count") or 0),\n            "original_asset_count": int(asset_rows[0].get("total") or 0) if asset_rows else 0,\n        }\n''')
r('''        if node_type == ProjectStructureNodeType.review_round_group:\n            return self._list_rounds(project_id, offset, limit)\n''','''        if node_type == ProjectStructureNodeType.source_asset_group:\n            return self._source_kind_groups(project_id)\n        if node_type == ProjectStructureNodeType.source_kind_group:\n            kind = self._derived_parent(node_id, "source-kind")\n            return self._list_original_assets(project_id, kind, offset, limit)\n        if node_type == ProjectStructureNodeType.review_round_group:\n            return self._list_rounds(project_id, offset, limit)\n''')
p.write_text(s,encoding='utf-8')
