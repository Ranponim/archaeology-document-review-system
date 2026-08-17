# 1) 인풋 리뷰 — 문서·사진·도면 입력 및 검수 회차 모델 코드리뷰

**Review date:** 2026-08-17  
**Repository:** `Ranponim/archaeology-document-review-system`  
**Reviewed branch:** `windows-docker-foundation`  
**Reviewed HEAD:** `d126941eb09fff6122fd9d079b2bf93705f52159`  
**Purpose:** 다음 구현 에이전트가 입력 모델과 검수 회차 모델을 수정하기 위한 코드리뷰 결과 문서

---

## 1. 결론

현재 구현은 기술적으로 `본문(report_body)`, `도판(plate_book)`, `도면(drawing_book)` PDF를 각각 업로드할 수 있다. 따라서 프론트엔드가 문자 그대로 본문만 받는 것은 아니다.

하지만 **원래 업무 관점에서는 입력 모델이 잘못 잡혀 있다.**

현재 시스템은 다음처럼 동작한다.

```text
파일 하나 선택
  ↓
종류 선택: 본문 / 도판 / 도면
  ↓
단계 선택: 1차 / 2차 / 3차 / 최종
  ↓
업로드
```

실제 고고학 보고서 검수에서는 한 번의 검수 회차가 보통 다음 자료의 조합이다.

```text
검수 회차 N
  ├─ 본문 초안 PDF
  ├─ 도판/사진 PDF
  └─ 도면 PDF
```

따라서 **입력 단위는 Document 하나가 아니라 ReviewRound 하나여야 한다.**

또한 `1차 / 2차 / 3차 / final`을 시스템 구조에 하드코딩한 현재 모델은 검수가 몇 회에 끝날지 사전에 알 수 없는 실제 업무와 맞지 않는다.

가장 중요한 결론은 다음 두 문장이다.

> **Neo4j는 입력하지 않은 도판/사진/도면을 알아서 생성하거나 찾아주는 시스템이 아니다. 사용자가 검수에 필요한 자료를 명시적으로 등록해야 하고, Neo4j는 등록된 자료 사이의 canonical 관계를 연결하고 검수 근거를 조회하는 역할을 해야 한다.**

> **검수 회차는 1차/2차/3차/final 고정 enum이 아니라 무한히 증가 가능한 ReviewRound sequence로 모델링해야 하며, final은 업로드 단계가 아니라 전문가 승인 결과여야 한다.**

현재 상태는 **Input Model P0 수정 필요**로 판정한다.

---

## 2. 현재 프론트엔드 입력 구조

관련 파일:

- `frontend/src/pages/ProjectDetailPage.tsx`
- `frontend/src/api.ts`

현재 UI에는 실제로 다음 선택지가 존재한다.

```text
문서 종류
- 본문
- 도판
- 도면

교정 단계
- 1차
- 2차
- 3차
- 최종

[원본 PDF 선택]
```

즉 `본문 / 도판 / 도면` 구분 자체는 구현되어 있다.

문제는 UX가 **"하나의 검수 세트"가 아니라 "파일 하나씩 등록"**으로 설계되어 있다는 점이다.

사용자는 같은 검수 회차에 속하는 세 자료의 관계를 직접 기억하고 다음 단계에서 다시 각각 선택해야 한다.

현재 검수 실행 화면도 다음과 같다.

```text
본문 버전       [선택]
도판 버전       [선택]
도면 버전       [선택]

[VLM]
[LLM]
[새 검수 실행]
```

이 구조에서는 사용자가 실수로 서로 다른 회차를 조합할 수 있다.

예:

```text
본문: 3차
도판: 1차
도면: 2차
```

Graph 시스템을 도입했음에도 불구하고 **어떤 버전 조합이 하나의 검수 단위인지 사용자가 다시 수동으로 결정하는 구조**다.

이것은 원래 목표와 맞지 않는다.

---

## 3. Graph가 나머지 입력을 알아서 처리하는가?

### 판정: 아니다.

현재 worker와 input resolver는 Graph-first 방식으로 개선되어 있다.

관련 파일:

- `backend/app/jobs/worker.py`
- `backend/app/jobs/run_inputs.py`
- `backend/app/graph/canonical_repository.py`

선택된 도판 버전이 있으면 시스템은 우선 Neo4j에서 해당 `DocumentVersion`에 속한 `Plate / PlatePanel`을 읽어 `PlateIndex`를 복원한다.

```text
plateVersionId
  ↓
DocumentVersion
  ↓ HAS_PLATE
Plate
  ↓ HAS_PANEL
PlatePanel
  ↓
PlateIndex
```

