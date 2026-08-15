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
)


def ensure_schema(driver: Driver, database: str | None = None) -> None:
    query_config = {"database_": database} if database is not None else {}
    for name, label in CONSTRAINTS:
        driver.execute_query(
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (node:{label}) REQUIRE node.id IS UNIQUE",
            **query_config,
        )
    driver.execute_query(
        "CREATE INDEX document_version_sha256 IF NOT EXISTS "
        "FOR (node:DocumentVersion) ON (node.sha256)",
        **query_config,
    )
    driver.execute_query(
        "CREATE INDEX correction_candidate_category IF NOT EXISTS "
        "FOR (node:CorrectionCandidate) ON (node.rule_category)",
        **query_config,
    )
