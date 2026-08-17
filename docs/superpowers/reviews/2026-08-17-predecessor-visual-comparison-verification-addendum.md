# Predecessor + Evidence-Aware Visual Comparison Verification Addendum

> **대상 브랜치:** `review-remediation-20260817`
>
> **이 문서의 기준 코드 HEAD:** `0a4ed22a8d2f591e87277589f531d9fa9aabf1f6`
>
> **상위 handoff:** `docs/superpowers/reviews/2026-08-17-post-remediation-evaluation-handoff.md`
>
> **목적:** 상위 handoff 이후 발견된 두 핵심 문제를 수정한 뒤, 다음 검증 에이전트가 실제 production 경로에서 독립적으로 재시험하도록 하는 추가 검증 계약서다.
>
> **중요:** 이 문서에 적힌 구현 내용은 “코드가 그렇게 작성되었다”는 설명일 뿐이다. 아래 acceptance gate를 실제로 실행하지 않고 PASS로 간주하면 안 된다.

---

# 1. 이번 추가 remediation의 이유

## 1.1 P0: 이전 본문 비교가 `ReviewRound PRECEDES`가 아니라 stage 문자열에 의존할 수 있었음

이전 검증 보고서는 Round #4가 Round #3의 body를 previous source로 사용한다고 PASS 처리했지만, production alignment 경로 일부는 사실상 다음과 같은 compatibility stage lookup을 사용할 수 있었다.

```text
Round #4
  -> "4차"
  -> previous stage "3차"
  -> DocumentVersion.stage == "3차" 탐색
```

실제 frontend는 upload 시 문서 stage를 검수 회차 번호로 사용하지 않고 `source`로 저장한다.

따라서 모든 DocumentVersion이 다음과 같은 실제 UI 상태일 수 있다.

```text
body v1.stage = source
body v2.stage = source
body v3.stage = source
```

이 상태에서 `3차`를 identity source로 사용하면 이전 본문을 잃어버린다.

### 수정 후 목표

```text
Current ReviewRound
    <-[:PRECEDES]- Previous ReviewRound

Previous ReviewRound
    -[:USES_BODY_VERSION]-> Previous body DocumentVersion

Current ReviewRound
    -[:USES_BODY_VERSION]-> Current body DocumentVersion
```

즉 **검수 순서와 비교 기준은 ReviewRound graph lineage가 authority**이며 `DocumentVersion.stage`는 predecessor identity source가 아니다.

---

## 1.2 UI/시각 근거 오류: 모든 Candidate를 도판 비교처럼 표시했음

사용자가 실제로 본 대표 증상:

```text
도면·도판 대조 표준 및 제안
표준 도판 / 사진 — 실제 패널 이미지
해당 에셋 렌더 없음

대상 유물/도판: obj_...
기존 원본: 길이 220cm
교정 제안: 길이 210cm
```

여기에는 두 문제가 섞여 있었다.

1. `길이 220cm -> 210cm` 같은 revision candidate가 실제로는 이전 본문과 현재 본문을 비교한 것인데 UI가 도판 비교처럼 보였다.
2. canonical target이 없는 것과 canonical target은 있지만 render 파일이 없는 것을 같은 “에셋 렌더 없음”으로 표현했다.

이 상태에서는 고고학자가 **무엇과 무엇을 비교해서 교정 후보가 생성되었는지 알 수 없다.**

---

# 2. 이번 코드 변경 내용

## 2.1 ReviewRound predecessor authority

주요 커밋:

```text
10aa118c feat(round): resolve predecessor from review lineage
c1345b3f test(round): reproduce explicit predecessor body alignment
9b3cfb74 fix(round): resolve body alignment from explicit review lineage
590077cb fix(worker): pass review round to body alignment
9b790aed fix(worker): preserve legacy alignment call contract
790b2ad6 test(round): prove predecessor reuse on real neo4j
```

### 의도

ReviewRound-backed AnalysisRun은 body alignment 시:

```text
review_round_id
  -> current ReviewRound
  -> previous ReviewRound through PRECEDES
  -> previous/current USES_BODY_VERSION
  -> exact VersionInput
```

을 사용해야 한다.

Legacy/non-ReviewRound worker call contract는 기존 테스트 호환을 위해 별도 fallback으로 남아 있을 수 있지만, **production ReviewRound run이 fallback stage lookup으로 내려가면 FAIL**이다.