도면도 동일하다.

```text
drawingVersionId
  ↓
DocumentVersion
  ↓ HAS_DRAWING
Drawing
  ↓ HAS_REGION
DrawingRegion
  ↓
DrawingIndex
```

Graph에 해당 canonical 자산이 없으면 저장된 PDF를 재파싱한다. 명시적으로 도판/도면 버전을 선택했는데 Graph에도 없고 PDF도 해석할 수 없으면 실패하도록 되어 있다.

따라서 역할은 정확히 다음과 같다.

```text
사용자 입력
  ↓
본문 / 도판 / 도면 자료 등록
  ↓
canonical ingest
  ↓
Neo4j
  ↓
Reference / Object / Plate / Drawing 관계 연결
  ↓
검수
```

**Graph는 자료 입력을 대체하지 않는다.**

프론트엔드에서 필요한 자산을 사용자가 등록할 수 있어야 한다.

---

## 4. 현재 시스템에서 "사진"의 의미

현재 canonical model은 다음 Reference만 일급으로 지원한다.

```python
ReferenceType = Literal["plate", "drawing"]
```

프론트 업로드도 PDF만 허용한다.

따라서 현재 MVP에서 사진은 별도 JPG 원본이 아니라 다음 의미다.

```text
plate_book PDF
  ↓
【도판 N】
  ↓
Plate
  ↓
PlatePanel
  ↓
도판 PDF 안에 편집된 실제 사진 영역
```

즉 현재 시스템의 실제 입력 계약은 다음과 같다.

```text
본문 PDF
도판/사진 PDF
도면 PDF
```

이 방향은 기존 고고학자 피드백과도 맞는다.

본문의 `도판 45`는 `4. 조사 후_45.JPG` 같은 Links 파일명이 아니라 출판물의 `【도판 45】`를 canonical identity로 사용해야 하기 때문이다.

따라서 MVP에서는 **도판 PDF를 사진의 canonical source로 보는 것이 맞다.**

다만 향후 원본 사진/JPG 또는 Illustrator/AI까지 검수 범위에 포함하려면 다음 provenance 계층을 별도로 추가해야 한다.

```text
PlatePanel
  ↓ DERIVED_FROM
OriginalPhotoAsset
```

```text
DrawingRegion
  ↓ DERIVED_FROM
OriginalDrawingAsset
```

이 raw asset 입력은 현재 프론트엔드와 backend upload model에 없다.

---

## 5. 최신 E2E 보고서의 입력 검증 한계

관련 파일:

`docs/superpowers/reviews/2026-08-17-e2e-validation-report.md`

최신 E2E 보고서는 실제 산노리 교정본으로 다음만 업로드했다고 명시한다.

```text
본문 1차 PDF
본문 2차 PDF
본문 3차 PDF
```

도판 PDF는 557MB / 578MB 대용량이라는 이유로 실제 E2E에서는 업로드하지 않았다.

그러므로 이 E2E가 실제로 증명한 것은 다음 범위다.

```text
본문 여러 버전
  ↓
Page / TextBlock / Caption
  ↓
Reference 추출
  ↓
ArchaeologyObject
  ↓
버전 정렬 / Rule Candidate
```

하지만 원래 제품 목표의 핵심인 다음 경로는 실제 데이터 E2E로 아직 증명되지 않았다.

```text
본문 "도판45"
  ↓
Reference(plate,45)
  ↓
RESOLVES_TO
  ↓
실제 도판 PDF 【도판45】
  ↓
PlatePanel 실제 사진
  ↓
VLM / Rule / Evidence
```

그리고:

```text
본문 "도면30"
  ↓
Reference(drawing,30)
  ↓
RESOLVES_TO
  ↓
실제 도면 PDF 【도면30】
  ↓
DrawingRegion
  ↓
VLM / Rule / Evidence
```

따라서 현재 E2E 보고서의 "전체 시스템 E2E 성공" 표현은 범위가 넓다.

다음 최종 E2E는 반드시 **깨끗한 Neo4j DB + 신규 프로젝트 + 본문/도판/도면 3종 실제 입력**으로 수행해야 한다.

---

## 6. `1차 / 2차 / 3차 / final` 모델 문제

### 6.1 Frontend 하드코딩

`ProjectDetailPage.tsx`의 단계 선택은 다음으로 고정되어 있다.

```text
1차
2차
3차
최종
```

### 6.2 Backend API는 오히려 N차를 받을 수 있음

`backend/app/api/projects.py`는 업로드 stage에 대해 대략 다음 형태를 허용한다.

```regex
source | final | [1-9][0-9]*차
```

