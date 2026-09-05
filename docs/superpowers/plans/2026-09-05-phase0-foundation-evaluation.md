# Phase 0 Foundation + Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the new SQLite source-of-truth, immutable artifact/intake snapshot foundation, auditable Finding/Evidence/HumanDecision model, and first-class gold evaluation harness without breaking current review flows.

**Architecture:** Add the redesign as a parallel foundation beside the existing Neo4j/revision-oriented implementation. New domain records are persisted in SQLite using Python 3.12 stdlib `sqlite3`; large files live in a content-addressed local artifact store. Existing review models are connected through explicit adapters, while real Discord/Google Drive, Canonical Asset QA, Codex review, and product UI remain later phases.

**Tech Stack:** Python >=3.12, stdlib `sqlite3`, dataclasses/enums, pathlib/hashlib/json, FastAPI codebase conventions, pytest, existing `uv` workflow.

**Spec:** `docs/superpowers/specs/2026-09-05-archaeology-review-system-redesign-design.md`

## Global Constraints

- SQLite is the sole structured source of truth for the redesigned review domain.
- Artifact files are immutable and content-addressed by SHA256.
- Neo4j is not written by Phase 0 and must not be required by the new foundation tests.
- AI never establishes canonical truth; Phase 0 contains no live AI calls.
- Previous proof revisions are audit/cache inputs only, never semantic ground truth.
- Human decisions are append-only and separate from AI/deterministic findings.
- Evidence is immutable; a Finding may not cite a nonexistent Evidence record.
- No `AgentBudget`, automatic cost router, provider escalation policy, or silent paid-provider fallback is introduced.
- Discord/Google Drive integration is represented only by source-reference and snapshot interfaces in this phase; no network adapter is implemented.
- Do not modify user source files or `/src` corpus content.
- Keep current production flows operational; migration occurs through adapters, not a big-bang rewrite.
- CI stays hermetic; real `/src`, Neo4j, live AI, Discord, and Google Drive are not required for Phase 0 tests.

---

## File Map

New focused modules:

- `backend/app/domain/review_core.py` — ReviewRequest, AnalysisRun, Finding, Evidence, HumanDecision and enums/invariants.
- `backend/app/domain/intake.py` — DriveResource/IntakeSnapshot transport-neutral records.
- `backend/app/domain/evaluation.py` — gold case/evaluation result records.
- `backend/app/storage/sqlite_db.py` — connection factory and transaction helper.
- `backend/app/storage/schema.py` — idempotent schema initialization.
- `backend/app/storage/review_repository.py` — persistence for requests/snapshots/runs/findings/evidence/decisions.
- `backend/app/services/content_artifact_store.py` — content-addressed immutable file store.
- `backend/app/services/intake_snapshot_service.py` — transport-neutral source snapshotting.
- `backend/app/services/legacy_review_adapter.py` — one-way adapters from current domain types into the new root model.
- `backend/app/evaluation/finding_set_evaluator.py` — deterministic generic gold evaluator.
- `tools/evaluate_review_gold.py` — local/CI CLI for gold fixtures.

Existing files modified:

- `backend/app/config.py` — new SQLite/artifact paths only.
- `.env.example` — document path overrides.
- `.github/workflows/remediation-ci.yml` — add Phase 0 focused tests to hermetic backend job only if current job does not already run all backend tests.

No existing `review_models.py`, `ai_review_finding.py`, graph repository, orchestrator, parser, or asset matcher is deleted in Phase 0.

---

### Task 1: Define the New Review Domain Contracts

**Files:**
- Create: `backend/app/domain/review_core.py`
- Create: `backend/app/domain/intake.py`
- Create: `backend/app/domain/evaluation.py`
- Test: `backend/tests/test_review_core_domain.py`
- Test: `backend/tests/test_intake_domain.py`

