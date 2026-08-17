# 3) 시각자산 / 프론트엔드 리뷰 — `시각 자산을 불러오지 못했습니다` 원인 분석 및 검수 UX 코드리뷰

**Review date:** 2026-08-17  
**Repository:** `Ranponim/archaeology-document-review-system`  
**Reviewed branch:** `windows-docker-foundation`  
**Reviewed HEAD:** `7383a1ffc5afb994729f38cd2ecd9ac8ab91a693`  
**Observed symptom:** Expert Proofreading Workspace의 Split-View에서 `시각 자산(본문 페이지/도판/도면)을 불러오지 못했습니다.`가 반복 표시됨  
**Purpose:** 다음 구현 에이전트가 실제 본문 PDF·도판 사진·도면을 안정적으로 조회하고 후보 종류에 맞게 비교 표시하도록 수정하기 위한 코드리뷰 결과 문서

---

## 1. 결론

현재 프론트엔드에는 실제 시각자산 표시용 컴포넌트와 backend render API가 구현되어 있다.

즉 단순히 "프론트에 이미지 뷰어가 없다"는 문제는 아니다.

현재 의도된 흐름은 다음과 같다.

```text
ProjectDetailPage
  ↓ candidate 선택
GET /api/v1/projects/{project}/candidates/{candidate}/visual-bundle
  ↓
VisualAssetService
  ↓
AssetRepository
  ↓ Neo4j
Candidate → Evidence → Page → DocumentVersion
Candidate → Object ← DEPICTS ← Plate/Panel/Drawing/Region
  ↓
VisualAssetMetadata(imageUrl, bbox, page, sha256)
  ↓
VisualAssetPane
  ↓
<img src=/api/v1/assets/.../render>
```

구조 자체는 맞다.

하지만 현재 코드는 이 흐름의 여러 경계에서 실패를 구분하지 못하고 있으며, 특히 `AssetRepository.get_candidate_visual_bundle()`의 Cypher와 후보별 시각자산 선택 방식에 P0 문제가 있다.

또한 첨부 화면의 후보들은 대부분 `feature_or_artifact_id` 규칙 후보인데, 이런 후보는 **도판/도면과 직접 연결된 시각 후보가 아닐 수도 있다.** 현재 UI는 후보 종류와 무관하게 항상 오른쪽을 `CANONICAL TARGET / VLM 비전 분석`으로 그려서, 실제로 VLM이 수행되지 않은 규칙 후보도 마치 도판·도면으로 검증된 것처럼 보일 수 있다.

### 핵심 판정

- 본문/도판/도면 render API 존재: **PASS**
- React visual component 존재: **PASS**
- 실제 candidate visual-bundle E2E 검증: **FAIL / 증거 없음**
- visual-bundle Neo4j query 안정성: **P0 수정 필요**
- source/canonical partial failure 처리: **FAIL**
- candidate 종류에 맞는 비교 화면: **FAIL**
- 실제 VLM 결과와 일반 Rule 결과 UI 구분: **FAIL**
- BBox provenance 유지: **부분 FAIL**
- 사용자에게 실패 원인 표시: **FAIL**

따라서 단순히 이미지 URL을 고치는 것이 아니라 **Candidate → 관련 Evidence → 실제 비교 자산** 계약을 다시 명확하게 만들어야 한다.

---

# 2. 현재 화면에서 확인되는 현상

첨부 화면에서는 선택 후보가:

```text
feature_or_artifact_id
원본: 토광묘
제안: 수혈
confidence: 95%
```

형태이며 왼쪽 Source Claim 영역에:

```text
시각 자산(본문 페이지/도판/도면)을 불러오지 못했습니다.
```

가 표시된다.

동시에:

```text
문서 버전
물리 124쪽
SHA-256
```

등 traceability metadata는 표시된다.

이것은 **Candidate/Traceability API 자체는 응답하지만 별도의 visual-bundle 요청이 실패하고 있음을 의미하는 UI 패턴**이다.

