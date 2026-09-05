# Phase 0 Foundation + Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the new SQLite source-of-truth, immutable artifact/intake snapshot foundation, auditable Finding/Evidence/HumanDecision model, and first-class gold evaluation harness without breaking current review flows.

**Architecture:** Build the redesign as a parallel foundation beside the existing Neo4j/revision-oriented implementation. New structured records persist in SQLite through stdlib `sqlite3`; large immutable inputs and derived files live in a content-addressed local artifact store. Existing review models connect through one-way adapters, while real Discord/Google Drive, Canonical Asset QA, Codex review, and product UI remain later phases.

**Tech Stack:** Python >=3.12, stdlib `sqlite3`, dataclasses/enums, pathlib/hashlib/json, existing FastAPI codebase conventions, pytest, existing `uv` workflow.

**Spec:** `docs/superpowers/specs/2026-09-05-archaeology-review-system-redesign-design.md`

## Global Constraints

- SQLite is the sole structured source of truth for the redesigned review domain.
- Artifact files are immutable and content-addressed by SHA256.
- Neo4j is not written by Phase 0 and is not required by Phase 0 tests.
- Phase 0 makes no live AI, Discord, or Google Drive calls.
- Previous proof revisions are audit/cache inputs only, never semantic ground truth.
- Human decisions are append-only records separate from findings.
- Evidence is immutable; a finding cannot be persisted with missing evidence IDs.
- No AgentBudget, automatic cost router, provider escalation policy, or silent paid-provider fallback is added.
- Do not modify `/src` or any user source file.
- Existing production flows stay operational; migration is via adapters, not a big-bang rewrite.
- CI remains hermetic.

---

## File Map

Create:

- `backend/app/domain/review_core.py` — request/run/finding/evidence/decision contracts.
- `backend/app/domain/intake.py` — transport-neutral resource/snapshot contracts.
- `backend/app/domain/evaluation.py` — generic gold/evaluation contracts.
- `backend/app/storage/__init__.py` — storage package marker.
- `backend/app/storage/sqlite_db.py` — SQLite connection factory.
- `backend/app/storage/schema.py` — idempotent schema initializer.
- `backend/app/storage/review_repository.py` — transactional persistence.
- `backend/app/services/review_request_service.py` — request state machine.
- `backend/app/services/content_artifact_store.py` — immutable content-addressed files.
- `backend/app/services/intake_snapshot_service.py` — source-ref snapshotting.
- `backend/app/services/legacy_review_adapter.py` — one-way migration adapters.
- `backend/app/evaluation/__init__.py` — evaluation package marker.
- `backend/app/evaluation/finding_set_evaluator.py` — deterministic generic evaluator.
- `tools/evaluate_review_gold.py` — gold evaluation CLI.

Modify only when required by a task:

- `backend/app/config.py`
- `.env.example`
- `.github/workflows/remediation-ci.yml`

Do not delete or rewrite existing `review_models.py`, `ai_review_finding.py`, graph repositories, orchestrators, parsers, or asset matching services in Phase 0.

---

### Task 1: Define the New Review Domain Contracts

**Files:**
- Create: `backend/app/domain/review_core.py`
- Create: `backend/app/domain/intake.py`
- Create: `backend/app/domain/evaluation.py`
- Test: `backend/tests/test_review_core_domain.py`
- Test: `backend/tests/test_intake_domain.py`

**Interfaces:**
- Produces all dataclasses/enums shown below. Later tasks must use these exact names and fields.

- [ ] **Step 1: Write failing invariant tests**

```python
from app.domain.review_core import (
    DecisionValue,
    EvidenceDataV2,
    HumanDecisionDataV2,
    ReviewRequestData,
    ReviewRequestStatus,
)


def test_review_request_defaults_to_received():
    value = ReviewRequestData(id="R-1", project_id="P-1", source="DISCORD")
    assert value.status is ReviewRequestStatus.RECEIVED


def test_document_evidence_requires_source_sha256():
    try:
        EvidenceDataV2(id="E-1", evidence_type="DOCUMENT_BLOCK", value="x")
    except ValueError as exc:
        assert "source_sha256" in str(exc)
    else:
        raise AssertionError("document-bound evidence must fail closed")


def test_human_decision_is_separate_record():
    value = HumanDecisionDataV2(
        id="D-1",
        finding_id="F-1",
        decision=DecisionValue.ACCEPT,
        created_at="2026-09-05T00:00:00Z",
    )
    assert value.decision is DecisionValue.ACCEPT
```

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_review_core_domain.py tests/test_intake_domain.py -v
```

Expected: import failure because the new modules do not exist.

- [ ] **Step 3: Implement exact domain contracts**

`backend/app/domain/review_core.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


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