### 추가 Real Neo4j 회귀

코드에는 body reuse를 포함한 실제 Neo4j predecessor regression이 추가되었다.

검증 에이전트는 테스트 이름만 보고 믿지 말고 아래 V13에서 직접 DB row와 실행 결과를 다시 확인한다.

---

## 2.2 Backend visual-bundle을 4개 비교 모드로 명시

주요 커밋:

```text
c6ef2b1b test(visual): reproduce evidence-aware comparison contract
a174c35b feat(visual): include review round context in candidate bundle
70fbf004 feat(visual): expose evidence-aware comparison modes
683cb1a5 feat(api): expose comparison semantics in visual bundle
84349a38 fix(visual): preserve canonical ambiguity reason
```

`GET /api/v1/projects/{project_id}/candidates/{candidate_id}/visual-bundle`은 다음 의미 중 하나를 표현해야 한다.

```text
version_change
plate_reference
drawing_reference
text_evidence
```

### A. `version_change`

사용 예:

```text
이전 본문: 길이 220cm
현재 본문: 길이 210cm
```

응답 의미:

```json
{
  "comparisonType": "version_change",
  "source": { "documentVersionId": "previous_body" },
  "comparison": { "documentVersionId": "current_body" },
  "canonical": null
}
```

**도판/도면을 임의로 붙이지 않는다.**

### B. `plate_reference`

Candidate 자신이 `도판 N` Reference를 가지고 있고 Graph의 `RESOLVES_TO`가 정확한 Plate/Panel을 확정했을 때만 사용한다.

필수 의미:

```text
reference.number
reference.targetId
canonical.documentVersionId
canonical.regionId
```

### C. `drawing_reference`

Candidate 자신이 `도면 N` Reference를 가지고 있고 Graph가 Drawing/Region을 정확히 resolve한 경우다.

### D. `text_evidence`

도판/도면 비교가 본질이 아닌 rule/text candidate다.

```text
canonical = null
comparison = null
renderStatus = not_applicable
```

이것은 “렌더 실패”가 아니다.

---

## 2.3 render identity와 render availability를 분리

새 필드 의미:

```text
renderStatus = ready
  Graph target 있음 + 이미지 전달 가능

renderStatus = missing_render
  Graph target/identity는 있음
  하지만 render 파일/페이지 전달이 불가능

renderStatus = not_applicable
  애초에 visual comparison candidate가 아님
```

### 매우 중요한 판정

아래 두 상태를 섞으면 FAIL이다.

```text
A. 도판 45라는 Graph target 자체를 확정하지 못함
B. 도판 45 target은 확정했지만 image render만 실패함
```

`B`에서는 UI가 최소 다음 provenance를 보여야 한다.

```text
Graph target ID
DocumentVersion ID
physical page (있다면)
renderStatus = missing_render
unresolvedReason / cause
```

그리고 **“도판이 없음”처럼 표현하면 안 된다.**

---

## 2.4 Frontend SplitViewInspector를 비교 의미에 따라 분기

주요 커밋:

```text
f550382a test(frontend): reproduce evidence-aware split view semantics
789036b0 feat(frontend): render evidence-aware comparison modes
dcaf0aea test(frontend): assert comparison semantics without ambiguous text queries
315b64ab test(frontend): align visual fallback with evidence-aware contract
```

### `version_change`

화면:

```text
LEFT  : 이전 본문 PDF page
RIGHT : 현재 본문 PDF page
```

배너:

```text
비교 근거: 본문 수정본 간 비교
```

금지:

```text
표준 도판 / 사진
해당 에셋 렌더 없음
```

### `plate_reference`

화면:

```text
LEFT  : 본문 PDF page
RIGHT : 정확히 resolve된 도판/사진
```

배너 예:

```text
비교 근거: 본문 ↔ 도판 45
```

Graph target ID와 owning DocumentVersion을 함께 보여준다.

### `drawing_reference`

화면:

```text
LEFT  : 본문 PDF page
RIGHT : 정확히 resolve된 도면/도면 영역
```

### `text_evidence`

오른쪽은 빈 도판 placeholder가 아니라 rule/evidence 설명이다.

### VLM 표시 규칙

다음 Evidence가 실제 존재할 때만 VLM 박스를 렌더한다.

