# Canonical Document–Object–Evidence Graph 설계

## 0. 문서 목적

이 문서는 현재 존재하는 `PDFParser / PageAligner / RuleEngine / AssetMatcher / VLM / Neo4j` 컴포넌트를 버리지 않고, **하나의 canonical Document–Object–Evidence 그래프를 중심으로 재정의하고 연결하기 위한 구현 설계서**다.

실제 구현은 별도 에이전트가 수행한다. 따라서 본 문서는 다음을 명확히 정의한다.

1. 시스템의 최종 목표와 비목표
2. 고고학적 식별자(canonical identity)의 기준
3. 각 컴포넌트의 책임과 금지사항
4. Neo4j canonical graph 모델
5. 전체 데이터 흐름과 상태 전이
6. 고고학자 피드백을 반영한 Golden Test 및 MVP 합격 기준
7. 현재 코드에서 무엇을 유지하고 무엇을 변경해야 하는지

이 설계에서 가장 중요한 기준은 **AI 정확도보다 identity correctness와 evidence traceability가 우선**이라는 점이다.

---

# 1. Implementation North Star

> 이 시스템은 단순 PDF diff 도구나 VLM 이미지 판독기가 아니다.
>
> 발굴보고서의 **본문·도면·도판·사진·버전 간 서술이 동일한 고고학적 대상을 올바르게 설명하는지 구조적으로 연결하고**, 불일치 또는 교정 후보를 **근거 경로와 함께 고고학자에게 제시하는 검수 시스템**이다.
>
> Deterministic document structure가 identity를 결정한다. Rule/LLM/VLM은 그 identity에 대한 Evidence를 생성한다.
>
> 불확실한 경우 잘못 연결하는 것보다 `unresolved`로 남기는 것이 올바른 동작이다.

최종적으로 시스템은 다음 질문에 답할 수 있어야 한다.

```text
본문 108쪽:
"2지점 시대미상 11·12호 토광묘"
"도면 59, 도판 88·89"

→ 도면 59가 실제 동일 유구를 다루는가?
→ 도판 88·89가 실제 동일 유구를 보여주는가?
→ 사진/도면의 시각적 특징이 본문의 설명과 모순되지 않는가?
→ 다른 페이지에서 같은 유구의 치수·시대·방향·번호를 다르게 설명하지 않는가?
→ 1차→2차→3차에서 무엇이 어떻게 바뀌었는가?
→ 발견된 문제는 어느 문서/버전/페이지/bbox에 근거하는가?
→ 전문가가 최종적으로 어떤 결정을 내렸는가?
```

---

# 2. 최상위 GOAL

## GOAL-0. Ground Truth를 AI보다 먼저 올바르게 구성한다

이 프로젝트의 모든 후속 기능보다 우선하는 목표다.

### 2.1 고고학자 피드백에서 확인된 핵심 사실

InDesign 작업 과정에서 여러 폴더의 사진을 가져와 저장할 때, 동일 파일명 충돌을 피하기 위해 Links 폴더의 파일명에 일련번호가 붙을 수 있다.

따라서 다음 등식은 **거짓**이다.

```text
Links 파일명에 포함된 숫자 == 실제 도판 번호
```

예를 들어:

```text
본문:
1지점 청동기시대 6호 석관묘
도판 45·46

Links 폴더:
4. 조사 후_45.JPG
```

여기서 `_45`는 도판 45라는 의미가 아니다. 실제로 고고학자 검증 결과 이 파일은 해당 6호 석관묘와 무관한 토광묘 사진이었다.

### 2.2 올바른 canonical plate identity

본문의 `도판 45`가 가리키는 대상은 Links 파일명이 아니라, 도판 PDF 내부에서 명시적으로 선언된 출판 식별자다.

예:

```text
<11.21-115집 논산 산노리 산17-1번지 유적-도판-3차 교정.pdf>

【도판 45】 1지점 청동기시대 6호 석관묘
① 조사 전
② 조사 중
③ 토층 A-A'
④ 동벽 세부
⑤ 유물 출토 상태
```

즉 canonical resolution은 다음 경로를 사용한다.

```text
본문 "도판 45"
      ↓
Reference(type=plate, number=45)
      ↓
도판 PDF에서 "【도판 45】" 검색
      ↓
Plate(number=45)
```

### 2.3 절대 규칙

- `Links filename number`는 도판 번호로 해석하지 않는다.
- `PDF physical page`도 도판 번호로 간주하지 않는다.
- 도판 번호는 우선적으로 PDF 안의 명시적 표기 `【도판 N】`에서 얻는다.
- 도면도 동일하게 명시적 publication identifier를 우선한다.
- INDD/IDML은 MVP 필수 입력이 아니다. PDF가 canonical publication source 역할을 할 수 있다.
- Links/원본 파일은 추후 provenance 보조 자료로만 사용한다.

### GOAL-0 Definition of Done

