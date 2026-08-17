# Post-Remediation Evaluation Handoff

> **대상 브랜치:** `review-remediation-20260817`
>
> **작성 시점 기준 HEAD:** `253a470ce9a7a68c9b716fe8d96445a9e2a32484`
>
> **목적:** 다음 에이전트가 현재 구현을 다시 개발하는 것이 아니라, 실제 production 경로를 독립적으로 시험하고 남은 정리 항목을 최소 수정한 뒤 검증 증거를 남기도록 하는 평가용 handoff 문서다.
>
> **평가자 역할:** 이후 ChatGPT는 구현자가 아니라 **평가자**로 동작한다. 다음 에이전트가 남긴 코드/테스트/Neo4j 증거/실행 결과를 기준으로 PASS/FAIL만 판정한다.

---

## 0. 가장 중요한 규칙

이 프로젝트의 목표는 단순 PDF 오탈자 검사가 아니다.

실제 목표는 다음 세 입력을 하나의 검수 회차로 묶고, Neo4j canonical graph를 통해 본문·사진/도판·도면의 관계를 검증하는 것이다.

```text
Project
  -> ReviewRound #N
      -> BODY_VERSION    -> 본문 PDF
      -> PLATE_VERSION   -> 도판/사진 PDF
      -> DRAWING_VERSION -> 도면 PDF
      -> AnalysisRun
          -> CorrectionCandidate
              -> Evidence
              -> ArchaeologyObject
              -> Reference
              -> canonical visual asset
              -> ReviewDecision
```

### 절대 위반하면 안 되는 domain invariant

1. `ReviewRound`가 한 분석 Run의 입력 authority다.
2. 사용자가 분석 실행 시 body/plate/drawing version ID를 별도로 다시 조합하면 안 된다.
3. `1차/2차/3차/final`은 사용자 검수 모델이 아니다. 검수는 `ReviewRound.sequence = 1..N`으로 무제한 진행될 수 있다.
4. `final`은 파일 업로드 단계가 아니라 전문가 승인 결과다.
5. InDesign Links filename 숫자는 publication plate/drawing identifier가 아니다.
6. `4. 조사 후_45.JPG`, `_45.JPG`, `photo_45.JPG` 같은 파일명은 `도판 45` identity를 결정할 수 없다.
7. canonical identity는 PDF 안의 명시적 publication identifier, 예를 들면 `【도판 45】`, `【도면 30】`에서 결정한다.
8. Neo4j 관계가 실제 분석 경로다. Graph를 제거해도 같은 성공 결과가 나오면 설계 실패다.
9. LLM/VLM은 identity를 만들거나 복구하지 않는다. deterministic structure + canonical graph가 identity를 확정한 뒤 semantic review에만 사용한다.
10. 모든 AI 결과는 `pending_review`이며 최종 승인자는 사람이다.
11. 개발 모드의 후보/AI/VLM budget은 비용을 줄이기 위한 것이며 전체 PDF parsing과 canonical graph 구축을 생략하는 기능이 아니다.
12. Golden Dataset은 전문가 provenance가 없는 사례를 `VALID_GROUND_TRUTH`라고 표시하면 안 된다.

---

# 1. 이번 remediation에서 실제로 바뀐 내용

아래는 `a25f0ab8...` 이후 현재 branch까지의 주요 구조적 변경을 기능 단위로 정리한 것이다.

## 1.1 Input model: `ReviewRound` 중심으로 변경

이전 문제:

```text
본문 v3
도판 v1
도면 v2
```

같은 조합을 분석 실행 직전에 사용자가 다시 선택할 수 있었고, `1차/2차/3차/final`이 데이터 모델과 UI 양쪽에 고정되어 있었다.

현재 production run contract는 다음과 같은 형태다.

```json
{
  "reviewRoundId": "round_xxx",
  "enableVlm": true,
  "enableAiReview": true
}
```

`backend/app/api/review_round_runs.py`가 `ReviewRound`를 다시 조회하여 body/plate/drawing DocumentVersion을 결정한다.

Frontend 역시 `ProjectDetailPage`에서 선택된 `ReviewRound` 하나만 `triggerProofreadingRun()`에 전달하도록 변경되었다.

현재 UI에서 파일 업로드 시 선택하는 것은 문서 종류뿐이다.

```text
본문
도판 / 사진
도면
```

회차 번호와 최종 여부는 업로드 폼이 아니라 ReviewRound에서 관리한다.

### 검수 회차 reuse

새 회차에서 변경되지 않은 시각 자산은 이전 회차 것을 재사용할 수 있다.

```text
Round #1
  body v1
  plate v1
  drawing v1

Round #2
  body v2
  plate v1  <- reuse
  drawing v1 <- reuse
```

이 구조가 실제 업무 모델의 기준이다.

---

## 1.2 Worker에서도 ReviewRound를 다시 resolve하도록 변경

API에서 한 번 resolve한 값을 그대로 믿지 않는다.

RQ worker는 `AnalysisRun.review_round_id`가 있으면 실행 시점에 다시 Neo4j의 ReviewRound를 읽고 해당 Round가 가리키는 세 DocumentVersion을 authority로 사용한다.

즉 AnalysisRun에 저장된 body/plate/drawing ID는 audit snapshot이며 ReviewRound membership을 덮어쓸 수 없다.

이 변경으로 다음 회귀를 차단했다.

```text
Round #4가 body v3를 재사용했는데
worker가 "4차" stage 문자열을 body identity로 사용하여 실패하는 문제
```