```text
Evidence.kind == vlm_observation
```

Candidate rationale나 generic explanation을 VLM 결과처럼 보여주면 FAIL이다.

---

## 2.5 Live validator 강화

커밋:

```text
0a4ed22a test(e2e): stress ReviewRound budget with source-stage fixtures
```

`scripts/run_live_10_api_validation.py`가 다음 방향으로 강화되었다.

1. 모든 문서 upload를 실제 frontend와 동일하게 `stage=source`로 수행.
2. body v1 / body v2를 실제 별도 PDF로 생성.
3. 50건 이상의 deterministic cheap finding을 만들기 위한 multi-page stress fixture 생성.
4. `raw_findings >= 50`을 assert.
5. `selected_candidates <= 10`, `expensive_operations <= 10` assert.
6. 모든 materialized Candidate의 traceability를 조회.
7. 모든 Candidate의 visual-bundle을 4개 비교 모드 계약으로 검증.
8. `version_change`, `plate_reference`, `drawing_reference`가 각각 최소 1개 선택되는 것을 요구.
9. 실제 render URL은 HTTP GET 후 `200`, `image/*`, non-empty bytes를 검사.
10. AI/VLM을 켠 실행에서는 `expensive_operations`가 1..10 범위인지 확인.

**주의:** 이 live script는 현재 GitHub Actions 기본 workflow가 자동 실행하는 acceptance test가 아니다. 반드시 검증 에이전트가 실제 Docker stack에서 별도로 실행해야 한다.

---

# 3. 현재 자동 CI 증거

이번 변경 코드 HEAD `0a4ed22a8d2f591e87277589f531d9fa9aabf1f6`에 대해:

```text
Workflow: Review remediation CI
Run: #84
Conclusion: success
```

세 job 모두 success:

```text
frontend
  typecheck PASS
  unit tests PASS
  build PASS

backend-hermetic
  compile PASS
  hermetic suite PASS

neo4j-e2e
  actual Neo4j containers startup PASS
  Real Neo4j integration/E2E PASS
```

### 이 CI가 아직 증명하지 않은 것

- Docker 전체 stack에서 새 50+ finding live validator가 실제 PASS하는지.
- 실제 브라우저에서 네 비교 모드가 올바른 이미지와 설명으로 보이는지.
- 실제 고고학 PDF에서 plate/drawing reference가 기대한 panel/region을 resolve하는지.
- 외부 AI/VLM provider call이 실제로 10회 이하에서 멈추는지.

따라서 아래 V13~V15는 반드시 별도로 실행한다.

---

# 4. Verification Gate V13 — `stage=source` + true predecessor full-stack

## 목적

**이번 P0 수정의 최종 acceptance다.**

단위 테스트 PASS만으로 끝내지 않는다.

## Fixture

모든 DocumentVersion의 stage를 강제로 동일하게 한다.

```text
stage = source
```

최소 다음 Round를 Real Neo4j에 생성한다.

```text
Round #1 -> body v1, plate p1, drawing d1
Round #2 -> body v2, plate p1, drawing d1
Round #3 -> body v2, plate p1, drawing d1   # body reuse
Round #4 -> body v3, plate p2, drawing d1
Round #5 -> body v4, plate p2, drawing d2
```

## 반드시 실제 worker를 통해 실행

가능하면 API -> RQ -> worker -> Neo4j -> Candidate 경로로 Round #4와 #5 분석을 실행한다.

worker helper를 직접 호출하고 끝내지 않는다.

## Expected

Round #4:

```text
previous body = Round #3 body = v2
current body  = Round #4 body = v3
```

Round #5:

```text
previous body = Round #4 body = v3
current body  = Round #5 body = v4
```

### 금지 조건

아래 중 하나라도 발견되면 P0 FAIL:

```text
"4차" -> "3차" 계산으로 previous DocumentVersion 검색
DocumentVersion.stage를 predecessor identity로 사용
Round #3의 body reuse를 놓치고 v3/v3 또는 v1/v3처럼 잘못 비교
previous body가 없는데 run이 조용히 성공
```

## Neo4j 증거

결과 문서에 실제 Cypher와 row를 첨부한다.

예시 의도:

```cypher
MATCH (current:ReviewRound {id:$round4})
MATCH (previous:ReviewRound)-[:PRECEDES]->(current)
OPTIONAL MATCH (previous)-[:USES_BODY_VERSION]->(prevBody:DocumentVersion)
OPTIONAL MATCH (current)-[:USES_BODY_VERSION]->(currBody:DocumentVersion)
RETURN previous.id, previous.sequence,
       prevBody.id, prevBody.stage,
       current.id, current.sequence,
       currBody.id, currBody.stage
```

관계 방향이 repository 구현과 다르면 실제 schema에 맞게 조정하되, **PRECEDES를 traversing했다는 사실**이 결과에 보여야 한다.

## Candidate/Evidence 증거

Round #4에서 실제 version-change Candidate 하나를 골라:

```text
candidateId
runId
reviewRoundId
previous DocumentVersion ID = v2
current DocumentVersion ID = v3
Evidence IDs
Page IDs
```

를 기록한다.

---

# 5. Verification Gate V14 — Evidence-aware visual comparison + Browser acceptance

이 gate는 사용자가 실제로 겪었던 UI 문제의 acceptance다.

## V14-A API contract

실제 Candidate에서 네 모드를 각각 찾아 visual-bundle JSON 원문을 저장한다.

가능하면 최소 4개 Candidate:

```text
C1 version_change
C2 plate_reference
C3 drawing_reference
C4 text_evidence
```

각 Candidate에 대해 결과 문서에 반드시 기록:

```text
projectId
reviewRoundId
runId
candidateId
ruleCategory
comparisonType
renderStatus
reference
source
comparison
canonical
unresolvedReason
```

---

## V14-B `version_change` browser 검증

대표적으로 다음처럼 숫자 변경 Candidate를 만든다.

```text
이전: 길이 220cm
현재: 길이 210cm
```

Expected UI:

```text
비교 근거: 본문 수정본 간 비교
LEFT  = 이전 본문
RIGHT = 현재 본문
```

두 렌더의 `documentVersionId`가 달라야 한다.

### 반드시 부정 assertion

다음 문구가 이 Candidate 화면에 나오면 FAIL:

```text
표준 도판 / 사진 — 실제 패널 이미지
해당 에셋 렌더 없음
```

단, 이전/현재 PDF page render 자체가 실제 unavailable이면 `render_unavailable` provenance는 표시할 수 있다. 그래도 도판 실패처럼 표현하면 안 된다.

### 제출 증거

- Candidate 전체 화면 screenshot
- 좌/우 pane이 모두 보이는 screenshot
- visual-bundle JSON
- 두 imageUrl에 대한 HTTP status/content-type

---

## V14-C `plate_reference` 검증

실제 `도판 45` Candidate를 사용한다.

Expected Graph/API:

```text
comparisonType = plate_reference
reference.number = 45
reference.targetId = exact resolved Plate/Panel
canonical.documentVersionId = owning plate DocumentVersion
```

UI:

```text
비교 근거: 본문 ↔ 도판 45
```

### Wrong-asset attack

같은 ArchaeologyObject에 Plate45, Plate46을 모두 연결한다.

Candidate는 도판 45를 명시한다.

삽입 순서를 두 가지로 바꿔도 결과는 반드시 Plate45여야 한다.

```text
Plate45 first / Plate46 second
Plate46 first / Plate45 second
```

첫 번째 자산을 임의 선택하면 P0 FAIL이다.

---

## V14-D `drawing_reference` 검증

도판과 동일하게 실제 `도면 30` Candidate를 만든다.

Expected:

```text
comparisonType = drawing_reference
reference.number = 30
reference.targetId = exact Drawing/DrawingRegion
canonical.documentVersionId = owning drawing DocumentVersion
```

실제 imageUrl도 `HTTP 200`, `Content-Type image/*`, non-empty bytes여야 한다.

---

## V14-E `text_evidence` 검증

visual reference가 본질이 아닌 Candidate를 선택한다.

Expected:

```text
comparisonType = text_evidence
canonical = null
comparison = null
renderStatus = not_applicable
```

UI는 rule/evidence 설명을 보여야 한다.

### 금지

```text
빈 도판 pane
"해당 에셋 렌더 없음"
unrelated ArchaeologyObject visual
```

---

## V14-F `missing_render` 진단 검증

