# 2) 그래프 / 검수 로직 리뷰 — Neo4j 중심 검수와 후보 생성 품질 코드리뷰

**Review date:** 2026-08-17  
**Repository:** `Ranponim/archaeology-document-review-system`  
**Reviewed branch:** `windows-docker-foundation`  
**Reviewed HEAD:** `7383a1ffc5afb994729f38cd2ecd9ac8ab91a693`  
**Purpose:** 다음 구현 에이전트가 Neo4j를 실제 검수 엔진으로 유지하면서 후보 폭증·오탐·감사 추적 문제를 수정하기 위한 코드리뷰 결과 문서

---

## 1. 결론

현재 구현은 이전 버전보다 크게 개선되었다. Neo4j는 더 이상 결과를 저장하는 수동 DB가 아니라 다음 동작에 실제 사용된다.

```text
TextBlock / Caption
    ├─ MENTIONS ─────────────→ ArchaeologyObject
    └─ REFERENCES → Reference → RESOLVES_TO → Plate / Drawing
                                             │
                                             └─ DEPICTS → ArchaeologyObject

ArchaeologyObject
    ↓ graph traversal
ObjectEvidenceBundle
    ├─ text_claims
    ├─ references
    ├─ plate_claims
    ├─ drawing_claims
    ├─ visual_observations
    └─ version_claims
        ↓
RuleEngine / LLM / VLM
        ↓
CorrectionCandidate
        ↓ SUPPORTED_BY
Evidence
```

`ProofreadingOrchestrator`는 production 기본에서 graph evidence가 없으면 in-memory 분석으로 조용히 계속하지 않도록 개선되었고, `ObjectEvidenceBundle`을 실제 Neo4j traversal 결과로 생성한다. 이 방향은 원래 설계와 맞다.

하지만 **현재 후보 생성 품질은 MVP 수준이라고 보기 어렵다.** 첨부 화면에서 한 프로젝트에 `2,472건`의 후보가 생성되고, `토광묘 → 수혈`, `유구 → 수혈`, `함정 → 함정유구` 같은 후보가 대량 발생하는 현상은 단순 UI 문제가 아니다. `ArchaeologyObject → Evidence → RuleEngine`의 의미 경계가 너무 넓기 때문에 생기는 구조적 오탐이다.

또한 현재 Graph ID와 Evidence bundle query가 project/run scope를 충분히 갖지 않아 **다른 프로젝트·다른 검수 실행·다른 revision의 Evidence가 섞일 위험**이 있다.

### 최종 판정

- Neo4j를 실제 동작에 사용한다: **PASS**
- Graph가 검수 입력의 authority다: **부분 PASS**
- Object 단위 evidence가 의미적으로 정확하다: **FAIL**
- 동일 프로젝트의 특정 검수 실행으로 evidence가 격리된다: **FAIL**
- 후보 수와 confidence가 전문가 검수에 사용할 수준으로 보정되어 있다: **FAIL**
- Candidate/Decision audit trail이 반복 실행에서도 불변성을 가진다: **FAIL 가능성이 높음**

따라서 다음 구현의 핵심은 **Graph를 줄이는 것이 아니라 Graph의 scope와 evidence granularity를 더 정확하게 만드는 것**이다.

---

# 2. 잘 구현된 부분

## 2.1 Production graph-first 경로

`backend/app/services/proofreading_orchestrator.py`는 `CanonicalRepository.get_object_evidence_bundle()`을 사용한다.

production에서 `allow_degraded_mode=False`일 때:

```text
Neo4j repository 없음
    → GRAPH_EVIDENCE_UNAVAILABLE
    → run failed

ObjectEvidenceBundle 없음
    → object unresolved/manual-review
    → semantic consistency check skip
```

으로 처리한다.

이것은 반드시 유지해야 한다. 다음 에이전트가 성능이나 테스트 편의를 위해 다시 `in-memory fallback`을 production 기본값으로 돌리면 안 된다.

## 2.2 Canonical reference identity

`Reference → RESOLVES_TO → Plate/Drawing` 구조와 Case 6 방어는 유지되고 있다.