단, **이 문서 뒤의 `검증 항목 V3`에서 predecessor body comparison이 실제 `ReviewRound PRECEDES`를 따르는지 반드시 다시 검증해야 한다.** 현재 `run_inputs.py`에는 compatibility stage 기반 코드가 남아 있기 때문이다.

---

## 1.3 DocumentVersion 순서와 ReviewRound 순서를 분리

기존에는 `DocumentVersion.stage` 값으로 `PRECEDES`를 만들 가능성이 있었다.

현재 목표 모델은 다음과 같다.

```text
DocumentVersion
  = 업로드된 실제 자료 버전

ReviewRound.sequence
  = 검수 업무 순서 1..N

ReviewRound -[:PRECEDES]-> ReviewRound
  = 검수 lineage
```

즉 `3차 -> 1차` 같은 잘못된 DocumentVersion lineage를 upload 순서로 만들면 안 된다.

---

## 1.4 Neo4j project/run isolation 강화

현재 remediation은 다음을 강화했다.

- `ArchaeologyObject` ID에 project scope 포함
- `(Project)-[:HAS_OBJECT]->(ArchaeologyObject)`
- AnalysisRun과 ReviewRound 연결
- Candidate의 project ownership
- Candidate의 run-specific identity
- Finding fingerprint와 Candidate instance ID 분리
- Evidence/traceability의 selected DocumentVersion scope
- Candidate decision/traceability/visual-bundle의 project scope

의도한 결과:

```text
Project A candidate를
Project B API URL을 통해 조회/승인/trace하면 실패해야 한다.
```

동일한 의미의 오류가 Round #1과 Round #2에서 다시 발견되어도 Candidate node 자체는 각각 별도 instance여야 한다.

```text
Run #1 -> Candidate A1 --fingerprint--> F
Run #2 -> Candidate A2 --fingerprint--> F

A1.id != A2.id
```

Round #1의 ReviewDecision이 Round #2 Candidate에 붙으면 FAIL이다.

---

## 1.5 False Positive 억제

이전 실물 테스트에서 후보가 2,000건 이상 폭증했다.

주요 원인 중 하나는 다음과 같은 morphology overlap이었다.

```text
수혈유구
 -> 수혈유구
 -> 수혈
 -> 유구
```

또한 한 TextBlock/rationale의 넓은 텍스트를 여러 객체 Evidence로 다시 해석하면서 잘못된 type mismatch가 만들어질 수 있었다.

현재 구현에는 longest-match/compatible-type guard와 strict rule layer가 추가되어 있다.

그러나 이것을 단순히 "해결됨"이라고 믿지 말고, 다른 에이전트는 실제 후보 수와 false-positive sample을 다시 측정해야 한다.

---

## 1.6 Development Candidate Budget = 10

개발 모드 기본값:

```text
REVIEW_MODE=development
DEVELOPMENT_CANDIDATE_BUDGET=10
```

`compose.yml`의 web/worker 모두 같은 값을 사용한다.

목표 pipeline:

```text
전체 PDF parse
 -> 전체 canonical graph 구축
 -> 전체 deterministic/cheap rule scan
 -> raw_findings 집계
 -> dedupe
 -> representative selection
 -> 최대 10개의 expensive operation
 -> LLM/VLM
 -> 최대 10건 수준의 상세 검수 materialization/UI
```

다음 수치는 서로 분리해서 기록되어야 한다.

```text
raw_findings
  != deduped_findings
  != selected_candidates

expensive_operations <= 10  (development mode)
```

**중요:** 화면에 10개만 보인다고 비용 제한이 성공한 것이 아니다. LLM/VLM 호출 자체가 budget 이전에 2,000번 실행되면 FAIL이다.

현재 `DevelopmentReviewBudget`은 `expensive_operations`를 별도 카운트하고 run summary에 기록한다.

---

## 1.7 Visual asset canonical path 강화

이전 UI의 대표 증상:

```text
시각 자산을 불러오지 못했습니다.
```

또는 Candidate와 무관한 첫 번째 도판을 임의 선택하는 문제가 있었다.

현재 방향은 다음 canonical path다.

```text
TextBlock / Caption
  -> REFERENCES
Reference
  -> RESOLVES_TO
Plate / PlatePanel / Drawing / DrawingRegion
  -> DEPICTS
ArchaeologyObject
```

Candidate visual bundle은 단순히 `ArchaeologyObject <- DEPICTS - 모든 자산`에서 첫 번째 것을 고르면 안 된다.

정확한 target을 확정할 수 없으면 다음이 정상이다.

```text
canonical = null
unresolvedReason = "..."
```

즉 잘못된 그림을 보여주는 것보다 fail-closed가 우선이다.

현재 live validator도 canonical image가 없을 때 explicit `unresolvedReason`이 있는지를 검사한다.

---

## 1.8 Frontend Split View

현재 frontend는 다음 구조를 목표로 한다.

```text
LEFT
  실제 본문 PDF page
  source bbox / evidence

RIGHT
  candidate가 참조한 실제 도판/사진 또는 도면
  canonical bbox / panel / region

BELOW
  deterministic finding
  VLM observation (실제 VLM evidence가 있을 때만)
  AI grounded explanation
  승인 / 반려 / 수정 / 보류
```

ReviewRound가 선택된 상태에서만 analysis를 시작하며, body/plate/drawing이 모두 없는 incomplete round는 실행하면 안 된다.

---

## 1.9 Golden Dataset 의미 수정