따라서 `4차`, `5차`, `10차` 업로드도 API 수준에서는 가능하다.

### 6.3 Neo4j lineage는 3차까지만 알고 있음

`backend/app/graph/project_repository.py`에는 다음 고정 rank가 있다.

```python
_STAGE_RANK = {
    "1차": 0,
    "2차": 1,
    "3차": 2,
    "final": 3,
}
```

따라서 `4차`가 업로드되어도 정상적인:

```text
3차 -[:PRECEDES]-> 4차
```

관계를 만들 수 없다.

### 6.4 Worker도 3차까지만 탐색

`backend/app/jobs/run_inputs.py`:

```python
BODY_STAGES = ("1차", "2차", "3차", "final")
```

### 6.5 Orchestrator도 동일한 고정 순서

`backend/app/services/proofreading_orchestrator.py` 역시 `1차 / 2차 / 3차 / final` 고정 순서를 가진다.

### 판정

이것은 UI 문제가 아니라 **도메인 모델 오류**다.

검수가 실제로 몇 차에서 종료될지 모르는 업무에서 fixed stage enum은 제거해야 한다.

---

## 7. 권장 도메인 모델: ReviewRound

새로운 중심 단위는 `DocumentVersion.stage`가 아니라 `ReviewRound`여야 한다.

### 권장 Graph

```text
Project
  │
  ├─ HAS_REVIEW_ROUND
  ▼
ReviewRound {sequence: 1, status: reviewing}
  ├─ USES_BODY_VERSION    → DocumentVersion(body v1)
  ├─ USES_PLATE_VERSION   → DocumentVersion(plate v1)
  └─ USES_DRAWING_VERSION → DocumentVersion(drawing v1)

ReviewRound #1
  ↓ PRECEDES
ReviewRound #2
  ↓ PRECEDES
ReviewRound #3
  ↓ PRECEDES
ReviewRound #4
  ...
```

`sequence`는 서버가 자동으로 증가시킨다.

사용자가 `1차`, `2차`, `3차`를 직접 입력할 필요가 없다.

---

## 8. 한 회차에서 자료 재사용 지원

실제 검수에서는 모든 파일이 매번 바뀌지 않을 수 있다.

예:

```text
Round #1
- 본문 v1
- 도판 v1
- 도면 v1

Round #2
- 본문 v2
- 도판 v1  ← 변경 없음 / 재사용
- 도면 v2

Round #3
- 본문 v3
- 도판 v2
- 도면 v2  ← 재사용
```

따라서 ReviewRound는 DocumentVersion을 새로 생성하는 단위가 아니라 **이번 검수에서 사용할 자산 조합을 고정하는 단위**여야 한다.

프론트에는 다음 기능이 필요하다.

```text
도판 / 사진
[새 PDF 업로드]
[✓ 이전 회차 자료 그대로 사용]

도면
[새 PDF 업로드]
[✓ 이전 회차 자료 그대로 사용]
```

이렇게 하면 서로 다른 회차 자산을 잘못 섞는 실수를 크게 줄일 수 있다.

---

## 9. `final`은 업로드 stage가 아니라 승인 상태여야 함

현재 모델은 사용자가 업로드 시점에 `최종`을 선택한다.

이 방식은 잘못된 책임 배치다.

업로드 시점에는 해당 회차가 정말 최종인지 알 수 없다.

권장 모델:

```text
ReviewRound.status =
- draft
- reviewing
- revisions_requested
- approved
- closed
```

전문가가 검수 결과를 모두 확인한 뒤:

```text
[이 회차 최종 승인]
```

을 누르면:

```text
ReviewRound.status = approved
Project.activeRound = null
```

등으로 종료한다.

따라서:

```text
Final = 파일 이름/단계 ❌
Final = 전문가 승인 결과 ✅
```

이어야 한다.

---

## 10. 권장 프론트엔드 입력 UX

현재:

```text
문서 종류 [본문 ▼]
교정 단계 [1차 ▼]
[원본 PDF 선택]
```

권장:

```text
┌─────────────────────────────────────┐
│ 새 검수본 등록                      │
│ 이번 회차: #4 (자동)               │
├─────────────────────────────────────┤
│ 본문 초안                           │
│ [ report_v4.pdf                  ] │
│                                     │
│ 도판 / 사진                         │
│ [ plate_v3.pdf                   ] │
│ [ ] 이전 회차 자료 그대로 사용     │
│                                     │
│ 도면                                │
│ [ drawing_v4.pdf                 ] │
│ [ ] 이전 회차 자료 그대로 사용     │
│                                     │
│ 원본 사진/도면 소스 (선택, 향후)    │
│ [ photos.zip / source assets ]      │
├─────────────────────────────────────┤
│              [검수본 등록]          │
└─────────────────────────────────────┘
```

