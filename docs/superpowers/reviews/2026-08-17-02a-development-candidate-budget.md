# 2-A) Development Candidate Budget — 개발 기간 비용 제한 및 10건 대표 검수 정책

**Review date:** 2026-08-17  
**Repository:** `Ranponim/archaeology-document-review-system`  
**Branch:** `windows-docker-foundation`  
**Parent review:** `2026-08-17-02-graph-review-logic-review.md`  
**Purpose:** 개발 기간 동안 2,000건 이상의 후보를 모두 AI/VLM/프론트 검수에 투입하지 않고, Neo4j Graph 검증은 유지하면서 비용이 발생하는 검수 대상을 대표 10건으로 제한한다.

---

## 1. 결론

이전 테스트에서 한 번의 실행에 `2,472건` 수준의 CorrectionCandidate가 생성되었다. 현재는 Graph/Object/RuleEngine의 오탐 원인을 수정하는 개발 단계이므로, 이 후보를 전부 LLM/VLM에 전달하거나 전부 전문가 UI 검수 대상으로 materialize하는 것은 비용과 디버깅 효율 모두 좋지 않다.

개발 기간에는 다음 정책을 적용한다.

```text
전체 입력 문서
   ↓
전체 PDF parsing
   ↓
전체 Neo4j canonical graph 구축
   ↓
전체 cheap deterministic rule scan
   ↓
Raw finding / 후보 통계 집계
   ↓
Development Candidate Selector
   ↓
대표 최대 10건 선택
   ↓
CorrectionCandidate materialize
   ↓
LLM / VLM
   ↓
Split-View / 전문가 검수
```

**중요:** 개발 비용을 줄이기 위해 Graph 범위를 10건으로 줄이면 안 된다.

Neo4j에는 본문·도판·도면 전체 구조와 canonical relationship을 계속 구축해야 한다. 그래야 `MENTIONS / REFERENCES / RESOLVES_TO / DEPICTS`가 실제 전체 문서에서 정상인지 검증할 수 있다.

제한 대상은 **비용이 크거나 사람이 직접 확인하는 downstream 단계**다.

---

# 2. 개발 모드 목표

개발 모드의 목적은 정답률 측정이 아니라 다음을 빠르게 확인하는 것이다.

1. 전체 PDF가 정상 parse 되는가.
2. 전체 문서가 Neo4j canonical graph에 정상 저장되는가.
3. Object/Reference/Plate/Drawing relationship이 정상 생성되는가.
4. RuleEngine이 어떤 종류의 후보를 얼마나 만드는가.
5. 대표 후보 10건에서 Evidence provenance가 정확한가.
6. 실제 본문/도판/도면 시각자산이 Split-View에 표시되는가.
7. VLM/LLM 입력이 Graph evidence에 grounding 되는가.
8. 전문가 ReviewDecision 저장이 정상 동작하는가.

따라서 개발 모드에서 `후보 10건`은 전체 검출 수를 숨기는 limit가 아니라 **비용이 발생하는 상세 검수 표본 수**다.

---

# 3. 절대 하면 안 되는 구현

다음 구현은 금지한다.

```python
candidates = candidates[:10]
```

또는:

```cypher
MATCH (c:CorrectionCandidate)
RETURN c
LIMIT 10
```

이 방식은 문서 앞부분의 동일 category만 반복적으로 선택할 수 있으며, 도판/도면/VLM 경로가 하나도 포함되지 않을 수 있다.

또한 전체 후보가 실제로 몇 건 발생했는지 알 수 없어 `2,472건` 같은 후보 폭증 버그를 숨기게 된다.

개발 제한은 **후보 생성 문제를 숨기는 장치가 아니라, 후보 생성 문제를 싸게 조사하기 위한 장치**여야 한다.

---

# 4. 전체 Graph 구축은 반드시 유지

개발 모드에서도 다음 Graph는 전체 입력에 대해 생성한다.

```text
Project
  ↓
ReviewRound
  ↓
DocumentVersion
  ↓
Page
  ├─ TextBlock
  └─ Caption

TextBlock / Caption
  ├─ MENTIONS → ArchaeologyObject
  └─ REFERENCES → Reference
                     ↓ RESOLVES_TO
                  Plate / Drawing
                     ↓ DEPICTS
               ArchaeologyObject
```