도판 번호는 Links 파일명 숫자가 아니라 publication identifier 기반이어야 하며, 이 invariant는 앞으로도 절대 변경하면 안 된다.

## 2.3 선택한 도판/도면 버전의 Graph-first index 재구성

`backend/app/jobs/run_inputs.py`는 선택된 `plate_version_id` / `drawing_version_id`에 대해 먼저 Neo4j의 `HAS_PLATE` / `HAS_DRAWING` 관계에서 index를 복원하고, 없을 때만 저장 PDF를 다시 parse한다.

선택된 version인데 canonical index가 비어 있으면 실패하도록 되어 있다. 이 방향도 유지해야 한다.

## 2.4 Candidate → Evidence → Page/Version audit path

`ReviewRepository.save_candidates()`는 다음 관계를 저장한다.

```text
Project -[:HAS_CANDIDATE]-> CorrectionCandidate
CorrectionCandidate -[:ABOUT]-> ArchaeologyObject
CorrectionCandidate -[:SUPPORTED_BY]-> Evidence
Evidence -[:EXTRACTED_FROM]-> Page
Evidence -[:FROM_VERSION]-> DocumentVersion
AnalysisRun -[:PRODUCED]-> CorrectionCandidate
```

감사 추적 구조 자체는 적절하다. 문제는 ID scope와 Evidence 내용의 정확성이다.

---

# 3. P0 — ArchaeologyObject ID가 Project scope를 포함하지 않는다

파일:

- `backend/app/services/object_resolver.py`

현재:

```python
def generate_object_id(site: str, canonical_name: str) -> str:
    key = f"{site}:{canonical_name}".strip(":")
```

`resolve_mentions()`는 `project_id`를 인자로 받지만 object ID 생성에는 사용하지 않는다.

따라서 서로 다른 프로젝트에서 동일한:

```text
1지점 청동기시대 6호 석관묘
```

가 나오면 같은 `obj_xxx`가 생성될 수 있다.

Neo4j에서는 `MERGE (obj:ArchaeologyObject {id:o.id})`이므로 두 프로젝트의 객체가 하나의 노드로 합쳐질 수 있다.

그 결과:

```text
Project A TextBlock ─MENTIONS→ obj_123
Project B TextBlock ─MENTIONS→ obj_123

get_object_evidence_bundle(obj_123)
       ↓
A와 B Evidence 혼합 가능
```

이 된다.

### 수정 원칙

Object identity는 **프로젝트 안에서는 revision을 넘어 동일 객체로 유지**되어야 하지만 프로젝트 밖에서는 절대로 공유되면 안 된다.

권장:

```python
object_id = hash(project_id, site, canonical_name)
```

또는:

```text
(Project)-[:HAS_OBJECT]->(ArchaeologyObject)
```

를 강제하고 모든 object query에 project scope를 포함한다.

### Acceptance Gate

서로 다른 Project A/B에 동일 canonical_name 객체를 넣었을 때:

```text
A object id != B object id
```

이어야 한다.

---

# 4. P0 — `get_object_evidence_bundle()`이 AnalysisRun을 실제 query filter로 사용하지 않는다

파일:

- `backend/app/graph/canonical_repository.py`

현재 signature:

```python
get_object_evidence_bundle(object_id, analysis_run_id=run_id)
```

이지만 `analysis_run_id`는 대체로 새 `EvidenceData.analysis_run_id`에 값을 넣는 데 사용된다.

핵심 Cypher는:

```cypher
MATCH (source)-[:MENTIONS]->(obj:ArchaeologyObject {id:$object_id})
OPTIONAL MATCH (page:Page)-[:HAS_BLOCK|HAS_CAPTION]->(source)
OPTIONAL MATCH (version:DocumentVersion)-[:HAS_PAGE]->(page)
```

처럼 object에서 시작하며 **현재 AnalysisRun이 선택한 DocumentVersion에 제한되지 않는다.**

따라서 하나의 ArchaeologyObject가 여러 revision에 걸쳐 존재하면 과거/현재/future version Evidence가 한 bundle 안에 함께 들어갈 수 있다.

Input Review에서 제안한 `ReviewRound`가 도입되면 더욱 명확하게 다음으로 제한해야 한다.

