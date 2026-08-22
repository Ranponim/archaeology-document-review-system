from __future__ import annotations

from collections import defaultdict
from typing import Any


_VISUAL_PATHS = {
    "Plate": "(corpus)-[:HAS_PLATE]->(asset:Plate)",
    "PlatePanel": "(corpus)-[:HAS_PLATE]->(:Plate)-[:HAS_PANEL]->(asset:PlatePanel)",
    "Drawing": "(corpus)-[:HAS_DRAWING]->(asset:Drawing)",
    "DrawingRegion": "(corpus)-[:HAS_DRAWING]->(:Drawing)-[:HAS_REGION]->(asset:DrawingRegion)",
}
_TEXT_PROPERTY = {
    "Plate": "title",
    "PlatePanel": "caption",
    "Drawing": "title",
    "DrawingRegion": "title",
}


class CorpusObjectGraphRepository:
    """Review-time visual/object graph operations scoped to one READY corpus."""

    def __init__(self, driver, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @property
    def _query_config(self) -> dict[str, str]:
        return {"database_": self._database} if self._database else {}

    def list_visual_descriptors(self, project_id: str, corpus_id: str) -> list[dict[str, str]]:
        descriptors: list[dict[str, str]] = []
        for label, path in _VISUAL_PATHS.items():
            text_property = _TEXT_PROPERTY[label]
            records, _, _ = self._driver.execute_query(
                f"""
                MATCH (project:Project {{id: $project_id}})-[:HAS_REFERENCE_CORPUS]->
                      (corpus:ReferenceCorpus {{id: $corpus_id}})
                WHERE corpus.projectId = $project_id AND corpus.status = 'ready'
                MATCH {path}
                RETURN asset.id AS id,
                       coalesce(asset.{text_property}, '') AS text
                ORDER BY asset.id
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                **self._query_config,
            )
            descriptors.extend(
                {
                    "label": label,
                    "id": str(row["id"]),
                    "text": str(row.get("text") or ""),
                }
                for row in records
                if row.get("id")
            )
        return descriptors

    def _group_links(self, links) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for link in links:
            label = str(link.asset_label)
            if label not in _VISUAL_PATHS:
                raise ValueError("unsupported corpus visual label")
            grouped[label].append(
                {"asset_id": str(link.asset_id), "object_id": str(link.object_id)}
            )
        return dict(grouped)

    def link_depicts(self, project_id: str, corpus_id: str, links) -> None:
        for label, params in self._group_links(links).items():
            path = _VISUAL_PATHS[label]
            records, _, _ = self._driver.execute_query(
                f"""
                MATCH (project:Project {{id: $project_id}})-[:HAS_REFERENCE_CORPUS]->
                      (corpus:ReferenceCorpus {{id: $corpus_id}})
                WHERE corpus.projectId = $project_id AND corpus.status = 'ready'
                UNWIND $links AS item
                MATCH {path}
                WHERE asset.id = item.asset_id
                MATCH (project)-[:HAS_OBJECT]->(obj:ArchaeologyObject {{id: item.object_id}})
                WHERE obj.projectId = $project_id
                MERGE (asset)-[rel:DEPICTS]->(obj)
                SET rel.method = 'strong_identifier',
                    rel.referenceCorpusId = $corpus_id,
                    rel.createdAt = coalesce(rel.createdAt, datetime()),
                    asset.depicts_status = 'linked'
                RETURN count(rel) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                links=params,
                **self._query_config,
            )
            saved = int(records[0].get("saved") or 0) if records else 0
            if saved != len(params):
                raise ValueError("corpus visual/object relationship escaped project or corpus scope")

    def mark_depicts_ambiguous(
        self,
        project_id: str,
        corpus_id: str,
        assets: list[tuple[str, str]],
    ) -> None:
        grouped: dict[str, list[str]] = defaultdict(list)
        for label, asset_id in assets:
            if label not in _VISUAL_PATHS:
                raise ValueError("unsupported corpus visual label")
            grouped[label].append(str(asset_id))

        for label, asset_ids in grouped.items():
            path = _VISUAL_PATHS[label]
            records, _, _ = self._driver.execute_query(
                f"""
                MATCH (project:Project {{id: $project_id}})-[:HAS_REFERENCE_CORPUS]->
                      (corpus:ReferenceCorpus {{id: $corpus_id}})
                WHERE corpus.projectId = $project_id AND corpus.status = 'ready'
                UNWIND $asset_ids AS asset_id
                MATCH {path}
                WHERE asset.id = asset_id
                SET asset.depicts_status = 'semantic_review'
                RETURN count(asset) AS saved
                """,
                project_id=project_id,
                corpus_id=corpus_id,
                asset_ids=asset_ids,
                **self._query_config,
            )
            saved = int(records[0].get("saved") or 0) if records else 0
            if saved != len(asset_ids):
                raise ValueError("ambiguous corpus visual escaped project or corpus scope")