기존 파일은 실제 전문가 provenance 없이 10개 case를 `Expert-verified` / `VALID_GROUND_TRUTH`라고 표현하고 있었다.

현재는 다음 정책으로 수정되었다.

```text
Case 1~5, 7~10
  ground_truth_status = NEEDS_REVALIDATION
  expert_verified = false

Case 6
  ground_truth_status = INVALID_GROUND_TRUTH_MAPPING
  expert_verified = true
```

Case 6에서 전문가가 확인한 것은 **옛 filename 기반 매핑이 틀렸다는 사실**이다.

```text
본문: 도판 45

올바른 identity source:
  【도판 45】

금지:
  4. 조사 후_45.JPG
```

향후 어떤 case를 `VALID_GROUND_TRUTH`로 승격하려면 최소 다음 provenance가 필요하다.

```text
expert_verified = true
verified_by
verified_at
source_pdf_sha256
canonical_publication_identifier
expert_note
```

Agent가 이 값을 임의로 만들어 넣으면 즉시 FAIL이다.

---

# 2. 현재 검증된 baseline

작성 시점 기준 GitHub Actions:

```text
Workflow: Review remediation CI
Run: #63
HEAD: 253a470ce9a7a68c9b716fe8d96445a9e2a32484
Conclusion: success
```

### Backend hermetic

```text
501 passed
7 skipped
12 deselected
```

### Real Neo4j integration + E2E

```text
42 passed
```

GitHub Actions는 실제 `neo4j:5.26-community` container 2개를 띄워 integration/application DB와 isolated repository DB를 분리한다.

### Frontend

```text
Typecheck PASS
Unit tests PASS
Build PASS
```

### 이 baseline이 증명하지 않는 것

위 결과를 다음과 같이 과대 해석하면 안 된다.

- 실제 500MB급 도판 PDF 전체 성능을 증명하지 않는다.
- 실제 고고학자의 domain correctness를 증명하지 않는다.
- Golden Case 1~5, 7~10이 진실임을 증명하지 않는다.
- 외부 AI/VLM semantic quality를 기본 CI가 증명하지 않는다.
- 모든 로컬 실물 fixture test가 CI에서 실행된 것은 아니다.
- production 모드에서 수천 candidate를 실제로 처리한 비용/성능을 증명하지 않는다.

따라서 다음 에이전트는 "CI green"만 보고 최종 PASS를 선언하면 안 된다.

---

# 3. 현재 남아 있는 정리 / 고위험 검증 항목

아래는 다음 에이전트가 **검증 우선**으로 확인해야 한다.

## C1. Legacy direct-version `/runs` handler 완전 제거 검토

현재 production route는 `backend/app/api/review_round_runs.py`의 strict ReviewRound contract가 먼저 등록된다.

그러나 `backend/app/api/reviews.py`에는 같은 path의 legacy handler 코드가 아직 남아 있다.

`main.py`는:

1. legacy route를 OpenAPI schema에서 숨기고
2. ReviewRound route를 먼저 등록하여 runtime에서 strict route가 먼저 match되도록 한다.

현재 동작상 보호는 되어 있지만 구조적으로 같은 POST path가 두 개 존재한다.

### 다음 에이전트 목표

먼저 runtime contract를 검증한다.

```text
POST /api/v1/projects/{project}/runs
bodyVersionId만 전달
reviewRoundId 없음

=> 422
=> legacy direct version run 생성 금지
```

이 gate가 확보되면 legacy route 자체를 삭제/비-route compatibility helper로 이동하는 정리를 권장한다.

**금지:** 테스트를 통과시키기 위해 direct-version public API를 다시 살리는 것.

---

## C2. Orchestrator factory module-level selector mutation 제거 검토

현재 `orchestrator_factory.py`는 import 시 다음 module symbol을 교체한다.

```python
proofreading_orchestrator_module.prioritize_and_cap_candidates = (
    select_development_candidates
)
```

현재 selector는 `max_candidates=None`이면 전체 set을 반환하므로 production cap을 강제로 10으로 만드는 코드는 아니지만, process-global mutation이라는 구조적 debt가 남아 있다.

### 다음 에이전트가 검증할 것

한 Python process에서 순서대로:

```text
1. development orchestrator 생성 (budget=10)
2. production orchestrator 생성 (budget=None)
3. development 재생성
4. production 재생성
```

해도 각 instance의 behavior가 다른 instance에 오염되지 않아야 한다.

가능하면 selector/budget을 instance dependency로 주입하여 global monkey-patch를 제거한다.

단, broad refactor는 금지한다.

---

## C3. Previous-body comparison이 `ReviewRound PRECEDES`를 따르는지 검증

이 항목은 중요도가 높다.

현재 worker는 **현재 Round의 body/plate/drawing identity**를 ReviewRound에서 다시 resolve한다.

그러나 `backend/app/jobs/run_inputs.py`의 body comparison helper에는 아직 다음 compatibility 개념이 남아 있다.

```text
N차 -> (N-1)차, N차
```

실제 업무에서는 Round sequence와 DocumentVersion.stage가 동일하다는 보장이 없다.

예:

```text
Round #1 = body v1
Round #2 = body v2
Round #3 = body v2  (본문 재사용)
Round #4 = body v3
```

Round #4의 previous body는 **Round #3가 가리키는 body v2**여야 한다.

`"3차" stage의 DocumentVersion`을 찾는 것이 아니다.

### Acceptance

