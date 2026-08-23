# Local Adobe-free revalidation report

검증일: 2026-08-24 (Asia/Seoul)  
실행 브랜치: `feature/adobe-free-provenance-20260823`  
구현 커밋: `9f612bc`  
계획: `docs/local_adobe_free_revalidation_plan.md`

## 결론

`/src`의 실제 파일 1,107개를 읽기 전용으로 전수 검사했다. Adobe InDesign/Illustrator, COM, ExtendScript는 사용하지 않았다. 본문 참조 인식은 384/384 페이지(100.0%)로 올라갔고, 도판 패널 분할은 1,933/2,804(68.9%)에서 2,750/2,804(98.1%)로 올라갔다.

반면 AI의 direct/verified 식별은 1/56(1.8%)에 머물렀고, JPG 연결은 보수적 matcher 기준 49/2,750(1.8%)뿐이다. 따라서 파일이 열리고 렌더된다는 사실을 identity/provenance 성공으로 세지 않았다. 계획의 cross-source 5/7 목표는 달성하지 못했으며 실제 complete는 2/7(28.6%)이다.

모든 수치의 기계 판독본은 [local_adobe_free_revalidation_metrics.json](local_adobe_free_revalidation_metrics.json)에 있다.

## 1. 실제 입력 전수검사

`/src`는 원래 workspace의 `src`를 가리키는 junction으로 연결하고 변경하지 않았다. 파일 수와 SHA-256을 직접 계산했다.

| 항목 | 실제 결과 |
|---|---:|
| 파일 | 1,107 |
| 총 바이트 | 24,836,460,954 |
| JPG / AI / PDF | 1,032 / 56 / 12 |
| INDD / HWP / ZIP / TXT | 1 / 4 / 1 / 1 |
| SHA-256 중복 파일 | 0 |
| basename 충돌 그룹 | 0 |
| 기존 1,107개 inventory와 일치 | 예 |

실행 환경은 Python 3.13.3, PyMuPDF 1.28.2, Pillow 11.2.1, pypdf 6.5.0, neo4j driver 5.28.4이다.

## 2. RED → 수정 → 재측정

실제 자료에서 발견한 실패를 최소 RED 테스트로 고정한 뒤 수정하고 같은 `/src`를 다시 측정했다.

- 본문 RED: 실제 본문에 있는 `삽도`와 `사진` 별칭이 parser에서 누락됨을 각각 재현. `삽도`는 drawing, `사진`은 plate로 분류하도록 수정했다.
- 도판 RED: 배지가 이미지에 래스터화되어 text bbox가 없는 실제 형태를 재현. 페이지의 기대 패널 수와 image rect 수가 정확히 일치하는 경우에만 reading order로 연결하도록 수정했다.
- 도판 RED: 실제 3차 도판 PDF 59페이지(도판 57)의 continuation caption 패널이 누락되는 것을 재현. 모든 text block의 caption marker를 기대 패널 집합에 포함하도록 수정했다.

수정 파일은 `backend/app/services/pdf_parser.py`, `backend/app/services/plate_parser.py`와 대응 테스트 두 파일이며 구현 커밋은 `9f612bc`이다. 패널 수와 image rect 수가 일치하지 않는 페이지에는 이 heuristic을 적용하지 않아 안전하게 unresolved로 남겼다.

## 3. 본문 본문/참조 성공률

전체 실제 본문 참조는 1차 31건, 2차 250건, 3차 814건의 direct citation occurrence이며, 범위 확장 후 31/320/941건, 합계 1,095/1,292건이다.

| 측정 | before | after |
|---|---:|---:|
| 계획의 historical page baseline | 182/384 (47.4%) | - |
| 기존 parser page coverage | 370/384 (96.4%) | 384/384 (100.0%) |
| citation occurrence | 1,054/1,095 (96.3%) | 1,095/1,095 (100.0%) |
| expanded occurrence | 1,251/1,292 (96.8%) | 1,292/1,292 (100.0%) |
| parser pattern false positive | 0 | 0 |

기존 parser의 누락 페이지는 2차 `[24, 25, 32, 37]`, 3차 `[24, 39, 40, 47, 52]`, 1차 `[19, 20, 27, 28, 32]`였다. 수정 후 누락 페이지는 없다. 라벨별 실제 body citation 수는 `도면 699`, `도판 347`, `원색도판 8`, `삽도 37`, `사진 4`이다.

`도판 1968`은 실제 2차 본문 25페이지에서 확인되지만 도판 PDF의 canonical plate 1968은 존재하지 않는다. parser pattern 자체의 false positive는 0건이지만, semantic 기준으로는 이 numeric/non-canonical citation 1건을 유효한 도판 identity로 세지 않고 명시적으로 재분류했다.

