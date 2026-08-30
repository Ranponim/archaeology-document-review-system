# Adobe-free 실제 panel → JPG acceptance 결과

측정 대상은 최신 HEAD `d6b1661506361ce11cdcdccce9330759cd979c6e`의 실제
`D:/Coding/archaeology-document-review-system/src`입니다. `/src`는 read-only로
사용했습니다.

## Corpus

- plate PDF: 3개
- JPG candidate: 1,032개; decode 성공 1,032개, 실패 0개
- parser가 찾은 전체 panel: 2,804개
- safely segmented panel: 2,750개
- insufficient panel: 54개
- matcher: `VisualAssetMatcher`
- minimum score: `0.97`
- minimum margin: `0.03`

2,750개는 세 plate PDF의 segmented panel 합계입니다: 각각 916, 916, 918개입니다.

## 결과

| 항목 | 수치 |
|---|---:|
| local high-confidence match (global gate 전) | 75 |
| collision으로 fail-closed 된 panel | 52 |
| collision source JPG | 12 |
| 최종 `DERIVED_VERIFIED` | 23 |
| segmented 중 verified | 23/2,750 = 0.84% |
| 전체 panel 중 verified | 23/2,804 = 0.82% |
| segmented unresolved | 2,727/2,750 = 99.16% |
| 전체 unresolved | 2,781/2,804 = 99.18% |

## Failure taxonomy

| local 결과 | 건수 |
|---|---:|
| below minimum score | 2,565 |
| ambiguous margin | 110 |
| local match | 75 |
| insufficient bbox | 54 |

최종 상태는 `DERIVED_VERIFIED` 23, `UNRESOLVED_COLLISION` 52,
`UNRESOLVED` 2,729입니다. collision gate는 동일 JPG를 여러 panel이 선택한
경우 모두 제거했으며, collision source를 verified로 승격하지 않았습니다.

## PDF별 결과

| PDF | 전체 | segmented | local match | collision | 최종 verified |
|---|---:|---:|---:|---:|---:|
| 11.19-2차 도판 PDF | 934 | 916 | 18 | 18 | 0 |
| 11.21-3차 도판 PDF | 934 | 916 | 18 | 18 | 0 |
| 11.8-1차 도판 PDF | 936 | 918 | 39 | 16 | 23 |

세 PDF 결과를 하나의 corpus로 합산했기 때문에, 동일 JPG를 서로 다른 PDF의
panel이 선택한 경우에도 전부 collision으로 처리했습니다.

## Safety

- filename-only promotion: 0
- path-only promotion: 0
- caption-only promotion: 0
- threshold bypass: 0
- collision promotion: 0
- source root mutation: false
- `safety_pass`: true

matcher 내부의 fingerprint/page lookup만 acceptance runner에서 cache/vectorize했고,
production threshold, score, margin, provenance policy는 변경하지 않았습니다.
전체 panel별 score, runner-up score, margin, local failure reason, final status,
source path는 [결과 JSON](local_adobe_free_panel_acceptance_d6b1661.json)에
기록했습니다. 기존 code-level TDD는 별도로 `55 passed`였고, 이번 결과는 그와
구분되는 실제 corpus 성능 측정입니다.