**Interfaces:**
- Produces: `ReviewRequestData`, `ReviewRequestStatus`, `AnalysisRunData`, `AnalysisRuntime`, `FindingData`, `FindingStatus`, `EvidenceDataV2`, `FindingEvidenceData`, `HumanDecisionDataV2`, `DecisionValue`, `DriveResourceData`, `IntakeSnapshotData`, `GoldCaseData`, `EvaluationResultData`.
- Later tasks persist these exact dataclasses; do not rename fields after Task 1.

- [ ] **Step 1: Write failing domain invariant tests**

Create tests that assert valid construction and the fail-closed invariants:

```python
from app.domain.review_core import (
    DecisionValue,
    EvidenceDataV2,
    FindingData,
    FindingEvidenceData,
    HumanDecisionDataV2,
    ReviewRequestData,
    ReviewRequestStatus,
)


def test_review_request_starts_received():
    request = ReviewRequestData(id="R-1", project_id="P-1", source="DISCORD")
    assert request.status is ReviewRequestStatus.RECEIVED


def test_evidence_rejects_empty_source_identity_for_document_block():
    try:
        EvidenceDataV2(id="E-1", evidence_type="DOCUMENT_BLOCK", value="x")
    except ValueError as exc:
        assert "source_sha256" in str(exc)
    else:
        raise AssertionError("document evidence must require source_sha256")


def test_human_decision_requires_supported_value():
    decision = HumanDecisionDataV2(
        id="D-1",
        finding_id="F-1",
        decision=DecisionValue.ACCEPT,
        created_at="2026-09-05T00:00:00Z",
    )
    assert decision.decision is DecisionValue.ACCEPT
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --directory backend pytest tests/test_review_core_domain.py tests/test_intake_domain.py -v
```

Expected: collection/import failure because the new domain modules do not exist.

- [ ] **Step 3: Implement the minimal domain records and enums**

`review_core.py` must define, at minimum:

```python
class ReviewRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IMPORTING = "IMPORTING"
    WAITING_CANONICAL_APPROVAL = "WAITING_CANONICAL_APPROVAL"
    ANALYZING = "ANALYZING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    REVIEWING = "REVIEWING"
    FINALIZED = "FINALIZED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class AnalysisRuntime(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    CODEX_SDK = "CODEX_SDK"
    DIRECT_API = "DIRECT_API"


class FindingStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    REVIEWED = "REVIEWED"


class DecisionValue(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    MODIFY = "MODIFY"
    DEFER = "DEFER"
```

`EvidenceDataV2` must validate document-bound evidence types (`DOCUMENT_BLOCK`, `RULE_RESULT`, `AGENT_OBSERVATION`) require `source_sha256`; canonical evidence types may instead carry `canonical_fact_id` or `canonical_asset_id`.

`FindingEvidenceData` fields are exactly `finding_id`, `evidence_id`, `role`, where role is one of `SUPPORTS`, `CONTRADICTS`, `CONTEXT`.

`intake.py` must include immutable `DriveResourceData` fields:

```python
id: str
source_ref: str
external_file_id: str
name: str
mime_type: str
modified_time: str | None
size: int
local_sha256: str
artifact_uri: str
role: Literal["CANONICAL", "PROOF"]
```

and `IntakeSnapshotData` fields `id`, `request_id`, `source_hash`, `resource_ids`, `created_at`.

`evaluation.py` must define a generic gold case that does not pretend to know Phase 1-3 metrics:

```python
@dataclass(frozen=True, slots=True)
class GoldCaseData:
    id: str
    engine: str
    expected_finding_types: tuple[str, ...]
    expected_entity_id: str | None = None
```

- [ ] **Step 4: Run domain tests to GREEN**

