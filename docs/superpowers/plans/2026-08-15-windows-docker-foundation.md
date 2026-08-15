# Windows Docker 검수 MVP 기반 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Windows Docker Desktop에서 한 명의 사용자가 브라우저로 프로젝트와 원본 파일을 등록하고, 읽기 전용 해시 저장·Neo4j 그래프 적재·비동기 분석 작업 상태 확인까지 수행한다.

**Architecture:** React 웹 앱은 FastAPI API만 호출하고, API는 업로드를 관리 볼륨에 저장한 뒤 Redis RQ 작업을 생성한다. worker는 파일 해시·메타데이터를 Neo4j에 적재하고 `AnalysisRun` 상태를 갱신한다. 원본 바이트와 API 키는 Neo4j에 저장하지 않는다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, neo4j Python Driver, Redis/RQ, React 18 + TypeScript + Vite, Neo4j 5.26 Community, Docker Compose, pytest, Playwright.

## Global Constraints

- Windows Docker Desktop + WSL2에서 `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1`로 실행한다.
- 서비스는 `web`, `worker`, `neo4j`, `redis` 네 개이며 UI는 `http://localhost:8080`에서 제공한다.
- `DATA_ROOT`는 컨테이너 내 `/data`이고 `incoming`, `derived`, `reports` 하위 디렉터리를 가진다.
- API 키는 `.env`의 `AI_API_KEY`만 읽고, API 응답·브라우저·Neo4j에 원문 키를 기록하지 않는다.
- 원본 파일은 SHA-256, 바이트 수, MIME 유형, 원본 파일명과 함께 보존하며 변경·삭제 API를 제공하지 않는다.
- Neo4j에는 파일 바이트가 아니라 URI·해시·메타데이터·관계·임베딩만 저장한다.
- 모든 업로드·작업 상태 변경은 `Project`, `Document`, `DocumentVersion`, `AnalysisRun` 노드와 연결한다.
- 자동 교정·전문가 결정·외부 AI 호출은 이 기반 계획의 범위 밖이다.

---

### Task 1: Docker Compose와 Windows 실행 기반

**Files:**
- Create: `compose.yml`
- Create: `.env.example`
- Create: `scripts/start.ps1`
- Create: `scripts/stop.ps1`
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `backend/pyproject.toml`
- Create: `frontend/package.json`
- Create: `tests/compose/test_compose_contract.py`

**Interfaces:**
- Consumes: `.env`의 `NEO4J_PASSWORD`, `AI_API_KEY`, `DATA_ROOT`
- Produces: `web:8080`, `worker`, `neo4j:7687`, `redis:6379` Compose 서비스와 명명 볼륨 `review_data`, `neo4j_data`

- [ ] **Step 1: Compose 계약 실패 테스트 작성**

```python
def test_compose_declares_required_services_and_volumes(compose):
    assert set(compose["services"]) == {"web", "worker", "neo4j", "redis"}
    assert compose["services"]["web"]["ports"] == ["8080:8080"]
    assert {"review_data", "neo4j_data"} <= set(compose["volumes"])
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/compose/test_compose_contract.py -v`

Expected: FAIL because `compose.yml` does not exist.

- [ ] **Step 3: Compose·환경·PowerShell 스크립트 구현**

`compose.yml`에 `web`과 `worker`가 동일한 `review_data:/data` 볼륨을 마운트하고, Neo4j에는 `NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}`와 `neo4j_data:/data`를 설정한다. `start.ps1`은 `.env`가 없으면 `.env.example` 복사를 안내하고, 있으면 `docker compose up --build -d`를 실행한다. `stop.ps1`은 `docker compose down`만 실행한다.

- [ ] **Step 4: 계약 테스트 통과 확인**

Run: `pytest tests/compose/test_compose_contract.py -v`

Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add compose.yml .env.example scripts backend/Dockerfile frontend/Dockerfile backend/pyproject.toml frontend/package.json tests/compose/test_compose_contract.py
git commit -m "feat: add Windows Docker foundation"
```

### Task 2: 파일 저장소와 도메인 모델

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/app/domain/models.py`
- Create: `backend/app/services/file_store.py`
- Create: `backend/tests/test_file_store.py`

