from neo4j import Driver

CONSTRAINTS = (
    ("project_id_unique", "Project"),
    ("document_id_unique", "Document"),
    ("document_version_id_unique", "DocumentVersion"),
    ("analysis_run_id_unique", "AnalysisRun"),
)


def ensure_schema(driver: Driver) -> None:
    for name, label in CONSTRAINTS:
        driver.execute_query(
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (node:{label}) REQUIRE node.id IS UNIQUE"
        )
    driver.execute_query(
        "CREATE INDEX document_version_sha256 IF NOT EXISTS "
        "FOR (node:DocumentVersion) ON (node.sha256)"
    )