Run the same pytest command. Expected: all new domain tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/review_core.py backend/app/domain/intake.py backend/app/domain/evaluation.py backend/tests/test_review_core_domain.py backend/tests/test_intake_domain.py
git commit -m "feat: add review foundation domain contracts"
```

---

### Task 2: Add SQLite Configuration, Connection, and Idempotent Schema

**Files:**
- Create: `backend/app/storage/__init__.py`
- Create: `backend/app/storage/sqlite_db.py`
- Create: `backend/app/storage/schema.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_sqlite_review_schema.py`

**Interfaces:**
- Consumes: Task 1 field names.
- Produces: `connect_review_db(path: Path) -> sqlite3.Connection`, `initialize_review_schema(conn: sqlite3.Connection) -> None`, `review_db_path() -> Path`, `review_artifact_root() -> Path`.

- [ ] **Step 1: Write failing schema tests**

```python
import sqlite3

from app.storage.schema import initialize_review_schema


def test_schema_is_idempotent_and_enables_foreign_keys(tmp_path):
    conn = sqlite3.connect(tmp_path / "review.sqlite3")
    initialize_review_schema(conn)
    initialize_review_schema(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "review_requests",
        "intake_snapshots",
        "drive_resources",
        "analysis_runs",
        "evidence",
        "findings",
        "finding_evidence",
        "human_decisions",
        "artifacts",
        "evaluation_runs",
        "evaluation_results",
    } <= tables
```

Add a second test asserting foreign-key insertion fails when `finding_evidence.evidence_id` does not exist.

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_sqlite_review_schema.py -v
```

Expected: import failure for `app.storage`.

- [ ] **Step 3: Implement connection/config/schema**

In `config.py`, add only path settings:

```python
def review_db_path() -> Path:
    return Path(os.environ.get("REVIEW_DB_PATH", "").strip() or DATA_ROOT / "review.sqlite3")


def review_artifact_root() -> Path:
    return Path(os.environ.get("REVIEW_ARTIFACT_ROOT", "").strip() or DATA_ROOT / "artifacts")
```

In `sqlite_db.py`:

```python
def connect_review_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
```

In `schema.py`, create the tables named in Step 1 with explicit foreign keys. Store enum values as TEXT. Add uniqueness constraints on `finding_evidence(finding_id, evidence_id, role)` and `artifacts(sha256, kind)`; make `human_decisions.id` primary key and never define an update trigger/API.

Update `.env.example` with:

```text
REVIEW_DB_PATH=/data/review.sqlite3
REVIEW_ARTIFACT_ROOT=/data/artifacts
```

- [ ] **Step 4: Run schema tests and config tests**

```bash
uv run --directory backend pytest tests/test_sqlite_review_schema.py tests/test_config.py -v
```

Expected: PASS. If `tests/test_config.py` does not exist, run only `test_sqlite_review_schema.py` and the full backend suite in Step 5 before commit.

- [ ] **Step 5: Run backend regression and commit**

```bash
uv run --directory backend pytest -q
```

Expected: existing suite remains green with existing intentional skips/xfails.

```bash
git add backend/app/storage backend/app/config.py .env.example backend/tests/test_sqlite_review_schema.py
git commit -m "feat: add sqlite review source of truth"
```

---

### Task 3: Implement Transactional Review Repository and State Transitions

**Files:**
- Create: `backend/app/storage/review_repository.py`
- Create: `backend/app/services/review_request_service.py`
- Test: `backend/tests/test_review_repository.py`
- Test: `backend/tests/test_review_request_service.py`

**Interfaces:**
- Consumes: `connect_review_db`, Task 1 dataclasses.
- Produces repository methods:
  - `create_request(request: ReviewRequestData) -> None`
  - `get_request(request_id: str) -> ReviewRequestData | None`
  - `save_snapshot(snapshot: IntakeSnapshotData, resources: Sequence[DriveResourceData]) -> None`
  - `create_analysis_run(run: AnalysisRunData) -> None`
  - `add_evidence(evidence: EvidenceDataV2) -> None`
  - `create_finding(finding: FindingData, links: Sequence[FindingEvidenceData]) -> None`
  - `append_human_decision(decision: HumanDecisionDataV2) -> None`
  - `list_finding_evidence(finding_id: str) -> list[EvidenceDataV2]`
- Produces service method `transition_request(request_id: str, target: ReviewRequestStatus) -> ReviewRequestData`.

