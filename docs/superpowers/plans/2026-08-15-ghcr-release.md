# GHCR 릴리스와 Windows 업데이트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GitHub Release를 검증된 GHCR Docker 이미지와 안전한 Windows 수동 업데이트·롤백으로 연결한다.

**Architecture:** `release.published` workflow가 테스트와 이미지 빌드 후 GHCR에 불변 버전 태그를 게시한다. Compose는 `APP_IMAGE_TAG`를 통해 같은 앱 이미지를 web과 worker에 적용한다. Windows update script는 현재 불변 태그를 기록하고 업데이트 후 health check가 실패하면 해당 태그로 롤백하며, 데이터 볼륨은 어떤 경우에도 삭제하지 않는다.

**Tech Stack:** GitHub Actions, GHCR, Docker Compose, PowerShell 7/Pester, Python pytest/YAML 검사.

## Global Constraints

- 이미지 저장소는 `ghcr.io/<repository-owner>/archaeology-document-review-system` 하나만 사용하며 Docker Hub에는 게시하지 않는다.
- workflow는 GitHub Release `published`에서만 이미지 게시하며 prerelease는 `latest`를 갱신하지 않는다.
- workflow 권한은 `contents: read`, `packages: write`, `attestations: write`, `id-token: write`만 사용한다.
- 모든 third-party action은 커밋 SHA로 고정한다.
- web과 worker는 같은 `APP_IMAGE_TAG`를 사용하고 `latest`가 아닌 불변 `vX.Y.Z` 태그가 설치·롤백의 기준이다.
- `.env`, `review_data`, `neo4j_data`, Redis 데이터 및 원본 바이트를 업데이트·롤백 중 삭제하거나 초기화하지 않는다.
- 자동 업데이트 에이전트, self-hosted runner, PC 원격 배포, Docker Hub 동시 게시은 범위 밖이다.
- 오류 출력·로그에는 API 키, 원본 URI, SHA-256, 파일명 또는 원본 바이트를 출력하지 않는다.

---

### Task 1: 릴리스 이미지 참조와 GHCR 게시 workflow

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `compose.yml`
- Create: `tests/release/test_release_workflow.py`

**Interfaces:**
- Consumes: GitHub Release tag `${{ github.event.release.tag_name }}` and `APP_IMAGE_TAG`
- Produces: `ghcr.io/${{ github.repository }}:vX.Y.Z`, prerelease-specific tags, and `latest` only for stable releases
- Produces: Compose `web`/`worker` image references with one identical `APP_IMAGE_TAG`

- [ ] **Step 1: Write failing workflow and Compose contract tests**

```python
def test_release_workflow_is_release_published_and_uses_minimum_permissions(workflow):
    assert workflow[True]["release"]["types"] == ["published"]
    assert workflow["permissions"] == {
        "contents": "read", "packages": "write", "attestations": "write", "id-token": "write"
    }

def test_compose_uses_one_versioned_app_image_for_web_and_worker(compose):
    web = compose["services"]["web"]
    worker = compose["services"]["worker"]
    assert web["image"] == worker["image"]
    assert "${APP_IMAGE_TAG" in web["image"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest tests/release/test_release_workflow.py -v`

Expected: FAIL because no release workflow or versioned Compose image reference exists.

- [ ] **Step 3: Implement the minimal workflow and Compose image reference**

```yaml
on:
  release:
    types: [published]
permissions:
  contents: read
  packages: write
  attestations: write
  id-token: write
```

Set `IMAGE_NAME: ghcr.io/${{ github.repository }}`. Run backend tests and Compose contract tests before `docker/build-push-action`; use metadata rules that publish `github.event.release.tag_name` always and `latest` only when `github.event.release.prerelease == false`. Add an attestation for the pushed digest. Add `image: ghcr.io/ranponim/archaeology-document-review-system:${APP_IMAGE_TAG:-latest}` to both app services while retaining their existing build contexts for local `docker compose up --build` development.

- [ ] **Step 4: Run contracts and build validation**

Run: `uv run --with pytest --with pyyaml pytest tests/release/test_release_workflow.py tests/compose/test_compose_contract.py -v && docker compose config`

