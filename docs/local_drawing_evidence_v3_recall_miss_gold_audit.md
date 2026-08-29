# Recall@10 miss 8건 gold audit

## 결론

현재 HEAD `2656d189cec72300c9ef3c1b01a936ce50887a7d`의 known gold 50건 acceptance에서 Recall@10 miss 8건을 실제 `.ai` 원본과 실제 본문 PDF 렌더로 다시 대조했다.

- audited misses: 8건
- 실제 gold가 맞다고 확인: 7건 (`7, 25, 30, 50, 51, 52, 53`)
- 기존 gold가 실제 본문 PDF와 맞지 않아 retrieval TDD에서 제외: 1건 (`36`)
- 기존 gold JSON은 수정하지 않음
- AUTO gate/resolver 정책, weight, Top-N, source/body 파일은 수정하지 않음

따라서 retrieval TDD 대상으로 허용되는 분모는 8건이 아니라 **gold-confirmed 7건**이다. source 50~53은 일반 drawing이 아닌 동일 `삽도 2`의 연도별 panel 유형으로 별도 처리해야 한다.

## 입력과 감사 방법

- HEAD: `2656d189cec72300c9ef3c1b01a936ce50887a7d`
- baseline: `docs/local_drawing_evidence_v3_luna_manual50_acceptance_4d33e6d.json`
- source root: `D:/Coding/archaeology-document-review-system/src` (read-only)
- body PDF SHA-256: `32ec1e2f02e3b088b0b014ca0294823caec8531850d5b68e3ad99d16cfcc8e60`
- parsed body packets: 828
- INDD exists and SHA-256 is `e0a0c268660eea8aea924d9afcd7925212c861a890c97aeb4ee2341d6451d75d`, but this environment has no discoverable Adobe InDesign executable, so INDD direct extraction was unavailable. The verdicts below are based on the actual body PDF and rendered AI originals.

`source_index`는 기존 gold note와 같은 1-based index이며, acceptance JSON의 `rows` 위치는 `source_index - 1`이다. 자세한 source SHA, render path, evidence와 수치는 companion JSON에 기록했다.

## 8건별 audit 및 retrieval 진단

| source | 기존 gold | 실제 대조 결과 | retrieval 분류 | pre rank/score | post rank/score | filter/원인 | TDD |
|---:|---|---|---|---:|---:|---|---|
| 7 | drawing 54 | confirmed; 본문 p120 `도면 54`와 burial plan/section·유물 배치 일치 | generated → hard-filtered | 1 / 15.987288 | 제거됨 | `disjoint_feature_pair`; source의 문맥 라벨 `25호/26호 토광묘`를 gold `2호`와 hard contradiction으로 오인 | ✅ |
| 25 | drawing 12 | confirmed; 본문 p44 `도면 12`와 지도 경계·도로·좌표·범례·축척 일치 | alive rank 11+ | 11 / 2.120370 | 11 / 2.120370 | filter 없음; strong site/grid가 부족하여 lexical·weak filename 신호만으로 11위 | ✅ |
| 30 | drawing 23 | confirmed; 본문 p68 `도면 23`과 1지점 지도·S=1/800·도형 일치 | alive rank 11+ | 15 / 13.945122 | 15 / 13.945122 | filter 없음; exact site-point/lexical은 있으나 경쟁 drawing이 앞섬 | ✅ |
| 36 | drawing 64 | **rejected gold**; AI 원본은 3지점, 본문 도면64는 2지점. 본문에 3지점 유구현황도 없음 | generated → hard-filtered | 53 / 2.128571 | 제거됨 | `disjoint_site_point` (source 3 vs proposed gold 2); 이는 retrieval root cause가 아니라 gold 불일치 증거 | ❌ |
| 50 | illustration 2 | confirmed; 본문 p40 `삽도 2` 1968 top-left panel과 동일 | alive rank 11+ | 134 / 0 | 134 / 0 | filter 없음; AI text facts 0, score tie가 drawing 1~10 뒤로 보냄 | ✅ |
| 51 | illustration 2 | confirmed; 본문 p40 `삽도 2` 1989 top-right panel과 동일 | alive rank 11+ | 134 / 0 | 134 / 0 | 동일 illustration/panel sparse-text tie 문제 | ✅ |
| 52 | illustration 2 | confirmed; 본문 p40 `삽도 2` 2007 bottom-left panel과 동일 | alive rank 11+ | 134 / 0 | 134 / 0 | 동일 illustration/panel sparse-text tie 문제 | ✅ |
| 53 | illustration 2 | confirmed; 본문 p40 `삽도 2` 2012 bottom-right panel과 동일 | alive rank 11+ | 134 / 0 | 134 / 0 | 동일 illustration/panel sparse-text tie 문제 | ✅ |