- immediate predecessor는 Graph의 `ReviewRound PRECEDES`로 결정한다.
- predecessor Round가 같은 body version을 재사용해도 정상이다.
- Round #4, #5 이상도 정상이다.
- `final` string이 필요하지 않다.

이 gate가 실패하면 다음 에이전트가 반드시 수정하고 real Neo4j regression test를 추가해야 한다.

---

## C4. CI에서 의도적으로 제외된 legacy/local tests 정리

현재 hermetic CI는 다음 범주의 테스트를 일부 ignore/deselect한다.

- real Neo4j 필요
- 로컬 archaeology source asset 필요
- 과거 direct-version/stage contract를 검증하는 legacy test

이것은 현재 CI를 green으로 만들기 위한 단순 은폐가 되어서는 안 된다.

다음 에이전트는 deselected legacy test가 새 ReviewRound contract의 equivalent test로 대체되었는지 확인한다.

대체 test가 없는 경우 새 contract test를 추가한다.

로컬 실제 자료가 필요한 테스트는 CI에 억지로 넣지 말고 `local_tests/` 또는 별도 acceptance 단계로 유지한다.

---

## C5. External AI/VLM semantic run

`scripts/run_live_10_api_validation.py`는 기본값이:

```text
ENABLE_LIVE_AI=0
ENABLE_LIVE_VLM=0
```

이다.

따라서 기본 live validation은 Graph/API/render pipeline을 증명하지만 외부 모델 semantic quality를 증명하지 않는다.

API key가 실제 환경에 있고 비용 사용이 허용된 경우에만:

```text
ENABLE_LIVE_AI=1
ENABLE_LIVE_VLM=1
DEVELOPMENT_CANDIDATE_BUDGET=10
```

으로 한 번 추가 실행한다.

비용 보호를 위해 budget 10을 해제하지 않는다.

API key가 없으면 결과 문서에 반드시:

```text
External AI semantic validation: NOT VERIFIED
External VLM semantic validation: NOT VERIFIED
Reason: no usable API key / execution not authorized
```

라고 적는다. 임의로 PASS 처리하지 않는다.

---

## C6. Warnings / technical cleanup

현재 CI에 다음 warning이 존재한다.

```text
backend/app/services/json_utils.py: invalid escape sequence '\s'
```

또 GitHub Actions에서 일부 action의 Node runtime deprecation warning이 보인다.

기능 blocker는 아니지만 다음 에이전트가 손대기 쉬운 범위라면 별도 small commit으로 정리한다.

기능 변경과 warning cleanup을 같은 commit에 섞지 않는다.

---

# 4. 다음 에이전트 작업 절차

## 작업 원칙

다음 에이전트는 반드시 **verification-first**로 진행한다.

```text
현재 코드 실행
 -> 실패 재현
 -> 실패 원인 기록
 -> failing regression test 작성
 -> 최소 수정
 -> targeted test
 -> 전체 공식 gate 재실행
 -> 결과 문서 작성
 -> push
```

### 금지 사항

- 먼저 대규모 refactor하고 나중에 테스트하기
- 실패한 테스트를 삭제/skip/deselect하여 green 만들기
- Golden Dataset expected value를 코드에 맞게 바꿔 green 만들기
- filename 숫자를 canonical identity로 다시 사용하기
- Neo4j 실패 시 in-memory 성공 fallback 추가하기
- AI/VLM로 Reference identity를 추측하기
- `candidates[:10]`만 넣어 개발 budget 구현했다고 주장하기
- UI fallback 문구만 바꾸고 실제 visual-bundle/render 실패를 해결했다고 주장하기
- 실제 실행하지 않은 항목을 보고서에서 PASS라고 쓰기

---

# 5. Verification Gate V0 — branch와 baseline 고정

먼저 다음을 실행한다.

```bash
git fetch origin
git checkout review-remediation-20260817
git pull --ff-only origin review-remediation-20260817
git status --short
git rev-parse HEAD
```

### 기록할 것

```text
start_sha=<실제 SHA>
working_tree_clean=true/false
```

이 handoff 작성 당시 baseline SHA는:

```text
253a470ce9a7a68c9b716fe8d96445a9e2a32484
```

다른 commit이 추가되어 있으면 되돌리지 말고 실제 start SHA를 결과 문서에 기록한다.

---

# 6. Verification Gate V1 — 공식 CI 재현

## V1-A Backend compile/hermetic

GitHub Actions의 `.github/workflows/remediation-ci.yml`을 source of truth로 사용한다.

최소:

```bash
cd backend
python -m compileall -q app
```

그리고 workflow의 `backend-hermetic` command를 그대로 실행하거나 GitHub Actions를 재실행한다.

작성 시점 기대 baseline:

```text
501 passed
7 skipped
12 deselected
```

숫자가 달라지는 것 자체는 실패가 아니다. 그러나 **failed > 0이면 FAIL**이다.

## V1-B Real Neo4j

공식 CI expected baseline:

```text
42 passed
```

로컬 disposable instance를 쓸 경우:

```bash
NEO4J_PASSWORD=testpass-2026 \
docker compose -f compose.yml -f compose.test.yml up -d neo4j-test redis
```

그 후 최소 real graph suite를 실행한다.

```bash
cd backend
export RUN_NEO4J_INTEGRATION=1
export NEO4J_URI=bolt://127.0.0.1:7688
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=testpass-2026
export TEST_NEO4J_URI=bolt://127.0.0.1:7688
export TEST_NEO4J_PASSWORD=testpass-2026
export REVIEW_MODE=development
export DEVELOPMENT_CANDIDATE_BUDGET=10

pytest -q tests/integration tests/test_real_neo4j_remediation.py -s
```