```text
AnalysisRun
  ↓ ANALYZES / USES_PLATE / USES_DRAWING
ReviewRound 또는 선택된 DocumentVersion set
  ↓
Page / TextBlock / Plate / Drawing
  ↓
ArchaeologyObject
```

### 권장 interface

```python
def get_object_evidence_bundle(
    project_id: str,
    review_round_id: str,
    analysis_run_id: str,
    object_id: str,
) -> ObjectEvidenceBundle:
    ...
```

### Kill-switch Test

동일 Object에 Round 1과 Round 2에서 서로 다른 치수를 저장한다.

Round 1 분석을 실행할 때 Round 2 Evidence를 query에서 제거/추가해도 Round 1 결과가 바뀌면 안 된다.

---

# 5. P0 — 현재 `feature_or_artifact_id` 후보 폭증의 핵심 원인

파일:

- `backend/app/services/rule_engine.py`

현재 `extract_types_from_evidence()`는 Evidence의 `value` 전체 문자열과 `rationale`을 대상으로 `ARCHAEOLOGICAL_TYPES` 모든 항목을 substring 검색한다.

개념적으로:

```python
for ftype in ARCHAEOLOGICAL_TYPES:
    if ftype in txt:
        types.append(ftype)
```

이다.

그런데 타입 목록에는 다음처럼 부모/자식 문자열이 함께 있다.

```text
수혈유구
수혈
유구

함정유구
함정
유구
```

따라서 원문에 단 하나의 `수혈유구`가 있어도 현재 방식은 동시에:

```text
수혈유구
수혈
유구
```

세 타입을 검출할 수 있다.

그 뒤 object.type과 모든 검출 타입을 비교해 `!=`이면 candidate를 만들기 때문에 정상 문장에서도:

```text
수혈유구 → 수혈
수혈유구 → 유구
```

같은 가짜 충돌이 생성된다.

첨부 화면의:

```text
토광묘 → 수혈
유구 → 수혈
함정 → 함정유구
```

같은 후보 패턴은 이 코드 구조와 매우 강하게 일치한다.

### 더 큰 문제

Object Evidence는 `source_block_ids` 기준으로 **전체 TextBlock**을 사용한다.

한 문단이:

```text
6호 토광묘를 조사하였으며 인접한 2호 수혈유구는 ...
```

처럼 여러 ArchaeologyObject를 언급하면 같은 block 전체 문자열이 여러 object의 `text_claim` Evidence가 된다.

그러면 6호 토광묘 object의 RuleEngine도 `수혈유구`를 자기 타입 claim으로 잘못 읽는다.

즉 현재 문제는:

```text
Object mention span
```

이 아니라:

```text
Object가 한 번 등장한 전체 block
```

을 사실 단위로 사용하는 데 있다.

### 수정 원칙

1. **Longest-match first** tokenization을 사용한다.
2. 이미 `수혈유구`가 매치된 span 안에서 `수혈`, `유구`를 다시 추출하지 않는다.
3. ObjectResolver의 `ExtractedMention.span`을 버리지 않는다.
4. Evidence를 `전체 block`이 아니라 **mention span / sentence / clause** 단위로 만든다.
5. 한 block에 여러 Object가 있으면 각 Object에 자기 span 주변 claim만 연결한다.
6. `Evidence.rationale`은 사실 추출 source로 절대 다시 읽지 않는다.

### Acceptance Gate

입력:

```text
1지점 청동기시대 6호 수혈유구를 조사하였다.
```

정답:

```text
type = 수혈유구
```

만 추출되어야 한다.

`수혈`, `유구`가 별도 type claim으로 생성되면 FAIL.

또한:

```text
6호 토광묘 ... 2호 수혈유구 ...
```

한 block에서 두 객체를 인식해도 6호 토광묘의 evidence bundle에 `2호 수혈유구`의 type claim이 들어가면 FAIL.

---

# 6. P0 — RuleEngine이 rationale을 다시 사실로 해석한다

현재 다음 함수들은 `ev.value`뿐 아니라 `ev.rationale`도 다시 scan한다.