## 4. 도판 PDF 패널 분할

세 판본의 실제 도판 PDF를 모두 읽었다. 패널 총수는 2차 934, 3차 934, 1차 936으로 합계 2,804이다.

| 측정 | before | after |
|---|---:|---:|
| segmented | 1,933/2,804 (68.9%) | 2,750/2,804 (98.1%) |
| insufficient | 871 | 54 |
| 권장 85% 이상 | 미달 | 달성 |

기존 871개는 taxonomy 합계가 정확히 871이다: `image_candidate_zero 852`, `image_candidate_multiple 19`, `badge_missing 0`, `non_image_or_other 0`, `unknown 0`. 수정 후 남은 54개도 전부 분류했다: `image_candidate_zero 54`, 나머지 0.

남은 54개는 세 판본에 같은 형태로 반복된다. 대표 실제 사례는 도판 61 panel 4, 도판 105 panels 1–3, 도판 132 panel 5, 도판 163 panels 3–4, 도판 164 panel 5–6, 도판 165 panel 3–6, 도판 166 panel 3–4, 도판 168 panel 5–7이다. 이 페이지들은 composite/object image rect가 추가로 존재하거나 caption의 번호가 이미지 내부에만 있어 image 수와 기대 패널 수가 일치하지 않는다. 그런 경우 reading-order 추정으로 번호를 만들지 않고 unresolved로 유지했다.

## 5. AI 56개 분할

AI 56개는 모두 실제로 열리고 PDF-compatible content로 렌더됐다. 그러나 식별 근거는 별개다.

| 분류 | 수 | 비율 |
|---|---:|---:|
| readable/open | 56/56 | 100.0% |
| renderable | 56/56 | 100.0% |
| PDF-compatible | 56/56 | 100.0% |
| internal semantic identity | 1/56 | 1.8% |
| resolved_any | 35/56 | 62.5% |
| direct 또는 derived_verified | 1/56 | 1.8% |
| heuristic-only(filename_identifier) | 34/56 | 60.7% |
| unresolved | 21/56 | 37.5% |

첫 21개 실제 파일은 `【도면  】`처럼 번호가 비어 있고 내부 PDF identifier도 없어 unresolved다. 파일명 후보 35개는 후보로만 세었으며 filename-only를 direct/verified로 승격하지 않았다.

## 6. 패널 → JPG matcher

실제 JPG 1,032개를 후보로 사용하고 `VisualAssetMatcher`의 기존 보수 기준(최고 score ≥ 0.97, 2위와 margin ≥ 0.03)을 그대로 적용했다. 2,750 segmented panel 중 결과는 unique high-score 49, ambiguous 55, low-score 2,646이다. candidate 처리 오류는 0건이다.

따라서 JPG 연결 성공률은 segmented panel 기준 49/2,750(1.8%), 전체 panel 기준 49/2,804(1.7%)다. high-score 결과가 곧 사람이 의미적으로 검수한 정답이라는 뜻은 아니다. 일부 페이지에서는 서로 다른 panel이 동일 후보에 높은 score를 보이는 collision이 있어, 이 측정 결과를 graph에 자동 확정하지 않았다.

성공 chain의 실제 예시는 다음과 같다.

1. 3차 도판 1 panel 1 → unique JPG, score 0.992865, margin 0.077420.
2. 3차 도판 2 panel 1 → unique JPG, score 0.988151, margin 0.047725.
3. 2차 도판 11 panel 1 → `4지점 그리드 전경.JPG`, score 0.975199, second 0.925816, margin 0.049383.
4. 2차 도판 57 panel 5 → `4-3. 주공 조사 중 및 토층.JPG`, score 0.972254.

이 목록은 동일 corpus의 실제 source SHA와 matcher evidence를 갖춘 측정 사례다. 다만 아래 ReferenceCorpus graph build에서는 matcher를 fail-closed로 주입해 panel `DERIVED_FROM` edge를 0개로 만들었으므로, 위 결과를 graph에 fake edge로 기록하지 않았다.

## 7. 교차 source 7개 표본

완전한 chain은 body reference/plate 또는 drawing identity/source SHA/panel segmentation/JPG evidence의 모든 hop이 direct 또는 derived_verified이고, ambiguity와 heuristic-only가 없을 때만 세었다.