`SplitViewInspector.tsx`는 visual-bundle 요청이 reject될 경우 상세 code를 사용하지 않고 바로 고정 문자열을 표시한다.

---

# 3. 요청 흐름 역추적

## Frontend

파일:

- `frontend/src/pages/ProjectDetailPage.tsx`
- `frontend/src/components/SplitViewInspector.tsx`
- `frontend/src/components/VisualAssetPane.tsx`
- `frontend/src/api.ts`

흐름:

```text
candidate 선택
  ↓
fetchTraceability()       → 정상 metadata 표시 가능
fetchVisualBundle()       → 실패 시 visualError
  ↓
GET /visual-bundle
```

## Backend

파일:

- `backend/app/api/reviews.py`
- `backend/app/graph/asset_repository.py`
- `backend/app/services/visual_asset_service.py`
- `backend/app/api/assets.py`

흐름:

```text
GET candidate visual-bundle
  ↓
AssetRepository.get_candidate_visual_bundle(candidate_id)
  ↓
Neo4j candidate/evidence/object/visual traversal
  ↓
VisualAssetService.get_candidate_visual_bundle()
  ↓
source page render + canonical asset render metadata
```

따라서 현재 오류는 `<img>` 태그 이전 단계에서도 발생할 수 있다.

---

# 4. P0 — `get_candidate_visual_bundle()` Cypher의 nested aggregation을 우선 의심해야 한다

파일:

- `backend/app/graph/asset_repository.py`

현재 query에는 개념적으로 다음 구조가 있다.

```cypher
collect(DISTINCT {
    label: head(labels(asset)),
    props: properties(asset),
    parent: properties(parent),
    children: [c IN collect(DISTINCT child) WHERE c IS NOT NULL | properties(c)]
}) AS canonical_assets
```

즉 바깥 `collect(...)`의 expression 내부에서 다시 `collect(...)`를 사용한다.

Cypher aggregation은 grouping 단계가 명확해야 하며 이런 형태의 nested aggregate는 실제 Neo4j에서 오류가 발생할 가능성이 매우 높다. 현재 증상처럼 **candidate마다 visual-bundle API 전체가 계속 실패하는 현상**과도 일치한다.

이 부분은 코드만 보고 임의 수정하지 말고 가장 먼저 실제 Neo4j에서 해당 query를 직접 실행해 오류 메시지를 확보해야 한다.

### 권장 query 구조

Aggregation 단계를 `WITH`로 분리한다.

```cypher
MATCH (cand:CorrectionCandidate {id:$candidate_id})
OPTIONAL MATCH (cand)-[:SUPPORTED_BY]->(ev:Evidence)
OPTIONAL MATCH (ev)-[:EXTRACTED_FROM]->(page:Page)
OPTIONAL MATCH (ev)-[:FROM_VERSION]->(version:DocumentVersion)
OPTIONAL MATCH (cand)-[:ABOUT]->(obj:ArchaeologyObject)
WITH cand, obj,
     collect(DISTINCT {
       evidence: properties(ev),
       page: properties(page),
       version: properties(version)
     }) AS evidence_chain

OPTIONAL MATCH (asset)-[:DEPICTS]->(obj)
OPTIONAL MATCH (parent)-[:HAS_PANEL|HAS_REGION]->(asset)
OPTIONAL MATCH (asset)-[:HAS_PANEL|HAS_REGION]->(child)
WITH cand, evidence_chain, asset, parent,
     collect(DISTINCT child) AS children
WITH cand, evidence_chain,
     collect(DISTINCT {
       label: head(labels(asset)),
       props: properties(asset),
       parent: properties(parent),
       children: [c IN children WHERE c IS NOT NULL | properties(c)]
     }) AS canonical_assets
RETURN properties(cand) AS candidate,
       evidence_chain,
       canonical_assets
```

또는 Neo4j version에 맞는 `COLLECT { ... }` subquery를 사용한다.

### Acceptance Gate

실제 Neo4j 컨테이너에서 최소 3종 candidate에 대해 직접 호출한다.

```text
text-only rule candidate
plate-reference candidate
drawing-reference candidate
```