1. Case 6에서 `_45.JPG`가 도판 45로 연결되는 경우가 0건이다.
2. `Reference(plate,45)`는 도판 PDF의 `【도판 45】`로 resolve된다.
3. 기존 VLM 10-case의 사진 매핑은 전부 재검증되어야 하며, Links 파일명 숫자만으로 선정된 케이스는 ground truth로 인정하지 않는다.
4. canonical resolution이 실패하면 `missing` 또는 `unresolved`로 남기고 임의 추론하지 않는다.

---

# 3. Goals

## GOAL-1. PDFParser를 구조 추출기로 확장한다

PDFParser는 단순 텍스트 추출기가 아니라, canonical graph에 적재 가능한 구조 데이터를 생성한다.

최소 출력:

- `Page`
- `TextBlock`
- `Caption`
- `Reference`
- `bbox`
- `physical_page`
- `printed_page`
- `render_uri`
- `source_sha256`

문서 유형별 parser mode를 둔다.

### report_body mode

추출 대상:

- 본문 문단
- 캡션
- 인쇄 페이지
- 도면/도판/표 참조
- 유적/지점/시대/유구/유물 식별 표현

### plate_book mode

추출 대상:

- `【도판 N】`
- 도판 제목
- ①②③… 패널 캡션
- 각 텍스트/이미지 영역 bbox
- 페이지 렌더

### drawing_book mode

추출 대상:

- `【도면 N】` 또는 동등한 명시적 도면 번호
- 도면 제목/유구명
- drawing region bbox
- 렌더 또는 파생 이미지

### GOAL-1 Done

`resolve_plate(45)`에 해당하는 구조가 Links 폴더 없이 다음까지 추적 가능해야 한다.

```text
DocumentVersion
→ Page
→ explicit identifier 【도판 45】
→ Plate
→ PlatePanel[]
→ bbox/render_uri
```

---

## GOAL-2. PageAligner는 동일 Document의 버전 간 정렬만 담당한다

PageAligner는 다음 관계만 처리한다.

```text
본문 1차 ↔ 본문 2차 ↔ 본문 3차
```

다음은 PageAligner의 책임이 아니다.

```text
본문 ↔ 도판
본문 ↔ 도면
```

이 관계는 `Reference → canonical target` resolution이 담당한다.

Alignment 결과는 단순 similarity score만 저장하지 않고 다음 상태를 가진다.

```text
exact
probable
manual_review
unmatched
```

낮은 유사도를 강제로 대응시키지 않는다.

### GOAL-2 Done

```text
(DocumentVersion)-[:PRECEDES]->(DocumentVersion)

(Page)-[:ALIGNED_TO {
  score,
  status,
  method,
  algorithm_version
}]->(Page)
```

가 재현 가능하게 생성되어야 한다.

---

## GOAL-3. RuleEngine을 Object/Evidence consistency engine으로 변경한다

RuleEngine의 핵심 역할은 line diff 자체가 아니라 **동일 ArchaeologyObject에 연결된 Evidence 사이의 충돌을 찾는 것**이다.

예:

```text
본문 A: 11호 토광묘 길이 275cm
본문 B: 11호 토광묘 길이 2.45m
```

두 Evidence가 동일 ArchaeologyObject에 연결되면 RuleEngine은 단위 정규화 후 실제 수치 충돌을 검출한다.

검사 대상:

- 유적/지점명
- 유구/유물 번호
- 유구 종류
- 시대
- 방향
- 치수
- 수량
- 고도
- 도면 번호
- 도판 번호
- 단위
- 캡션
- 조사 단계
- 빈 참조
- 표기/문장부호/띄어쓰기

기존 line-diff 로직은 **버전 변경 탐지 보조 기능**으로 유지할 수 있다.

모든 후보는 반드시:

```text
status = pending_review
```

로 시작한다.

자동 `confirmed` 금지.

---

## GOAL-4. AssetMatcher를 Reference Resolver로 재정의한다

AssetMatcher의 주 책임을 다음으로 변경한다.

```text
Reference → canonical publication asset
```

도판의 경우:

```text
Reference(type=plate, number=45)
          ↓
Canonical Graph
          ↓
Plate(number=45)
```

도면도 동일하다.

### 금지사항

- 파일 stem에 `45`가 있다는 이유만으로 `Plate 45`로 선택하지 않는다.
- 단일 filename 후보라는 이유만으로 `exact`로 승격하지 않는다.
- Links 디렉터리의 이름/일련번호를 publication identity로 사용하지 않는다.

### Resolver 상태

```text
resolved
ambiguous
missing
unresolved
```

`exact`이라는 용어는 canonical resolution과 semantic correctness를 혼동하므로 제거하거나 사용하지 않는다.

---

## GOAL-5. VLM을 Matcher가 아니라 Observer로 사용한다

VLM은 asset identity를 결정하지 않는다.

VLM 입력은 반드시 이미 canonical graph에서 resolve된 영역이어야 한다.

```text
Reference
→ canonical Plate/Drawing
→ Region
→ VLM
```