@dataclass(frozen=True, slots=True)
class ReviewRequestData:
    id: str
    project_id: str
    source: str
    status: ReviewRequestStatus = ReviewRequestStatus.RECEIVED
    canonical_source_ref: str | None = None
    proof_source_ref: str | None = None
    intake_snapshot_id: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisRunData:
    id: str
    request_id: str
    task_type: str
    runtime: AnalysisRuntime
    status: str
    provider: str | None = None
    endpoint_profile: str | None = None
    model: str | None = None
    reasoning_level: str | None = None
    prompt_version: str | None = None
    toolset_version: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceDataV2:
    id: str
    evidence_type: str
    value: Any
    method: str = "unknown"
    source_sha256: str | None = None
    document_revision_id: str | None = None
    page_id: str | None = None
    block_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    canonical_fact_id: str | None = None
    canonical_asset_id: str | None = None
    analysis_run_id: str | None = None
    rationale: str | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.evidence_type in {"DOCUMENT_BLOCK", "RULE_RESULT", "AGENT_OBSERVATION"}:
            if not self.source_sha256:
                raise ValueError("source_sha256 is required for document-bound evidence")
        if self.evidence_type == "CANONICAL_FACT" and not self.canonical_fact_id:
            raise ValueError("canonical_fact_id is required for canonical fact evidence")
        if self.evidence_type == "CANONICAL_ASSET" and not self.canonical_asset_id:
            raise ValueError("canonical_asset_id is required for canonical asset evidence")


@dataclass(frozen=True, slots=True)
class FindingData:
    id: str
    request_id: str
    engine: str
    finding_type: str
    status: FindingStatus = FindingStatus.PENDING_REVIEW
    revision_id: str | None = None
    severity: str = "medium"
    subject_entity_id: str | None = None
    canonical_entity_id: str | None = None
    original_text: str | None = None
    suggested_text: str | None = None
    analysis_run_id: str | None = None
    fingerprint: str | None = None
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class FindingEvidenceData:
    finding_id: str
    evidence_id: str
    role: str

    def __post_init__(self) -> None:
        if self.role not in {"SUPPORTS", "CONTRADICTS", "CONTEXT"}:
            raise ValueError("invalid finding evidence role")


@dataclass(frozen=True, slots=True)
class HumanDecisionDataV2:
    id: str
    finding_id: str
    decision: DecisionValue
    created_at: str
    reviewer: str = ""
    note: str = ""
    modified_text: str | None = None
    previous_decision_id: str | None = None
```

`backend/app/domain/intake.py`:

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class DriveResourceData:
    id: str
    snapshot_id: str
    source_ref: str
    external_file_id: str
    name: str
    mime_type: str
    modified_time: str | None
    size: int
    local_sha256: str
    artifact_uri: str
    role: Literal["CANONICAL", "PROOF"]


@dataclass(frozen=True, slots=True)
class IntakeSnapshotData:
    id: str
    request_id: str
    source_hash: str
    resource_ids: tuple[str, ...]
    created_at: str
```

`backend/app/domain/evaluation.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GoldCaseData:
    id: str
    engine: str
    expected_finding_types: tuple[str, ...]
    expected_entity_id: str | None = None


@dataclass(frozen=True, slots=True)
class EvaluationResultData:
    run_id: str
    suite_id: str
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    false_positives_per_case: float
```

- [ ] **Step 4: Run GREEN**

```bash
uv run --directory backend pytest tests/test_review_core_domain.py tests/test_intake_domain.py -v
```