Graph가 정확한 Plate 또는 Drawing target을 resolve한 뒤, 테스트용 disposable environment에서 render 파일만 의도적으로 unavailable하게 만든다.

Expected:

```text
comparisonType = plate_reference or drawing_reference
reference.targetId != null
canonical metadata != null
renderStatus = missing_render
```

Browser에는 최소 다음이 보여야 한다.

```text
Graph target ID
DocumentVersion ID
physical page if available
Render status: missing_render
reason code
```

### 절대 금지

```text
"도판/도면 자체가 없음"으로 오인시키는 메시지
canonical identity를 null로 덮어쓰기
다른 image를 fallback으로 선택
```

---

## V14-G 실제 VLM observation 검증

VLM Evidence 없는 Candidate:

```text
VLM 비전 분석 관찰 소견
```

영역이 **없어야 한다.**

실제 다음 Evidence가 연결된 Candidate에서만:

```text
kind = vlm_observation
method = vlm
```

VLM box가 나타나야 한다.

Generic candidate rationale가 같은 문장이라도 VLM evidence가 아니면 VLM box를 만들면 FAIL이다.

---

# 6. Verification Gate V15 — 50+ finding development budget live stress

## 필수 실행 파일

```bash
python scripts/run_live_10_api_validation.py
```

실제 Docker stack에서 실행한다.

기본 환경:

```text
REVIEW_MODE=development
DEVELOPMENT_CANDIDATE_BUDGET=10
VALIDATION_RAW_FINDING_FLOOR=50
ENABLE_LIVE_AI=0
ENABLE_LIVE_VLM=0
```

## 반드시 확인할 출력

```text
raw_findings >= 50
deduped_findings <= raw_findings
selected_candidates <= 10
expensive_operations <= 10
```

그리고 모든 upload가:

```text
stage=source
```

인지 실제 DB/API에서 확인한다.

### 비교 모드 분포

live script는 materialized Candidate 중 최소 다음을 요구한다.

```text
version_change >= 1
plate_reference >= 1
drawing_reference >= 1
```

이 assertion이 실패하면 단순히 테스트를 완화하지 않는다.

먼저 다음을 분리해서 진단한다.

1. raw rule finding 자체가 생성되지 않았나?
2. Reference가 Graph에서 RESOLVES_TO되지 않았나?
3. representative selector가 visual category를 굶겼나?
4. Candidate materialization 전에 type이 손실됐나?

필요하다면 RED regression을 먼저 추가하고 최소 수정한다.

---

## V15-B 실제 AI/VLM cost cap

Provider credential 및 네트워크 사용이 가능한 검증 환경이면 두 번째 run:

```text
ENABLE_LIVE_AI=1
ENABLE_LIVE_VLM=1
```

Expected:

```text
1 <= expensive_operations <= 10
```

가능하면 provider/client mock counter가 아니라 실제 client invocation count도 기록한다.

### credential이 없으면

`PASS`라고 쓰지 않는다.

결과:

```text
EXTERNAL AI/VLM COST CAP = NOT VERIFIED
reason = credentials/provider unavailable
```

으로 기록한다.

---

# 7. Case 6 regression도 다시 확인

이번 visual 변경이 canonical identity 규칙을 약화시키면 안 된다.

다시 확인:

```text
본문: 도판 45
파일명: 4. 조사 후_45.JPG
```

Expected:

```text
filename 숫자 45는 identity 권한 없음
explicit publication identifier 【도판 45】가 authority
```

`plate_reference` mode를 새로 만들면서 filename suffix를 shortcut으로 쓰게 되었다면 즉시 P0 FAIL이다.

---

# 8. 검증 에이전트가 남겨야 할 증거 형식

최종 결과 파일:

```text
docs/superpowers/reviews/2026-08-17-post-remediation-verification-result.md
```

기존 파일이 있다면 이번 결과를 별도 **"Predecessor + Evidence-Aware Visual Revalidation"** 섹션으로 추가하거나, 명확한 superseding 결과를 작성한다.

## 결과 상단 필수

```text
start_sha
end_sha
branch
Docker compose/config hash if relevant
GitHub Actions run number
validator command
validator timestamp/timezone
```

## V13 증거 필수

```text
Round #1..#5 IDs
각 body/plate/drawing version IDs
각 DocumentVersion.stage
PRECEDES Cypher
Cypher raw result
Round #4 run ID
Round #4 previous body ID
Round #4 current body ID
version-change Candidate ID + Evidence IDs
```

