from neo4j import Driver

CONSTRAINTS = (
    ("project_id_unique", "Project"),
    ("document_id_unique", "Document"),
    ("document_version_id_unique", "DocumentVersion"),
    ("analysis_run_id_unique", "AnalysisRun"),
    ("page_id_unique", "Page"),
    ("text_block_id_unique", "TextBlock"),
    ("caption_id_unique", "Caption"),
    ("correction_candidate_id_unique", "CorrectionCandidate"),
    ("evidence_id_unique", "Evidence"),
    ("reference_id_unique", "Reference"),
    ("plate_id_unique", "Plate"),
    ("plate_panel_id_unique", "PlatePanel"),
    ("drawing_id_unique", "Drawing"),
    ("drawing_region_id_unique", "DrawingRegion"),
    ("archaeology_object_id_unique", "ArchaeologyObject"),
    ("original_asset_id_unique", "OriginalAsset"),
    ("review_decision_id_unique", "ReviewDecision"),
    ("review_round_id_unique", "ReviewRound"),
)


INDEXES = (
    ("document_version_sha256", "DocumentVersion", ("sha256",)),
    ("correction_candidate_category", "CorrectionCandidate", ("rule_category",)),
    ("plate_number", "Plate", ("number",)),
    ("drawing_number", "Drawing", ("number",)),
    ("drawing_region_number", "DrawingRegion", ("number",)),
    ("archaeology_object_canonical_name", "ArchaeologyObject", ("canonical_name",)),
    ("reference_type_number", "Reference", ("ref_type", "number")),
    ("evidence_kind", "Evidence", ("kind",)),
)


def ensure_schema(driver: Driver, database: str | None = None) -> None:
    query_config = {"database_": database} if database is not None else {}
    for name, label in CONSTRAINTS:
        driver.execute_query(
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (node:{label}) REQUIRE node.id IS UNIQUE",
            **query_config,
        )
    for name, label, props in INDEXES:
        props_str = ", ".join(f"node.{p}" for p in props)
        driver.execute_query(
            f"CREATE INDEX {name} IF NOT EXISTS "
            f"FOR (node:{label}) ON ({props_str})",
            **query_config,
        )