Expected: PASS; `web` and `worker` resolve to the same tag and no secret environment value appears in workflow output metadata.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml compose.yml tests/release/test_release_workflow.py
git commit -m "ci: publish release images to GHCR"
```

### Task 2: Windows versioned update, health verification, and rollback

**Files:**
- Create: `scripts/update.ps1`
- Create: `scripts/healthcheck.ps1`
- Create: `tests/release/test_update_scripts.py`

**Interfaces:**
- Consumes: `scripts/update.ps1 [-Version vX.Y.Z | latest]`, `.env`, `APP_IMAGE_TAG`, Docker Compose
- Produces: `.release-state.json` containing only the prior image tag and timestamp
- Produces: exit `0` after a healthy update; non-zero after an attempted rollback or failed first installation

- [ ] **Step 1: Write failing script contract tests**

```python
def test_update_script_pulls_starts_and_healthchecks_requested_tag(text):
    assert "ValidateSet" in text
    assert "docker compose pull" in text
    assert "docker compose up -d" in text
    assert "healthcheck.ps1" in text

def test_update_script_records_prior_tag_and_never_removes_volumes(text):
    assert ".release-state.json" in text
    assert "APP_IMAGE_TAG" in text
    assert "down -v" not in text
    assert "volume rm" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/release/test_update_scripts.py -v`

Expected: FAIL because update and healthcheck scripts do not exist.

- [ ] **Step 3: Implement safe scripts**

```powershell
param([ValidatePattern('^(latest|v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.]+)?)$')][string] $Version = 'latest')
# Persist only previous APP_IMAGE_TAG, set process APP_IMAGE_TAG, pull, up -d, then call healthcheck.
# On healthcheck failure restore prior tag and run compose up -d; never call compose down -v.
```

`healthcheck.ps1` must poll `/health` with a finite timeout and check `docker compose ps --status running` contains web, worker, neo4j, and redis. It must use safe fixed messages rather than serializing response bodies or environment variables.

- [ ] **Step 4: Run static contracts and PowerShell syntax validation**

Run: `uv run --with pytest pytest tests/release/test_update_scripts.py -v && pwsh -NoProfile -Command "[void][scriptblock]::Create((Get-Content ./scripts/update.ps1 -Raw)); [void][scriptblock]::Create((Get-Content ./scripts/healthcheck.ps1 -Raw))"`

Expected: PASS; invalid tags are rejected before Docker commands and scripts have no data-destructive command.

- [ ] **Step 5: Commit**

```bash
git add scripts/update.ps1 scripts/healthcheck.ps1 tests/release/test_update_scripts.py
git commit -m "feat: add Windows release update and rollback"
```

### Task 3: Release operation documentation and end-to-end dry-run validation

**Files:**
- Modify: `README.md`
- Create: `tests/release/test_release_docs.py`

**Interfaces:**
- Consumes: public/private GHCR availability and an installed Docker Desktop
- Produces: documented first install, versioned update, stable update, rollback, and private registry login commands

- [ ] **Step 1: Write failing documentation test**

```python
def test_readme_documents_ghcr_install_update_rollback_and_data_retention(readme):
    for phrase in ("ghcr.io", "update.ps1", "v1.0.0", "rollback", "review_data", "neo4j_data"):
        assert phrase in readme
    assert "docker compose down -v" not in readme
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/release/test_release_docs.py -v`

Expected: FAIL because README lacks the release operations section.

- [ ] **Step 3: Document concrete release operations**

Add a compact “Windows release update” section: initial `docker login ghcr.io` only for private packages, explicit `APP_IMAGE_TAG=v1.0.0 docker compose pull && docker compose up -d`, recommended `powershell -ExecutionPolicy Bypass -File .\scripts\update.ps1 -Version v1.0.0`, healthcheck, and how automatic rollback works. State exactly that source documents and named volumes are preserved and no autonomous update agent exists.

- [ ] **Step 4: Run all release contracts and a Compose dry run**

Run: `uv run --with pytest --with pyyaml pytest tests/release tests/compose/test_compose_contract.py -v && APP_IMAGE_TAG=v0.0.0-test docker compose config`

Expected: PASS; rendered web/worker use the test tag, workflow tests pass, script and documentation contracts pass.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/release/test_release_docs.py
git commit -m "docs: explain GHCR release updates"
```

## Plan self-review

- Spec coverage: Task 1 covers Release trigger, tests-before-publish, GHCR tags, minimum permission, SHA-pinned actions and attestation. Task 2 covers explicit Windows update, health checks, rollback, tag validation and volume preservation. Task 3 covers user operations and dry-run evidence.
- Scope: It excludes remote deployment, automatic agent, Docker Hub, and data migration as required.
- Consistency: `APP_IMAGE_TAG`, `scripts/update.ps1`, `scripts/healthcheck.ps1`, and the same GHCR image name are defined once and used consistently across all tasks.
- Placeholder scan: no incomplete implementation placeholders remain.