**Interfaces:**
- Produces: `StoredFile(uri: str, sha256: str, size_bytes: int, mime_type: str, original_name: str)`
- Produces: `FileStore.store_upload(project_id: UUID, upload: UploadFile) -> StoredFile`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_store_upload_preserves_bytes_and_returns_content_addressed_uri(tmp_path):
    stored = FileStore(tmp_path).store_bytes("p1", "보고서.pdf", b"PDF")
    assert stored.sha256 == hashlib.sha256(b"PDF").hexdigest()
    assert (tmp_path / stored.uri).read_bytes() == b"PDF"
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && pytest tests/test_file_store.py -v`

Expected: FAIL with `ModuleNotFoundError: app.services.file_store`.

- [ ] **Step 3: 최소 구현**

`FileStore`는 `/data/incoming/<project-id>/<sha256>/<safe-filename>`에 `xb` 모드로 바이트를 한 번만 기록한다. 같은 해시·이름 파일이 있으면 바이트를 비교하고 같은 파일이면 기존 `StoredFile`을 반환하며, 다르면 `FileExistsError`를 낸다. 허용 MIME은 PDF, HWP, HWPX, JPEG, PNG, TIFF, AI다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && pytest tests/test_file_store.py -v`

Expected: PASS; 중복 저장과 허용하지 않은 MIME 테스트를 포함한다.

- [ ] **Step 5: 커밋**

```bash
git add backend/app backend/tests/test_file_store.py
git commit -m "feat: preserve uploaded source files"
```

### Task 3: Neo4j 스키마와 프로젝트 저장소

**Files:**
- Create: `backend/app/graph/client.py`
- Create: `backend/app/graph/schema.py`
- Create: `backend/app/graph/project_repository.py`
- Create: `backend/tests/test_project_repository.py`

**Interfaces:**
- Produces: `ensure_schema(driver) -> None`
- Produces: `ProjectRepository.create_project(name: str, internal_code: str | None) -> Project`
- Produces: `ProjectRepository.add_document_version(project_id: str, stored: StoredFile, stage: str) -> DocumentVersion`

- [ ] **Step 1: 실패 통합 테스트 작성**

```python
def test_document_version_links_project_document_file_and_analysis_run(neo4j_driver):
    repo = ProjectRepository(neo4j_driver)
    project = repo.create_project("산노리", "NONSAN-001")
    version = repo.add_document_version(project.id, stored_pdf, "source")
    assert repo.graph_shape(version.id) == {
        "Project": 1, "Document": 1, "DocumentVersion": 1, "AnalysisRun": 1
    }
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && pytest tests/test_project_repository.py -v`

Expected: FAIL because repository and schema are absent.

- [ ] **Step 3: 제약조건·인덱스·Cypher 구현**

`ensure_schema`는 `Project.id`, `Document.id`, `DocumentVersion.id`, `AnalysisRun.id`의 unique constraint와 `DocumentVersion.sha256` index를 만든다. `add_document_version`은 `(:Project)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)`와 `(:AnalysisRun {status:'queued', step:'ingest'})-[:ANALYZES]->(:DocumentVersion)`을 단일 write transaction에서 생성한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && pytest tests/test_project_repository.py -v`

Expected: PASS against Compose Neo4j test database.

- [ ] **Step 5: 커밋**

```bash
git add backend/app/graph backend/tests/test_project_repository.py
git commit -m "feat: persist project graph metadata"
```

### Task 4: 업로드·프로젝트 REST API

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/app/api/projects.py`
- Create: `backend/app/api/schemas.py`
- Create: `backend/tests/test_projects_api.py`

**Interfaces:**
- Produces: `POST /api/projects` → `201 {id, name, internalCode}`
- Produces: `POST /api/projects/{project_id}/documents?stage=source` → `202 {documentVersionId, analysisRunId}`
- Produces: `GET /api/projects/{project_id}` → project, document versions, analysis runs

- [ ] **Step 1: 실패 API 테스트 작성**

```python
def test_upload_creates_queued_ingest_run(client):
    project = client.post("/api/projects", json={"name": "산노리"}).json()
    result = client.post(f"/api/projects/{project['id']}/documents?stage=source", files={"file": ("a.pdf", b"%PDF", "application/pdf")})
    assert result.status_code == 202
    assert result.json()["analysisRunId"]
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && pytest tests/test_projects_api.py -v`

Expected: FAIL with 404.

- [ ] **Step 3: API 구현**