`tests/test_project_repository.py`는 DB isolation 조건을 확인하고 별도 disposable DB가 필요하면 CI 방식처럼 두 번째 Neo4j를 사용한다.

## V1-C Frontend

```bash
cd frontend
npm ci
npm run typecheck
npm test -- --run
npm run build
```

모두 PASS해야 한다.

---

# 7. Verification Gate V2 — Public API는 ReviewRound-only인가

## V2-A OpenAPI

OpenAPI에서 production `POST /api/v1/projects/{project_id}/runs` request schema가 `reviewRoundId`를 요구하는지 확인한다.

## V2-B Runtime

실제 test Project에 대해 다음 요청을 보낸다.

```json
{
  "bodyVersionId": "some-body-version",
  "plateVersionId": "some-plate-version",
  "drawingVersionId": "some-drawing-version"
}
```

`reviewRoundId`가 없다.

### Expected

```text
HTTP 422
AnalysisRun 생성 안 됨
RQ job enqueue 안 됨
```

### 추가 공격 테스트

ReviewRound가 Project A 소속인데 Project B URL로 실행:

```text
POST /api/v1/projects/B/runs
{ reviewRoundId: round_from_A }
```

Expected:

```text
4xx
AnalysisRun 없음
```

이것이 통과한 뒤 C1 legacy handler removal을 진행할 수 있다.

---

# 8. Verification Gate V3 — Unbounded ReviewRound + true predecessor

이 gate는 현재 코드의 고위험 지점이다.

Real Neo4j에서 최소 5개 Round를 만든다.

```text
Round #1 -> body v1, plate p1, drawing d1
Round #2 -> body v2, plate p1, drawing d1
Round #3 -> body v2, plate p1, drawing d1   # body reuse
Round #4 -> body v3, plate p2, drawing d1
Round #5 -> body v4, plate p2, drawing d2
```

### 검증

1. sequence가 `1,2,3,4,5`로 생성된다.
2. Round #3은 body v2 재사용이 가능하다.
3. Round #4 실행 시 current body는 v3이다.
4. Round #4의 previous body comparison source는 **Round #3의 body v2**다.
5. `DocumentVersion.stage == "3차"`인 파일을 찾았기 때문에 v2를 골랐다는 식이면 FAIL이다.
6. Round #5도 같은 규칙으로 동작한다.
7. UI/API에서 `final` stage 선택이 필요하지 않다.
8. Round 승인 시 `approvedAt`을 두 번 승인해도 최초 timestamp가 유지된다.

### 실패 시 수정 원칙

predecessor는 반드시:

```text
(current:ReviewRound)<-[:PRECEDES]-(previous:ReviewRound)
```

또는 repository가 정의한 동등한 명시적 ReviewRound lineage를 통해 찾는다.

`N차 -> N-1차` 문자열 계산은 identity source로 사용하지 않는다.

---

# 9. Verification Gate V4 — Neo4j가 진짜 분석 core인가

Disposable DB에서만 수행한다.

## Baseline

정상 canonical graph를 만들고 분석하여 결과를 저장한다.

필수 관계 예:

```text
TextBlock/Caption -[:MENTIONS]-> ArchaeologyObject
TextBlock/Caption -[:REFERENCES]-> Reference
Reference -[:RESOLVES_TO]-> Plate/PlatePanel/Drawing/DrawingRegion
VisualAsset -[:DEPICTS]-> ArchaeologyObject
AnalysisRun -[:PRODUCED]-> CorrectionCandidate
Candidate -[:SUPPORTED_BY]-> Evidence
Evidence -[:EXTRACTED_FROM]-> Page
Evidence -[:FROM_VERSION]-> DocumentVersion
Candidate -[:HAS_DECISION]-> ReviewDecision
```

## Kill-switch tests

별도 fixture/run에서 하나씩 관계를 제거하거나 resolve 실패 상태를 만든다.

### K1 `RESOLVES_TO` 제거

Expected:

- canonical visual/reference result가 baseline과 같으면 FAIL
- unrelated visual first-match로 대체하면 FAIL
- unresolved/manual-review/fail-closed가 정상

### K2 `MENTIONS` 제거

Expected:

- 같은 object grounded analysis가 그대로 성공하면 FAIL

### K3 `DEPICTS` 제거

Expected:

- visual/object semantic evidence가 그대로 연결되면 FAIL

### 핵심 판정 문장

> `REFERENCES`, `RESOLVES_TO`, `MENTIONS`, `DEPICTS`를 끊어도 같은 성공 결과가 나오면 이 시스템은 Graph 기반 시스템이 아니다.

기존 integration test가 이 invariant를 이미 커버한다고 판단한다면, test 이름과 assertion line을 결과 문서에 정확히 적는다. 말로만 "커버됨"이라고 하지 않는다.

---

# 10. Verification Gate V5 — Development 비용 budget

환경:

```text
REVIEW_MODE=development
DEVELOPMENT_CANDIDATE_BUDGET=10
```

의도적으로 cheap rule finding이 10개를 훨씬 넘도록 fixture를 만든다.

예:

```text
raw_findings >= 50
```

### Expected diagnostics

```text
raw_findings >= deduped_findings
selected_candidates <= 10
expensive_operations <= 10
selection_mode = development_stratified_pre_ai
```

### 반드시 확인