등록 완료 후:

```text
ReviewRound #4

본문   report_v4.pdf       ✅ Graph Ready
도판   plate_v3.pdf        ✅ Graph Ready
도면   drawing_v4.pdf      ✅ Graph Ready

Reference unresolved       4건
Plate panel insufficient   2건
Drawing region insufficient 1건

[검수 시작]
```

사용자가 검수 실행 단계에서 버전 3개를 다시 선택하게 하지 않는 것이 중요하다.

---

## 11. ReviewRun도 ReviewRound를 참조해야 함

현재 run payload는 다음을 직접 가진다.

```text
body_version_id
plate_version_id
drawing_version_id
version_stage
```

권장:

```text
review_round_id
```

그리고 backend가 Graph에서:

```text
ReviewRound
  ├─ USES_BODY_VERSION
  ├─ USES_PLATE_VERSION
  └─ USES_DRAWING_VERSION
```

을 조회해 실제 입력을 결정해야 한다.

즉:

```text
Frontend
  ↓ reviewRoundId 하나 전송
Backend
  ↓ Neo4j
ReviewRound
  ↓
정확한 DocumentVersion 3종 resolve
  ↓
ProofreadingRun
```

이 구조가 Graph를 제대로 활용하는 방식이다.

---

## 12. Plate / Drawing version validation 문제

현재 proofreading run 생성에서 본문 버전은 `project + kind + stage + version_id`로 강하게 확인한다.

반면 plate/drawing은 일부 경로에서 `get_document_version_by_id()`만 호출한다.

따라서 backend 경계에서는 최소 다음을 보장해야 한다.

```python
resolve_version_input(
    project_id=project_id,
    kind="plate_book",
    version_id=plate_version_id,
)
```

```python
resolve_version_input(
    project_id=project_id,
    kind="drawing_book",
    version_id=drawing_version_id,
)
```

잘못된 프로젝트의 Version이나 잘못된 kind의 Version을 run에 연결해서는 안 된다.

ReviewRound 모델을 도입하면 이 문제도 자연스럽게 줄어든다.

---

## 13. Neo4j 권장 관계

최소 추가:

```text
(:Project)-[:HAS_REVIEW_ROUND]->(:ReviewRound)
(:ReviewRound)-[:USES_BODY_VERSION]->(:DocumentVersion)
(:ReviewRound)-[:USES_PLATE_VERSION]->(:DocumentVersion)
(:ReviewRound)-[:USES_DRAWING_VERSION]->(:DocumentVersion)
(:ReviewRound)-[:PRECEDES]->(:ReviewRound)
(:AnalysisRun)-[:REVIEWS]->(:ReviewRound)
```

선택 확장:

```text
(:PlatePanel)-[:DERIVED_FROM]->(:OriginalAsset)
(:DrawingRegion)-[:DERIVED_FROM]->(:OriginalAsset)
```

`DocumentVersion PRECEDES DocumentVersion` 관계는 필요한 경우 각 kind 내부 history로 유지할 수 있지만 **검수 업무의 회차 순서는 ReviewRound PRECEDES가 authority**가 되어야 한다.

---

## 14. P0 구현 항목

### P0-INPUT-1 — ReviewRound 도메인 도입

- `ReviewRound` node 생성
- unlimited integer `sequence`
- status 기반 종료
- Project별 다음 sequence 서버 자동 결정

### P0-INPUT-2 — fixed stage 제거

제거 대상:

```text
frontend: 1차/2차/3차/final select
ProjectRepository._STAGE_RANK
run_inputs.BODY_STAGES
ProofreadingOrchestrator.STAGE_ORDER
```

기존 데이터 호환이 필요하면 migration adapter만 두고 신규 workflow에는 사용하지 않는다.

### P0-INPUT-3 — ReviewRound input bundle UI

한 화면에서:

- 본문 PDF
- 도판 PDF
- 도면 PDF
- 이전 자산 재사용

을 등록한다.

### P0-INPUT-4 — run은 review_round_id 기준 실행

프론트가 임의의 body/plate/drawing 조합을 다시 만드는 구조를 제거한다.

### P0-INPUT-5 — 실제 3종 E2E

깨끗한 Neo4j DB에서 최소:

```text
Round #1
본문 PDF
도판 PDF
도면 PDF
```

를 실제 업로드하고 다음을 검증한다.

```text
TextBlock
  ↓ REFERENCES
Reference
  ↓ RESOLVES_TO
Plate/Drawing
  ↓ DEPICTS
ArchaeologyObject
```