즉 다음 수치는 개발 모드에서도 실제 전체 문서 기준으로 확인 가능해야 한다.

```text
pages_parsed
objects_resolved
references_found
references_resolved
plates_indexed
plate_panels_indexed
drawings_indexed
drawing_regions_indexed
mentions_edges
references_edges
resolves_to_edges
depicts_edges
raw_findings_count
```

Graph를 10개 후보 주변으로만 구축하면 FAIL이다.

---

# 5. 비용 제한 지점

## 5.1 Cheap 단계 — 전체 실행

다음은 전체 문서에 실행한다.

- PDF parsing
- Caption / Reference extraction
- ArchaeologyObject extraction
- Neo4j node/relationship persistence
- canonical Reference resolution
- deterministic RuleEngine scan
- raw finding count/category statistics

## 5.2 Expensive 단계 — 최대 10건

다음 단계는 개발 모드에서 선택된 대표 후보만 실행한다.

- 상세 `CorrectionCandidate` materialization
- LLM contextual review
- VLM visual review
- image crop/render를 포함한 고비용 visual processing
- 전문가 Split-View 상세 검수 대상

단, 특정 버그 분석에서 VLM 또는 visual route를 반드시 검증해야 하면 selection policy가 해당 category를 최소 1건 포함하도록 한다.

---

# 6. 권장 설정

환경 변수 또는 Settings로 명확히 분리한다.

```env
REVIEW_MODE=development
DEV_CANDIDATE_LIMIT=10
DEV_CANDIDATE_SELECTION=stratified
DEV_CANDIDATE_SEED=archaeology-mvp-v1
```

Production:

```env
REVIEW_MODE=production
DEV_CANDIDATE_LIMIT=0
```

`0`은 unlimited를 의미한다.

Production에서 개발 limit가 적용되면 FAIL이다.

권장 domain contract:

```python
@dataclass(frozen=True)
class ReviewBudget:
    mode: Literal["development", "production"]
    max_materialized_candidates: int | None
    selection_strategy: Literal["stratified", "all"]
    deterministic_seed: str
```

또는:

```python
DevelopmentReviewBudget(
    max_candidates=10,
    strategy="stratified",
    deterministic=True,
)
```

---

# 7. 대표 10건 선택 전략

단순 random sample보다 **category-aware deterministic sampling**을 사용한다.

초기 권장 quota:

```text
numeric_value                     2
feature_or_artifact_id            2
figure_plate_table_photo_ref      2
direction_period_term             1
annotation_resolution             1
plate / VLM visual path           1
drawing / VLM visual path         1
-----------------------------------
총                               10
```

실제 category가 없는 경우 남은 quota는 다른 category에 deterministic하게 재배분한다.

### 반드시 포함해야 할 특수 샘플

가능하면 10건 안에 다음을 포함한다.

1. `Reference → RESOLVES_TO → Plate`가 있는 후보 1건 이상
2. `Reference → RESOLVES_TO → Drawing`이 있는 후보 1건 이상
3. 실제 visual asset render가 가능한 후보 1건 이상
4. 서로 다른 Evidence 2건 이상을 비교하는 후보 1건 이상
5. `feature_or_artifact_id` 후보 1건 이상
6. numeric/unit 후보 1건 이상

Case 6 regression은 별도 automated gate이므로 10건 표본에 우연히 포함되는 것에 의존하지 않는다.

---

# 8. Deterministic selection 필수

동일 입력과 동일 코드에서 선택된 10건이 매 실행마다 바뀌면 디버깅이 어렵다.

따라서 selection은 deterministic해야 한다.

권장 순서:

```text
1. finding normalization
2. candidate fingerprint 생성
3. category grouping
4. fingerprint 또는 stable hash 정렬
5. category quota 적용
6. remaining quota deterministic fill
```

예:

```python
stable_key = sha256(
    f"{project_id}:{review_round_id}:{rule}:{object_id}:{normalized_claims}".encode()
).hexdigest()
```

단 `analysis_run_id`는 매 실행 바뀌므로 sampling stable key에는 넣지 않는다.

---