VLM은 다음과 같은 관찰을 구조화한다.

```json
{
  "status": "PARTIAL",
  "observations": {
    "site_label": "...",
    "feature_number": "...",
    "object_type": "...",
    "investigation_stage": "...",
    "soil_layer": "...",
    "orientation": "...",
    "scale": "..."
  },
  "supported_claims": [],
  "contradicted_claims": [],
  "unobservable_claims": [],
  "confidence": 0.84
}
```

허용 상태:

```text
SUPPORTED
PARTIAL
CONTRADICTED
INSUFFICIENT_EVIDENCE
```

### VLM 금지사항

- "이 사진이 도판 45다"를 결정하지 않는다.
- 단순 site 일치만으로 전체 match를 만들지 않는다.
- feature number가 불일치하는데 site가 같다는 이유로 match 처리하지 않는다.
- VLM 결과만으로 `DEPICTS` 관계를 expert-confirmed 상태로 승격하지 않는다.

---

## GOAL-6. Neo4j를 canonical System of Record로 사용한다

Neo4j는 파일 바이트 저장소가 아니라 **문서 구조, 고고학 개체, 참조, 근거, 후보, 전문가 판단을 연결하는 시스템 기록**이다.

최소 핵심 노드:

```text
Project
Document
DocumentVersion
Page
TextBlock
Caption
Reference
Plate
PlatePanel
Drawing
DrawingRegion
OriginalAsset
ArchaeologyObject
Evidence
CorrectionCandidate
ReviewDecision
AnalysisRun
```

---

## GOAL-7. ReviewPipeline을 단일 Orchestrator로 만든다

실행 순서를 고정한다.

```text
1. File ingest
2. Document classification
3. PDF structural parsing
4. Graph persistence
5. Version alignment
6. Reference extraction
7. Canonical reference resolution
8. ArchaeologyObject resolution
9. Rule-based consistency checks
10. Plate/Drawing region extraction
11. VLM observation
12. LLM contextual proofreading
13. Evidence aggregation
14. CorrectionCandidate creation
15. Expert review
```

단계를 건너뛰는 직접 경로를 허용하지 않는다.

특히 다음 호출은 금지한다.

```text
AssetMatcher → VLM
```

반드시:

```text
Reference
→ canonical target
→ region
→ VLM
```

순서여야 한다.

---

## GOAL-8. 모든 Candidate를 설명 가능하게 만든다

Candidate 하나를 클릭했을 때 최소한 다음 질문에 답할 수 있어야 한다.

- 왜 문제인가?
- 어떤 ArchaeologyObject의 문제인가?
- 어느 Document인가?
- 어느 DocumentVersion인가?
- 몇 physical page인가?
- 인쇄 페이지는 몇 쪽인가?
- 어느 bbox인가?
- 어떤 도판/도면/사진과 연결되는가?
- 어떤 rule/model이 문제를 발견했는가?
- VLM/LLM은 무엇을 관찰했는가?
- 전문가가 어떤 판단을 내렸는가?

Evidence source path가 끊기면 후보 상태를 다음처럼 처리한다.

```text
evidence_incomplete
```

---

## GOAL-9. Human in the Loop을 강제한다

AI는 최종 교정을 승인하지 않는다.

```text
pending_review
  ├─ accepted
  ├─ rejected
  ├─ modified
  └─ deferred
```

모든 결정은 `ReviewDecision`으로 append-only 저장한다.

---

# 4. Non-Goals

MVP에서는 다음을 목표로 하지 않는다.

- HWP/PDF 자동 수정 및 재편집
- INDD 원본을 필수 입력으로 요구
- Links 파일명만으로 원본 provenance 완전 복원
- VLM 단독으로 고고학적 개체 정체성 확정
- 다중 사용자 동시 편집
- 자동 accepted 처리
- 모든 Illustrator/DWG 원본 형식을 첫 MVP에서 완전 파싱

INDD/IDML은 향후 provenance 강화를 위한 선택 기능이다. MVP의 publication identity는 PDF를 기준으로 구성한다.

---

# 5. System Invariants

구현 에이전트는 아래 규칙을 테스트로 고정해야 한다.

## INV-01

```text
Links filename number != plate number
```

## INV-02

```text
PDF physical page != publication plate number
```

## INV-03

도판 ID는 우선적으로 명시적 `【도판 N】` 표기에서 얻는다.

## INV-04

도면 ID도 우선적으로 명시적 publication identifier에서 얻는다.

## INV-05

VLM/LLM은 canonical identity를 생성하거나 덮어쓸 수 없다.

## INV-06

파일명 일치만으로 `RESOLVES_TO`, `DEPICTS`, `CAPTION_OF`의 확정 관계를 만들지 않는다.

## INV-07

모든 `CorrectionCandidate`는 `pending_review`로 시작한다.

## INV-08

모든 Candidate에는 최소 1개 이상의 source-addressable Evidence가 있어야 한다.

