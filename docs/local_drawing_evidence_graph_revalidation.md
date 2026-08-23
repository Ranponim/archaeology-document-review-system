# Local Drawing Evidence Graph 재검증

이 문서는 `feature/adobe-free-provenance-20260823`를 로컬에서 pull한 뒤 실제 `/src` 1,107개 자산으로 Drawing Evidence Graph를 재검증하기 위한 실행 절차다.

## 목적

기존 실제 결과는 다음과 같다.

| AI identity 지표 | 기존 |
|---|---:|
| PDF-compatible / renderable | 56/56 |
| internal semantic identity | 1/56 (1.8%) |
| filename heuristic candidate 포함 resolved_any | 35/56 (62.5%) |
| direct 또는 verified | 1/56 (1.8%) |
| heuristic-only | 34/56 (60.7%) |
| unresolved | 21/56 (37.5%) |

새 resolver의 목적은 filename-only를 verified로 승격하는 것이 아니라, 본문 `Reference/Caption/주변 TextBlock`과 AI 내부 PDF text/content의 독립 증거가 충분히 일치하는 경우에만 `DERIVED_VERIFIED`를 생성하는 것이다.

## 필수 안전 조건

- `/src`는 읽기 전용이다.
- Adobe InDesign/Illustrator, COM, ExtendScript를 사용하지 않는다.
- filename-only candidate는 `DERIVED_VERIFIED`로 세지 않는다.
- point/grid hard contradiction은 verified 금지다.
- near-tie/1:N conflict는 ambiguous/unresolved로 남긴다.
- 출력 JSON/Markdown은 `/src` 밖에 저장한다.

## 준비

```bash
git switch feature/adobe-free-provenance-20260823
git pull
cd backend
python -m pip install -e . pytest pytest-asyncio
cd ..
```

Windows PowerShell에서도 같은 순서로 실행할 수 있다. `/src`가 junction인 경우 실제 원본을 수정하지 않는지 먼저 확인한다.

## 실행

저장소 루트에서:

```bash
python tools/evaluate_drawing_evidence_graph.py \
  --source-root src \
  --output-json docs/local_drawing_evidence_graph_metrics.json \
  --output-report docs/local_drawing_evidence_graph_report.md \
  --blinded
```

PowerShell:

```powershell
python tools/evaluate_drawing_evidence_graph.py `
  --source-root src `
  --output-json docs/local_drawing_evidence_graph_metrics.json `
  --output-report docs/local_drawing_evidence_graph_report.md `
  --blinded
```

도구는 `본문`이 들어간 PDF 중 파일명 날짜 `M.D`가 가장 최신인 교정본을 본문 context source로 선택한다. 현재 corpus에서는 11.21 교정본이 선택되는 것이 정상이다.

## 시험 1: 35-file blinded silver-label evaluation

filename에 `도면 N`/`삽도 N`이 있는 AI만 대상으로 한다.

1. filename 숫자를 resolver 입력에서 제거한다.
2. AI 내부 text/content + body context만으로 candidate를 생성한다.
3. Top-1/Top-3 candidate를 만든 뒤에만 숨겨둔 filename number와 비교한다.
4. filename은 ground truth가 아니라 silver label이다. 불일치는 자동 오류로 세지 않고 review case로 남긴다.

필수 출력:

- labeled_files
- Top-1 agreement/rate
- Top-3 agreement/rate
- unique verified
- ambiguous
- unresolved
- hidden filename과 content Top-1이 다른 사례

## 시험 2: Full 56 AI resolution

모든 evidence를 허용하고 56개를 corpus-wide 한 번에 resolve한다.

필수 출력:

- direct
- derived_verified
- heuristic_only
- ambiguous
- unresolved
- resolver diagnostics
- source별 최종 상태

### 성공 판단

숫자를 맞추기 위해 threshold를 낮추지 않는다.

1차 성공은 다음 모두를 만족할 때다.

- 기존 direct 1개를 보존한다.
- filename-only verified는 0개다.
- 실제 independent graph evidence로 새 `derived_verified`가 1개 이상 나온다. 단, 0개라면 corpus 자체의 정보 부족이라는 근거를 보고한다.
- known false verified가 검토 표본에서 0개다.
- ambiguous/conflict가 숨겨지지 않는다.

## Neo4j production path 확인

로컬 DB가 준비돼 있다면 ReferenceCorpus build를 한 번 실행하고 다음을 확인한다.

- `ReferenceCorpus`가 READY여도 unresolved count가 diagnostics에 남는다.
- `(OriginalAsset)-[:PROPOSES]->(DrawingCandidate)`가 존재한다.
- candidate에 `SUPPORTED_BY`/`CONTRADICTED_BY` evidence가 보인다.
- heuristic-only candidate에는 canonical `TARGETS`가 없다.
- direct/derived_verified candidate에만 `TARGETS`와 canonical Drawing provenance가 존재한다.
- 동일 corpus를 재실행해도 deterministic ID/MERGE로 candidate/evidence/context node 수가 중복 증가하지 않는다.

## 결과 파일

실행 후 반드시 다음 두 파일을 남긴다.

- `docs/local_drawing_evidence_graph_metrics.json`
- `docs/local_drawing_evidence_graph_report.md`

보고서에서 기존 `1 direct / 34 heuristic-only / 21 unresolved`과 새 결과를 직접 비교하고, derived_verified 사례마다 최소 다음을 적는다.

- AI 파일 상대경로
- 선택된 drawing number
- evidence families
- 핵심 context entity (`point/grid/direction/type/feature/section`)
- score / runner-up / margin
- contradiction 여부
- filename evidence 사용 여부

실패하거나 0건이어도 수치를 그대로 기록한다. 결과를 좋게 보이기 위해 heuristic을 verified로 재분류하지 않는다.