- [ ] **Step 1: Write failing repository/state tests**

Test atomic evidence validation:

```python
def test_create_finding_fails_if_linked_evidence_missing(repo):
    finding = FindingData(
        id="F-1",
        revision_id="REV-1",
        engine="EDITORIAL_QA",
        finding_type="TYPO",
        status=FindingStatus.PENDING_REVIEW,
        analysis_run_id="RUN-1",
        created_at="2026-09-05T00:00:00Z",
    )
    with pytest.raises(ValueError, match="evidence"):
        repo.create_finding(
            finding,
            [FindingEvidenceData("F-1", "E-MISSING", "SUPPORTS")],
        )
```

Test state rules:

```python
def test_request_cannot_jump_from_received_to_published(service):
    with pytest.raises(ValueError, match="invalid transition"):
        service.transition_request("R-1", ReviewRequestStatus.PUBLISHED)
```

Allowed transitions must be exactly:

```python
{
    RECEIVED: {IMPORTING, FAILED},
    IMPORTING: {WAITING_CANONICAL_APPROVAL, ANALYZING, FAILED},
    WAITING_CANONICAL_APPROVAL: {ANALYZING, FAILED},
    ANALYZING: {READY_FOR_REVIEW, FAILED},
    READY_FOR_REVIEW: {REVIEWING, FAILED},
    REVIEWING: {FINALIZED, FAILED},
    FINALIZED: {PUBLISHED, FAILED},
    PUBLISHED: set(),
    FAILED: set(),
}
```

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_review_repository.py tests/test_review_request_service.py -v
```

Expected: import failures.

- [ ] **Step 3: Implement repository with explicit transactions**

Use `with self._conn:` for every multi-row write. `create_finding` must first query all evidence IDs and raise before inserting the Finding if any are missing. `append_human_decision` inserts only; it must not update or delete an older decision row.

`ReviewRequestService.transition_request` loads current state, checks the exact map above, updates the request status in one transaction, and returns the refreshed record.

- [ ] **Step 4: Run focused and foreign-key tests**

```bash
uv run --directory backend pytest tests/test_review_repository.py tests/test_review_request_service.py tests/test_sqlite_review_schema.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/review_repository.py backend/app/services/review_request_service.py backend/tests/test_review_repository.py backend/tests/test_review_request_service.py
git commit -m "feat: persist auditable review records"
```

---

### Task 4: Add the Content-Addressed Immutable Artifact Store

**Files:**
- Create: `backend/app/services/content_artifact_store.py`
- Test: `backend/tests/test_content_artifact_store.py`

**Interfaces:**
- Produces `StoredArtifact` and `ContentArtifactStore` methods:
  - `put_bytes(data: bytes, *, kind: str, suffix: str = "") -> StoredArtifact`
  - `put_file(source: Path, *, kind: str) -> StoredArtifact`
  - `path_for(artifact: StoredArtifact) -> Path`
  - `verify(artifact: StoredArtifact) -> bool`
- Storage path format is `<root>/<kind>/<sha256[:2]>/<sha256><suffix>`.

- [ ] **Step 1: Write failing immutability/dedupe tests**

```python
def test_same_content_reuses_same_artifact(tmp_path):
    store = ContentArtifactStore(tmp_path)
    a = store.put_bytes(b"canonical", kind="intake", suffix=".bin")
    b = store.put_bytes(b"canonical", kind="intake", suffix=".bin")
    assert a.sha256 == b.sha256
    assert a.uri == b.uri


def test_verify_detects_mutated_artifact(tmp_path):
    store = ContentArtifactStore(tmp_path)
    artifact = store.put_bytes(b"proof", kind="intake", suffix=".pdf")
    store.path_for(artifact).write_bytes(b"tampered")
    assert store.verify(artifact) is False
```

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_content_artifact_store.py -v
```

- [ ] **Step 3: Implement atomic write-by-hash**