| 표본 | 결과 | 실제 실패 이유 |
|---|---|---|
| plate 1 | complete | direct plate identifier, panel 1 segmented, JPG score 0.992865/margin 0.077420 |
| plate 2 | complete | direct plate identifier, panel 1 segmented, JPG score 0.988151/margin 0.047725 |
| plate 3 | unresolved | panel 1 best score 0.953910 < 0.97 |
| plate 4 | unresolved | panel 1 best score 0.927872 < 0.97 |
| literal `도판 1968` | false positive 재분류 | 본문 25페이지 numeric citation이나 canonical plate 없음 |
| drawing 1 | unresolved | 실제 AI의 filename_identifier heuristic-only |
| drawing 2 | unresolved | 실제 AI의 filename_identifier heuristic-only |

결과는 2/7 = 28.6%로 계획의 최소 목표 5/7(71.4%)와 권장 7/7 모두 미달이다. 이는 실패를 숨기지 않은 실제 수치다.

## 8. Adobe-free ReferenceCorpus/Neo4j 검증

새 test Neo4j에 실제 source asset 1,089개(plate PDF 1, JPG 1,032, AI 56)를 넣고 Adobe-free mode로 ReferenceCorpus를 build했다. 3차 도판 PDF 하나를 corpus의 plate PDF로 사용했으며, parser가 만든 plate 182개/panel 934개와 drawing 56개 AI resolver 결과를 사용했다.

- build status: `READY`
- visual `DERIVED_FROM`: 209개(plate 182 + direct drawing 1 + heuristic drawing 26)
- panel `DERIVED_FROM`: 0개
- evidence: direct 183, derived_verified 0, heuristic 26, unresolved panel 934
- conflicted drawing numbers: 1, 3, 4, 5
- unresolved drawing source IDs: 29개

panel matcher를 graph build에 연결하지 않은 것은 의도적인 fail-closed 검증이다. 실제 matcher 측정 결과를 근거 없이 graph edge로 승격하지 않았다. build 결과를 query로 확인한 뒤 audit corpus/node는 test DB에서 삭제했고, integration test 실행 시 오염이 남지 않도록 확인했다.

## 9. 테스트 결과와 남은 제한

검증 결과:

- `python -m compileall -q app`: passed. 기존 `json_utils.py`의 invalid escape warning은 있었지만 compile exit code는 0이다.
- focused: `29 passed in 4.91s`.
- Neo4j integration: `22 passed in 3.38s`.
- Linux Docker full backend: `668 passed, 61 skipped, 9 failed`.

full backend는 green으로 주장할 수 없다. 실패는 변경 파일과 무관한 기존/환경 문제로 분류했다: Adobe unavailable contract 1건, Docker image의 `/tools` 미포함 1건, legacy AI endpoint가 404 대신 405를 반환하는 2건, production orchestrator mock signature 3건, pytest async plugin 미설치 2건. Windows host의 전체 collection도 `FileStore`가 `os.O_DIRECTORY`/`os.O_NOFOLLOW`를 요구해 24 import error가 발생했다. 따라서 full backend는 실패/NOT GREEN으로 기록한다.

unresolved 또는 재검토 대상은 최소 다음과 같다.

1. 도판 61 panel 4: image rect 수가 기대 패널 수보다 많음.
2. 도판 105 panels 1–3: composite image rect 때문에 안전한 1:1 매핑 불가.
3. 도판 132 panel 5: object group 번호를 panel 번호로 추측할 수 없음.
4. 도판 163 panels 3–4: rasterized badge와 composite rect 충돌.
5. 도판 164 panels 5–6: image candidate association 불충분.
6. 도판 165 panels 3–6: 여러 composite rect로 순서 매핑 불가.
7. 도판 166 panels 3–4: continuation/composite 구조 unresolved.
8. 도판 168 panels 5–7: expected panel과 image rect 불일치.
9. AI `【도면  】1지점 고려시대 1호 석곽묘 평·입단면도 및 출토유물.ai`: 내부/파일명 번호 없음.
10. AI `【도면  】2지점 조선시대 1호 주거지 평·단면도 및 출토유물.ai`: 내부/파일명 번호 없음.
11. AI `【도면  】3지점 조선시대 1호 옹관묘평·단면도 및 출토유물 1.ai`: 내부/파일명 번호 없음.
12. plate 3 panel 1: low-score matcher.
13. plate 4 panel 1: low-score matcher.
14. literal `도판 1968`: numeric false positive/non-canonical citation.
15. drawing 1/2: filename heuristic-only.

다음 구현 권고는 unresolved composite pages에 대한 사람 검수 또는 별도 layout 모델, AI 내부 identifier 복구/명시적 manifest, JPG 후보의 collision 검수와 durable visual hash, 그리고 Windows-compatible FileStore flags 정리다. 현재 수치는 그 작업이 끝났다고 가정하지 않는다.