- 전체 PDF/Graph는 모두 구축됨
- `raw_findings`는 10으로 잘려 저장되지 않음
- UI 후보 수가 10 이하라는 것만 확인하고 끝내지 않음
- AI/VLM 실제 호출 counter가 10 이하임
- plate/drawing 후보가 존재할 경우 stratified selector가 visual path를 완전히 굶기지 않는지 확인

### Production control

같은 테스트 process 또는 별도 process에서:

```text
REVIEW_MODE=production
DEVELOPMENT_CANDIDATE_BUDGET unset
CANDIDATE_BUDGET unset
```

으로 production orchestrator를 만들어 10 hard cap이 적용되지 않는지 확인한다.

이 test는 C2 global selector mutation 여부도 같이 검증한다.

---

# 11. Verification Gate V6 — Candidate run/project isolation

동일한 finding을 두 AnalysisRun에서 의도적으로 발생시킨다.

### Expected

```text
run1_candidate.id != run2_candidate.id
findingFingerprint may be equal
```

Round #1 Candidate를 accepted한 뒤 Round #2 동일 finding Candidate를 조회한다.

Expected:

```text
Round #2 candidate = pending_review
Round #1 decision이 Round #2에 보이면 FAIL
```

Cross-project API도 검사한다.

```text
Project B URL + Project A candidate id
```

다음 endpoint 모두 4xx여야 한다.

```text
candidate detail
candidate decision
candidate traceability
candidate visual-bundle
```

---

# 12. Verification Gate V7 — Visual asset / Split View

두 종류를 따로 검증한다.

## V7-A Synthetic raster E2E

현재 `scripts/run_live_10_api_validation.py`는 도판/도면 PDF 안에 실제 PNG raster를 삽입한다.

따라서 text-only fixture가 아니다.

아래 live E2E를 실행하면 visual-bundle이 반환한 `imageUrl`에 실제 GET을 보내:

```text
HTTP 200
Content-Type: image/*
response bytes > 0
```

를 확인한다.

## V7-B Wrong-asset prevention

하나의 ArchaeologyObject에 관련 visual asset을 최소 2개 연결하는 fixture를 만든다.

예:

```text
Object 6호 석관묘
  <- DEPICTS - Plate45
  <- DEPICTS - Plate46
```

Candidate가 `도판 45` Reference에서 발생했다면:

```text
canonical = Plate45
```

이어야 한다.

단순히 query 첫 번째 asset을 Plate45로 우연히 반환하도록 fixture order를 만들지 않는다. 순서를 반대로 넣는 test도 한다.

정확한 target을 확정할 수 없으면:

```text
canonical = null
unresolvedReason != null
```

이어야 한다.

## V7-C Frontend

브라우저에서 최소 다음 3개 상태를 screenshot으로 남긴다.

1. source page + canonical 도판 정상 표시
2. source page + canonical 도면 정상 표시
3. canonical unresolved 상태에서 잘못된 asset 대신 명시적 unresolved UI

단순 `시각 자산을 불러오지 못했습니다` screenshot만으로는 원인 확인이 불가능하다.

각 screenshot과 함께 candidate ID, project ID, visual-bundle JSON 일부를 결과 문서에 기록한다.

---

# 13. Verification Gate V8 — Case 6 filename trap

반드시 real Neo4j integration 또는 동등한 end-to-end fixture로 확인한다.

Input concept:

```text
본문 reference = 도판 45
explicit publication asset = 【도판 45】
decoy filename = 4. 조사 후_45.JPG
```

### Expected

```text
Reference(plate,45)
 -> RESOLVES_TO
Plate(publication_identifier=45)
```

### Forbidden

```text
Reference(plate,45)
 -> filename suffix 45
 -> 4. 조사 후_45.JPG
```

### 추가 negative

본문이 `도판 91`을 가리키지만 explicit `【도판 91】`이 없고 `_91.JPG`만 있다면:

```text
unresolved
```

이어야 한다.

filename decoy 때문에 Plate91을 만들거나 resolve하면 FAIL이다.

---

# 14. Verification Gate V9 — Golden Dataset provenance

현재 파일:

```text
backend/tests/fixtures/golden/golden_dataset.yaml
```

### Expected

```text
Case 1~5, 7~10
  NEEDS_REVALIDATION
  expert_verified=false

Case 6
  INVALID_GROUND_TRUTH_MAPPING
  expert_verified=true
```

`VALID_GROUND_TRUTH` case가 새로 생겼다면 다음 필드가 모두 실제 근거와 함께 있어야 한다.

```text
verified_by
verified_at
source_pdf_sha256
canonical_publication_identifier
expert_note
```

다음 테스트를 반드시 실행한다.

```bash
cd backend
pytest -q \
  tests/test_golden_ground_truth_provenance.py \
  tests/test_golden_verification_gates.py
```

Agent가 테스트 통과를 위해 expert provenance를 허구로 입력하면 평가에서 즉시 FAIL이다.

---

# 15. Verification Gate V10 — Live 10 API validation

개발 stack을 띄운다.

예:

```bash
export NEO4J_PASSWORD=testpassword
export WEB_PORT=18080
export REVIEW_MODE=development
export DEVELOPMENT_CANDIDATE_BUDGET=10

docker compose up -d --build neo4j redis web worker
```

service가 올라온 뒤:

```bash
VALIDATION_BASE_URL=http://localhost:18080 \
DEVELOPMENT_CANDIDATE_BUDGET=10 \
python scripts/run_live_10_api_validation.py
```