모두 query syntax/server error 없이 반환되어야 한다.

---

# 5. P0 — 현재 E2E는 visual-bundle을 실제로 검증하지 않았다

현재 repository의 E2E validation report는 실제 산노리 본문 PDF 1·2·3차를 넣어 Graph 관계와 후보 생성을 검증했다.

하지만 보고서 자체에 대용량 도판 PDF는 이번 E2E에서 업로드하지 않았다고 적혀 있다.

따라서 다음은 아직 실제 사용자 흐름으로 증명되지 않았다.

```text
본문 Reference
  → RESOLVES_TO
실제 Plate / PlatePanel
  → 실제 image render
  → browser 표시
```

및:

```text
본문 Reference
  → Drawing / DrawingRegion
  → 실제 image render
  → browser 표시
```

Graph node count가 존재하는 것과 browser에서 시각 자산이 열리는 것은 다른 테스트다.

### 필수 신규 E2E

깨끗한 Neo4j DB에서:

```text
본문 PDF
도판 PDF
도면 PDF
```

를 실제 등록한 뒤 known candidate 하나를 선택한다.

다음 API를 모두 확인한다.

```http
GET /candidate/{id}/visual-bundle        → 200
GET /assets/pages/{id}/render            → 200 + non-empty PNG
GET /assets/plate-panels/{id}/render     → 200 + image bytes
GET /assets/drawing-regions/{id}/render  → 200 + image bytes
```

그리고 browser에서 실제 이미지가 보이는 것까지 검증해야 한다.

---

# 6. P0 — body-only 후보에 canonical visual이 없는 것은 정상일 수 있다

첨부 화면의 후보는 `feature_or_artifact_id`이다.

이 후보가 단순히 여러 본문 revision의 object type claim 충돌에서 생성됐다면 반드시 Plate/Photo/Drawing을 가져야 하는 후보가 아니다.

즉:

```text
본문 A 주장
vs
본문 B 주장
```

만으로 생성된 후보일 수 있다.

이 경우 올바른 UI는:

```text
왼쪽: 본문 Evidence A
오른쪽: 본문 Evidence B
시각자산: 해당 없음
```

이다.

현재 UI처럼 모든 후보에:

```text
CANONICAL TARGET
도면·도판 대조 표준
VLM 비전 분석 관찰 소견
```

을 고정 표시하면 안 된다.

### Candidate review mode가 필요하다

예:

```text
text_vs_text
text_vs_plate
text_vs_drawing
text_vs_vlm
multi_evidence
```

backend가 candidate의 실제 Evidence graph를 보고 mode를 반환하는 것이 가장 안전하다.

---

# 7. P0 — UI가 실제 VLM 결과가 없어도 `VLM 비전 분석`으로 표시한다

파일:

- `frontend/src/components/SplitViewInspector.tsx`

현재 VLM box는 후보 종류와 관계없이 항상 렌더된다.

표시값도:

```tsx
archObj?.vlm_verdict ||
primaryEvidence?.rationale ||
'도판 내 유물 번호와 본문 서술 간의 번호 상이점 교차 검증됨.'
```

이다.

즉 실제 `vlm_observation` Evidence가 없어도 일반 `graph_traversal` rationale을 VLM 결과처럼 보여주거나, 마지막에는 임의의 VLM-like 문장을 표시한다.

첨부 화면에서도 Evidence 방식은 `graph_traversal`인데 오른쪽에는 `VLM 비전 분석 관찰 소견`, `AI 예측도 100%`가 나타난다.

이것은 전문가 검수 UI에서 매우 위험하다.

### 수정

실제 graph에:

```text
Evidence.kind == vlm_observation
```

이 존재할 때만 VLM box를 표시한다.

없으면:

```text
VLM 검증 없음
```

또는 section 자체를 숨긴다.

절대로 fallback 문장을 만들어 VLM 결과처럼 보여주지 않는다.

---

# 8. P0 — Visual bundle이 candidate-specific target이 아니라 Object의 첫 visual asset을 고른다