- `extract_types_from_evidence()`
- `extract_periods_from_evidence()`
- `extract_orientations_from_evidence()`
- `extract_references_from_evidence()`

하지만 `rationale`은 이미 Rule/Parser/Graph가 만든 설명 문자열이다.

```text
원본 Evidence
   ↓
시스템 rationale 생성
   ↓
RuleEngine이 rationale를 다시 원본 사실처럼 파싱
```

하면 시스템이 자기 설명을 자기 근거로 재사용하는 순환이 생긴다.

### 수정

사실 추출 대상으로 허용할 field를 명시한다.

```text
Evidence.value
source text span
structured attributes
```

만 사용하고 `rationale`은 설명/감사 전용으로 둔다.

---

# 7. P0 — Candidate ID가 AnalysisRun/Project scope를 포함하지 않는다

예:

```text
cand_type_mismatch_{object_id}_{index}
cand_period_mismatch_{object_id}_{index}
```

`ReviewRepository.save_candidates()`는:

```cypher
MERGE (cand:CorrectionCandidate {id:c.candidate_id})
```

를 사용한다.

따라서 같은 object에서 동일 순서로 후보가 생성되는 재실행은 기존 Candidate node를 재사용할 수 있다.

그러면:

- 이전 AnalysisRun의 Candidate에 새 Evidence가 붙음
- 여러 Project가 같은 Candidate를 공유할 위험
- 이전 ReviewDecision이 새 실행의 후보에 남음
- audit history의 의미가 깨짐

### 수정 원칙

Candidate는 실행 시점의 immutable finding이다.

권장:

```text
candidate_id = UUID
```

또는 deterministic key를 쓰더라도:

```text
{project_id}:{review_round_id}:{analysis_run_id}:{rule}:{object_id}:{source_evidence_ids}
```

을 포함해야 한다.

`MERGE` 재사용을 의도한다면 candidate fingerprint와 candidate instance를 분리한다.

```text
FindingFingerprint
CorrectionCandidate(instance per run)
```

### Acceptance Gate

같은 input으로 Run A와 Run B를 두 번 실행하면:

```text
Candidate A.id != Candidate B.id
```

이어야 하며 Run A의 ReviewDecision이 Run B에 보이면 FAIL.

---

# 8. P0 — Reference Evidence ID가 occurrence를 잃는다

Graph bundle의 reference evidence ID는 개념적으로:

```text
ev_ref_{object_id}_{ref_type}_{number}
```

형태다.

동일 Object가 본문 여러 페이지에서 `도판 45`를 반복 참조하면 서로 다른 reference occurrence가 하나의 Evidence ID로 합쳐질 수 있다.

이것은 provenance 손실이다.

### 수정

Reference Evidence ID에 최소 다음 중 하나를 포함한다.

```text
Reference node id
source block/caption id
page id
DocumentVersion id
```

권장:

```text
ev_ref_{reference_node_id}_{object_id}
```

---

# 9. P0 — `DEPICTS`는 유용하지만 현재 object 연결 근거가 너무 암묵적이다

`compute_depicts_links()`는 Plate/Drawing title/caption 문자열과 ArchaeologyObject의 canonical/weak identifier substring을 비교한다.

숫자 하나만으로 연결하지 않는 방어는 좋다.

그러나 weak identifier가 유일하다는 이유만으로:

```text
6호석관묘
```

같은 텍스트를 바로 `DEPICTS` 확정 edge로 만들 수 있다.

Graph에서 `DEPICTS`는 이후 visual evidence retrieval의 핵심 관계이므로 단순 convenience relation이 아니다.

### 권장

관계 자체에 provenance를 기록한다.

```text
(asset)-[:DEPICTS {
  method: 'explicit_caption_object_match',
  confidence: 1.0,
  source_version_id: ...,
  analysis_run_id: ...
}]->(obj)
```

weak match는 `DEPICTS_CANDIDATE` 또는 `semantic_review`로 두고 VLM/Rule 입력의 authoritative edge로 사용하지 않는 것이 안전하다.

가능하면:

```text
TextBlock → Reference → RESOLVES_TO → Plate
TextBlock → MENTIONS → Object
```