Use SHA256 of raw bytes, create parent directory, write to a sibling temp file, then `Path.replace()` only when destination does not exist. If destination exists, do not overwrite it. Return:

```python
@dataclass(frozen=True, slots=True)
class StoredArtifact:
    sha256: str
    kind: str
    uri: str
    size: int
```

`verify()` must recompute SHA256 from disk and compare to the stored digest.

- [ ] **Step 4: Run artifact tests**

```bash
uv run --directory backend pytest tests/test_content_artifact_store.py -v
```

Expected: PASS on repeated writes and mutation detection.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/content_artifact_store.py backend/tests/test_content_artifact_store.py
git commit -m "feat: add immutable content artifact store"
```

---

### Task 5: Add Transport-Neutral Intake Snapshotting with a Local Fixture Source

**Files:**
- Create: `backend/app/services/intake_snapshot_service.py`
- Create: `backend/tests/fixtures/intake/canonical/photo-001.jpg`
- Create: `backend/tests/fixtures/intake/proof/proof.txt`
- Test: `backend/tests/test_intake_snapshot_service.py`

**Interfaces:**
- Consumes: `ContentArtifactStore`, `DriveResourceData`, `IntakeSnapshotData`, repository `save_snapshot`.
- Produces `ExternalResourceSource` protocol and `LocalFixtureResourceSource` test implementation.
- `ExternalResourceSource.list(ref: str, role: str) -> Sequence[ExternalResourceMeta]`
- `ExternalResourceSource.read(file_id: str) -> bytes`
- `IntakeSnapshotService.create_snapshot(request_id: str, canonical_ref: str, proof_ref: str) -> IntakeSnapshotData`.

- [ ] **Step 1: Write failing snapshot reproducibility tests**

```python
def test_snapshot_hash_depends_on_downloaded_content_not_mutable_path(service, source):
    first = service.create_snapshot("R-1", "canonical", "proof")
    source.replace_bytes("proof/proof.txt", b"changed")
    second = service.create_snapshot("R-2", "canonical", "proof")
    assert first.source_hash != second.source_hash


def test_snapshot_records_canonical_and_proof_roles(service, repo):
    snap = service.create_snapshot("R-1", "canonical", "proof")
    resources = repo.list_snapshot_resources(snap.id)
    assert {r.role for r in resources} == {"CANONICAL", "PROOF"}
```

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_intake_snapshot_service.py -v
```

- [ ] **Step 3: Implement source protocol and snapshot algorithm**

The service must:

1. enumerate canonical and proof metadata through the protocol;
2. download each resource once;
3. persist bytes to `ContentArtifactStore(kind="intake")`;
4. create `DriveResourceData` using the resulting SHA/URI;
5. compute `source_hash = sha256("\0".join(sorted(role + ":" + local_sha256)))`;
6. set snapshot ID to `snapshot:{request_id}:{source_hash[:16]}`;
7. save snapshot/resources transactionally through `ReviewRepository`.

`LocalFixtureResourceSource` accepts a root `Path` and treats `canonical_ref`/`proof_ref` as relative directories. It exists only for hermetic tests and early local development.

- [ ] **Step 4: Run snapshot and artifact tests**

```bash
uv run --directory backend pytest tests/test_intake_snapshot_service.py tests/test_content_artifact_store.py -v
```