Expected: PASS.

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
- Create: `backend/tests/test_review_config.py`
- Create: `backend/tests/test_sqlite_review_schema.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces `review_db_path() -> Path`, `review_artifact_root() -> Path`, `connect_review_db(path: Path) -> sqlite3.Connection`, `initialize_review_schema(conn) -> None`.

- [ ] **Step 1: Write failing config/schema tests**

```python
def test_review_paths_follow_environment(monkeypatch, tmp_path):
    db = tmp_path / "state.sqlite3"
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("REVIEW_DB_PATH", str(db))
    monkeypatch.setenv("REVIEW_ARTIFACT_ROOT", str(artifacts))
    assert review_db_path() == db
    assert review_artifact_root() == artifacts
```

```python
def test_schema_is_idempotent_and_enforces_foreign_keys(tmp_path):
    conn = connect_review_db(tmp_path / "review.sqlite3")
    initialize_review_schema(conn)
    initialize_review_schema(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "review_requests", "intake_snapshots", "drive_resources", "analysis_runs",
        "evidence", "findings", "finding_evidence", "human_decisions", "artifacts",
        "evaluation_runs", "evaluation_results",
    } <= tables
```

Add one test that inserts a `finding_evidence` row with a missing evidence ID and asserts `sqlite3.IntegrityError`.

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_review_config.py tests/test_sqlite_review_schema.py -v
```

Expected: import failures.

- [ ] **Step 3: Implement config/connection/schema**

Add to `backend/app/config.py`:

```python
def review_db_path() -> Path:
    raw = os.environ.get("REVIEW_DB_PATH", "").strip()
    return Path(raw) if raw else DATA_ROOT / "review.sqlite3"


def review_artifact_root() -> Path:
    raw = os.environ.get("REVIEW_ARTIFACT_ROOT", "").strip()
    return Path(raw) if raw else DATA_ROOT / "artifacts"
```

`sqlite_db.py`:

```python
import sqlite3
from pathlib import Path


def connect_review_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
```

`schema.py` must execute one `SCHEMA_SQL` string with these tables/keys:

```sql
CREATE TABLE IF NOT EXISTS review_requests (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  canonical_source_ref TEXT,
  proof_source_ref TEXT,
  intake_snapshot_id TEXT,
  created_at TEXT,
  completed_at TEXT
);
CREATE TABLE IF NOT EXISTS intake_snapshots (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES review_requests(id),
  source_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drive_resources (
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL REFERENCES intake_snapshots(id),
  source_ref TEXT NOT NULL,
  external_file_id TEXT NOT NULL,
  name TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  modified_time TEXT,
  size INTEGER NOT NULL,
  local_sha256 TEXT NOT NULL,
  artifact_uri TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('CANONICAL','PROOF'))
);
CREATE TABLE IF NOT EXISTS analysis_runs (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES review_requests(id),
  task_type TEXT NOT NULL,
  runtime TEXT NOT NULL,
  status TEXT NOT NULL,
  provider TEXT, endpoint_profile TEXT, model TEXT, reasoning_level TEXT,
  prompt_version TEXT, toolset_version TEXT, input_hash TEXT, output_hash TEXT,
  started_at TEXT, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  evidence_type TEXT NOT NULL,
  value_json TEXT NOT NULL,
  method TEXT NOT NULL,
  source_sha256 TEXT,
  document_revision_id TEXT,
  page_id TEXT,
  block_id TEXT,
  bbox_json TEXT,
  canonical_fact_id TEXT,
  canonical_asset_id TEXT,
  analysis_run_id TEXT REFERENCES analysis_runs(id),
  rationale TEXT,
  confidence REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES review_requests(id),
  engine TEXT NOT NULL,
  finding_type TEXT NOT NULL,
  status TEXT NOT NULL,
  revision_id TEXT,
  severity TEXT NOT NULL,
  subject_entity_id TEXT,
  canonical_entity_id TEXT,
  original_text TEXT,
  suggested_text TEXT,
  analysis_run_id TEXT REFERENCES analysis_runs(id),
  fingerprint TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS finding_evidence (
  finding_id TEXT NOT NULL REFERENCES findings(id),
  evidence_id TEXT NOT NULL REFERENCES evidence(id),
  role TEXT NOT NULL CHECK(role IN ('SUPPORTS','CONTRADICTS','CONTEXT')),
  PRIMARY KEY(finding_id, evidence_id, role)
);
CREATE TABLE IF NOT EXISTS human_decisions (
  id TEXT PRIMARY KEY,
  finding_id TEXT NOT NULL REFERENCES findings(id),
  decision TEXT NOT NULL CHECK(decision IN ('ACCEPT','REJECT','MODIFY','DEFER')),
  created_at TEXT NOT NULL,
  reviewer TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  modified_text TEXT,
  previous_decision_id TEXT REFERENCES human_decisions(id)
);
CREATE TABLE IF NOT EXISTS artifacts (
  sha256 TEXT NOT NULL,
  kind TEXT NOT NULL,
  uri TEXT NOT NULL,
  size INTEGER NOT NULL,
  PRIMARY KEY(sha256, kind)
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
  id TEXT PRIMARY KEY,
  suite_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_results (
  run_id TEXT PRIMARY KEY REFERENCES evaluation_runs(id),
  suite_id TEXT NOT NULL,
  true_positive INTEGER NOT NULL,
  false_positive INTEGER NOT NULL,
  false_negative INTEGER NOT NULL,
  precision REAL NOT NULL,
  recall REAL NOT NULL,
  false_positives_per_case REAL NOT NULL
);
```

