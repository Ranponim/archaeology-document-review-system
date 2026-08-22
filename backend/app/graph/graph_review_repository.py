from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Literal


ReferenceKind = Literal["plate", "drawing"]


@dataclass(frozen=True, slots=True)
class GraphReferenceResolution:
    status: str
    reference_type: str
    number: str
    reference_corpus_id: str
    target_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CorpusIntegrityReport:
    ok: bool
    status: str
    visual_count: int = 0
    artifact_count: int = 0
    provenance_gap_count: int = 0
    cross_project_count: int = 0
    duplicate_numbers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GraphVisualNode:
    id: str
    label: str
    number: str
    title: str
    reference_corpus_id: str


@dataclass(frozen=True, slots=True)
class GraphObjectReference:
    id: str
    reference_type: str
    number: str
    raw_text: str | None = None
    source_block_id: str | None = None


class GraphReviewRepository:
    """Focused graph queries for corpus-mode deterministic review.

    Every visual lookup is rooted at Project -> ReferenceCorpus. This keeps
    revision identity explicit and prevents a Reference or visual with the same
    publication number in another corpus/project from becoming authority.
    Rule modules consume this repository instead of embedding Cypher.
    """

    def __init__(self, driver: Any, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @property
    def _query_config(self) -> dict[str, Any]:
        return {"database_": self._database} if self._database is not None else {}

    def _corpus_status(self, project_id: str, corpus_id: str) -> str | None:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            WHERE corpus.projectId = $project_id
            RETURN corpus.status AS status
            LIMIT 1
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            **self._query_config,
        )
        if not records:
            return None
        return str(records[0].get("status") or "").strip().lower()

    def _require_ready_corpus(self, project_id: str, corpus_id: str) -> None:
        status = self._corpus_status(project_id, corpus_id)
        if status is None:
            raise ValueError(
                f"reference corpus '{corpus_id}' is not owned by project '{project_id}'"
            )
        if status != "ready":
            raise ValueError(
                f"reference corpus '{corpus_id}' must be READY before review"
            )

    @staticmethod
    def _first_int(records: list[Any], key: str) -> int:
        if not records:
            return 0
        return int(records[0].get(key) or 0)

    def validate_corpus_integrity(
        self, project_id: str, corpus_id: str
    ) -> CorpusIntegrityReport:
        status = self._corpus_status(project_id, corpus_id)
        if status is None:
            return CorpusIntegrityReport(
                ok=False,
                status="missing",
                errors=("CORPUS_NOT_FOUND",),
            )
        if status != "ready":
            return CorpusIntegrityReport(
                ok=False,
                status=status,
                errors=("CORPUS_NOT_READY",),
            )

        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            OPTIONAL MATCH (corpus)-[:HAS_PLATE|HAS_DRAWING]->(visual)
            RETURN count(DISTINCT visual) AS visual_count
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            **self._query_config,
        )
        visual_count = self._first_int(records, "visual_count")

        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            OPTIONAL MATCH (corpus)-[:HAS_ARTIFACT]->(artifact:DerivedArtifact)
            RETURN count(DISTINCT artifact) AS artifact_count
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            **self._query_config,
        )
        artifact_count = self._first_int(records, "artifact_count")

        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            OPTIONAL MATCH (corpus)-[:HAS_PLATE]->(:Plate)-[:HAS_PANEL]->(panel:PlatePanel)
            OPTIONAL MATCH (panel)-[:DERIVED_FROM]->(panel_source:OriginalAsset)
            WITH project, corpus,
                 count(CASE WHEN panel IS NOT NULL AND
                     (panel_source IS NULL OR panel_source.projectId <> $project_id)
                     THEN 1 END) AS panel_gaps
            OPTIONAL MATCH (corpus)-[:HAS_DRAWING]->(:Drawing)-[:HAS_REGION]->(region:DrawingRegion)
            OPTIONAL MATCH (region)-[:DERIVED_FROM]->(region_source:OriginalAsset)
            RETURN panel_gaps + count(CASE WHEN region IS NOT NULL AND
                     (region_source IS NULL OR region_source.projectId <> $project_id)
                     THEN 1 END) AS provenance_gap_count
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            **self._query_config,
        )
        provenance_gap_count = self._first_int(records, "provenance_gap_count")

        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            OPTIONAL MATCH (corpus)-[:USES_SOURCE]->(source:OriginalAsset)
            WITH project, corpus,
                 count(CASE WHEN source IS NOT NULL AND source.projectId <> $project_id
                       THEN 1 END) AS source_cross
            OPTIONAL MATCH (corpus)-[:HAS_PLATE|HAS_DRAWING]->(visual)
            RETURN source_cross + count(CASE WHEN visual IS NOT NULL AND
                     visual.referenceCorpusId <> $corpus_id THEN 1 END)
                   AS cross_project_count
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            **self._query_config,
        )
        cross_project_count = self._first_int(records, "cross_project_count")

        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            MATCH (corpus)-[:HAS_PLATE]->(visual:Plate)
            WITH 'plate:' + toString(visual.number) AS duplicate_number,
                 count(visual) AS duplicate_count
            WHERE duplicate_count > 1
            RETURN duplicate_number
            UNION ALL
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            MATCH (corpus)-[:HAS_DRAWING]->(visual:Drawing)
            WITH 'drawing:' + toString(visual.number) AS duplicate_number,
                 count(visual) AS duplicate_count
            WHERE duplicate_count > 1
            RETURN duplicate_number
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            **self._query_config,
        )
        duplicate_numbers = tuple(
            sorted(
                str(row.get("duplicate_number"))
                for row in records
                if row.get("duplicate_number") is not None
            )
        )

        errors: list[str] = []
        if visual_count <= 0:
            errors.append("EMPTY_CANONICAL_GRAPH")
        if artifact_count <= 0:
            errors.append("MISSING_DERIVED_ARTIFACT")
        if provenance_gap_count > 0:
            errors.append("MISSING_PROVENANCE")
        if cross_project_count > 0:
            errors.append("CROSS_PROJECT_RELATIONSHIP")
        if duplicate_numbers:
            errors.append("DUPLICATE_VISUAL_NUMBER")
        return CorpusIntegrityReport(
            ok=not errors,
            status=status,
            visual_count=visual_count,
            artifact_count=artifact_count,
            provenance_gap_count=provenance_gap_count,
            cross_project_count=cross_project_count,
            duplicate_numbers=duplicate_numbers,
            errors=tuple(errors),
        )

    def resolve_reference(
        self,
        project_id: str,
        corpus_id: str,
        reference_type: str,
        number: str,
    ) -> GraphReferenceResolution:
        self._require_ready_corpus(project_id, corpus_id)
        normalized_type = str(reference_type or "").strip().lower()
        normalized_number = str(number or "").strip()
        if normalized_type not in {"plate", "drawing"} or not normalized_number:
            return GraphReferenceResolution(
                status="INVALID",
                reference_type=normalized_type,
                number=normalized_number,
                reference_corpus_id=corpus_id,
            )

        if normalized_type == "plate":
            query = """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            MATCH (corpus)-[:HAS_PLATE]->(target:Plate)
            WHERE corpus.projectId = $project_id
              AND toString(target.number) = $number
            RETURN target.id AS id
            ORDER BY target.id ASC
            """
        else:
            query = """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            MATCH (corpus)-[:HAS_DRAWING]->(target:Drawing)
            WHERE corpus.projectId = $project_id
              AND toString(target.number) = $number
            RETURN target.id AS id
            ORDER BY target.id ASC
            """

        records, _, _ = self._driver.execute_query(
            query,
            project_id=project_id,
            corpus_id=corpus_id,
            number=normalized_number,
            **self._query_config,
        )
        target_ids = tuple(
            sorted(
                {
                    str(row.get("id"))
                    for row in records
                    if row.get("id") is not None
                }
            )
        )
        if not target_ids:
            status = "MISSING"
        elif len(target_ids) == 1:
            status = "RESOLVED"
        else:
            status = "AMBIGUOUS"
        return GraphReferenceResolution(
            status=status,
            reference_type=normalized_type,
            number=normalized_number,
            reference_corpus_id=corpus_id,
            target_ids=target_ids,
        )

    def visuals_for_object(
        self, project_id: str, corpus_id: str, object_id: str
    ) -> list[GraphVisualNode]:
        self._require_ready_corpus(project_id, corpus_id)
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            MATCH (project)-[:HAS_OBJECT]->(object:ArchaeologyObject {id: $object_id})
            MATCH (corpus)-[:HAS_PLATE]->(visual:Plate)-[:DEPICTS]->(object)
            RETURN 'Plate' AS label, visual.id AS id,
                   toString(visual.number) AS number, visual.title AS title
            UNION ALL
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            MATCH (project)-[:HAS_OBJECT]->(object:ArchaeologyObject {id: $object_id})
            MATCH (corpus)-[:HAS_PLATE]->(:Plate)-[:HAS_PANEL]->(visual:PlatePanel)-[:DEPICTS]->(object)
            RETURN 'PlatePanel' AS label, visual.id AS id,
                   '' AS number, visual.caption AS title
            UNION ALL
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            MATCH (project)-[:HAS_OBJECT]->(object:ArchaeologyObject {id: $object_id})
            MATCH (corpus)-[:HAS_DRAWING]->(visual:Drawing)-[:DEPICTS]->(object)
            RETURN 'Drawing' AS label, visual.id AS id,
                   toString(visual.number) AS number, visual.title AS title
            UNION ALL
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            MATCH (project)-[:HAS_OBJECT]->(object:ArchaeologyObject {id: $object_id})
            MATCH (corpus)-[:HAS_DRAWING]->(:Drawing)-[:HAS_REGION]->(visual:DrawingRegion)-[:DEPICTS]->(object)
            RETURN 'DrawingRegion' AS label, visual.id AS id,
                   toString(visual.number) AS number, visual.title AS title
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            object_id=object_id,
            **self._query_config,
        )
        items = [
            GraphVisualNode(
                id=str(row.get("id")),
                label=str(row.get("label") or ""),
                number=str(row.get("number") or ""),
                title=str(row.get("title") or ""),
                reference_corpus_id=corpus_id,
            )
            for row in records
            if row.get("id") is not None
        ]
        return sorted(items, key=lambda item: (item.label, item.number, item.id))

    def references_for_object(
        self, project_id: str, object_id: str
    ) -> list[GraphObjectReference]:
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_OBJECT]->
                  (object:ArchaeologyObject {id: $object_id})
            MATCH (source)-[:MENTIONS]->(object)
            MATCH (source)-[:REFERENCES]->(ref:Reference)
            RETURN ref.id AS id,
                   ref.ref_type AS ref_type,
                   toString(ref.number) AS number,
                   ref.raw_text AS raw_text,
                   coalesce(ref.source_block_id, source.id) AS source_block_id
            ORDER BY id ASC
            """,
            project_id=project_id,
            object_id=object_id,
            **self._query_config,
        )
        return [
            GraphObjectReference(
                id=str(row.get("id")),
                reference_type=str(row.get("ref_type") or ""),
                number=str(row.get("number") or ""),
                raw_text=(
                    str(row.get("raw_text"))
                    if row.get("raw_text") is not None
                    else None
                ),
                source_block_id=(
                    str(row.get("source_block_id"))
                    if row.get("source_block_id") is not None
                    else None
                ),
            )
            for row in records
            if row.get("id") is not None
        ]

    @staticmethod
    def _resolution_evidence_id(
        project_id: str,
        corpus_id: str,
        analysis_run_id: str,
        reference_id: str,
        resolution: GraphReferenceResolution,
    ) -> str:
        identity = "|".join(
            [
                project_id,
                corpus_id,
                analysis_run_id,
                reference_id,
                resolution.reference_type,
                resolution.number,
                resolution.status,
                ",".join(resolution.target_ids),
            ]
        )
        return "resolution:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    def save_resolution_evidence(
        self,
        project_id: str,
        corpus_id: str,
        analysis_run_id: str,
        reference_id: str,
        resolution: GraphReferenceResolution,
    ) -> str:
        self._require_ready_corpus(project_id, corpus_id)
        if resolution.reference_corpus_id != corpus_id:
            raise ValueError("resolution evidence corpus does not match selected corpus")
        evidence_id = self._resolution_evidence_id(
            project_id,
            corpus_id,
            analysis_run_id,
            reference_id,
            resolution,
        )
        records, _, _ = self._driver.execute_query(
            """
            MATCH (project:Project {id: $project_id})-[:HAS_REFERENCE_CORPUS]->
                  (corpus:ReferenceCorpus {id: $corpus_id})
            WHERE corpus.projectId = $project_id
            OPTIONAL MATCH (project)-[:HAS_RUN]->(run:AnalysisRun {id: $analysis_run_id})
            MERGE (evidence:ResolutionEvidence {id: $evidence_id})
            SET evidence.projectId = $project_id,
                evidence.referenceCorpusId = $corpus_id,
                evidence.analysisRunId = $analysis_run_id,
                evidence.referenceId = $reference_id,
                evidence.referenceType = $reference_type,
                evidence.number = $number,
                evidence.status = $status,
                evidence.targetIds = $target_ids,
                evidence.updatedAt = datetime(),
                evidence.createdAt = coalesce(evidence.createdAt, datetime())
            MERGE (evidence)-[:FOR_CORPUS]->(corpus)
            FOREACH (_ IN CASE WHEN run IS NULL THEN [] ELSE [1] END |
                MERGE (run)-[:HAS_RESOLUTION_EVIDENCE]->(evidence)
            )
            RETURN evidence.id AS id
            """,
            project_id=project_id,
            corpus_id=corpus_id,
            analysis_run_id=analysis_run_id,
            reference_id=reference_id,
            evidence_id=evidence_id,
            reference_type=resolution.reference_type,
            number=resolution.number,
            status=resolution.status,
            target_ids=list(resolution.target_ids),
            **self._query_config,
        )
        if not records:
            raise ValueError("resolution evidence could not be persisted in selected corpus")
        return str(records[0].get("id") or evidence_id)