## INV-09

모든 Evidence는 최소 다음으로 원본까지 역추적 가능해야 한다.

```text
source_sha256
DocumentVersion
Page
bbox/region
```

## INV-10

원본 파일은 절대 자동 수정하지 않는다.

## INV-11

canonical resolution이 불확실하면 잘못된 단일 후보를 선택하지 않고 `ambiguous` 또는 `unresolved`로 남긴다.

## INV-12

VLM confidence는 expert approval 권한이 아니다.

---

# 6. Canonical Graph Model

## 6.1 Document 계층

```text
Project
 │
 ├── Document(kind=report_body)
 │      ├── DocumentVersion(stage=1차)
 │      ├── DocumentVersion(stage=2차)
 │      └── DocumentVersion(stage=3차)
 │
 ├── Document(kind=plate_book)
 │      └── DocumentVersion(stage=3차)
 │
 └── Document(kind=drawing_book)
        └── DocumentVersion(stage=3차)
```

하나의 `Document` 아래에 여러 `DocumentVersion`을 둔다. 각 업로드를 별도의 Document로 만드는 모델은 금지한다.

## 6.2 구조 노드

```text
DocumentVersion
  └─ HAS_PAGE → Page
                   ├─ HAS_BLOCK → TextBlock
                   ├─ HAS_CAPTION → Caption
                   ├─ HAS_PLATE → Plate
                   └─ HAS_DRAWING → Drawing
```

## 6.3 Reference

본문:

```text
① 유구(도면 : 30, 도판 : 45ㆍ46)
```

는 다음으로 구조화한다.

```text
TextBlock
 ├─ REFERENCES → Reference(type=drawing, number=30)
 ├─ REFERENCES → Reference(type=plate, number=45)
 └─ REFERENCES → Reference(type=plate, number=46)
```

Reference는 문자열이 아니라 first-class node 또는 동등한 독립 구조여야 한다.

```text
Reference(type=plate, number=45)
   └─ RESOLVES_TO → Plate(number=45)
```

## 6.4 Plate와 PlatePanel

```text
Plate 45
 title = "1지점 청동기시대 6호 석관묘"

 ├─ HAS_PANEL → PlatePanel 45-1 "조사 전"
 ├─ HAS_PANEL → PlatePanel 45-2 "조사 중"
 ├─ HAS_PANEL → PlatePanel 45-3 "토층 A-A'"
 ├─ HAS_PANEL → PlatePanel 45-4 "동벽 세부"
 └─ HAS_PANEL → PlatePanel 45-5 "유물 출토 상태"
```

PlatePanel 최소 속성:

```text
id
panel_index
caption
bbox
physical_page
render_uri
source_sha256
```

## 6.5 Drawing과 DrawingRegion

도면 파일 하나가 여러 번호/패널을 포함할 수 있으므로 file-level identity만으로 충분하지 않다.

```text
Drawing
 ├─ HAS_REGION → DrawingRegion 58
 ├─ HAS_REGION → DrawingRegion 59
 └─ HAS_REGION → DrawingRegion 60
```

## 6.6 ArchaeologyObject

본문·도판·도면을 연결하는 semantic hub다.

예:

```text
ArchaeologyObject
site = "논산 산노리 산17-1번지"
point = "1지점"
period = "청동기시대"
type = "석관묘"
number = "6호"
canonical_name = "1지점 청동기시대 6호 석관묘"
```

관계:

```text
(TextBlock|Caption)-[:MENTIONS]->(ArchaeologyObject)
(Plate|PlatePanel)-[:DEPICTS]->(ArchaeologyObject)
(Drawing|DrawingRegion)-[:DEPICTS]->(ArchaeologyObject)
```

자동 생성된 semantic 관계에는 반드시 다음 메타데이터를 둔다.

```text
confidence
method
status
analysis_run_id
created_at
```

`status` 예:

```text
candidate
semantic_review
expert_confirmed
rejected
```

## 6.7 Evidence

Evidence는 시스템의 핵심 산출물이다.

예:

```text
Evidence E1
kind = text_claim
source = 본문 54쪽
value = "1지점 청동기시대 6호 석관묘"

Evidence E2
kind = reference
value = "도판 45"

Evidence E3
kind = plate_caption
value = "【도판 45】 1지점 청동기시대 6호 석관묘"

Evidence E4
kind = vlm_observation
value = "토층 단면이 관찰됨"
confidence = 0.92
```

모든 Evidence는 원본 위치와 provenance를 가진다.

## 6.8 Candidate

```text
CorrectionCandidate
  ├─ ABOUT → ArchaeologyObject
  ├─ SUPPORTED_BY → Evidence
  └─ HAS_DECISION → ReviewDecision
```

## 6.9 AnalysisRun

AI/규칙/파서 재현성을 위해 다음을 저장한다.

```text
parser_version
alignment_version
rule_version
model
model_version
prompt_version
preprocessor_version
request_hash
response_hash
input_source_hashes
token_usage
cost
status
started_at
finished_at
```

