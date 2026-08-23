# /src Adobe-free 재검증 계획서

작성 목적: 로컬 Codex가 실제 `/src` 자산을 사용해 Adobe-free provenance 변경의 효과를 재측정하고, 실패 원인을 수정한 뒤 before/after 수치와 근거를 남기기 위한 실행 문서.

대상 브랜치: `feature/adobe-free-provenance-20260823`

관련 문서:
- `docs/local_real_asset_audit_instructions.md`
- `docs/local_real_asset_audit_report.md`
- `docs/superpowers/specs/2026-08-23-adobe-free-provenance-design.md`
- `docs/superpowers/plans/2026-08-23-adobe-free-provenance.md`

---

## 1. 이번 재검증의 목적

기존 `/src` 실자산 감사에서 파일 자체의 사용 가능성은 높았지만, 구조적 provenance와 본문→원본 연결 성능은 낮았다.

기존 기준값은 다음과 같다.

| 지표 | 기존 결과 |
|---|---:|
| `/src` 전체 파일 | 1,107 |
| SHA-256 중복 | 0 |
| 본문 PDF | 3개 / 815페이지 |
| AI PDF-compatible 및 렌더링 | 56/56, 100% |
| JPG 디코드 | 1,032/1,032, 100% |
| 본문 참조 파서 페이지 회수 | 182/384, 47.4% |
| 도판 패널 분할 | 1,933/2,804, 68.9% |
| AI 내부 semantic 도면 ID 추출 | 1/56, 1.8% |
| 완전한 본문→원본 체인 | 0/7, 0% |

이번 작업의 목적은 Adobe/COM/ExtendScript를 사용하지 않은 상태에서 아래 네 가지를 실제 파일로 개선·검증하는 것이다.

1. 본문에서 도판/도면 참조를 더 정확하게 회수한다.
2. 도판 PDF의 panel geometry 실패 871건을 원인별로 분해하고 가능한 범위에서 deterministic segmentation을 개선한다.
3. AI의 `internal semantic extraction`과 별도로 `resolved identity`를 구축한다.
4. 기존 AdobeManifest 필수 경로를 대체해 본문→도판/도면→실제 source asset으로 이어지는 provenance chain을 만든다.

**수치를 맞추기 위해 추측 연결을 성공으로 세면 안 된다.** 목표를 달성하지 못하면 낮은 수치 그대로 보고하고, 실패 원인과 재현 가능한 샘플을 남긴다.

---

## 2. 로컬에서 반드시 사용할 실제 데이터

실제 자산 루트는 저장소의 `/src`이다.

`/src`는 **읽기 전용**으로 취급한다.

금지 사항:
- 파일명 변경
- 폴더 이동/재구성
- 원본 덮어쓰기
- Adobe InDesign/Illustrator 실행
- COM/ExtendScript/Windows Adobe bridge 호출
- 실패 데이터를 성공으로 변환하기 위한 임의 metadata 작성

시작 시 반드시 다음을 다시 inventory 하고 기존 기준값과 비교한다.

- 전체 파일 수
- 확장자별 파일 수
- 각 파일 SHA-256
- SHA 중복 그룹
- 본문 PDF 3개와 페이지 수
- 도판 PDF 1/2/3차 판본
- INDD 수
- AI 수
- JPG 수
- IDML/AdobeManifest sidecar 존재 여부

inventory가 기존 1,107개와 달라졌다면 **시험을 계속하되 데이터셋 변경 사실을 보고서 최상단에 표시**하고 이전 결과와 단순 백분율 비교하지 않는다.

---

## 3. 현재 코드에서 반드시 검증할 변경 지점

다음 파일을 먼저 읽고 실제 구현 계약을 파악한다.

- `backend/app/domain/canonical_models.py`
- `backend/app/services/pdf_parser.py`
- `backend/app/services/drawing_identity_resolver.py`
- `backend/app/services/visual_asset_matcher.py`
- `backend/app/services/reference_corpus_service.py`
- `backend/app/graph/reference_corpus_repository.py`