## V14 증거 필수

각 비교 모드마다:

```text
candidateId
comparisonType
visual-bundle JSON
source image URL/status
comparison/canonical image URL/status
reference.targetId if applicable
canonical.documentVersionId if applicable
browser screenshot path
```

`missing_render` fixture도 별도 screenshot을 남긴다.

## V15 증거 필수

live validator raw output 전체 또는 artifact path를 제공한다.

최소 숫자:

```text
raw_findings
deduped_findings
selected_candidates
expensive_operations
comparison mode counts
```

AI/VLM enabled run을 했다면 실제 call-count 증거도 첨부한다.

---

# 9. 다음 에이전트의 수정 권한

이 검증 단계의 기본 역할은 **검증**이다.

실패를 발견했을 때만 코드를 수정한다.

순서:

```text
1. 실패 재현
2. RED regression test 작성
3. production code 최소 수정
4. targeted test GREEN
5. backend/frontend/Real Neo4j 전체 CI GREEN
6. live validator 재실행
7. 결과 문서 갱신
```

금지:

```text
테스트 assertion을 지워서 PASS 만들기
raw_findings floor를 낮춰서 PASS 만들기
visual mode requirement를 제거해서 PASS 만들기
missing_render를 canonical=null로 바꿔 숨기기
도판/도면 첫 번째 asset fallback 재도입
DocumentVersion.stage 기반 predecessor lookup 재도입
```

---

# 10. 평가자가 최종 PASS로 인정할 기준

다음 P0가 모두 충족되어야 한다.

```text
[ ] 모든 stage=source 상태에서 ReviewRound predecessor comparison 정확
[ ] Round reuse에서도 previous body 정확
[ ] version_change가 이전본문 ↔ 현재본문으로 표시
[ ] numeric version candidate에 fake plate pane 없음
[ ] plate_reference는 exact RESOLVES_TO target만 표시
[ ] drawing_reference는 exact RESOLVES_TO target만 표시
[ ] text_evidence에는 fake visual 없음
[ ] missing_render는 identity loss와 구분됨
[ ] VLM box는 실제 vlm_observation에서만 표시
[ ] raw_findings >= 50 live stress 실행
[ ] selected_candidates <= 10
[ ] expensive_operations <= 10
[ ] Case 6 filename trap 유지
[ ] CI frontend/backend/Real Neo4j 전체 GREEN
```

외부 provider를 사용할 수 없는 경우:

```text
External AI/VLM semantic/call-count = NOT VERIFIED
```

는 허용할 수 있지만, **검증하지 않은 항목을 PASS로 표시하는 것은 허용하지 않는다.**

---

# 11. 현재 알려진 비차단 P1

`frontend/src/api.ts`의 `CandidateVisualBundle` 정적 타입은 과거 최소 필드 형태가 남아 있고, 현재 `SplitViewInspector`가 backend의 확장 필드를 local evidence-aware intersection으로 읽는다.

현재 TypeScript typecheck/build는 PASS하고 runtime contract도 처리하지만, 다음 cleanup 시 public frontend API type을 backend schema와 완전히 동기화하는 것을 권장한다.

이 항목은 이번 P0 acceptance를 막지는 않지만 검증 결과에 P1로 기록한다.

---

# 12. 최종 판정 형식

검증 에이전트는 마지막에 아래 형식을 사용한다.

```text
V13 ReviewRound predecessor: PASS / FAIL
V14-A API 4-mode contract: PASS / FAIL
V14-B version-change browser: PASS / FAIL
V14-C plate exact-target: PASS / FAIL
V14-D drawing exact-target: PASS / FAIL
V14-E text-evidence semantics: PASS / FAIL
V14-F missing-render diagnostics: PASS / FAIL
V14-G real VLM-only display: PASS / FAIL
V15 50+ finding live stress: PASS / FAIL
V15-B external AI/VLM cost cap: PASS / FAIL / NOT VERIFIED
Case 6 identity regression: PASS / FAIL
Full CI: PASS / FAIL

Overall: PASS / FAIL
P0 remaining: N
P1 remaining: N
```

**P0가 하나라도 FAIL이면 Overall PASS를 선언하지 않는다.**