### Script가 증명해야 하는 것

1. Project 생성
2. body v1 / plate v1 / drawing v1 ingest 완료
3. Round #1 생성
4. repeated approve 시 `approvedAt` 불변
5. 실제 body v2 생성
6. Round #2 = body v2 + plate v1 reuse + drawing v1 reuse
7. run은 ReviewRound ID로 실행
8. AnalysisRun completed
9. diagnostics의 body/plate/drawing가 Round #2와 정확히 일치
10. raw/deduped/selected/expensive budget 검사
11. candidate 1..10
12. candidate status = pending_review
13. traceability 조회
14. visual-bundle 조회
15. render URL이 있으면 실제 image bytes 200
16. canonical target이 없으면 unresolvedReason 필수
17. expert decision 저장
18. Round #2 approve

마지막 console PASS 문구만 캡처하지 말고 각 gate의 assertion 결과를 결과 문서에 요약한다.

---

# 16. Verification Gate V11 — 실제 고고학 자료 acceptance

이 단계는 로컬에 실제 자료가 있을 때 수행한다.

Raw source asset은 Git에 올리지 않는다.

최소 입력:

```text
실제 본문 초안 PDF
실제 도판/사진 PDF
실제 도면 PDF
```

가능하면 작은 representative subset부터 사용한다.

## 최소 10 candidate가 아니라 최대 10 expensive review

개발 모드 budget은 유지한다.

```text
DEVELOPMENT_CANDIDATE_BUDGET=10
```

다음 항목을 사람이 직접 확인한다.

### A. 본문 오탈자/문맥

- source PDF page가 정확한가
- bbox/text가 Candidate와 일치하는가
- 제안 수정이 다른 문단 Evidence를 섞지 않는가

### B. 본문 -> 도판/사진

- 본문 `도판 N`과 실제 `【도판 N】`이 일치하는가
- panel 표시가 정확한가
- InDesign Links filename이 identity에 개입하지 않는가

### C. 본문 -> 도면

- 본문 `도면 N`과 실제 `【도면 N】`이 일치하는가
- 실제 drawing render/region을 가져오는가

### D. 여러 visual이 같은 Object를 depict하는 경우

- Candidate의 Reference가 가리킨 visual만 표시하는가
- unrelated first asset을 선택하지 않는가

### E. Visual API failure

`시각 자산을 불러오지 못했습니다`가 나타나면 다음을 모두 수집한다.

```text
projectId
candidateId
GET visual-bundle HTTP status
visual-bundle JSON
source imageUrl HTTP status
canonical imageUrl HTTP status
backend log relevant traceback
Neo4j Reference/RESOLVES_TO query result
```

UI screenshot 하나만으로 bug report를 끝내지 않는다.

---

# 17. Verification Gate V12 — 외부 AI/VLM (허가된 경우만)

API key가 있고 실행 비용 사용이 허가된 경우:

```bash
ENABLE_LIVE_AI=1 \
ENABLE_LIVE_VLM=1 \
DEVELOPMENT_CANDIDATE_BUDGET=10 \
VALIDATION_BASE_URL=http://localhost:18080 \
python scripts/run_live_10_api_validation.py
```

### 반드시 기록

```text
raw_findings
selected_candidates
expensive_operations
실제 AI call count
실제 VLM call count
모델명
오류/timeout 횟수
```

### Semantic 확인

VLM result가 있다면 실제 body claim과 visual evidence를 비교했는지 확인한다.

다음은 실패다.

```text
VLM이 image vs 자기 caption/title만 확인
본문 claim이 prompt/evidence에 없음
```

정상은:

```text
Graph-derived body claim
 + canonical Reference target
 + rendered visual
 -> SUPPORTED / PARTIAL / CONTRADICTED / INSUFFICIENT_EVIDENCE
```

---

# 18. 실패를 발견했을 때의 수정 규칙

다음 에이전트는 verification에서 failure를 발견하면 다음 순서를 지킨다.

1. 실패를 재현하는 가장 작은 test 작성
2. 그 test가 기존 HEAD에서 RED인지 확인
3. root cause를 파일/함수/Graph path 수준으로 기록
4. 최소 수정
5. targeted test GREEN
6. 관련 integration test GREEN
7. 공식 3개 CI gate GREEN
8. 변경 이유를 verification result 문서에 기록
9. 별도 commit

### Commit 예

```text
test(round): reproduce predecessor reuse regression
fix(round): resolve previous body from ReviewRound lineage

test(api): reject legacy direct-version run at runtime
refactor(api): remove duplicate legacy runs route

refactor(orchestrator): inject candidate selector per instance
fix(warnings): use raw regex doc example in json_utils
```

한 commit에 unrelated 변경을 섞지 않는다.

---

# 19. 다른 에이전트가 반드시 만들어야 할 결과 문서

검증 완료 후 다음 파일을 생성한다.

```text
docs/superpowers/reviews/2026-08-17-post-remediation-verification-result.md
```

아래 template을 그대로 사용한다.