Expected: PASS without network access.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/intake_snapshot_service.py backend/tests/test_intake_snapshot_service.py backend/tests/fixtures/intake
git commit -m "feat: snapshot immutable review inputs"
```

---

### Task 6: Add One-Way Legacy Adapters Without Changing Existing Flows

**Files:**
- Create: `backend/app/services/legacy_review_adapter.py`
- Test: `backend/tests/test_legacy_review_adapter.py`

**Interfaces:**
- Consumes existing `app.domain.review_models.EvidenceData`, `CorrectionCandidateData`, and `app.domain.ai_review_finding.AIReviewFindingData`.
- Produces:
  - `adapt_legacy_evidence(value, *, new_id: str) -> EvidenceDataV2`
  - `adapt_correction_candidate(value, *, revision_id: str, analysis_run_id: str) -> tuple[FindingData, list[EvidenceDataV2], list[FindingEvidenceData]]`
  - `adapt_ai_review_finding(value, *, revision_id: str) -> FindingData`
- No function converts a new Finding back into a legacy correction candidate.

- [ ] **Step 1: Write failing safety adapter tests**

```python
def test_filename_or_caption_heuristic_is_not_promoted_by_adapter():
    legacy = CorrectionCandidateData(
        candidate_id="C-1",
        rule_category="figure_plate_table_photo_ref",
        evidence=EvidenceData(
            id="old-E",
            kind="reference",
            source_sha256="abc",
            document_version_id="REV-1",
            page_id="p1",
            method="filename_only",
            value="도판 1",
            confidence=0.99,
        ),
    )
    finding, evidence, links = adapt_correction_candidate(
        legacy,
        revision_id="REV-1",
        analysis_run_id="RUN-1",
    )
    assert finding.status is FindingStatus.PENDING_REVIEW
    assert evidence[0].evidence_type != "CANONICAL_ASSET"
```

Also assert AI adapter preserves model provenance only through `analysis_run_id`/finding association and does not create canonical evidence from `rationale`.

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_legacy_review_adapter.py -v
```

- [ ] **Step 3: Implement explicit mapping tables**

Map legacy evidence kinds conservatively:

```python
LEGACY_EVIDENCE_TYPE = {
    "text_claim": "DOCUMENT_BLOCK",
    "reference": "DOCUMENT_BLOCK",
    "plate_caption": "DOCUMENT_BLOCK",
    "drawing_caption": "DOCUMENT_BLOCK",
    "vlm_observation": "AGENT_OBSERVATION",
    "rule_finding": "RULE_RESULT",
    "version_change": "RULE_RESULT",
}
```

No legacy evidence kind maps to `CANONICAL_FACT` or `CANONICAL_ASSET` unless a future phase supplies an explicit approved canonical ID. Preserve old IDs/value/rationale/method as audit fields where the new record allows them.

- [ ] **Step 4: Run adapter plus existing model tests**

```bash
uv run --directory backend pytest tests/test_legacy_review_adapter.py tests/test_review_models.py -v
```

If `tests/test_review_models.py` is not present, run `pytest -q` before commit.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/legacy_review_adapter.py backend/tests/test_legacy_review_adapter.py
git commit -m "feat: bridge legacy findings into review foundation"
```

---

### Task 7: Build the Generic Gold Evaluation Harness and Persist Evaluation Runs

**Files:**
- Create: `backend/app/evaluation/__init__.py`
- Create: `backend/app/evaluation/finding_set_evaluator.py`
- Create: `backend/tests/fixtures/gold/foundation_findings.json`
- Create: `backend/tests/test_finding_set_evaluator.py`
- Create: `tools/evaluate_review_gold.py`
- Modify: `backend/app/storage/review_repository.py`
- Test: `backend/tests/test_evaluation_repository.py`

**Interfaces:**
- Consumes: `GoldCaseData`, `FindingData`, SQLite evaluation tables.
- Produces:
  - `evaluate_finding_types(cases: Sequence[GoldCaseData], predictions: Mapping[str, Sequence[FindingData]]) -> EvaluationResultData`
  - repository `create_evaluation_run(...)`, `save_evaluation_result(...)`.
- CLI input is a JSON fixture plus optional predictions JSON; no model/network invocation.

- [ ] **Step 1: Write failing precision/recall tests**

```python
def test_finding_set_metrics_count_tp_fp_fn():
    cases = [
        GoldCaseData("case-1", "EDITORIAL_QA", ("TYPO", "DOCUMENT_INTERNAL_CONTRADICTION")),
        GoldCaseData("case-2", "EDITORIAL_QA", ("TYPO",)),
    ]
    predictions = {
        "case-1": [finding("TYPO"), finding("GRAMMAR")],
        "case-2": [finding("TYPO")],
    }
    result = evaluate_finding_types(cases, predictions)
    assert result.true_positive == 2
    assert result.false_positive == 1
    assert result.false_negative == 1
    assert result.precision == pytest.approx(2 / 3)
    assert result.recall == pytest.approx(2 / 3)