그리고 실제 Split View에서:

```text
본문 페이지 + bbox
vs
도판 사진 panel 또는 도면 region
```

이 표시되어야 한다.

---

## 15. MVP Acceptance Criteria — Input Review

아래 모두 만족해야 Input Model 수정 완료로 판정한다.

- [ ] 사용자가 `1차 / 2차 / 3차 / final`을 직접 선택하지 않는다.
- [ ] ReviewRound sequence가 프로젝트별로 자동 증가한다.
- [ ] 4차, 5차, 10차 이상의 검수 반복도 코드 변경 없이 가능하다.
- [ ] 한 ReviewRound가 사용할 본문/도판/도면 DocumentVersion을 Graph에서 명확히 가진다.
- [ ] 새 회차에서 변경되지 않은 도판/도면은 이전 DocumentVersion 재사용이 가능하다.
- [ ] proofreading run은 `review_round_id`에서 실제 세 입력을 Graph로 resolve한다.
- [ ] frontend가 검수 실행 전에 세 자료의 Graph readiness를 표시한다.
- [ ] selected plate/drawing version이 같은 프로젝트 및 올바른 document kind인지 backend가 검증한다.
- [ ] Neo4j가 없는 입력 자료를 "알아서 처리"하는 것처럼 보이는 UX가 없다.
- [ ] 최종 승인 여부는 upload stage가 아니라 전문가/프로젝트 workflow 상태로 관리된다.
- [ ] 실제 E2E에 본문 PDF, 도판 PDF, 도면 PDF 세 종류가 모두 포함된다.
- [ ] 최종 E2E는 깨끗한 Neo4j DB 또는 project-scoped count로 검증한다.

---

## 16. 반드시 피해야 하는 구현

다음 구현은 리뷰 거부 대상이다.

1. `BODY_STAGES = ("1차", "2차", "3차", "final")` 형태 유지
2. `STAGE_ORDER`에 4차, 5차를 계속 수동 추가
3. 사용자가 매 run마다 body/plate/drawing version을 임의 조합
4. 도판/도면 미입력 상태를 Graph가 알아서 해결한다고 간주
5. 본문 PDF만으로 전체 문서·사진·도면 E2E 성공 선언
6. global Neo4j node count를 특정 프로젝트 E2E 결과로 사용
7. `final`을 업로드 옵션으로 계속 노출
8. ReviewRound 없이 DocumentVersion stage만으로 업무 회차를 표현
9. 원본 JPG 파일명 숫자를 도판 identity로 재사용
10. ReviewRound에 연결된 asset이 있는데도 frontend에서 별도 수동 선택을 요구

---

## 17. 최종 권장 구조

```text
Project
  │
  ├─ ReviewRound #1
  │    ├─ BodyVersion v1
  │    ├─ PlateVersion p1
  │    └─ DrawingVersion d1
  │
  ├─ ReviewRound #2
  │    ├─ BodyVersion v2
  │    ├─ PlateVersion p1  (reuse)
  │    └─ DrawingVersion d2
  │
  ├─ ReviewRound #3
  │    ├─ BodyVersion v3
  │    ├─ PlateVersion p2
  │    └─ DrawingVersion d2 (reuse)
  │
  └─ ... unlimited
```

각 회차는:

```text
Input Bundle
  ↓
Canonical Ingest
  ↓
Neo4j Graph Ready
  ↓
Graph-backed ProofreadingRun
  ↓
Text ↔ Plate/Photo ↔ Drawing comparison
  ↓
CorrectionCandidate
  ↓
Expert ReviewDecision
```

으로 동작한다.

검수자가 어느 시점에서 충분하다고 판단하면 해당 ReviewRound를 `approved`로 종료한다.

---

# 최종 판정

현재 구현은 **본문/도판/도면 PDF 각각의 업로드 기능과 Graph ingest 기능은 존재한다.** 따라서 단순히 "본문만 받는다"고 평가하면 정확하지 않다.

그러나 사용자 경험과 도메인 모델은 여전히 **파일 중심 + 고정 1/2/3차 중심**이다.

원래 시스템의 목적을 제대로 표현하려면 다음으로 전환해야 한다.

```text
현재
DocumentVersion + stage

↓

목표
ReviewRound + Input Bundle + Graph relationships
```

이 변경은 부가 UX 개선이 아니라 **P0 도메인 모델 수정**이다.

다음 구현 에이전트는 이 Input Review를 우선 적용한 뒤 Graph/검수 로직과 프론트 시각 검수 기능을 이어서 검증해야 한다.