---

# 7. Canonical Evidence Path

이번 시스템의 가장 중요한 실제 그래프 경로는 다음이다.

```text
Project
  ↓
Document(report_body)
  ↓
DocumentVersion(3차)
  ↓
Page 78
  ↓
TextBlock
"① 유구(도면:30, 도판:45·46)"
  │
  ├─ MENTIONS ───────────────→ ArchaeologyObject
  │                           "1지점 청동기 6호 석관묘"
  │                                      ▲
  └─ REFERENCES → Reference(plate,45)     │
                      ↓                   │
                 RESOLVES_TO              │
                      ↓                   │
                   Plate 45 ── DEPICTS ───┘
                      ↓
                   HAS_PANEL
                      ↓
                 PlatePanel 45-3
                   "토층 A-A'"
                      ↓
                VLM Observation
                      ↓
                   Evidence
                      ↓
              CorrectionCandidate
                      ↓
                ReviewDecision
```

MVP에서는 최소 하나 이상의 실제 케이스가 이 전체 경로를 완성해야 한다.

---

# 8. Component Contracts

| Component | 책임 | 금지사항 |
|---|---|---|
| `PDFParser` | 페이지/블록/캡션/reference/bbox/plate identity 추출 | 의미 정합 최종 판단 |
| `PageAligner` | 동일 Document 버전 간 페이지 대응 | 본문↔도판/도면 연결 |
| `RuleEngine` | ArchaeologyObject/Evidence consistency 검사 | 자동 승인 |
| `AssetMatcher` | Reference→canonical target resolution | Links filename 숫자를 도판 ID로 사용 |
| `VLM` | canonical region의 시각 관찰 및 claim 비교 | asset identity 결정 |
| `Neo4j` | canonical graph + provenance + review history | 원본 이미지 binary 저장 |
| `ReviewPipeline` | 전체 단계 orchestration | 순서 우회 |

---

# 9. Full Processing Flow

## Phase A. Ingest

```text
Upload
→ streaming SHA-256
→ immutable source storage
→ document kind classification
→ Document/DocumentVersion 생성
```

## Phase B. Structure

```text
PDFParser
→ Page/TextBlock/Caption/Reference
→ bbox/render
→ Neo4j persistence
```

도판/도면 문서는 explicit identifier index를 만든다.

```text
plate_number → Page/Plate

drawing_number → Page/DrawingRegion
```

## Phase C. Version Alignment

동일 report_body Document의 버전만 정렬한다.

```text
1차 Page ↔ 2차 Page ↔ 3차 Page
```

## Phase D. Object Resolution

본문의 유적/지점/시대/유구/유물 표현을 정규화하여 `ArchaeologyObject` 후보를 만든다.

불확실한 개체 병합은 `semantic_review`로 남긴다.

## Phase E. Reference Resolution

```text
본문 Reference(plate,45)
→ Plate index 조회
→ Plate 45
```

파일명 기반 검색보다 explicit publication identifier가 항상 우선한다.

## Phase F. Deterministic Consistency

RuleEngine이 그래프를 따라 같은 Object의 여러 Evidence를 비교한다.

## Phase G. Visual Observation

canonical PlatePanel/DrawingRegion만 VLM에 전달한다.

## Phase H. Contextual LLM Review

LLM은 전체 PDF를 받지 않는다.

입력은 다음으로 제한한다.

```text
target TextBlock
neighbor blocks
same ArchaeologyObject evidence
resolved plate/drawing captions
relevant deterministic rule outputs
```

## Phase I. Evidence Aggregation

AI/Rule 결과를 source-addressable Evidence로 변환한다.

## Phase J. Candidate + Expert Review

모든 후보는 pending_review로 생성한다.

---

# 10. Error / Uncertainty Model

최소 상태:

```text
input_error
conversion_error
extraction_error
alignment_error
reference_missing
reference_ambiguous
object_ambiguous
asset_missing
semantic_review
evidence_incomplete
api_error
rate_limited
manual_review
unresolved
```

오류는 실패 단계만 재실행 가능해야 한다.

---

# 11. 고고학자 피드백 기반 MVP Golden Test

이 섹션은 MVP 합격 여부를 결정하는 필수 시험이다.

## GT-01. Case 6 Links Filename Trap

### 입력

본문:

```text
1지점 청동기시대 6호 석관묘
① 유구(도면 : 30, 도판 : 45ㆍ46)
```

도판 PDF:

```text
【도판 45】 1지점 청동기시대 6호 석관묘
① 조사 전
② 조사 중
③ 토층 A-A'
④ 동벽 세부
⑤ 유물 출토 상태
```

Links 폴더에는 다음과 같이 `_45`를 포함하지만 실제로는 unrelated 토광묘 사진이 존재한다.

```text
4. 조사 후_45.JPG
```

### Expected PASS

```text
Reference(plate,45)
→ 도판 PDF의 【도판 45】
→ Plate(45)
```