관련 회귀 테스트:

- `backend/tests/test_adobe_free_provenance.py`
- `backend/tests/test_adobe_free_reference_corpus.py`
- `backend/tests/test_reference_corpus_repository.py`

먼저 focused test를 실행한다.

```bash
cd backend
python -m compileall -q app
pytest -q \
  tests/test_adobe_free_provenance.py \
  tests/test_adobe_free_reference_corpus.py \
  tests/test_reference_corpus_repository.py
```

그 다음 저장소 CI와 동일하거나 더 강한 범위의 backend/hermetic 및 Neo4j E2E를 실행한다. 로컬 환경 차이로 CI-equivalent 실행이 불가능한 항목은 생략하지 말고 `NOT RUN`과 이유를 보고한다.

---

## 4. 필요한 정보와 기록 항목

실험 도중 아래 정보를 반드시 수집한다. 추측으로 채우지 않는다.

### 4.1 본문 PDF

각 1/2/3차 본문 PDF별로:
- 파일 경로
- SHA-256
- 페이지 수
- 직접 관찰되는 도판 참조 occurrence 수
- 직접 관찰되는 도면 참조 occurrence 수
- 참조가 존재하는 unique page 수
- parser가 회수한 occurrence/page 수
- missed reference 예시
- false positive 예시
- 표기 유형별 성공률

표기 유형은 최소 다음을 별도 집계한다.

- `도판 1`
- `도판: 1`
- `【도판 1】`
- `원색도판 2`
- `【원색도판 2】`
- `도면 1`
- `도면: 1`
- `【도면 1】`
- 숫자가 연도/수량 등으로 오인될 수 있는 사례

### 4.2 도판 PDF

1/2/3차 도판 PDF 각각에 대해:
- Plate header 회수 수
- panel 총수
- segmented 수
- insufficient 수
- insufficient 871건 전체의 failure taxonomy

failure taxonomy는 최소 다음 네 그룹을 구분한다.

1. `badge_missing`: panel badge/label 자체 미검출
2. `image_candidate_zero`: 대응 image rect 후보 0개
3. `image_candidate_multiple`: 후보가 2개 이상이라 결정 불가
4. `non_image_or_other`: PDF image object가 아니거나 기타 geometry 문제

모든 insufficient panel은 정확히 하나의 원인 그룹 또는 명시적인 `unknown`에 들어가야 한다. 합계가 전체 insufficient와 일치해야 한다.

### 4.3 Plate panel → JPG source matching

새 matcher를 실제 도판 PDF와 `/src` JPG에 적용한다.

각 match는 다음을 기록한다.

- Plate number
- panel index
- panel bbox/status
- matched source asset 경로/ID
- match method
- score 또는 deterministic comparison 근거
- evidence level
- unique candidate 여부

성공으로 셀 수 있는 것은 `direct` 또는 `derived_verified`뿐이다.

`heuristic`은 candidate 생성에는 사용할 수 있지만 verified source chain 성공으로 세지 않는다.

여러 JPG가 동일 점수/근거로 남으면 `unresolved`로 유지한다.

### 4.4 AI 도면

56개 AI 각각에 대해 다음 세 지표를 **분리**한다.

1. `file readable/renderable`
2. `internal semantic identity`
3. `resolved identity`

기존의 1/56, 1.8%는 **AI 파일 내부 콘텐츠에서 명시적인 도면 ID를 직접 추출한 비율**이다. filename/context resolver로 identity가 올라가더라도 이 기존 semantic 지표를 덮어쓰면 안 된다.

각 AI에 대해 다음을 기록한다.

- 경로
- SHA-256
- PDF-compatible 여부
- 렌더 성공 여부
- 내부 텍스트에서 직접 도면 번호가 있는지
- filename candidate 번호
- 본문/다른 source와 교차 검증된 번호
- 최종 resolved number
- evidence level
- evidence method
- unresolved 이유