`AssetRepository.get_candidate_visual_bundle()`은:

```text
Candidate → ABOUT → ArchaeologyObject
asset → DEPICTS → ArchaeologyObject
```

를 따라 object를 묘사하는 visual asset들을 모은다.

그 후 `VisualAssetService.get_candidate_visual_bundle()`은 collection의 첫 entry를 canonical asset으로 사용한다.

문제는 하나의 ArchaeologyObject에:

```text
Plate 45
Plate 46
Drawing 30
Drawing 31
```

처럼 여러 asset이 연결될 수 있다는 것이다.

candidate가 `도판45` reference 문제인데 collection의 첫 asset이 Drawing30이면 **정상적으로 이미지를 불러와도 잘못된 그림을 보여주는 더 위험한 버그**가 된다.

### 수정 원칙

visual target은 Object 전체에서 고르면 안 된다.

Candidate가 어떤 Evidence/Reference 때문에 만들어졌는지를 따라가야 한다.

권장 canonical path:

```text
CorrectionCandidate
  → SUPPORTED_BY → Evidence
  → source Reference ID
  → RESOLVES_TO → exact Plate/Drawing
```

또는 Candidate 생성 시:

```text
(cand)-[:COMPARES_TO]->(PlatePanel/DrawingRegion/Page)
```

같은 명시적 relation을 저장한다.

Frontend는 이 exact relation만 렌더해야 한다.

---

# 9. P0 — Evidence가 여러 개인데 source page도 첫 번째를 임의로 고른다

Candidate 하나는 여러 Evidence를 가질 수 있다.

예:

```text
Evidence A: 본문 revision N p124
Evidence B: 본문 revision N+1 p126
```

하지만 `get_candidate_visual_bundle()`은 evidence chain에서 처음 렌더 가능한 entry 하나를 `source`로 설정한다.

collection order가 의미적으로 `원본`이라는 보장은 없다.

그래서 feature mismatch 같은 버전 비교 후보에 필요한 것은 사실:

```text
Source A page
Comparison B page
```

두 장이다.

현재 `CandidateVisualBundle`의:

```text
source
canonical
```

2-field 계약 자체가 모든 candidate category를 표현하지 못한다.

### 권장 새 contract

```json
{
  "candidateId": "...",
  "reviewMode": "text_vs_text",
  "views": [
    {
      "role": "source",
      "evidenceId": "...",
      "asset": { ... }
    },
    {
      "role": "comparison",
      "evidenceId": "...",
      "asset": { ... }
    }
  ],
  "vlmObservation": null
}
```

도판 후보라면:

```text
source body page
canonical plate panel
```

도면 후보라면:

```text
source body page
canonical drawing region
```

으로 반환한다.

---

# 10. P0 — 한쪽 render 실패가 visual-bundle 전체 실패가 된다

`VisualAssetService.get_candidate_visual_bundle()`에서 source page를 구성할 때:

```text
version.uri 없음
파일 없음
PyMuPDF render 실패
```

중 하나가 발생하면 `VisualAssetIncompleteError`가 throw될 수 있다.

현재 API는 이를 `404 evidence_incomplete`로 반환한다.

그러면 canonical asset이 정상이어도 frontend는 bundle 전체를 받지 못한다.

### 수정

시각 Evidence는 partial result를 허용해야 한다.

예:

```json
{
  "candidateId": "...",
  "reviewMode": "text_vs_plate",
  "views": [
    {
      "role": "source",
      "status": "render_failed",
      "errorCode": "source_pdf_missing",
      "metadata": { ... }
    },
    {
      "role": "canonical",
      "status": "ready",
      "asset": { ... }
    }
  ]
}
```

후보 자체가 존재하는데 한 이미지가 없다는 이유로 endpoint 전체를 CandidateNotFound처럼 처리하면 안 된다.

---

# 11. P0 — Frontend가 backend의 `evidence_incomplete`를 잃어버린다

파일:

- `frontend/src/api.ts`

현재 `decode()`는 명시적으로:

```text
input_error
server_error
```

만 code로 보존한다.

backend가:

```json
{"code":"evidence_incomplete"}
```

를 반환해도 `detail`이 없으면 최종적으로 `server_error`가 될 수 있다.

그리고 `SplitViewInspector`는 error code를 사용하지 않고:

```text
시각 자산(본문 페이지/도판/도면)을 불러오지 못했습니다.
```

라는 하나의 문구만 보여준다.

### 수정

`ApiError`가 모든 backend error code + HTTP status + request_id를 보존하도록 한다.

예:

```typescript
class ApiError extends Error {
  code: string;
  status: number;
  requestId?: string;
}
```

UI는 다음을 구분한다.

```text
evidence_incomplete  → "이 후보에는 렌더 가능한 시각 근거가 없습니다."
asset_not_found      → "Graph 자산 노드를 찾지 못했습니다."
render_failed        → "원본 PDF 렌더에 실패했습니다."
server_error         → "서버 오류 — Request ID ..."
not_applicable       → 오류가 아니라 정상 상태
```

---

# 12. P1 — visual-bundle을 Parent와 Child가 중복 요청한다

`ProjectDetailPage`는 selected candidate 변경 시 `fetchVisualBundle()`을 호출해 cache한다.

동시에 `SplitViewInspector`도 prop이 아직 도착하지 않았으면 자체적으로 `fetchVisualBundle()`을 호출한다.

따라서 candidate 선택 시 동일 endpoint가 2회 호출될 수 있다.

실패 시:

- Parent는 error를 조용히 무시
- Child는 generic error 표시

가 된다.

### 수정

데이터 소유자를 하나로 통일한다.

추천:

```text
ProjectDetailPage / React Query
  ↓
visualBundle + loading + error
  ↓ props
SplitViewInspector = pure renderer
```

또는 TanStack Query/SWR 같은 cache layer를 쓴다.

MVP에서는 별도 library 추가 없이 parent 한 곳에서만 fetch해도 충분하다.

---

# 13. P1 — `<img>` 실제 render 실패를 감지하지 않는다

`VisualAssetPane.tsx`의 `<img>`는 `onError` handler가 없다.

따라서 visual-bundle metadata API가 200이어도:

```text
GET imageUrl → 404/500
```

이면 browser의 broken image 상태만 남고 frontend는 원인을 알 수 없다.

### 수정

`VisualAssetPane` 자체에:

```text
loading
loaded
error
retry
```

state를 둔다.

`onError`에서 해당 asset id/imageUrl을 표시하고 재시도 버튼을 제공한다.

---

# 14. P1 — TextBlock/Caption BBox가 Neo4j 저장 과정에서 소실된다

파일:

- `backend/app/graph/review_repository.py`

`_page_to_param()`에서 block에 저장하는 값은 주로:

```text
id
text
normalized_text
order
block_type
```

이며 Caption도 bbox/source provenance가 충분히 전달되지 않는다.

`save_pages_and_blocks()`도 TextBlock/Caption의 bbox를 저장하지 않는다.

반면 `CanonicalRepository._query_text_claims()`는:

```python
bbox = source.get("bbox")
```

를 읽는다.

따라서 Graph traversal로 다시 만든 Evidence는 bbox가 `None`이 되기 쉽다.

첨부 화면의:

```text
BBOX 좌표: 전체 영역
```

표시와도 일치한다.

### 수정

TextBlock/Caption persistence에 최소:

```text
bbox
source_sha256
physical_page
```

를 저장한다.

그리고 source visual page에서 해당 bbox가 실제 원문 문장을 정확히 highlight하는 integration test를 작성한다.

---

# 15. P1 — `canonicalAsset == null`은 항상 오류가 아니다

Frontend는 후보 종류를 먼저 판단해야 한다.

예:

| Candidate | 기대 시각 비교 |
|---|---|
| typo | 본문 page만 또는 text context |
| version text change | 이전 본문 vs 현재 본문 |
| feature/type conflict | 관련 Evidence 2개 이상 |
| plate reference | 본문 vs Plate/Panel |
| drawing reference | 본문 vs Drawing/Region |
| VLM contradiction | 본문 + exact visual target + VLM observation |