### Forbidden FAIL

```text
Reference(plate,45)
→ *_45.JPG
```

### MVP Gate

**이 테스트에서 filename 숫자를 도판 번호로 해석하면 MVP 전체 FAIL.**

VLM이 이후 어떤 결과를 내는지는 이 테스트의 합격 여부와 무관하다. canonical mapping 단계에서 차단되어야 한다.

---

## GT-02. Physical Page != Plate Number

도판 PDF 물리 페이지와 `【도판 N】` 값이 다른 fixture를 사용한다.

예:

```text
physical_page = 47
explicit identifier = 【도판 45】
```

Expected:

```text
Plate.number == 45
Page.physical_page == 47
```

둘을 혼동하면 FAIL.

---

## GT-03. Ambiguous Filename

다음 파일들이 동시에 존재한다고 가정한다.

```text
photo_45.JPG
조사후_45.JPG
45_1.JPG
```

명시적 plate PDF가 존재하면 filename 후보 수와 무관하게 Plate 45 identity에 영향을 주지 않아야 한다.

---

## GT-04. Missing Explicit Plate

본문은 `도판 91`을 참조하지만 도판 PDF에서 `【도판 91】`을 찾을 수 없는 경우:

Expected:

```text
reference status = missing/unresolved
```

임의의 `_91.JPG`를 골라서는 안 된다.

---

## GT-05. Site Same, Feature Different

본문 기대값:

```text
2지점 2호 토광묘
```

VLM 관찰:

```text
site = 2지점
feature = 25호 토광묘
```

Expected:

```text
CONTRADICTED or PARTIAL
```

site가 같다는 이유로 SUPPORTED 처리하면 FAIL.

---

## GT-06. Single Image Is Insufficient Evidence

유물 단일 정면 사진만 존재하고 본문에는 배면 가공/측면 날을 기술한 경우:

Expected:

```text
unobservable_claims 포함
status = PARTIAL 또는 INSUFFICIENT_EVIDENCE
```

사진에 보이지 않는 특징을 match로 확정하면 FAIL.

---

## GT-07. Version Alignment Reject

서로 무관한 두 페이지를 similarity가 낮은데도 강제 align하지 않아야 한다.

Expected:

```text
manual_review 또는 unmatched
```

---

## GT-08. Candidate Starts Pending

모든 Rule/LLM/VLM 후보는:

```text
pending_review
```

로 생성되어야 한다.

자동 `confirmed/accepted`가 하나라도 있으면 FAIL.

---

## GT-09. Evidence Traceability

임의의 Candidate를 하나 선택했을 때 다음 역추적이 모두 가능해야 한다.

```text
Candidate
→ Evidence
→ DocumentVersion
→ Page
→ bbox/region
→ source_sha256
```

하나라도 끊기면 FAIL.

---

## GT-10. End-to-End Canonical Path

실제 고고학 fixture에서 다음 전체 경로를 확인한다.

```text
Body Text
→ Reference
→ Plate/Drawing
→ PlatePanel/DrawingRegion
→ ArchaeologyObject
→ Evidence
→ Candidate
→ ReviewDecision
```

---

# 12. 기존 VLM 10-Case 실증의 처리 원칙

기존 10-case 결과를 그대로 MVP 성능 기준으로 사용하지 않는다.

이유:

- 일부 케이스는 Links filename 숫자를 도판 번호로 오해했을 가능성이 있다.
- Case 6은 실제 오매칭이 고고학자에 의해 확인되었다.
- 잘못된 사진을 입력한 경우 VLM 관찰 자체는 유효할 수 있어도 해당 본문과의 `MATCH/PARTIAL` 평가는 ground truth가 아니다.

따라서 기존 케이스에는 다음 상태를 추가한다.

```text
VALID_GROUND_TRUTH
INVALID_GROUND_TRUTH_MAPPING
NEEDS_REVALIDATION
```

Case 6은 최소:

```text
INVALID_GROUND_TRUTH_MAPPING
```

으로 처리한다.

새 MVP Golden Dataset은 도판 PDF의 `【도판 N】`을 출발점으로 고고학자가 확인한 정답을 사용해야 한다.

---

# 13. Golden Dataset 스키마

각 정답 케이스는 최소 다음 필드를 가진다.

```yaml
case_id: GT_CASE_006
body_document_sha256: ...
body_version: 3차
body_physical_page: 78
body_printed_page: 54
body_text: "1지점 청동기시대 6호 석관묘 ... 도판 45·46"

object:
  site: "논산 산노리 산17-1번지"
  point: "1지점"
  period: "청동기시대"
  type: "석관묘"
  number: "6호"

reference:
  type: plate
  number: 45

canonical_target:
  source_document_sha256: ...
  explicit_identifier: "【도판 45】"
  physical_page: ...
  title: "1지점 청동기시대 6호 석관묘"

panels:
  - index: 1
    caption: "조사 전"
  - index: 2
    caption: "조사 중"
  - index: 3
    caption: "토층 A-A'"

forbidden_filename_matches:
  - "4. 조사 후_45.JPG"

expert_verified: true
expert_note: "Links의 _45는 도판번호가 아님"
```

