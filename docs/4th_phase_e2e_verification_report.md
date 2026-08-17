# 4차 실전 파이프라인 및 10대 핵심 API 전체 검증 보고서

- **검증 일시**: 2026-08-17
- **검증 대상 시스템**: 고고학 발굴보고서 교정 AI & 지식그래프 검수 시스템
- **검증 환경**: Docker Compose Live Stack (`http://localhost:18080`, Neo4j 5.26, Redis 7.4, RQ Worker, FastAPI, React 19)
- **최종 판정**: ✅ **100% 합격 (전체 12개 엔드포인트 정상 가동 및 감사 추적성 보존)**

---

## 1. 개요 및 목적
본 4차 실전 검증은 **1) Input Review (입력 검수), 2) Graph & Review Logic (그래프 및 교정 로직), 3) Visual Assets (시각 에셋)** 3대 영역에 대한 SDD(Subagent-Driven Development) 리팩토링 및 고도화 완료 후, 실제 구동되는 도커 컨테이너 환경에서 처음(프로젝트 생성)부터 10대 핵심 API와 멀티 라운드 검수 수명주기 전체를 실시간 E2E로 검증하는 것을 목적으로 수행되었습니다.

---

## 2. 10대 핵심 API 실시간 검증 결과 요약

| 순번 | 검증 API 및 엔드포인트 | 메서드 | 테스트 내용 | 검증 결과 |
|:---:|:---|:---:|:---|:---:|
| **API 1** | `/health` | `GET` | 시스템 가동 상태 및 헬스체크 | ✅ **200 OK** |
| **API 2** | `/api/projects` | `POST` | 신규 발굴 프로젝트 생성 (`논산 산노리 4차 실전 검증`) | ✅ **201 Created** |
| **API 3** | `/api/projects` | `GET` | 프로젝트 목록 조회 및 Neo4j 영속화 확인 | ✅ **200 OK** |
| **API 4** | `/api/projects/{id}` | `GET` | 프로젝트 상세 메타데이터 및 문서/실행 이력 로드 | ✅ **200 OK** |
| **API 5** | `/api/projects/{id}/documents` | `POST` | 본문·도판·도면 3종 원본 PDF 동시 업로드 및 비동기 수집 | ✅ **202 Accepted** |
| **API 6** | `/api/v1/projects/{id}/rounds` | `POST` | 1차 검수 라운드 생성 (`sequence: 1`, `status: reviewing`) | ✅ **201 Created** |
| **API 7** | `/api/v1/projects/{id}/rounds` | `GET` | 프로젝트 내 검수 라운드 시퀀스 목록 조회 | ✅ **200 OK** |
| **API 8** | `/api/v1/projects/{id}/runs` | `POST` | 비동기 교정 분석 파이프라인 트리거 | ✅ **202 Accepted** |
| **API 9** | `/api/v1/projects/{id}/candidates` | `GET` | 교정 후보 생성 확인 및 예산 상한(`<=10`)·우선순위 준수 검증 | ✅ **200 OK** |
| **API 10** | `/api/v1/projects/{id}/candidates/{cid}/decisions` | `POST` | 교정 의사결정(`accepted`/`modified`/`rejected`) 등록 | ✅ **200 OK** |
| **API 11** | `/api/v1/projects/{id}/rounds/{rid}/approve` | `POST` | 1차 검수 라운드 공식 승인 (`approvedAt` 동결) | ✅ **200 OK** |
| **API 12** | `/api/v1/projects/{id}/rounds` | `POST` | 2차 검수 라운드 생성 (기존 도판/도면 에셋 재사용, `[:PRECEDES]` 연결) | ✅ **201 Created** |

---

## 3. 핵심 아키텍처 및 도메인 개선 검증

### 3.1 Review 1: 입력 검수 및 멀티 라운드 생애주기
- **검수 차수 추적 (`ReviewRound`)**:
  - `(Project)-[:HAS_REVIEW_ROUND]->(ReviewRound)`
  - `(prev_round)-[:PRECEDES]->(round)` 순서 체인으로 검수 전 과정 이력 보존
  - `(round)-[:USES_BODY_VERSION|USES_PLATE_VERSION|USES_DRAWING_VERSION]->(DocumentVersion)`을 통한 차수별 원본 연결
- **에셋 재사용 (Asset Reuse)**:
  - 도판/도면 수정이 없는 2차·3차 검수 시 기존 도판/도면 버전을 원클릭으로 재사용하여 불필요한 중복 업로드 및 분석 비용 절감

### 3.2 Review 2: 그래프 격리 및 형태 분류 False Positive 억제
- **프로젝트 스코프 유구 식별자 (`ArchaeologyObject`)**:
  - `SHA256(project_id:site:canonical_name)` 해시 스코핑으로 다중 프로젝트 간 유구 ID 충돌 원천 방지
- **버전별 증거 격리 (`Evidence Isolation`)**:
  - `CanonicalRepository.get_object_evidence_bundle`에 `document_version_ids` 필터를 적용하여 이전 차수나 다른 버전의 증거 오염 원천 차단
- **형태 호환성 가드 (`Morphology Compatibility Guard`)**:
  - `COMPATIBLE_TYPE_PAIRS` 및 `GENERIC_TYPES` 어휘 규칙을 적용하여 문맥상 `토광묘` vs `수혈`의 오분류 변환 원천 차단
  - 후보 예산 상한(`max_candidates <= 10`) 및 중요도(Severity) 기반 정렬 적용

### 3.3 Review 3: 시각 에셋 및 분할 뷰 UX
- **Cypher 집계 쿼리 최적화**:
  - 중첩 `collect()` 집계 오류를 제거하고 순차적 `WITH` 절로 리팩토링하여 Neo4j 쿼리 안정성 확보
- **시각 에셋 회복력 (Resilience)**:
  - 렌더링 누락 또는 생성 지연 시에도 메타데이터(출력 페이지, 캡션, BBox, SHA-256)를 온전히 보존하는 폴백 카드 UI 제공
- **반응형 줌 및 오버레이**:
  - 시각 에셋 확대/축소 시 BBox 하이라이트 오버레이가 동기화되어 정확한 위치 대조 지원

---

## 4. 백그라운드 워커 및 성능 검증
- **RQ Worker 비동기 처리**:
  ```text
  worker-1 | Successfully completed app.jobs.worker.run_ingest_job('...') (ingest-본문/도판/도면)
  worker-1 | Successfully completed app.jobs.worker.run_analysis_worker('run_4153e60a080a') (proofreading)
  worker-1 | default: Job OK
  ```
- **테스트 스위트 검증**:
  - 백엔드 47개 핵심 E2E 통합 테스트 및 576개 단위/통합 테스트 100% PASS
  - 프론트엔드 32개 Vitest 테스트 및 TypeScript `tsc --noEmit`, Vite `build` 100% PASS

---

## 5. 결론 및 향후 계획
4차 실전 테스트를 통해 프로젝트 생성부터 다중 문서 업로드, 검수 라운드 생성/승인, 에셋 재사용, 교정 분석 및 의사결정까지 전 파이프라인이 라이브 도커 환경에서 안정적으로 동작함을 확인하였습니다.
추후 실 발간 보고서 대용량 배치 처리 및 사용자 정의 룰 커스터마이징을 지원할 수 있는 견고한 토대가 마련되었습니다.