`initialize_review_schema` enables foreign keys and calls `conn.executescript(SCHEMA_SQL)`.

Update `.env.example`:

```text
REVIEW_DB_PATH=/data/review.sqlite3
REVIEW_ARTIFACT_ROOT=/data/artifacts
```

- [ ] **Step 4: Run GREEN**

```bash
uv run --directory backend pytest tests/test_review_config.py tests/test_sqlite_review_schema.py -v
```

Expected: PASS.

- [ ] **Step 5: Run regression and commit**

```bash
uv run --directory backend pytest -q
git add backend/app/storage backend/app/config.py .env.example backend/tests/test_review_config.py backend/tests/test_sqlite_review_schema.py
git commit -m "feat: add sqlite review source of truth"
```

---

### Task 3: Implement Transactional Repository and Request State Machine

**Files:**
- Create: `backend/app/storage/review_repository.py`
- Create: `backend/app/services/review_request_service.py`
- Test: `backend/tests/test_review_repository.py`
- Test: `backend/tests/test_review_request_service.py`

**Interfaces:**
- Repository methods:
  - `create_request(request) -> None`
  - `get_request(request_id) -> ReviewRequestData | None`
  - `update_request_status(request_id, status) -> None`
  - `save_snapshot(snapshot, resources) -> None`
  - `list_snapshot_resources(snapshot_id) -> list[DriveResourceData]`
  - `create_analysis_run(run) -> None`
  - `add_evidence(evidence) -> None`
  - `create_finding(finding, links) -> None`
  - `list_finding_evidence(finding_id) -> list[EvidenceDataV2]`
  - `append_human_decision(decision) -> None`
  - `list_human_decisions(finding_id) -> list[HumanDecisionDataV2]`
  - `create_evaluation_run(run_id, suite_id, created_at) -> None`
  - `save_evaluation_result(result) -> None`
  - `get_evaluation_result(run_id) -> EvaluationResultData | None`
- Service method: `transition_request(request_id, target) -> ReviewRequestData`.

- [ ] **Step 1: Write failing repository/state tests**

```python
def test_finding_with_missing_evidence_is_rejected(repo):
    finding = FindingData(
        id="F-1", request_id="R-1", engine="EDITORIAL_QA", finding_type="TYPO",
    )
    with pytest.raises(ValueError, match="missing evidence"):
        repo.create_finding(finding, [FindingEvidenceData("F-1", "E-X", "SUPPORTS")])
```

```python
def test_request_cannot_jump_from_received_to_published(service):
    with pytest.raises(ValueError, match="invalid transition"):
        service.transition_request("R-1", ReviewRequestStatus.PUBLISHED)
```

Use this exact transition map:

```python
ALLOWED = {
    ReviewRequestStatus.RECEIVED: {ReviewRequestStatus.IMPORTING, ReviewRequestStatus.FAILED},
    ReviewRequestStatus.IMPORTING: {
        ReviewRequestStatus.WAITING_CANONICAL_APPROVAL,
        ReviewRequestStatus.ANALYZING,
        ReviewRequestStatus.FAILED,
    },
    ReviewRequestStatus.WAITING_CANONICAL_APPROVAL: {
        ReviewRequestStatus.ANALYZING,
        ReviewRequestStatus.FAILED,
    },
    ReviewRequestStatus.ANALYZING: {
        ReviewRequestStatus.READY_FOR_REVIEW,
        ReviewRequestStatus.FAILED,
    },
    ReviewRequestStatus.READY_FOR_REVIEW: {
        ReviewRequestStatus.REVIEWING,
        ReviewRequestStatus.FAILED,
    },
    ReviewRequestStatus.REVIEWING: {
        ReviewRequestStatus.FINALIZED,
        ReviewRequestStatus.FAILED,
    },
    ReviewRequestStatus.FINALIZED: {
        ReviewRequestStatus.PUBLISHED,
        ReviewRequestStatus.FAILED,
    },
    ReviewRequestStatus.PUBLISHED: set(),
    ReviewRequestStatus.FAILED: set(),
}
```

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_review_repository.py tests/test_review_request_service.py -v
```

- [ ] **Step 3: Implement repository and service**

Use `json.dumps`/`json.loads` for `EvidenceDataV2.value` and bbox, and enum `.value` for storage. Multi-row writes use `with self._conn:`.

Before `create_finding` inserts anything, query all linked evidence IDs. If any are absent:

```python
missing = sorted(requested_ids - existing_ids)
if missing:
    raise ValueError(f"missing evidence: {', '.join(missing)}")
```

`append_human_decision` performs INSERT only. No repository method updates/deletes a human decision in Phase 0.

`transition_request` loads the request, validates `ALLOWED[current]`, updates in one transaction, then returns the refreshed record.

- [ ] **Step 4: Run GREEN**

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

### Task 4: Add Immutable Artifact Store and Intake Snapshot Service

**Files:**
- Create: `backend/app/services/content_artifact_store.py`
- Create: `backend/app/services/intake_snapshot_service.py`
- Create: `backend/tests/fixtures/intake/canonical/photo-001.jpg`
- Create: `backend/tests/fixtures/intake/proof/proof.txt`
- Test: `backend/tests/test_content_artifact_store.py`
- Test: `backend/tests/test_intake_snapshot_service.py`

**Interfaces:**
- `ContentArtifactStore.put_bytes(data, kind, suffix="") -> StoredArtifact`
- `ContentArtifactStore.put_file(source, kind) -> StoredArtifact`
- `ContentArtifactStore.path_for(artifact) -> Path`
- `ContentArtifactStore.verify(artifact) -> bool`
- `ExternalResourceSource.list(ref, role) -> Sequence[ExternalResourceMeta]`
- `ExternalResourceSource.read(file_id) -> bytes`
- `IntakeSnapshotService.create_snapshot(request_id, canonical_ref, proof_ref) -> IntakeSnapshotData`.

- [ ] **Step 1: Write failing artifact/snapshot tests**

```python
def test_same_bytes_dedupe_to_same_uri(tmp_path):
    store = ContentArtifactStore(tmp_path)
    a = store.put_bytes(b"same", kind="intake", suffix=".bin")
    b = store.put_bytes(b"same", kind="intake", suffix=".bin")
    assert (a.sha256, a.uri) == (b.sha256, b.uri)
```

```python
def test_snapshot_hash_changes_when_downloaded_content_changes(service, source):
    first = service.create_snapshot("R-1", "canonical", "proof")
    source.replace_bytes("proof/proof.txt", b"changed")
    second = service.create_snapshot("R-2", "canonical", "proof")
    assert first.source_hash != second.source_hash
```

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_content_artifact_store.py tests/test_intake_snapshot_service.py -v
```

- [ ] **Step 3: Implement exact behavior**

`StoredArtifact`:

```python
@dataclass(frozen=True, slots=True)
class StoredArtifact:
    sha256: str
    kind: str
    uri: str
    size: int
```

Path format is `<root>/<kind>/<sha256[:2]>/<sha256><suffix>`. Write through a sibling temporary file and `Path.replace()` only when destination does not exist. Existing destinations are never overwritten. `verify()` recomputes SHA256.

`ExternalResourceMeta` fields are `file_id`, `name`, `mime_type`, `modified_time`, `size`, `source_ref`.

`LocalFixtureResourceSource` implements the protocol from a test root and exposes `replace_bytes(relative_path, data)` for tests.