### source 7: 실제 gold는 맞지만 hard filter가 제거

본문 p120의 캡션은 `【도면 54】 2지점 조선시대 2호 토광묘 평·단면도 및 출토유물`이다. AI 원본은 같은 도면의 burial geometry와 50/51 유물 배치를 보여준다. 다만 AI 내부 텍스트에는 주변 feature인 `25호 토광묘`, `26호 토광묘`가 잡힌다.

현재 진단에서는 gold candidate가 filter 전 1위였고 score도 `15.987288`이지만, body anchor에서 얻은 `토광묘:2`와 source 전체 텍스트에서 얻은 `토광묘:25`, `토광묘:26`의 disjoint pair를 `disjoint_feature_pair`로 처리하여 제거됐다. 이 건은 confirmed retrieval TDD target이다. 수정 시 문맥 feature와 도면 identity를 분리해야 하며, AUTO gate를 바꾸면 안 된다.

### source 25와 30: gold는 맞고 살아 있으나 Top-10 밖

source 25는 본문 p44의 `도면 12`와 지도 자체가 일치하며, source filename도 `도면12`이다. gold는 filter 후 11위(`2.120370`)로 살아 있다.

source 30은 본문 p68의 `도면 23`과 `1지점`, `S=1/800`, 지도 형상이 일치한다. gold는 filter 후 15위(`13.945122`)로 살아 있다. 두 건 모두 hard contradiction이 없어 ranking/TDD 대상이다.

### source 36: retrieval TDD에서 제외해야 하는 gold 오류

source 원본은 제목부터 `3지점-유구현황도`이고 이미지 좌상단도 `3지점`이다. 기존 gold `drawing 64`의 본문 캡션은 `2지점 유구현황도(S=1/500)`이며 렌더에도 `2지점`이 명시된다. 실제 본문 PDF의 site-map 캡션 목록에도 `3지점 유구현황도`가 없다.

따라서 `disjoint_site_point` 제거를 완화하여 drawing 64를 살리는 것은 잘못된 gold에 맞추는 회귀다. 이 건은 known gold에서 재검토되어야 하며, 현재 retrieval 수정의 성공률 분모에 넣지 않는다.

### source 50~53: illustration/panel 별도 유형

네 AI 원본은 각각 1968/1989/2007/2012 항공사진 panel이고, 본문 p40의 `【삽도 2】 조사 지역 일대 연도별 항공사진` 2×2 panel에 정확히 대응한다. 네 건 모두 동일 canonical target `illustration:2`가 맞다.

하지만 AI extraction에는 사실상 `조사대상지역`만 남아 evidence가 0개이고 score가 모두 0이다. 후보가 생성되어도 `drawing 1..10` 등이 tie-break에서 먼저 나오며, full post-filter rank는 134/142다. 이는 일반 drawing의 feature/number retrieval과 다른 sparse visual panel problem이다. TDD는 panel identity/year/visual signature를 retrieval ordering에 추가하는 방향이어야 하며, AUTO promotion 정책을 변경하는 근거로 사용하면 안 된다.

## TDD 허용 범위

다음 7건만 retrieval TDD에 포함한다.

1. source 7: contextual feature labels causing a false hard filter.
2. source 25: confirmed map at rank 11.
3. source 30: confirmed site map at rank 15.
4. source 50~53: four confirmed illustration panels at rank 134, one separate panel test family.

source 36은 현재 gold가 실제 본문과 불일치하므로 제외한다. 이후 테스트/수정은 먼저 이 audit artifact를 기준으로 RED를 만들고, 최소 retrieval 수정 후 GREEN을 측정해야 한다. AUTO precision, AUTO coverage, review rate와 safety counters는 기존 회귀 기준을 그대로 유지한다.