이라는 동일 source context를 이용해 Plate/Object 관계를 만들고, title substring은 보조 증거로만 사용한다.

---

# 10. P1 — ObjectEvidenceBundle은 evidence family뿐 아니라 claim field를 구조화해야 한다

현재 bundle은:

```text
text_claims
references
plate_claims
drawing_claims
visual_observations
version_claims
```

으로 나뉘지만 RuleEngine은 다시 문자열에서 period/type/dimension/orientation을 추출한다.

그 결과 같은 문자열을 여러 Rule이 각자 재해석한다.

권장 구조:

```python
ObjectEvidenceBundle(
    object_id=...,
    type_claims=[...],
    period_claims=[...],
    dimension_claims={"길이": [...], "너비": [...]},
    orientation_claims=[...],
    references=[...],
    plate_claims=[...],
    drawing_claims=[...],
    visual_observations=[...],
)
```

각 claim은 반드시:

```text
source node id
DocumentVersion
Page
bbox/span
method
```

를 가져야 한다.

RuleEngine은 raw text substring mining이 아니라 같은 field의 claim들만 비교해야 한다.

---

# 11. P1 — 모든 heuristic 후보 confidence가 0.95로 보이는 문제

첨부 화면은 `알고리즘 신뢰도 95%`를 보여준다.

하지만 `feature type mismatch` 후보의 0.95는 통계적으로 calibration된 확률이 아니라 코드에 고정된 heuristic 값이다.

전문가 UI에 `%`로 표시하면 실제 정확도 95%처럼 오해할 수 있다.

### 수정

둘 중 하나를 선택한다.

1. calibration dataset이 생길 때까지 heuristic confidence를 `%`로 표시하지 않는다.
2. `confidence_kind`를 추가한다.

```text
rule_strength = high / medium / low
model_probability = 0.82
expert_validation_rate = ...
```

현재 0.95 고정값은 `rule_strength=high` 정도로 표시하는 것이 더 적절하다.

---

# 12. P1 — Candidate deduplication은 문자열이 아니라 Evidence identity 기반이어야 한다

현재 pairwise evidence 비교 구조는 Evidence가 늘어날수록 후보가 급격히 증가할 수 있다.

특히 동일 semantic conflict가:

```text
text claim A ↔ text claim B
text claim A ↔ plate claim C
text claim B ↔ plate claim C
```

처럼 여러 candidate로 반복될 수 있다.

권장 candidate fingerprint:

```text
rule_name
object_id
normalized_field
normalized_value_set
source_evidence_ids
```

을 사용해 동일 의미 충돌을 한 후보로 묶고, 후보 아래에 supporting evidence를 여러 개 연결한다.

```text
CorrectionCandidate
  ├─ SUPPORTED_BY → Evidence A
  ├─ SUPPORTED_BY → Evidence B
  └─ SUPPORTED_BY → Evidence C
```

이것이 Graph의 장점을 실제 UX에 활용하는 방식이다.

---

# 13. Input Review의 ReviewRound를 Graph 중심에 넣어야 한다

`1) 인풋 리뷰`에서 제안한 구조를 Graph 검수에도 그대로 적용한다.

```text
Project
  ↓ HAS_REVIEW_ROUND
ReviewRound #N
  ├─ BODY_VERSION → DocumentVersion
  ├─ PLATE_VERSION → DocumentVersion
  └─ DRAWING_VERSION → DocumentVersion

AnalysisRun
  ↓ REVIEWS
ReviewRound #N
```

이렇게 해야 `get_object_evidence_bundle()`이 **이번 검수 회차의 자료만** query할 수 있다.

최종적으로 Rule/LLM/VLM 입력은:

```text
AnalysisRun
  → ReviewRound
  → selected DocumentVersions
  → Object-specific Evidence
```

의 traversal 결과여야 한다.

---

# 14. 최우선 구현 순서

## P0-G1 — Graph namespace 수정

- `ArchaeologyObject.id`에 project scope 추가
- `CorrectionCandidate.id`를 run-instance unique로 변경
- Reference Evidence occurrence ID 수정

## P0-G2 — Run/Round scoped evidence query