따라서 `canonical == null`을 무조건 "불러오기 실패"로 해석하면 안 된다.

Backend가 `review_mode`와 `visual_status`를 명시적으로 반환해야 한다.

---

# 16. 권장 Frontend 구조

현재 Split-View를 후보 종류에 따라 adaptive하게 만든다.

## text_vs_text

```text
┌──────────────────────┬──────────────────────┐
│ 이전/근거 본문 PDF   │ 비교 본문 PDF        │
│ 해당 bbox highlight  │ 해당 bbox highlight  │
└──────────────────────┴──────────────────────┘
```

## text_vs_plate

```text
┌──────────────────────┬──────────────────────┐
│ 본문 PDF             │ 실제 도판/사진 panel │
│ 참조 문장 highlight  │ panel highlight      │
└──────────────────────┴──────────────────────┘
```

## text_vs_drawing

```text
┌──────────────────────┬──────────────────────┐
│ 본문 PDF             │ 실제 도면            │
│ 문장 highlight       │ drawing region       │
└──────────────────────┴──────────────────────┘
```

## VLM candidate

위 visual comparison 아래에 실제 `vlm_observation` Evidence만 별도로 표시한다.

```text
Verdict: SUPPORTED / PARTIAL / CONTRADICTED / INSUFFICIENT_EVIDENCE
Observed claims
Contradicted claims
Unobservable claims
```

---

# 17. P0 구현 순서

## P0-V1 — visual-bundle Neo4j query 실제 재현

1. screenshot의 candidate id로 visual-bundle endpoint 호출
2. backend log / request-id 확보
3. `AssetRepository.get_candidate_visual_bundle()` Cypher를 cypher-shell에서 직접 실행
4. nested aggregation 오류 여부 확인
5. query를 staged aggregation으로 수정

## P0-V2 — Candidate Review Bundle 계약 수정

기존:

```text
source + canonical
```

에서 후보별 role 기반:

```text
review_mode
views[]
vlm_observation
```

으로 변경한다.

## P0-V3 — candidate-specific target 연결

Object의 첫 visual asset이 아니라 candidate가 실제 참조한 exact Reference/target을 반환한다.

## P0-V4 — partial failure / not-applicable 처리

한 자산 실패가 전체 endpoint 404가 되지 않게 한다.

## P0-V5 — Frontend truthful rendering

실제 VLM Evidence가 없으면 VLM section을 표시하지 않는다.

## P1-V6 — bbox persistence

TextBlock/Caption bbox를 Neo4j에 저장하고 실제 highlight까지 검증한다.

## P1-V7 — fetch/error UX 정리

중복 fetch 제거, 상세 error code, image onError/retry 구현.

---

# 18. 반드시 추가할 테스트

### Test V-01 — visual-bundle real Neo4j query

FakeDriver 금지.

실제 Neo4j에 Candidate/Evidence/Page/Version/Object/PlatePanel graph를 넣고 endpoint가 200인지 확인한다.

### Test V-02 — body-only text candidate

도판/도면이 없는 text-only 후보.

PASS:

```text
HTTP 200
review_mode=text_vs_text 또는 text_only
visual_status=not_applicable/partial
```

404 generic failure이면 FAIL.

### Test V-03 — exact Plate target

본문 `도판45` candidate가 정확히 `【도판45】` panel image를 반환해야 한다.

다른 Plate가 object에 함께 연결되어 있어도 Plate45가 아닌 자산을 반환하면 FAIL.

### Test V-04 — exact Drawing target

본문 `도면30` candidate가 Drawing30/Region만 반환해야 한다.

### Test V-05 — render bytes

bundle의 모든 `imageUrl`을 실제 GET하여:

```text
status=200
content-type=image/png|image/jpeg
bytes > 0
```

확인한다.

### Test V-06 — bbox highlight