Snapshot algorithm:

```python
items = []
for role, ref in (("CANONICAL", canonical_ref), ("PROOF", proof_ref)):
    for meta in source.list(ref, role):
        data = source.read(meta.file_id)
        stored = artifacts.put_bytes(data, kind="intake", suffix=Path(meta.name).suffix)
        items.append((role, meta, stored))
source_hash = hashlib.sha256(
    "\0".join(sorted(f"{role}:{stored.sha256}" for role, _, stored in items)).encode()
).hexdigest()
snapshot_id = f"snapshot:{request_id}:{source_hash[:16]}"
```

Create `DriveResourceData.snapshot_id = snapshot_id`, save snapshot/resources transactionally, and return the snapshot.

- [ ] **Step 4: Run GREEN**

```bash
uv run --directory backend pytest tests/test_content_artifact_store.py tests/test_intake_snapshot_service.py -v
```

Expected: PASS without network access.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/content_artifact_store.py backend/app/services/intake_snapshot_service.py backend/tests/test_content_artifact_store.py backend/tests/test_intake_snapshot_service.py backend/tests/fixtures/intake
git commit -m "feat: snapshot immutable review inputs"
```

---

### Task 5: Add Conservative One-Way Legacy Adapters

**Files:**
- Create: `backend/app/services/legacy_review_adapter.py`
- Test: `backend/tests/test_legacy_review_adapter.py`

**Interfaces:**
- Consumes current `app.domain.review_models.EvidenceData`, `CorrectionCandidateData`, and `app.domain.ai_review_finding.AIReviewFindingData`.
- Produces:
  - `adapt_legacy_evidence(value, new_id) -> EvidenceDataV2`
  - `adapt_correction_candidate(value, request_id, revision_id, analysis_run_id) -> tuple[FindingData, list[EvidenceDataV2], list[FindingEvidenceData]]`
  - `adapt_ai_review_finding(value, request_id, revision_id) -> FindingData`
- There is no reverse adapter from the new domain into legacy correction candidates.

- [ ] **Step 1: Write failing safety tests**

```python
def test_filename_only_evidence_never_becomes_canonical(adapter_input):
    finding, evidence, links = adapt_correction_candidate(
        adapter_input,
        request_id="R-1",
        revision_id="REV-1",
        analysis_run_id="RUN-1",
    )
    assert finding.status is FindingStatus.PENDING_REVIEW
    assert all(e.evidence_type not in {"CANONICAL_FACT", "CANONICAL_ASSET"} for e in evidence)
```

Add an AI adapter test proving rationale/confidence do not create canonical evidence IDs.

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_legacy_review_adapter.py -v
```

- [ ] **Step 3: Implement conservative mapping**

Use exactly:

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

No legacy kind maps to `CANONICAL_FACT` or `CANONICAL_ASSET`. Preserve legacy value/rationale/method/confidence where representable. Use the caller-supplied request/revision/run IDs; never infer canonical identity from filename/path/caption or AI rationale.

- [ ] **Step 4: Run GREEN and regression**

```bash
uv run --directory backend pytest tests/test_legacy_review_adapter.py -v
uv run --directory backend pytest -q
```

Expected: no new failures.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/legacy_review_adapter.py backend/tests/test_legacy_review_adapter.py
git commit -m "feat: bridge legacy findings into review foundation"
```

---

### Task 6: Add the Generic Gold Evaluation Harness

**Files:**
- Create: `backend/app/evaluation/__init__.py`
- Create: `backend/app/evaluation/finding_set_evaluator.py`
- Create: `backend/tests/fixtures/gold/foundation_findings.json`
- Create: `backend/tests/fixtures/gold/foundation_predictions.json`
- Create: `backend/tests/test_finding_set_evaluator.py`
- Create: `backend/tests/test_evaluation_repository.py`
- Create: `tools/evaluate_review_gold.py`
- Modify: `backend/app/storage/review_repository.py`

**Interfaces:**
- `evaluate_finding_types(cases, predictions, run_id, suite_id) -> EvaluationResultData`.
- Evaluation repository methods are the exact Task 3 methods.

- [ ] **Step 1: Write failing evaluator/repository tests**

```python
def test_metrics_count_tp_fp_fn():
    cases = [
        GoldCaseData("case-1", "EDITORIAL_QA", ("TYPO", "DOCUMENT_INTERNAL_CONTRADICTION")),
        GoldCaseData("case-2", "EDITORIAL_QA", ("TYPO",)),
    ]
    predictions = {
        "case-1": [finding("TYPO"), finding("GRAMMAR")],
        "case-2": [finding("TYPO")],
    }
    result = evaluate_finding_types(cases, predictions, "EV-1", "suite-1")
    assert (result.true_positive, result.false_positive, result.false_negative) == (2, 1, 1)
    assert result.precision == pytest.approx(2 / 3)
    assert result.recall == pytest.approx(2 / 3)
