# Task 1 TDD Checkpoint

- RED workflow: Review remediation CI #111 (`32049811415`).
- RED backend: 3 new failures, 543 passed, 7 skipped; failures were missing Project timestamps, missing API timestamps, and HWP accepted by publication endpoint.
- RED frontend: 1 new failure, 38 passed; creation timestamp was not rendered.
- RED Real Neo4j: green.
- Initial GREEN production commit: `99eedbb9fe08d592f337dee0ed1aa2251dc6e449`.
- Input rejection test was corrected from 422 to the established 400 `input_error` contract while retaining no-storage/no-graph/no-enqueue assertions.
- Real Neo4j then exposed a Cypher clause-boundary error: Neo4j requires `WITH project` between `SET project.updatedAt = datetime()` and the following `OPTIONAL MATCH`.
- Minimal production fix: `e5617083236b89c0536b97577906d729ce0c248b` (`fix(projects): preserve cypher clause boundary for timestamp update`).
- This documentation-only commit triggers a fresh full CI run on that production tree because pushes performed by `GITHUB_TOKEN` do not recursively trigger workflows.