- `get_object_evidence_bundle()`을 project + ReviewRound + AnalysisRun scoped query로 변경
- 다른 revision/project evidence가 섞이지 않는 integration test 작성

## P0-G3 — Entity-local claim extraction

- `ExtractedMention.span` 보존
- source block 전체가 아닌 mention/sentence/clause evidence 생성
- longest-match archaeological type parser 적용
- rationale 재파싱 금지

## P0-G4 — Candidate explosion 억제

- field별 structured claim 비교
- same-conflict fingerprint dedupe
- hard-coded confidence 0.95 제거/재정의

## P1-G5 — DEPICTS provenance 강화

- relation에 method/confidence/source 기록
- weak substring match는 authoritative DEPICTS 금지

---

# 15. 반드시 추가할 Real Neo4j Integration Tests

### Test G-01 — Project isolation

Project A/B에 같은 canonical object를 넣는다.

PASS:

```text
A Object != B Object
```

그리고 A bundle에 B page/evidence가 한 건도 없어야 한다.

### Test G-02 — ReviewRound isolation

Round 1과 Round 2에서 같은 Object의 치수를 다르게 만든다.

Round 1 run bundle은 Round 1 자료만 반환해야 한다.

### Test G-03 — Overlapping type token

`수혈유구` 한 단어에서 `수혈`, `유구` 후보가 생성되면 FAIL.

### Test G-04 — Multiple objects in one paragraph

```text
6호 토광묘 ... 2호 수혈유구 ...
```

두 object가 생성되어도 각 object type evidence는 자기 mention span에 한정되어야 한다.

### Test G-05 — Candidate instance isolation

동일 문서를 두 번 분석한다.

두 run의 Candidate ID와 ReviewDecision history가 섞이면 FAIL.

### Test G-06 — Graph dependency kill-switch

`MENTIONS`, `REFERENCES`, `RESOLVES_TO`, `DEPICTS` 중 해당 검사에 필요한 relation을 제거하면 관련 검사 결과가 정상적으로 `unresolved/insufficient_evidence`가 되어야 한다.

숨은 in-memory shortcut으로 동일 결과가 나오면 FAIL.

---

# 16. MVP 완료 조건

다음 조건이 모두 충족되어야 `Graph / 검수 로직`을 MVP PASS로 판정한다.

1. Neo4j는 production analysis의 필수 dependency다.
2. 모든 Object는 Project scope를 가진다.
3. 모든 분석 Evidence는 선택한 ReviewRound/AnalysisRun의 DocumentVersion에 제한된다.
4. 같은 문단의 다른 ArchaeologyObject 사실이 섞이지 않는다.
5. `수혈유구`가 `수혈`/`유구`로 중복 type parsing되지 않는다.
6. rationale을 다시 사실 source로 사용하지 않는다.
7. Candidate instance가 AnalysisRun별 immutable하다.
8. Candidate마다 source-addressable Evidence가 있다.
9. `DEPICTS`가 왜 생성됐는지 relation provenance를 설명할 수 있다.
10. 동일 의미 conflict는 한 Candidate 아래 여러 Evidence로 묶인다.
11. Case 6 canonical identity invariant가 계속 통과한다.
12. Real Neo4j integration test에서 project/run/round isolation이 증명된다.

---

## 최종 요약

현재 Neo4j는 **실제로 사용되고 있으며 방향도 맞다.** 문제는 Graph 사용 여부가 아니라 Graph 안에 넣는 `Object / Evidence / Candidate`의 의미 범위가 아직 너무 넓다는 것이다.

특히 현재 화면의 2,472개 후보와 `토광묘 → 수혈` 같은 결과는 Neo4j를 빼야 한다는 신호가 아니다. 반대로 **Object mention span과 ReviewRound scope를 Graph에 더 정확히 표현해야 한다는 신호**다.

다음 구현 에이전트는 후보 수를 임의 threshold로 줄이거나 UI에서 숨기는 방식으로 해결하면 안 된다. `Project → ReviewRound → DocumentVersion → Page → Object-specific Claim`의 provenance를 정확히 만든 뒤 RuleEngine이 그 구조화된 claim만 비교하도록 수정해야 한다.