최종 MVP 테스트에서는 반드시 expert-verified fixture만 pass/fail ground truth로 사용한다.

---

# 14. MVP Acceptance Criteria

## AC-01 Canonical Plate Resolution

본문 `도판 N`이 도판 PDF `【도판 N】`으로 resolution되어야 한다.

## AC-02 Zero Filename Hallucination

Links 파일명 숫자 기반 false mapping:

```text
0건
```

한 건이라도 발생하면 MVP FAIL.

## AC-03 Physical/Publication Number Separation

physical page와 plate/drawing number가 항상 별도 필드로 저장된다.

## AC-04 Version Trace

1차/2차/3차 동일 내용 페이지의 대응 및 변화 이력을 조회할 수 있다.

## AC-05 Object Trace

본문·도판·도면이 동일 ArchaeologyObject를 통해 연결될 수 있다.

## AC-06 Evidence Trace

모든 후보에서 원본 DocumentVersion/Page/bbox/source hash까지 역추적 가능하다.

## AC-07 AI Boundary

LLM/VLM이 canonical reference를 생성하거나 덮어쓴 사례:

```text
0건
```

## AC-08 Review Boundary

전문가 승인 없이 accepted 되는 Candidate:

```text
0건
```

## AC-09 Case 6 Mandatory Pass

`4. 조사 후_45.JPG`가 도판 45로 판단되지 않아야 한다.

## AC-10 Full Graph Path

최소 1개 이상의 실제 사례에서 다음 경로가 완성되어야 한다.

```text
Body Text
→ Reference
→ Plate/Drawing
→ Region
→ ArchaeologyObject
→ Evidence
→ Candidate
→ ReviewDecision
```

## AC-11 Reproducibility

동일 입력 + 동일 parser/rule/model/prompt/preprocess version으로 재실행할 때 canonical resolution 결과가 동일해야 한다.

## AC-12 Uncertainty Safety

정답을 확정할 수 없는 경우 `unresolved/manual_review`로 남기며 잘못된 자동 연결을 만들지 않는다.

---

# 15. MVP Metrics

정확도 지표는 단계별로 분리한다.

## Identity Layer

가장 우선한다.

```text
Canonical Reference Precision = 1.00 목표
Filename-number false mapping = 0
```

MVP에서 identity precision은 recall보다 우선한다. 못 찾으면 unresolved가 허용되지만, 틀린 대상을 고르면 안 된다.

## Object Resolution

```text
Precision >= 0.98
Ambiguous cases are allowed to remain unresolved
```

## Plate/Drawing Region Retrieval

```text
Correct target Recall@1 >= 0.95
Wrong explicit target selection <= 0.01
```

## Rule Candidate

고고학자 golden set을 기준으로 평가한다.

```text
Precision >= 0.90
Recall >= 0.80
```

## VLM Observation

VLM은 identity가 아니라 claim observation 정확도로 평가한다.

예:

```text
feature label correctness
site label correctness
object type correctness
investigation stage correctness
supported/contradicted/unobservable classification
```

`is_match accuracy` 단일 점수만 사용하지 않는다.

---

# 16. 현재 코드 Migration 방향

기존 컴포넌트는 유지하고 contract를 바꾼다.

## PDFParser

유지:

- text extraction entry point
- page-range API 개념
- 기본 normalization

변경:

- bbox/layout 지원
- Reference 복수 값/범위 지원
- plate/drawing mode 추가
- explicit `【도판 N】`, `【도면 N】` 추출
- page render 생성

## PageAligner

유지:

- 버전 간 similarity/alignment 개념

변경:

- 강제 match 방지 threshold/status
- actual DocumentVersion ID 사용
- ALIGNED_TO persistence

## RuleEngine

유지:

- deterministic 검사 계층
- version diff 보조 기능

변경:

- object/evidence consistency 중심
- 실제 numeric/site/period/direction 규칙 구현
- 모든 candidate pending_review

## AssetMatcher

유지:

- resolver/service boundary

변경:

- filename number fallback 제거 또는 provenance-only로 격리
- Graph Reference Resolver로 전환
- resolved/ambiguous/missing/unresolved 반환

## VLMReviewService

유지:

- 외부 VLM 호출
- 이미지 cache

변경:

- `is_match bool` 중심 계약 제거
- structured observations/claim verdicts
- site AND feature/object conflict logic
- model/prompt/preprocessor를 cache key에 포함

## Neo4j

추가:

- Reference
- Plate/PlatePanel
- Drawing/DrawingRegion
- ArchaeologyObject
- OriginalAsset
- ReviewDecision
- 관계 메타데이터

기존 Document/DocumentVersion 모델은 하나의 Document에 복수 버전이 연결되도록 수정한다.