```

Add a test where `cases=[]` and require `ValueError("gold cases required")`; this permanently prevents precision/recall claims without gold.

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_finding_set_evaluator.py tests/test_evaluation_repository.py -v
```

- [ ] **Step 3: Implement evaluator, persistence, and deterministic CLI**

The evaluator compares `(case_id, finding_type)` pairs only. It does not score Asset Top-1, entity-link accuracy, or canonical contradiction semantics; those specialized metrics belong to Phases 1-3.

Fixture format:

```json
{
  "suite_id": "foundation-smoke-v1",
  "cases": [
    {"id": "case-typo", "engine": "EDITORIAL_QA", "expected_finding_types": ["TYPO"]},
    {"id": "case-clean", "engine": "EDITORIAL_QA", "expected_finding_types": []}
  ]
}
```

CLI:

```bash
uv run --directory backend python ../tools/evaluate_review_gold.py \
  --gold tests/fixtures/gold/foundation_findings.json \
  --predictions tests/fixtures/gold/foundation_predictions.json
```

It prints JSON containing `suite_id`, `true_positive`, `false_positive`, `false_negative`, `precision`, and `recall`, and exits nonzero on malformed/no-gold input.

- [ ] **Step 4: Run evaluator tests and CLI**

```bash
uv run --directory backend pytest tests/test_finding_set_evaluator.py tests/test_evaluation_repository.py -v
uv run --directory backend python ../tools/evaluate_review_gold.py --gold tests/fixtures/gold/foundation_findings.json --predictions tests/fixtures/gold/foundation_predictions.json
```

Expected: tests PASS and CLI emits deterministic JSON.

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation backend/app/storage/review_repository.py backend/tests/test_finding_set_evaluator.py backend/tests/test_evaluation_repository.py backend/tests/fixtures/gold tools/evaluate_review_gold.py
git commit -m "feat: add gold review evaluation harness"
```

---

### Task 8: Prove the Phase 0 End-to-End Foundation Flow

**Files:**
- Create: `backend/tests/integration/test_review_foundation_flow.py`
- Modify: `.github/workflows/remediation-ci.yml` only if needed to ensure this test runs in the hermetic backend job.

**Interfaces:**
- Consumes all Phase 0 components.
- Produces one acceptance contract: local source refs -> immutable snapshot -> deterministic analysis run -> evidence-backed finding -> append-only human decision -> persisted evaluation result.

- [ ] **Step 1: Write the end-to-end failing test**

The test must perform this exact sequence against `tmp_path`:

```python
request = ReviewRequestData(id="R-E2E", project_id="P-1", source="DISCORD")
repo.create_request(request)
service.transition_request("R-E2E", ReviewRequestStatus.IMPORTING)

snapshot = intake.create_snapshot("R-E2E", "canonical", "proof")
service.transition_request("R-E2E", ReviewRequestStatus.ANALYZING)

run = AnalysisRunData(
    id="RUN-E2E",
    request_id="R-E2E",
    task_type="foundation-smoke",
    runtime=AnalysisRuntime.DETERMINISTIC,
    status="COMPLETED",
    started_at="2026-09-05T00:00:00Z",
    completed_at="2026-09-05T00:00:01Z",
)
repo.create_analysis_run(run)