```

```python
def test_no_gold_refuses_accuracy_claim():
    with pytest.raises(ValueError, match="gold cases required"):
        evaluate_finding_types([], {}, "EV-1", "suite-1")
```

- [ ] **Step 2: Run RED**

```bash
uv run --directory backend pytest tests/test_finding_set_evaluator.py tests/test_evaluation_repository.py -v
```

- [ ] **Step 3: Implement evaluator, fixture, persistence, CLI**

Evaluator compares `(case_id, finding_type)` pairs only. It computes:

```python
precision = tp / (tp + fp) if tp + fp else 0.0
recall = tp / (tp + fn) if tp + fn else 0.0
false_positives_per_case = fp / len(cases)
```

`foundation_findings.json`:

```json
{
  "suite_id": "foundation-smoke-v1",
  "cases": [
    {"id": "case-typo", "engine": "EDITORIAL_QA", "expected_finding_types": ["TYPO"]},
    {"id": "case-clean", "engine": "EDITORIAL_QA", "expected_finding_types": []}
  ]
}
```

`foundation_predictions.json`:

```json
{
  "case-typo": [{"finding_type": "TYPO"}],
  "case-clean": []
}
```

CLI command:

```bash
uv run --directory backend python ../tools/evaluate_review_gold.py \
  --gold tests/fixtures/gold/foundation_findings.json \
  --predictions tests/fixtures/gold/foundation_predictions.json
```

Output JSON keys: `suite_id`, `true_positive`, `false_positive`, `false_negative`, `precision`, `recall`, `false_positives_per_case`. Exit nonzero for malformed input or zero gold cases.

Do not implement Asset Top-1, entity-link accuracy, or canonical contradiction metrics here; those belong to Phases 1-3.

- [ ] **Step 4: Run GREEN**

```bash
uv run --directory backend pytest tests/test_finding_set_evaluator.py tests/test_evaluation_repository.py -v
uv run --directory backend python ../tools/evaluate_review_gold.py --gold tests/fixtures/gold/foundation_findings.json --predictions tests/fixtures/gold/foundation_predictions.json
```

Expected: tests PASS; CLI reports precision/recall 1.0 for the smoke fixture.

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation backend/app/storage/review_repository.py backend/tests/test_finding_set_evaluator.py backend/tests/test_evaluation_repository.py backend/tests/fixtures/gold tools/evaluate_review_gold.py
git commit -m "feat: add gold review evaluation harness"
```

---

### Task 7: Lock the Phase 0 End-to-End Acceptance Contract

**Files:**
- Create: `backend/tests/integration/test_review_foundation_flow.py`
- Modify: `.github/workflows/remediation-ci.yml` only if the current hermetic backend job would otherwise omit this test.

**Interfaces:**
- Consumes every Phase 0 component.
- Produces one acceptance flow: local source refs -> immutable snapshot -> deterministic AnalysisRun -> evidence-backed Finding -> append-only HumanDecision -> persisted gold result.

- [ ] **Step 1: Write the failing integration test**

Use a tmp SQLite DB/artifact root and the local fixture source. The test must execute:

```python
repo.create_request(ReviewRequestData(id="R-E2E", project_id="P-1", source="DISCORD"))
request_service.transition_request("R-E2E", ReviewRequestStatus.IMPORTING)
snapshot = intake.create_snapshot("R-E2E", "canonical", "proof")
request_service.transition_request("R-E2E", ReviewRequestStatus.ANALYZING)

repo.create_analysis_run(AnalysisRunData(
    id="RUN-E2E",
    request_id="R-E2E",
    task_type="foundation-smoke",
    runtime=AnalysisRuntime.DETERMINISTIC,
    status="COMPLETED",
    started_at="2026-09-05T00:00:00Z",
    completed_at="2026-09-05T00:00:01Z",
))

proof_resource = next(r for r in repo.list_snapshot_resources(snapshot.id) if r.role == "PROOF")
repo.add_evidence(EvidenceDataV2(
    id="E-E2E",
    evidence_type="DOCUMENT_BLOCK",
    source_sha256=proof_resource.local_sha256,
    value="오타 문장",
    method="fixture",
    analysis_run_id="RUN-E2E",
))
repo.create_finding(
    FindingData(
        id="F-E2E",
        request_id="R-E2E",
        revision_id="REV-E2E",
        engine="EDITORIAL_QA",
        finding_type="TYPO",
        analysis_run_id="RUN-E2E",
        created_at="2026-09-05T00:00:01Z",
    ),
    [FindingEvidenceData("F-E2E", "E-E2E", "SUPPORTS")],
)
repo.append_human_decision(HumanDecisionDataV2(
    id="D-E2E",
    finding_id="F-E2E",
    decision=DecisionValue.ACCEPT,
    created_at="2026-09-05T00:00:02Z",
))
```

Then assert:

```python
assert artifacts.verify(artifact_for(proof_resource)) is True
assert [e.id for e in repo.list_finding_evidence("F-E2E")] == ["E-E2E"]
assert [d.id for d in repo.list_human_decisions("F-E2E")] == ["D-E2E"]
```

Create and persist a one-case `TYPO` gold evaluation and assert precision/recall are 1.0.

- [ ] **Step 2: Run integration RED/GREEN cycle**

```bash
uv run --directory backend pytest tests/integration/test_review_foundation_flow.py -v
```

Only fix Phase 0 modules needed by this contract. Do not modify graph, AI, parser, or asset production paths to force this test green.

- [ ] **Step 3: Run all Phase 0 tests**

```bash
uv run --directory backend pytest \
  tests/test_review_core_domain.py \
  tests/test_intake_domain.py \
  tests/test_review_config.py \
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

Expected: PASS with no external services or credentials.

- [ ] **Step 4: Run full backend regression and inspect CI config**

```bash
uv run --directory backend pytest -q
```

Expected: no new failures beyond current intentional skips/xfails.

Inspect `.github/workflows/remediation-ci.yml`. If the hermetic backend job already runs the full backend pytest suite, leave the workflow unchanged. If it filters test paths and omits `tests/integration/test_review_foundation_flow.py`, add that path to the existing hermetic pytest invocation without adding Neo4j/Redis/API dependencies.

- [ ] **Step 5: Commit acceptance**

```bash
git add backend/tests/integration/test_review_foundation_flow.py .github/workflows/remediation-ci.yml
git commit -m "test: lock phase zero review foundation acceptance"
```

---

## Phase 0 Completion Gate

Phase 0 is complete only when tests demonstrate all of the following:

- SQLite initializes idempotently and enforces foreign keys.
- Request state transitions fail closed on illegal jumps.
- Input content is copied into an immutable SHA256 artifact store before analysis.
- Snapshot identity changes when downloaded content changes.
- Findings cannot be persisted with missing evidence.
- Human decisions remain append-only and separate from findings.
- Legacy filename/path/caption/VLM evidence is not promoted into canonical truth by adapters.
- Evaluation refuses precision/recall reporting with zero gold cases.
- End-to-end Phase 0 runs without Neo4j, live AI, Discord, Google Drive, `/src`, or API credentials.
- Existing backend regression remains green.

## Explicit Non-Goals

Separate plans will cover:

- CanonicalAsset/CanonicalMetadata/CanonicalEntity/CanonicalFact production flow.
- Persistent SIFT and incremental Asset QA.
- Codex SDK runtime, Luna max/xhigh, ReviewToolGateway, Direct API runtime/model switching.
- EntityMention/DocumentClaim and B1 whole-document review.
- B2 canonical comparison and Neo4j projection redesign.
- Real Discord bot and Google Drive adapters.
- Review Web UI and ReviewPackage generation/publishing.
- HWP/HWPX acceptance and cross-platform product hardening.