# 9. Candidate 생성과 Raw Finding을 분리

개발 기간에는 2,472건을 모두 Neo4j `CorrectionCandidate`로 저장할 필요가 없다.

권장 구조:

```text
RuleEngine
   ↓
RawFinding / FindingSummary
   ├─ total = 2472
   ├─ by_category
   ├─ by_object
   ├─ by_rule
   └─ duplicate/fingerprint stats
         ↓
CandidateSelector
         ↓
10 selected findings
         ↓
CorrectionCandidate
```

즉 `CorrectionCandidate`는 전문가가 실제 검수할 finding instance로 정의한다.

전체 raw finding을 반드시 DB에 저장해야 한다면 별도 lightweight node/table을 사용한다.

```text
RuleFinding
```

또는 AnalysisRun summary property/별도 통계 저장소를 사용한다.

중요한 것은 `전체 탐지 수`와 `실제 AI/전문가 검수 후보 수`를 분리하는 것이다.

---

# 10. AnalysisRun에 반드시 기록할 통계

개발 모드 run은 최소 다음을 저장한다.

```json
{
  "review_mode": "development",
  "raw_findings_count": 2472,
  "materialized_candidates_count": 10,
  "llm_reviewed_count": 10,
  "vlm_reviewed_count": 2,
  "candidate_limit": 10,
  "selection_strategy": "stratified_deterministic"
}
```

또한 category별 전체 수와 선택 수를 함께 저장한다.

```json
{
  "raw_by_category": {
    "feature_or_artifact_id": 1840,
    "numeric_value": 220,
    "figure_plate_table_photo_ref": 50
  },
  "selected_by_category": {
    "feature_or_artifact_id": 2,
    "numeric_value": 2,
    "figure_plate_table_photo_ref": 2
  }
}
```

이 정보가 있어야 후보 폭증이 개선되는지 개발 과정에서 비교할 수 있다.

---

# 11. Frontend 표시

개발 모드에서는 사용자가 10건만 나온 것을 전체 탐지 결과라고 오해하면 안 된다.

현재 후보 목록 상단을 다음처럼 표시한다.

```text
개발 검증 모드

전체 Rule 탐지: 2,472건
상세 검수 표본: 10건
AI/VLM 비용 제한: ON
선택 방식: Category-balanced deterministic sample
```

후보 목록 제목도:

```text
교정 후보 목록 (10건 / 전체 탐지 2,472건)
```

처럼 표현한다.

Production에서는 이 개발 배너를 표시하지 않는다.

---

# 12. LLM / VLM 비용 정책

개발 모드에서 선택된 10건이라고 해서 10건 모두 VLM을 호출할 필요는 없다.

### LLM

텍스트/문맥 판단이 필요한 selected candidate만 호출한다.

### VLM

다음 조건을 모두 만족하는 selected candidate에만 호출한다.

```text
canonical visual target resolved
AND
visual render/crop available
AND
본문 claim과 visual claim 비교가 의미 있음
```

예를 들어 단순 typo 또는 text-only numeric conflict에 VLM을 호출하면 안 된다.

따라서:

```text
selected_candidates = 10
LLM calls <= 10
VLM calls <= visual-relevant selected candidates
```

가 정상이다.

---

# 13. 후보 2,472건 문제 자체는 계속 수정해야 한다

Development Candidate Budget은 2,472건 발생을 정상화하는 기능이 아니다.

`2) 그래프 / 검수 로직 리뷰`에서 지적한 다음 문제는 그대로 P0다.

- `수혈유구` → `수혈`, `유구` substring 중복 parsing
- 하나의 TextBlock에서 다른 ArchaeologyObject claim 혼합
- `Evidence.rationale` 재파싱
- pairwise conflict duplicate 폭증
- project/run/review-round scope 부족
- Candidate fingerprint/dedup 부족

예를 들어 수정 전:

```text
raw_findings_count = 2472
selected = 10
```

수정 후:

```text
raw_findings_count = 85
selected = 10
```

처럼 **raw finding 자체가 합리적인 수준으로 떨어지는 것**도 별도로 관찰해야 한다.

---

# 14. 구현 위치 권장

다음 파일/계층에 역할을 분리한다.

### Domain

신규 권장:

```text
backend/app/domain/review_budget.py
```

### Candidate selector

신규 권장:

```text
backend/app/services/candidate_selector.py
```

책임:

```python
select_for_development(
    findings: list[RawFinding],
    budget: ReviewBudget,
) -> CandidateSelectionResult
```

### Orchestrator

`backend/app/services/proofreading_orchestrator.py`

순서:

```text
Graph build
→ Rule scan
→ raw statistics
→ CandidateSelector
→ materialize selected candidates
→ LLM/VLM selected only
→ persist selected candidates
```

### Run repository

`backend/app/graph/review_repository.py`

AnalysisRun에 budget/selection statistics 저장.

### Frontend

`frontend/src/pages/ProjectDetailPage.tsx`

- development mode banner
- raw finding count
- selected candidate count
- selection strategy 표시

---

# 15. 테스트

## Test DB-01 — 전체 Graph는 limit의 영향을 받지 않는다

동일 문서에 `DEV_CANDIDATE_LIMIT=10`과 unlimited를 각각 실행한다.

PASS:

```text
Page count 동일
TextBlock count 동일
ArchaeologyObject count 동일
Reference count 동일
RESOLVES_TO count 동일
MENTIONS count 동일
DEPICTS count 동일
```

CorrectionCandidate 수만 다를 수 있다.

## Test DB-02 — 2,000개 raw finding이어도 materialized candidate는 10개

```text
raw_findings_count = 2472
materialized_candidates_count = 10
```

이어야 한다.

## Test DB-03 — category stratification

여러 category가 존재하는 fixture에서 첫 10개가 같은 category여도 selected 10건은 quota에 따라 분산되어야 한다.

## Test DB-04 — deterministic

같은 입력으로 두 번 실행한다.

Candidate instance ID는 run별 달라도 되지만 **선택된 finding fingerprint set**은 동일해야 한다.

## Test DB-05 — visual path 포함

Plate/Drawing 후보가 raw findings에 존재하면 10건 샘플에 각각 최소 1건 포함되어 visual-bundle/VLM/Split-View 경로가 개발 중 계속 검증되어야 한다.

## Test DB-06 — production unlimited

```text
REVIEW_MODE=production
```

에서는 DEV limit가 적용되지 않아야 한다.

## Test DB-07 — 비용 호출 수

LLM/VLM mock counter로 확인한다.

```text
LLM call count <= materialized candidate count
VLM call count <= selected visual candidate count
```

전체 2,472 raw finding 수만큼 호출되면 FAIL.

---

# 16. 개발 완료 Gate

Development Candidate Budget 구현은 다음을 모두 만족해야 완료다.

1. 개발 모드 기본 상세 검수 후보 수는 최대 10건이다.
2. 전체 PDF parsing과 Neo4j canonical graph 구축은 제한하지 않는다.
3. 전체 deterministic rule scan count를 유지한다.
4. `raw_findings_count`와 `materialized_candidates_count`를 분리한다.
5. 단순 `candidates[:10]`을 사용하지 않는다.
6. selected 10건은 category-aware deterministic sample이다.
7. 도판/도면 visual path가 가능한 경우 sample에 포함된다.
8. LLM/VLM은 selected candidate만 대상으로 한다.
9. Frontend는 `전체 탐지 N건 / 개발 상세검수 10건`을 명확히 표시한다.
10. Production에는 개발 limit가 적용되지 않는다.
11. 기존 `2) Graph/검수 로직`의 오탐 감소 작업을 중단하거나 숨기지 않는다.

---

## 최종 요약

개발 중에는 **2,472건 전체를 AI/전문가 검수할 이유가 없다.**

그러나 비용 절감을 위해 Graph 자체를 축소하면 이 프로젝트의 핵심 설계를 검증할 수 없다.

따라서 개발 운영 원칙은 다음 한 줄로 고정한다.

> **전체 문서 → 전체 Neo4j Graph → 전체 cheap rule scan → 대표 10건만 Candidate/LLM/VLM/UI 상세 검수.**

이 방식으로 개발 비용을 제한하면서도 Graph identity, 관계 연결, 후보 폭증 원인, 도판/도면 시각 검수 경로를 계속 실제 데이터로 검증한다.