Evidence 의미:

- `direct`: source 내부의 명시적인 authoritative identifier
- `derived_verified`: 서로 독립적인 2개 이상의 deterministic evidence로 같은 identity를 확인
- `heuristic`: filename 등 단독 추정
- `unresolved`: 안전한 identity 결정 불가

filename 숫자 하나만으로 `direct`나 `derived_verified`를 주면 안 된다.

---

## 5. 본문 참조 parser 재검증

기존 page-level 기준은 `182/384 = 47.4%`였다.

새 parser를 동일 `/src` 본문 3개에 적용하고 다음을 산출한다.

```text
edition
expected_reference_pages
parsed_reference_pages
page_recall
expected_occurrences
parsed_occurrences
occurrence_recall
false_positive_count
false_positive_examples
missed_examples
```

### 목표

- 필수: **47.4%보다 실제 회수율이 상승할 것**
- 1차 목표: **page recall >= 90%**
- 권장 목표: **page recall >= 95%**
- 새로운 regex 때문에 명백한 연도/수량 오인 등 false positive가 증가하면 개선으로 인정하지 않는다.

목표 미달 시 가장 많이 실패하는 실제 표기 유형부터 fixture를 추가하고 parser를 수정한 뒤 다시 전수 실행한다.

테스트 fixture는 synthetic 문자열만 사용하지 말고 실제 `/src`에서 발견된 표현을 익명화/최소화해서 회귀 테스트에 반영한다.

---

## 6. 도판 panel segmentation 재검증

기존 수치:

```text
총 panel      2,804
segmented     1,933 (68.9%)
insufficient    871 (31.1%)
```

먼저 871건을 taxonomy로 분해한 뒤 가장 큰 실패군부터 수정한다.

### 원칙

- candidate가 애매하면 bbox를 만들지 않는다.
- geometry와 PDF object evidence 없이 nearest-neighbor만으로 확정하지 않는다.
- 실패율을 낮추려고 `insufficient`를 임의 성공으로 바꾸지 않는다.

### 목표

- 필수: failure taxonomy가 **871/871, 100% accounting**될 것
- 1차 목표: deterministic segmentation **>= 80%**
- 권장 목표: deterministic segmentation **>= 85%**
- 85%가 실제 PDF 구조상 불가능하면 수치를 조작하지 말고 제한 원인을 증명한다.

개선 전후를 각 판본별로 따로 보고한다.

---

## 7. AI identity resolver 재검증

기존 직접 semantic 추출은 `1/56 = 1.8%`이다.

이 수치를 다음 두 값으로 분리해서 보고한다.

```text
internal_semantic_identity = X/56
resolved_identity_any_level = Y/56
resolved_direct_or_verified = Z/56
heuristic_only = H/56
unresolved = U/56
```

### 기대치

실제 감사에서 filename에 도면/삽도 번호가 있던 AI가 35/56이었으므로 새 resolver의 **candidate coverage**는 적어도 이 근처가 나오는 것이 합리적이다. 그러나 filename-only는 verified 성공으로 세지 않는다.

### 목표

- `internal_semantic_identity`는 기존 1/56과 별도 보존
- `resolved_identity_any_level` 1차 목표: **>= 35/56 (62.5%)**
- `direct + derived_verified`는 가능한 만큼 최대화하되 별도 수치로 보고
- heuristic-only는 그래프에 evidence level과 method를 남기고 authority로 승격하지 않음
- unresolved는 그대로 유지

본문 reference, AI 내부 텍스트, 파일명, 인접 설명/제목 등 독립 evidence가 같은 번호를 가리키는지 확인해 `derived_verified` 승격 규칙을 테스트한다.

---

## 8. 본문 → 원본 provenance chain 재검증

기존 대표 7개 chain은 모두 실패했다.

반드시 동일 샘플을 다시 추적한다.