known text bbox와 plate/drawing bbox를 browser에서 overlay하고 스크린샷 테스트로 확인한다.

### Test V-07 — no fake VLM UI

`vlm_observation` Evidence가 없는 candidate에서 `VLM 비전 분석 관찰 소견`이 나타나면 FAIL.

### Test V-08 — partial render failure

source render를 의도적으로 실패시켜도 canonical asset이 정상인 경우 canonical 이미지는 화면에 보여야 한다.

### Test V-09 — Browser E2E

Playwright 또는 동등한 브라우저 E2E에서:

```text
project open
candidate click
source image loaded
comparison image loaded
no generic visual error
next candidate
image updates
```

를 검증한다.

---

# 19. 이번 증상의 우선 진단 결론

현재 screenshot만으로 runtime stack trace를 직접 볼 수 없으므로 단 하나의 원인을 100% 확정해서는 안 된다.

하지만 코드상 우선순위는 명확하다.

### 가장 먼저 확인할 원인

**`AssetRepository.get_candidate_visual_bundle()`의 nested aggregation Cypher**

이 query는 visual-bundle 요청마다 공통으로 실행되므로, 여기서 server-side query failure가 나면 현재처럼 모든 후보에서 동일한 generic visual error가 반복될 수 있다.

### 그 다음 확인할 원인

1. Evidence의 `FROM_VERSION`이 실제 DocumentVersion URI까지 연결되는지
2. source Page의 `HAS_PAGE` 관계와 physical_page가 존재하는지
3. 해당 PDF가 DATA_ROOT에 실제 존재하는지
4. 도판/도면이 해당 run에 실제 선택·ingest됐는지
5. canonical target이 candidate-specific Reference로 연결되어 있는지
6. render URI/file이 존재하는지

이 순서로 확인해야 한다.

---

# 20. MVP 완료 조건

다음이 모두 충족되어야 `3) 시각자산 / 프론트엔드` 리뷰를 PASS로 닫는다.

1. `visual-bundle` query가 real Neo4j에서 검증된다.
2. body-only candidate가 generic visual error로 보이지 않는다.
3. 본문 PDF actual page가 browser에서 표시된다.
4. 본문 bbox가 실제 문장을 highlight한다.
5. Plate candidate는 exact Plate/Panel을 표시한다.
6. Drawing candidate는 exact Drawing/Region을 표시한다.
7. Object의 임의 첫 visual asset을 사용하지 않는다.
8. actual VLM Evidence가 없는 후보에 VLM 결과를 꾸며서 표시하지 않는다.
9. 한쪽 render 실패 시 다른 Evidence는 계속 표시된다.
10. backend error code/request id를 frontend가 보존한다.
11. duplicate visual-bundle request가 제거된다.
12. `<img>` render 404/500을 UI가 감지하고 설명한다.
13. 실제 본문+도판+도면 3종 E2E와 browser E2E가 통과한다.

---

## 최종 요약

현재 프론트의 `시각 자산을 불러오지 못했습니다`는 단순 CSS/이미지 태그 문제가 아니다.

가장 먼저 `visual-bundle`의 Neo4j query를 실제 DB에서 재현해야 하며, 그 다음 **candidate가 어떤 Evidence와 어떤 canonical visual을 비교해야 하는지** 계약을 수정해야 한다.

특히 현재처럼 모든 후보를 `본문 vs 도판/도면 + VLM` 화면으로 강제하면 text-only 규칙 후보까지 잘못된 시각 의미를 갖게 된다.

최종 Split-View는 **후보 종류가 아니라 실제 Graph Evidence path를 기준으로 화면을 구성**해야 한다.

```text
CorrectionCandidate
   ↓ SUPPORTED_BY
Evidence(s)
   ↓
Graph가 실제 비교 대상 역할(role)을 결정
   ↓
Frontend가 source/comparison/plate/drawing/VLM을 사실대로 렌더
```

이 구조가 되어야 이 화면이 단순 AI 결과 목록이 아니라 실제 고고학자용 문서·사진·도면 교차 검수 도구가 된다.