---

# 17. 구현 우선순위

## P0 — Identity correctness

```text
Document / DocumentVersion 정상화
→ PDF structure + bbox
→ explicit Plate/Drawing index
→ Reference nodes
→ Reference Resolver
→ Neo4j canonical graph
→ Case 6 regression
```

P0가 완료되지 않으면 VLM/LLM 성능 작업을 진행하지 않는다.

## P1 — Object / Evidence

```text
ArchaeologyObject resolver
→ Evidence model
→ RuleEngine consistency
→ PageAligner 안정화
→ Candidate persistence
```

## P2 — AI interpretation

```text
VLM Observer
→ contextual LLM
→ Evidence aggregation
```

## P3 — Expert review UX

```text
split view
→ source bbox highlight
→ related plate/drawing
→ approve/reject/modify/defer
→ audit report
```

---

# 18. 구현 에이전트가 절대 먼저 하면 안 되는 일

다음은 P0 전에 최적화하지 않는다.

- VLM 모델 교체/벤치마크
- prompt 튜닝
- vector search 고도화
- filename fuzzy matching 개선
- 자동 accepted 기능
- 고급 UI

Case 6과 같은 identity 오류가 존재하는 상태에서는 이 작업들이 성능을 올려도 시스템 신뢰성을 높이지 못한다.

---

# 19. MVP 최종 시험 절차

최종 MVP 시험은 다음 순서로 진행한다.

## Stage 1. Golden Dataset Lock

고고학자가 직접 확인한 canonical mapping fixture를 freeze한다.

각 fixture에 source SHA256을 저장한다.

## Stage 2. Deterministic Identity Test

LLM/VLM 호출 없이 다음만 검증한다.

```text
본문 reference
→ explicit plate/drawing identifier
→ correct canonical target
```

**Stage 2가 실패하면 이후 AI 시험을 수행하더라도 MVP 실패다.**

## Stage 3. Object Graph Test

본문/도판/도면의 object 연결을 검증한다.

## Stage 4. Evidence Trace Test

각 관계와 후보가 source page/bbox/hash로 추적 가능한지 검증한다.

## Stage 5. Rule Consistency Test

전문가가 만든 known error/known correct fixture로 precision/recall을 측정한다.

## Stage 6. VLM Observation Test

identity를 이미 고정한 상태에서 VLM의 관찰 정확도만 측정한다.

## Stage 7. Human Review Test

pending_review 후보를 전문가가 accept/reject/modify/defer 할 수 있고 audit trail이 남는지 확인한다.

## Stage 8. End-to-End Re-run

동일 source/hash/version으로 재실행하여 canonical mapping과 candidate evidence path가 재현되는지 확인한다.

---

# 20. Final MVP Pass/Fail Rule

다음 중 하나라도 발생하면 **MVP FAIL**이다.

1. Links filename 숫자를 도판/도면 번호로 해석함
2. physical PDF page를 publication plate number로 해석함
3. Case 6에서 unrelated `_45.JPG`를 도판 45로 선택함
4. VLM/LLM이 canonical identity를 변경함
5. evidence source가 없는 Candidate가 생성됨
6. pending_review를 거치지 않고 자동 accepted 됨
7. 동일 입력에서 canonical resolution이 비결정적으로 바뀜
8. 명시적 reference가 없는데 filename 추론으로 확정 관계를 만듦

다음 조건을 모두 만족하면 MVP PASS다.

1. 고고학자 Golden Dataset의 canonical identity test 통과
2. Case 6 regression test 통과
3. 모든 Candidate evidence traceability 보장
4. 하나 이상의 실제 full canonical path 완성
5. 전문가 승인 workflow와 audit trail 동작
6. 불확실 사례가 안전하게 unresolved/manual_review로 남음

---

# 21. 설계 결론

이 프로젝트의 핵심 개선은 새 AI 모델을 붙이는 것이 아니라 다음 여섯 컴포넌트를 하나의 데이터 계약으로 묶는 것이다.

```text
PDFParser
   ↓
PageAligner
   ↓
RuleEngine
   ↓
Reference Resolver (AssetMatcher)
   ↓
VLM / LLM
   ↓
Neo4j Document–Object–Evidence Graph
```

보다 정확하게는 흐름의 중심은 Neo4j이며 각 컴포넌트가 독립된 정답을 만드는 것이 아니라 canonical graph를 읽고 쓰는 구조다.

```text
Document Structure
       ↓
Canonical Identity
       ↓
ArchaeologyObject
       ↓
Evidence
       ↓
Rule / LLM / VLM interpretation
       ↓
CorrectionCandidate
       ↓
Expert ReviewDecision
```

고고학자 피드백에서 드러난 Case 6 오류는 이 설계의 핵심 원칙을 검증하는 대표 실패 사례다.

**MVP의 가장 중요한 성공 기준은 AI가 많이 맞히는 것이 아니라, 틀린 대상을 자신 있게 연결하지 않는 것이다.**