- 도판 1
- 도판 2
- 도판 3
- 도판 4
- literal `도판 1968`
- 도면 1
- 도면 2

기존에는 INDD page/bounds/linkPath 또는 Adobe manifest가 중간 authority여서 `0/7`이었다.

이번에는 Adobe-free graph로 다음 두 수준을 구분한다.

### A. Identity chain

```text
Body reference
  -> canonical Plate/Drawing
  -> source Plate PDF or AI asset
```

### B. Deep provenance chain

도판:

```text
Body reference
  -> Plate
  -> PlatePanel
  -> verified original JPG
```

도면:

```text
Body reference
  -> Drawing
  -> verified AI source asset
```

### complete 판정 규칙

다음 조건을 모두 만족해야 complete다.

- 모든 hop이 같은 project/reference corpus scope 안에 있음
- source asset SHA가 실제 `/src` 파일과 일치함
- identity/source edge에 evidence level과 method가 있음
- 최종 authority hop이 `heuristic`만으로 결정되지 않음
- ambiguity가 있으면 unresolved로 남김

### 목표

- 기존 `0/7`보다 반드시 개선 여부를 측정
- 1차 목표: **verified complete >= 5/7**
- 권장 목표: **verified complete 7/7**

단, `도판 1968`이 실제로 false-positive reference로 판정되면 억지로 chain을 만들지 않는다. 이 경우 `reference_false_positive`로 별도 판정하고 분모를 임의로 바꾸지 말고 `0/7 baseline sample 중 1건이 false positive로 재분류됨`이라고 명시한다.

---

## 9. ReferenceCorpus 실제 build 시험

최종적으로 Adobe 없이 실제 corpus build를 실행한다.

최소 입력 역할:

- `plate_pdf`: 실제 도판 PDF
- `plate_link`: 실제 JPG source set
- `drawing_source`: 실제 AI 56개

INDD는 provenance 원본으로 보관할 수 있지만 Adobe-free READY의 필수 authority가 되어서는 안 된다.

확인 항목:

1. build가 Adobe converter client를 호출하지 않는지
2. corpus status가 정상 state transition을 거치는지
3. Plate/Drawing 노드가 corpus scope로 저장되는지
4. evidence level/method가 Neo4j에 보존되는지
5. unresolved panel/drawing이 fake `DERIVED_FROM` source edge를 만들지 않는지
6. verified panel만 실제 JPG source edge를 갖는지
7. cross-project/cross-corpus source가 섞이지 않는지
8. READY validation이 heuristic/unresolved를 direct evidence로 오인하지 않는지

실제 Neo4j를 사용할 수 있으면 node/relationship count와 대표 Cypher 결과를 보고서에 포함한다.

---

## 10. 수정 반복 규칙

시험 중 실패를 발견하면 다음 순서를 지킨다.

1. 실패 샘플을 최소 재현한다.
2. RED 회귀 테스트를 추가한다.
3. 최소 코드 수정으로 GREEN으로 만든다.
4. focused test 실행.
5. `/src` 전체 재측정.
6. 전체 backend/Neo4j 검증.
7. metric이 실제로 좋아졌는지 before/after 비교.

단순히 테스트가 GREEN인 것과 실제 `/src` metric 개선을 동일하게 취급하지 않는다.

---

## 11. 반드시 생성할 최종 산출물

완료 후 아래 파일을 작성한다.

### `docs/local_adobe_free_revalidation_report.md`

보고서 첫 부분에 반드시 아래 표를 넣는다.

| 지표 | Before | After | 변화 | 판정 |
|---|---:|---:|---:|---|
| 본문 참조 page recall | 182/384 (47.4%) |  |  |  |
| 도판 panel segmentation | 1,933/2,804 (68.9%) |  |  |  |
| AI internal semantic identity | 1/56 (1.8%) |  |  |  |
| AI resolved identity any level | 기존 미측정 |  |  |  |
| AI direct+derived_verified | 기존 미측정 |  |  |  |
| verified complete chain | 0/7 |  |  |  |

