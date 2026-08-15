# Agent Handoff — 2026-08-15

## 목적과 고정 결정

이 저장소는 Windows Docker Desktop에서 한 명이 로컬 브라우저로 고고학 문서 검수를
수행하는 기반 MVP를 구현 중이다.

- 원본 PDF/HWP/HWPX/사진/AI 파일은 로컬 Docker named volume에 읽기 전용으로 보존한다.
- Neo4j Community는 원본 바이트가 아닌 해시·URI·메타데이터·문서/자산 관계·향후 임베딩만
  저장한다.
- 검색 설계는 Neo4j 그래프 범위 지정 → full-text/vector → RRF → rerank이며, 별도 vector DB는
  현재 도입하지 않는다.
- 교정 후보는 자동 반영하지 않으며 모든 결정은 전문가 승인이 필요하다.
- 외부 LLM/VLM/embedding API 사용은 허용되지만 이 기반 단계에는 실제 AI 호출을 넣지 않는다.
- 배포는 GitHub Release → GHCR 단일 registry → 사용자가 명시적으로 실행하는 Windows update
  방식이다. PC 자동 업데이트 에이전트와 self-hosted runner는 범위 밖이다.
- `src/`에는 대용량 원본이 있으며 무시(ignored) 대상이다. 변경하거나 Git에 추가하지 않는다.

## 브랜치와 현재 위치

- 기준 브랜치: `main`
- 작업 브랜치: `windows-docker-foundation`
- 작업 worktree: `.worktrees/windows-docker-foundation`
- 현재 HEAD: `a85cc90 feat: add local project upload interface`
- origin: `https://github.com/Ranponim/archaeology-document-review-system.git`
- 원격으로 push/PR은 아직 하지 않았다.

## 완료한 기반 구현

| 영역 | 상태 | 주요 커밋/검증 |
| --- | --- | --- |
| Compose/Windows 시작 | 완료·검토 통과 | `119911b`, `e6929d9`; services=`web, worker, neo4j, redis` |
| 해시 기반 원본 저장 | 완료·검토 통과 | `862508a`~`5ad67e5`; symlink traversal/TOCTOU 방어, 읽기 전용 보존 |
| Neo4j 프로젝트 그래프 | 완료·검토 통과 | `60b87ad`, `3066c20`; 테스트 DB 설정 없이는 연결 전 fail-closed |
| 프로젝트/업로드 API | 완료·검토 통과 | `9fcf022`, `1c1979f`; 500 오류도 경로·해시·원본 바이트를 로그/응답에 노출하지 않음 |
| Redis RQ ingest | 완료·검토 통과 | `7e1849f`, `0baf412`; 중복/취소/실패/재시도, Redis 복구 retry endpoint |
| 웹 UI/E2E | 구현 완료, **독립 검토 대기** | `a85cc90`; Playwright 프로젝트 생성·PDF 업로드 1건, PowerShell healthcheck 통과 |

Task 6 구현자가 보고한 최신 검증은 backend 88 passed, Compose 계약 5 passed + Redis 장애 복구 smoke,
Ruff(변경 범위), TypeScript/Vite build, npm audit 0, PowerShell healthcheck healthy, Playwright 1 passed다.
이 수치는 독립 검토 전의 구현자 보고이므로 최종 합격 주장으로 사용하지 않는다.

## 필수 보안/운영 제약

- Compose의 서비스 수는 정확히 `web`, `worker`, `neo4j`, `redis` 네 개를 유지한다.
- `web`은 실제 FastAPI `/api`와 `/health`를 제공해야 하며, UI 정적 자산을 제공해도 API가
  끊기면 안 된다.
- `AI_API_KEY`는 worker 환경에만 제공한다. 브라우저/API 응답/Neo4j/로그에 기록하지 않는다.
- 테스트는 기본 `localhost:7687`, `neo4j:7687`, system DB 또는 앱 `NEO4J_URI`를 절대 사용하지
  않는다. 명시적 disposable test URI/database/user/password/flag 없이는 드라이버 생성 전에 실패해야 한다.
- Redis enqueue 실패는 retryable failed state만 남기는 것으로 끝내지 않는다. 현재 구현에는 프로젝트
  소유권을 확인하는 retry API가 있다.
- 파일·그래프 실패 때 content-addressed 원본은 동시 참조 안전성을 위해 삭제하지 않는다. 고아 파일은
  reconciliation 대상이다.
- 일반 테스트가 생성한 `__pycache__`, `backend/uv.lock`, egg-info는 **미추적 생성물**이다.
  커밋하지 말고 필요 시 정확한 경로만 안전하게 격리한다.

## 다음 순서

1. `a85cc90`의 Task 6을 독립 read-only 리뷰한다. Docker 안에서 React 정적 자산, FastAPI `/api`,
   healthcheck, PowerShell 오류 경로, Playwright 격리를 검증한다. 문제면 같은 구현자에게 fix round를
   요청하고 재리뷰한다.
2. Task 6이 통과하면 `.superpowers/sdd/2026-08-15-windows-docker-foundation/progress.md`에 완료를
   기록하고, foundation 계획 전체의 최종 검토/검증을 수행한다.
3. 승인된 GHCR 릴리스 명세와 계획을 실행한다.
   - 명세: `docs/superpowers/specs/2026-08-15-ghcr-release-design.md` (`ca25062`)
   - 계획: `docs/superpowers/plans/2026-08-15-ghcr-release.md` (`390e627`)
   - Task 1: SHA-pinned GitHub Release workflow, 테스트 선행, GHCR 불변 태그/안정판 latest,
     attestation, Compose `APP_IMAGE_TAG` 통일
   - Task 2: `update.ps1` + `healthcheck.ps1`, 입력 태그 검증, 현재 태그 기록, health 실패 롤백,
     `down -v`/볼륨 삭제 금지
   - Task 3: README 설치·특정 버전·업데이트·롤백·private GHCR login 문서와 dry run
4. GHCR 계획도 태스크별 독립 리뷰와 최종 검증 후에만 foundation 브랜치를 main에 병합한다.

## 핵심 문서와 검증 기록

- 제품 설계: `docs/superpowers/specs/2026-08-15-neo4j-review-mvp-design.md`
- 기반 계획: `docs/superpowers/plans/2026-08-15-windows-docker-foundation.md`
- GHCR 설계/계획: 위 “다음 순서” 경로
- 태스크 보고서/검토: `.superpowers/sdd/2026-08-15-windows-docker-foundation/`
  - 이 경로는 진행 기록이며, 각 `task-N-report.md`와 `task-N-review.md`를 먼저 읽는다.
- 현재 기반 ledger: `.superpowers/sdd/2026-08-15-windows-docker-foundation/progress.md`

## 인계 시 권장 확인 명령

```bash
git status --short
git log --oneline -12
cd backend && uv run --with pytest pytest -q
uv run --with pytest --with pyyaml pytest tests/compose/test_compose_contract.py -v
docker compose config
```

통합 Neo4j/E2E는 기존 사용자 Docker 데이터가 아니라 새 Compose project name, 명시적 임시 포트,
명시적 disposable DB 설정을 사용하고 종료 시 컨테이너·network·volume을 제거한다.