evidence = EvidenceDataV2(
    id="E-E2E",
    evidence_type="DOCUMENT_BLOCK",
    source_sha256=repo.list_snapshot_resources(snapshot.id)[-1].local_sha256,
    value="오타 문장",
    method="fixture",
)
repo.add_evidence(evidence)
repo.create_finding(
    FindingData(
        id="F-E2E",
        revision_id="REV-E2E",
        engine="EDITORIAL_QA",
        finding_type="TYPO",
        status=FindingStatus.PENDING_REVIEW,
        analysis_run_id="RUN-E2E",
        created_at="2026-09-05T00:00:01Z",
    ),
    [FindingEvidenceData("F-E2E", "E-E2E", "SUPPORTS")],
)
repo.append_human_decision(
    HumanDecisionDataV2(
        id="D-E2E",
        finding_id="F-E2E",
        decision=DecisionValue.ACCEPT,
        created_at="2026-09-05T00:00:02Z",
    )
)
```

Then assert the artifact verifies, the finding resolves to the evidence, the decision remains a separate row, and a one-case gold evaluation produces precision/recall 1.0.

- [ ] **Step 2: Run RED/GREEN cycle**

Run before any fixes:

```bash
uv run --directory backend pytest tests/integration/test_review_foundation_flow.py -v
```

If it fails because of integration mismatches, make only the minimum fixes in the Phase 0 modules; do not modify graph/AI/asset production paths to satisfy this test.

Run again until PASS.

- [ ] **Step 3: Run all Phase 0 tests together**

```bash
uv run --directory backend pytest \
  tests/test_review_core_domain.py \
  tests/test_intake_domain.py \
  tests/test_sqlite_review_schema.py \
  tests/test_review_repository.py \
  tests/test_review_request_service.py \
  tests/test_content_artifact_store.py \
  tests/test_intake_snapshot_service.py \
  tests/test_legacy_review_adapter.py \
  tests/test_finding_set_evaluator.py \
  tests/test_evaluation_repository.py \
  tests/integration/test_review_foundation_flow.py -v
```

Expected: PASS with no network, Neo4j, `/src`, or API credentials.

- [ ] **Step 4: Run full backend regression suite**

```bash
uv run --directory backend pytest -q
```

Expected: no new failures beyond existing intentional skips/xfails documented by current test configuration.

If the hermetic CI job already runs `pytest`, no workflow change is needed. If it filters tests and would omit the new integration test, update `.github/workflows/remediation-ci.yml` so the backend hermetic job includes `tests/integration/test_review_foundation_flow.py` without adding external services.

- [ ] **Step 5: Commit Phase 0 acceptance**

```bash
git add backend/tests/integration/test_review_foundation_flow.py .github/workflows/remediation-ci.yml
git commit -m "test: lock phase zero review foundation acceptance"
```

---

## Phase 0 Completion Gate

Phase 0 is complete only when all of the following are demonstrated by tests/CI:

- SQLite initializes idempotently and enforces foreign keys.
- ReviewRequest transitions fail closed on illegal jumps.
- Intake content is copied into an immutable SHA256 artifact store before analysis.
- Snapshot identity changes when downloaded source content changes.
- Findings cannot be persisted with missing evidence.
- Human decisions are append-only records separate from Findings.
- Legacy filename/path/caption/VLM evidence is not silently promoted into canonical truth by adapters.
- Evaluation refuses to report precision/recall without gold cases.
- The complete Phase 0 integration flow runs without Neo4j, live AI, Discord, Google Drive, or `/src`.
- The existing backend regression suite remains green.

## Explicit Non-Goals for This Plan

The following are intentionally deferred to separate implementation plans:

- CanonicalAsset/CanonicalMetadata/CanonicalEntity/CanonicalFact production flows.
- Persistent SIFT feature generation and incremental Asset QA.
- Codex SDK runtime, Luna max/xhigh, ReviewToolGateway, or Direct API runtime.
- EntityMention/DocumentClaim extraction and B1 whole-document contradiction analysis.
- B2 canonical fact comparison and Neo4j projection redesign.
- Real Discord bot commands/events.
- Real Google Drive authentication/list/download/upload.
- Review Web UI.
- PDF/XLSX/annotated PDF/JSON ReviewPackage publication.
- HWP/HWPX acceptance.