그 아래에 반드시 포함할 내용:

- 실행한 commit SHA
- `/src` inventory와 dataset 변경 여부
- Python/PyMuPDF/Pillow 등 실제 버전
- Adobe/COM을 사용하지 않았다는 확인
- focused test 결과
- full backend/Neo4j 결과
- 각 metric 계산식
- 실패 taxonomy
- 대표 성공 chain 최소 3개
- 대표 unresolved/failure 최소 10개
- 남은 구조적 한계
- 다음 코드 변경 권고

### `docs/local_adobe_free_revalidation_metrics.json`

사람이 읽는 보고서와 별도로 최소 다음 field를 machine-readable JSON으로 저장한다.

```json
{
  "commit": "",
  "dataset": {
    "files": 0,
    "sha_duplicates": 0,
    "body_pdfs": 0,
    "body_pages": 0,
    "ai_files": 0,
    "jpg_files": 0
  },
  "body_reference": {
    "expected_pages": 384,
    "parsed_pages": 0,
    "page_recall": 0.0,
    "false_positives": 0
  },
  "plate_segmentation": {
    "total": 2804,
    "segmented": 0,
    "rate": 0.0,
    "failure_taxonomy": {}
  },
  "drawing_identity": {
    "total": 56,
    "internal_semantic": 0,
    "resolved_any_level": 0,
    "direct_or_verified": 0,
    "heuristic_only": 0,
    "unresolved": 0
  },
  "cross_source_chain": {
    "baseline_total": 7,
    "verified_complete": 0,
    "heuristic_only": 0,
    "unresolved": 0,
    "false_positive_reference": 0
  }
}
```

---

## 12. 완료 판정

다음 조건이 모두 충족되어야 이 로컬 재검증을 완료로 본다.

- `/src`를 실제로 다시 전수 검사함
- focused regression tests GREEN
- 실행 가능한 전체 backend/Neo4j 검증 GREEN 또는 명시적인 NOT RUN 사유 존재
- 본문 참조 before/after 수치 존재
- panel segmentation before/after 수치와 871건 failure taxonomy 존재
- AI semantic과 resolved identity를 분리해서 보고함
- 7개 대표 chain을 모두 다시 추적함
- heuristic-only를 verified complete로 세지 않음
- unresolved 사례를 삭제/숨기지 않음
- report + metrics JSON 작성 완료

목표 수치를 못 넘겨도 **실패 원인을 재현 가능하게 증명했다면 보고서는 완료**할 수 있다. 단, 목표 미달을 성공으로 표현해서는 안 된다.

---

## 13. 로컬 Codex에 줄 실행 지시문

다음 문장을 그대로 사용해도 된다.

> `docs/local_adobe_free_revalidation_plan.md`를 처음부터 끝까지 읽고 그대로 실행해. 실제 자산은 `/src` 아래에 있고 원본은 절대 수정하지 마. Adobe/COM/ExtendScript는 사용하지 마. 먼저 focused regression test를 실행하고, 그 다음 `/src` 전체를 재검사해서 기존 47.4%, 68.9%, 1.8%, 0/7 수치가 어떻게 변했는지 실제 측정해. AI internal semantic identity와 resolved identity는 반드시 분리해. panel segmentation 실패 871건은 전부 원인 taxonomy로 분류해. 실패를 발견하면 RED test를 추가한 뒤 수정하고 다시 전체 `/src`를 측정해. heuristic-only 연결은 verified success로 세지 마. 최종적으로 `docs/local_adobe_free_revalidation_report.md`와 `docs/local_adobe_free_revalidation_metrics.json`을 작성하고, 수정한 코드/테스트와 함께 commit해. 완료 보고에는 commit SHA, 실행한 테스트, before/after metric, 남은 unresolved를 포함해.`