Pydantic 요청·응답 모델로 입력을 검증한다. 업로드 API는 파일 저장과 Neo4j transaction이 모두 성공할 때만 202을 반환한다. 실패 시 파일 URI·해시·원본 바이트를 응답이나 로그에 노출하지 않고 `input_error` 코드와 `request_id`만 반환한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && pytest tests/test_projects_api.py -v`

Expected: PASS; 잘못된 stage, MIME, 존재하지 않는 project의 4xx 테스트를 포함한다.

- [ ] **Step 5: 커밋**

```bash
git add backend/app/main.py backend/app/api backend/tests/test_projects_api.py
git commit -m "feat: expose project upload API"
```

### Task 5: Redis RQ 작업자와 재시도 가능한 분석 상태

**Files:**
- Create: `backend/app/jobs/queue.py`
- Create: `backend/app/jobs/ingest.py`
- Create: `backend/app/jobs/worker.py`
- Create: `backend/tests/test_ingest_job.py`

**Interfaces:**
- Consumes: `AnalysisRun(id, status='queued', step='ingest')`
- Produces: `enqueue_ingest(analysis_run_id: str) -> str`
- Produces: 상태 전이 `queued → running → completed | failed | cancelled`

- [ ] **Step 1: 실패 상태 전이 테스트 작성**

```python
def test_ingest_job_marks_completed_and_is_idempotent(fake_repo):
    run = fake_repo.queued_run()
    ingest_document(run.id, fake_repo, fake_extractor)
    assert fake_repo.run(run.id).status == "completed"
    ingest_document(run.id, fake_repo, fake_extractor)
    assert fake_extractor.calls == 1
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && pytest tests/test_ingest_job.py -v`

Expected: FAIL because job module is absent.

- [ ] **Step 3: 작업자 구현**

업로드 API가 `enqueue_ingest`를 호출한다. ingest 작업은 파일 해시가 이미 처리된 `DocumentVersion`이면 기존 추출 결과를 재사용하고, 새 파일이면 MIME·페이지 수·텍스트 추출 가능 여부를 기록한다. 예외는 `failed`와 `input_error`, `conversion_error`, `api_error`, `rate_limited` 중 하나로 정규화하고 재시도 가능 여부를 저장한다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && pytest tests/test_ingest_job.py -v`

Expected: PASS; 중복 실행, 취소 상태, 변환 실패 상태 테스트를 포함한다.

- [ ] **Step 5: 커밋**

```bash
git add backend/app/jobs backend/tests/test_ingest_job.py
git commit -m "feat: process analysis jobs asynchronously"
```

### Task 6: 단일 사용자 웹 UI와 Compose 종단간 검증

**Files:**
- Create: `frontend/src/api.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/pages/ProjectsPage.tsx`
- Create: `frontend/src/pages/ProjectDetailPage.tsx`
- Create: `frontend/tests/project-upload.spec.ts`
- Create: `scripts/healthcheck.ps1`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 4 API endpoints
- Produces: 프로젝트 생성, 파일 업로드, analysis run 상태 표시 UI

- [ ] **Step 1: 실패 브라우저 테스트 작성**

```typescript
test('사용자가 프로젝트와 PDF를 등록하면 queued 상태를 본다', async ({ page }) => {
  await page.goto('http://localhost:8080');
  await page.getByLabel('프로젝트명').fill('산노리');
  await page.getByRole('button', { name: '프로젝트 생성' }).click();
  await page.setInputFiles('input[type=file]', 'tests/fixtures/sample.pdf');
  await expect(page.getByText('queued')).toBeVisible();
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd frontend && npx playwright test tests/project-upload.spec.ts`

Expected: FAIL because UI is absent.

- [ ] **Step 3: 최소 UI와 헬스체크 구현**

UI는 프로젝트명 입력, 파일 선택, 업로드 진행 상태, 문서 버전별 작업 상태와 실패 코드만 표시한다. `healthcheck.ps1`은 `http://localhost:8080/health`, API health, Neo4j Bolt, Redis ping을 순서대로 검사하고 실패한 서비스 이름만 출력한다. README에는 Windows Docker Desktop 설치, `.env` 설정, 시작·중지·헬스체크·데이터 볼륨 경로를 추가한다.

- [ ] **Step 4: 종단간 테스트 통과 확인**

Run: `docker compose up --build -d; powershell -ExecutionPolicy Bypass -File .\scripts\healthcheck.ps1; cd frontend && npx playwright test tests/project-upload.spec.ts`

Expected: healthcheck exit 0 and Playwright PASS.

- [ ] **Step 5: 커밋**

```bash
git add frontend scripts/healthcheck.ps1 README.md
git commit -m "feat: add local project upload interface"
```

## 후속 계획 경계

이 기반 완료 후 별도 계획으로 다음을 수행한다.

1. 문단·캡션·사진·도면 영역 추출, `ArchaeologyObject` 관계 적재, Neo4j 벡터·전문 인덱스와 하이브리드 검색.
2. 오탈자·일관성·문맥·사진·도면 교차 후보, 외부 AI API 감사 로그, 전문가 전수 승인 화면, Excel·HTML·PDF 보고서.