```markdown
# Post-Remediation Verification Result

## 1. Execution identity

- branch:
- start_sha:
- end_sha:
- verifier:
- date/time:
- OS:
- Docker version:
- Python:
- Node:

## 2. Code changes made during verification

- commit SHA / message / why
- no code changes이면 "none"

## 3. Official gates

### backend-hermetic
- command/workflow run:
- passed:
- failed:
- skipped:
- deselected:
- artifact/run URL or identifier:

### real Neo4j
- passed:
- failed:
- Neo4j version:
- DB isolation used:

### frontend
- typecheck:
- unit tests:
- build:

## 4. V2 ReviewRound-only API

- no-reviewRoundId request status:
- cross-project Round request status:
- AnalysisRun created? yes/no
- evidence:

## 5. V3 Unbounded ReviewRound / predecessor

- Round #1 inputs:
- Round #2 inputs:
- Round #3 inputs:
- Round #4 inputs:
- Round #5 inputs:
- Round #4 previous body resolved from:
- proof this came from ReviewRound lineage:
- PASS/FAIL:

## 6. V4 Neo4j kill-switch

### RESOLVES_TO
- baseline:
- relation removed:
- result changed how:
- PASS/FAIL:

### MENTIONS
...

### DEPICTS
...

## 7. V5 development budget

- raw_findings:
- deduped_findings:
- selected_candidates:
- expensive_operations:
- AI calls:
- VLM calls:
- production mode candidate count behavior:
- PASS/FAIL:

## 8. V6 candidate isolation

- run1 candidate id:
- run2 candidate id:
- shared fingerprint:
- decision leakage observed? yes/no
- cross-project endpoint statuses:
- PASS/FAIL:

## 9. V7 visual assets

- source render:
- plate render:
- drawing render:
- wrong-asset fixture result:
- unresolved fixture result:
- screenshots:
- PASS/FAIL:

## 10. V8 Case 6

- explicit identifier:
- forbidden filename:
- actual RESOLVES_TO target:
- missing Plate91 result:
- PASS/FAIL:

## 11. V9 Golden provenance

- VALID_GROUND_TRUTH count:
- NEEDS_REVALIDATION count:
- Case6 status:
- provenance test output:
- PASS/FAIL:

## 12. V10 Live API E2E

- completed run id:
- ReviewRound id:
- body/plate/drawing version ids:
- candidate count:
- budget summary:
- visual endpoint result:
- PASS/FAIL:

## 13. V11 Real archaeology acceptance

- dataset description only (do not commit raw files):
- body tested:
- plate/photo tested:
- drawing tested:
- candidate examples checked:
- visual examples checked:
- failures:
- PASS/FAIL/NOT VERIFIED:

## 14. V12 External AI/VLM

- AI: PASS/FAIL/NOT VERIFIED
- VLM: PASS/FAIL/NOT VERIFIED
- reason if not verified:
- model/call counts if executed:

## 15. Remaining issues

### P0
- ...

### P1
- ...

### P2
- ...

## 16. Final verifier statement

- SOFTWARE GATE: PASS/FAIL
- GRAPH AUTHORITY GATE: PASS/FAIL
- VISUAL GATE: PASS/FAIL
- DOMAIN GOLDEN QUALITY: PASS/FAIL/NOT VERIFIED
- READY FOR EVALUATOR REVIEW: YES/NO
```

---

# 20. 평가자가 사용할 최종 PASS/FAIL 기준

다음 에이전트가 위 결과를 push하면 평가자는 아래 기준으로만 판단한다.

## P0 — 하나라도 실패하면 최종 FAIL

1. ReviewRound 없이 public analysis run 실행 가능
2. Round와 다른 body/plate/drawing 조합으로 worker 실행
3. Round #4 이상 또는 asset/body reuse에서 분석 identity가 stage 문자열 때문에 깨짐
4. immediate previous body가 ReviewRound lineage가 아닌 임의 stage lookup으로 잘못 선택됨
5. Neo4j 핵심 관계를 끊어도 같은 성공 분석
6. Cross-project Candidate/ReviewRound 접근 가능
7. 동일 finding Candidate instance가 여러 Run에서 공유됨
8. 이전 ReviewDecision이 새 Run Candidate로 누출
9. development expensive operations > 10
10. raw findings를 10으로 잘라 실제 FP volume을 숨김
11. Candidate visual이 정확한 Reference가 아닌 unrelated first asset을 선택
12. Case 6에서 filename suffix로 `도판 45` identity를 결정
13. 미검증 Golden case를 expert provenance 없이 `VALID_GROUND_TRUTH`로 승격
14. 실패한 test를 skip/deselect/expected value 수정으로 숨김

## P1 — Software MVP는 PASS 가능하지만 반드시 issue로 남김

- duplicate legacy route code가 runtime에서 unreachable하지만 여전히 존재
- module-level selector monkey-patch
- warning/deprecation
- polling/backoff 개선
- large PDF performance tuning
- UI display polish

## Domain quality 별도 판정

다음 둘을 절대 합치지 않는다.

```text
Software architecture / graph correctness PASS

!=

Archaeology domain ground-truth quality PASS
```

Case 1~5, 7~10은 전문가 재검증 전까지 domain benchmark의 최종 PASS 근거로 사용할 수 없다.

---

# 21. 다음 에이전트에게 전달할 한 문장

> 현재 코드를 다시 설계하지 말고, `review-remediation-20260817`의 실제 production path를 위 V0~V12 순서대로 독립 검증하라. 먼저 실패를 증명하고 그 다음 최소 수정하라. 특히 ReviewRound predecessor, Graph kill-switch, 개발비용 10건, candidate/run isolation, 정확한 visual target, Case 6 filename trap을 증거와 함께 확인하고 `2026-08-17-post-remediation-verification-result.md`를 push하라. 결과가 올라오면 다음 단계는 구현이 아니라 evaluator의 코드/증거 재리뷰다.
