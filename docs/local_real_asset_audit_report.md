# /src 실제 자산 감사 보고서

감사일: 2026-08-23<br>
범위: src/ 전체 파일과 docs/local_real_asset_audit_instructions.md의 검증 요구사항<br>
원칙: src/는 읽기 전용으로 다뤘고, 파일명만으로 도면·도판의 정체성을 확정하지 않았다. Adobe/COM/ExtendScript는 실행하지 않았다. PDF/AI 검사는 PyMuPDF 1.28.2, 이미지 검사는 Pillow 11.2.1로 원본 바이트를 직접 열고 디코드·렌더링했다.

## 1. Executive Summary

| 지표 | 실제 결과 |
|---|---:|
| /src 전체 파일 수 | **1,107** |
| 본문 PDF 수 / 총 페이지 수 | **3 / 815** |
| /src PDF 전체 열기·첫 페이지 렌더링 | **12/12, 100%** |
| INDD 수 / IDML 수 | **1 / 0** |
| AI 수 | **56** |
| AI 중 PDF-compatible 수 / 비율 | **56/56, 100%** |
| AI 전체 열기·전체 페이지 렌더링 | **56/56, 100%** |
| JPG 원본 디코드 | **1,032/1,032, 100%** |
| 본문에서 직접 확인한 도면 참조 발생 수 / 고유 번호 수 | **736 / 132** |
| 본문에서 직접 확인한 도판 참조 발생 수 / 고유 번호 수 | **359 / 130** |
| 현재 본문 참조 파서의 참조 페이지 회수 | **182/384, 47.4%** |
| 도판 패널 영역 분할 | **1,933/2,804, 68.9%** |
| AI 도면 레코드 추출 | **1/56, 1.8%** |
| 완전한 본문→도판/도면→원본 체인 | **0/7, 0%** |

파일의 물리적 사용성은 높았다. 그러나 현재 구현이 요구하는 구조적 provenance는 확보되지 않았다. 특히 본문에는 도면 1, 도판 1처럼 콜론이 없는 실제 표기가 있고, 현재 PDFParser는 도면:·도판: 형태만 찾기 때문에 1차 본문 참조를 한 건도 회수하지 못했다. INDD에서는 링크 파일명 흔적을 상당수 복구했지만 페이지·그래픽 bounds·linkPath를 연결하는 구조화된 DOM 레코드는 만들 수 없었다.

## 2. /src inventory

### 2.1 확장자별 실제 수량과 용량

| 유형 | 파일 수 | 바이트 |
|---|---:|---:|
| .jpg/.JPG | 1,032 | 9,150,444,888 |
| .ai | 56 | 820,982,636 |
| .pdf | 12 | 2,008,231,627 |
| .hwp | 4 | 137,522,688 |
| .indd | 1 | 355,942,400 |
| .txt | 1 | 1,852 |
| .zip | 1 | 12,363,334,863 |
| 합계 | **1,107** | **24,836,460,954** |

SHA-256은 1,107/1,107개에 대해 계산했고 고유 해시는 1,107개였다. 중복 hash 그룹은 **0**, 동일 basename 충돌 그룹도 **0**이다.

ZIP은 압축 해제하지 않고 중앙 디렉터리만 읽었다. 논산 산노리 보고서 작업.zip은 1,120 entries(파일 1,106, 디렉터리 14), 비압축 합계 12,473,126,091 bytes이며 .ai 56, .jpg 1,032, .indd 1, .pdf 12 등 현재 작업 트리와 같은 확장자 구성을 선언한다. 압축 내부 파일은 별도 검증 성공률에 중복 집계하지 않았다.

### 2.2 검증에 사용한 대표 hash

| 자산 | SHA-256 |
|---|---|
| src/도판(사진들)/논산 산노리 도판 V2.indd | e0a0c268660eea8aea924d9afcd7925212c861a890c97aeb4ee2341d6451d75d |
| src/완성까지 가던 교정본들/11.8-본문-1차 교정/11.8-115집 논산 산노리 산17-1번지 유적-본문-1차 교정.pdf | ac2dcd575f247276d0641bbc2104395e180b4e0148daeda0402b9aff9464eba8 |
| src/완성까지 가던 교정본들/11.19-2차 교정/11.19-115집 논산 산노리 산17-1번지 유적-본문-2차 교정.pdf | 7f6ad24597448a27491e2ed2113ebd381446e6790974348d3980ee48e97d6eb1 |
| src/완성까지 가던 교정본들/11.21-3차 교정/11.21-115집 논산 산노리 산17-1번지 유적-본문-3차 교정.pdf | 32ec1e2f02e3b088b0b014ca0294823caec8531850d5b68e3ad99d16cfcc8e60 |

## 3. INDD result

대상은 src/도판(사진들)/논산 산노리 도판 V2.indd 1개, 355,942,400 bytes이다. 파일 선두는 PDF/OLE가 아닌 InDesign 바이너리 형식으로 확인됐다. IDML은 **0개**이고 /src 안의 AdobeManifestV1 JSON sidecar도 **0개**다.

바이너리에서 관찰된 흔적은 다음과 같다.

- <x:xmpmeta> 1,263회, DocumentID 549회, InDesign 300회.
- ASCII Links 10,873회, .JPG 10,047회, .jpg 871회, .ai 27회.
- file:F:/.../Links/...jpg 형태의 path-like 토큰은 정규식 기준 10,570회(고유 raw token 4,091개)였다. 이는 반복 저장된 문자열 흔적이며 10,570개를 link instance 성공으로 세지 않았다.
- percent-decoding 후 고유 basename은 1,098개였다. 현재 src/도판(사진들)/Links의 1,031개 파일 중 **1,031/1,031(100%)**가 basename으로 발견됐고, 복구된 basename 기준으로는 **1,031/1,098(93.9%)**가 로컬 파일과 일치했다. 나머지 67개는 현재 Links에 없는 이름이었다.
- src/도판(사진들)/지침.txt의 InDesign 패키지 보고서는 **1,101 link found, 0 missing, 0 inaccessible**, RGB 이미지 1,100 item이라고 명시한다. 이 1,101은 링크 인스턴스 선언값이고, 로컬 1,031 파일과의 일대일 identity 검증값으로 사용하지 않았다.

### 3.1 INDD에서 실패한 구조 추출

| 필요한 증거 | 결과 |
|---|---:|
| InDesign page index/label 직접 추출 | **0/1** |
| textFrame text/bounds 직접 추출 | **0/1** |
| graphic bounds 직접 추출 | **0/1** |
| page graphic과 linkPath 연결 | **0/1** |
| AdobeManifestV1 또는 IDML sidecar | **0/1** |

즉, 링크 파일명 흔적과 XMP는 실제로 존재하지만, 페이지 → 그래픽 bounds → linkPath → 로컬 원본 관계를 binary 문자열 검색만으로 안전하게 복원할 수 없었다. 이 때문에 INDD를 판독 성공으로 표시하거나, 파일명·링크 순서로 도판 identity를 추측하지 않았다.

## 4. AI result

56개 .ai를 파일 선두 시그니처와 PyMuPDF 양쪽으로 검사했다.

- PDF-compatible 선두 %PDF-: **56/56, 100%**.
- PyMuPDF open: **56/56, 100%**.
- 모든 AI 페이지의 in-memory raster render: **56/56, 100%**.
- 모든 AI는 PDF text block/vector drawing/image reference를 읽을 수 있었지만, PDF primitive가 Illustrator DOM의 artboard, textFrame, placedItem이라는 뜻은 아니다.
- 파일명에 도면/삽도 번호가 있는 파일은 **35/56**이다. 이것은 후보 생성용 문자열일 뿐 canonical identity 성공으로 세지 않았다.
- AI 본문 내용에서 명시적인 도면 번호가 추출된 파일은 **1/56**뿐이다. 실제 파일은 src/환경 도면/도면14. 2지점 S1E1 북동 토층 cs5.ai이며 도면 14 레코드 1개가 나왔다.

현재 DrawingParser.parse() 실행 결과는 예외 없이 **56/56**이었지만, 실제 semantic drawing record는 **1개**, 빈 결과를 반환한 파일은 **55/56**이었다. 따라서 “호출 성공 100%”와 “도면 추출 성공 1.8%”를 구분해야 한다. 추출된 도면 14도 regions는 0개였다.

## 5. Links / plates result

### 5.1 이미지 원본

src/의 JPG 1,032개를 verify() 후 다시 열어 load()까지 수행했다. 성공 **1,032/1,032(100%)**, 실패 0건이다. 이 중 src/도판(사진들)/Links는 1,031개이고 나머지 1개는 src/환경 도면의 JPG이다. EXIF field가 있는 파일은 1,032/1,032였고, 해상도 조합은 178종이었다. 전체 inventory SHA-256 기준 중복 파일은 없다.

### 5.2 실제 도판 PDF와 PlateParser

대상은 1차·2차·3차 도판 교정 PDF 3개, 각각 186페이지다. 목차만 PDF는 헤더 추출 대상에서 제외했다.

| 도판 PDF | 실제 도판 헤더 | PlateParser records | 패널 수 | segmented | insufficient |
|---|---:|---:|---:|---:|---:|
| 1차 | 182 | 182 | 936 | 647 | 289 |
| 2차 | 182 | 182 | 934 | 644 | 290 |
| 3차 | 182 | 182 | 934 | 642 | 292 |
| 합계 | **546** | **546 (100%)** | **2,804** | **1,933 (68.9%)** | **871 (31.1%)** |

도판 번호/header 레코드 자체는 546/546으로 회수됐지만, 이미지 rect와 패널 badge가 안전하게 하나로 결정되지 않은 패널이 871개였다. 이 871개는 실패 사례로 유지해야 하며 임의 bbox를 생성하면 안 된다.

## 6. Cross-source examples

본문의 직접 추출 토큰과 실제 파일을 연결하는 체인을 다음처럼 시도했다. 본문 reference는 성공으로 세되, 중간 구조가 없으면 complete로 세지 않았다.

| 체인 | 실제 본문 증거 | 다음 단계 | 결과 |
|---|---|---|---|
| 도판 1 | 2차 본문 p.3의 도판 1 | INDD page/bounds/linkPath | 실패 |
| 도판 2 | 2차 본문 p.5의 원색도판 2 | INDD page/bounds/linkPath | 실패 |
| 도판 3 | 2차 본문 p.6의 원색도판 3 | INDD page/bounds/linkPath | 실패 |
| 도판 4 | 2차 본문 p.7의 원색도판 4 | INDD page/bounds/linkPath | 실패 |
| literal 도판 1968 | 2차 본문 p.25의 도판 1968 토큰 | INDD page/bounds/linkPath | 실패 |
| 도면 1 | 2차 본문 p.2의 도면 1 | AI 본문 ID 또는 manifest | 실패 |
| 도면 2 | 2차 본문 p.15의 도면 2 | AI 본문 ID 또는 manifest | 실패 |

따라서 cross-source chain은 도판 **0/5**, 도면 **0/2**, 전체 **0/7(0%)**이다. 도판 체인의 실패 원인은 로컬 링크 파일이 없어서가 아니라 INDD 내부의 페이지·그래픽·linkPath 관계가 없기 때문이다. 도면 체인의 실패 원인은 후보 AI 파일명은 있어도 두 샘플 모두 AI 본문에서 명시적 ID가 나오지 않았기 때문이다.

## 7. AdobeManifestV1 feasibility

현재 backend/app/domain/adobe_manifest.py의 필드 요구와 실제 /src 증거를 대조했다.

| ManifestV1 필드 | INDD 1개 | AI 56개 | 판정 |
|---|---:|---:|---|
| sourceSha256 | 직접 1/1 | 직접 56/56 | inventory hash로 채울 수 있음 |
| sourceAssetId | 불가 1/1 | 불가 56/56 | /src에 upload asset ID 없음 |
| application | extension/package 선언 1/1 | extension-only 56/56 | AI 쪽은 DOM 확인 전 heuristic |
| pages / artboards | page DOM 0/1 | artboard DOM 0/56 | AI의 PDF page 1/56은 derived evidence일 뿐 |
| textFrames | 0/1 | 0/56 | PDF text blocks는 semantic DOM과 다름 |
| graphics / placedItems | 0/1 | 0/56 | PDF vector drawings/image refs는 DOM placed item이 아님 |
| linkPath | page 연결 0/1 | 0/56 | path-like 문자열은 있으나 object association 없음 |
| artifacts | sidecar 0/1 | sidecar 0/56 | source tree에 converter manifest 없음 |

요약하면 sourceSha256만 **57/57 직접 확보**했고, sidecar manifest는 **0/57**이다. INDD DOM 필드 4종은 **1/1 unavailable**, Illustrator DOM 필드 4종은 **56/56 unavailable**이다. AI의 PDF open/render 결과는 fallback evidence로는 유효하지만 AdobeManifestV1을 충족하지 않는다.

## 8. Current implementation mismatch

1. backend/app/services/pdf_parser.py의 현재 정규식은 도면\s*:\s*..., 도판\s*:\s*...처럼 콜론을 요구한다. 실제 본문은 도면 1, 도판 1, 【원색도판 2】를 사용한다.

   | 본문 교정본 | 원문 참조 페이지 | parser 참조 페이지 | 페이지 회수율 |
   |---|---:|---:|---:|
   | 1차, 264p | 22 | 0 | **0/22, 0%** |
   | 2차, 269p | 110 | 46 | **46/110, 41.8%** |
   | 3차, 282p | 252 | 136 | **136/252, 54.0%** |
   | 합계 | **384** | **182** | **182/384, 47.4%** |

   파서가 참조를 만든 885건은 bbox **885/885**, source SHA **885/885**를 갖지만, 이는 추출된 결과의 provenance completeness이고 원문 참조 recall 100%를 뜻하지 않는다. 원문에서 놓친 참조 페이지는 **202/384**다.

2. PlateParser는 도판 header를 100% 회수했지만 panel segmentation은 68.9%다. bbox_status=insufficient인 871개를 성공으로 저장하면 현재 요구사항의 보수적 판정과 어긋난다.

3. DrawingParser는 56개 AI 호출에서 예외가 없지만 55개가 빈 결과다. 예외 없음은 semantic extraction 성공률로 사용할 수 없다.

4. backend/app/services/reference_corpus_service.py는 .indd와 .ai를 converter roles로 보내고 ReferenceCanonicalizer는 AdobeManifestV1의 pages/artboards/graphics/placedItems를 canonical graph authority로 사용한다. 실제 /src에는 그 manifest가 없으므로, 현재 AI PDF fallback이나 파일명만으로 canonical graph를 만들면 provenance 계약을 위반한다.

## 9. Recommended architecture A/B/C

### A. Adobe DOM bridge를 정식 경로로 유지

Windows의 InDesign/Illustrator에서 실제 파일을 열고, 현재 JSX가 요구하는 pages, artboards, textFrames, graphics/placedItems, linkPath를 AdobeManifestV1로 내보낸다. 변환 직전·직후 source SHA-256을 비교하고, 모든 linkPath를 workspace 상대경로와 원본 hash로 검증한다. canonical identity는 manifest의 실제 텍스트/배치에서만 만든다.

### B. Adobe 없는 로컬 audit fallback

현재처럼 PDF-compatible AI와 PDF 도판 교정본의 open/render/primitive 검사는 preview·품질 감사용으로 사용한다. 다만 결과 필드를 derived로 표시하고, artboard, placedItems, INDD page/bounds/linkPath는 unavailable로 남긴다. 이 모드에서는 canonical graph READY를 허용하지 않고 unresolved provenance를 보고한다.

### C. 재현 가능한 sidecar/IDML 전달

Adobe 실행이 어려운 환경에는 원본과 함께 AdobeManifestV1 JSON 또는 IDML과 source asset ID/hash를 전달한다. sidecar의 모든 linkPath는 로컬 Links의 basename뿐 아니라 SHA-256까지 확인하고, 없는 67개 복구 path 이름과 package report의 1,101 link instance를 별도 unresolved 목록으로 남긴다.

## 10. Next implementation tasks

1. PDFParser 참조 정규식을 콜론 선택형과 【...】, 원색도판 변형까지 실제 본문 표기에 맞게 보완하고, 1차·2차·3차의 페이지 회수율을 별도 회귀 테스트로 고정한다.
2. 파서 결과에 direct, derived, heuristic, unavailable provenance 상태를 추가한다. 파일명에서 나온 도면 N·삽도 N은 canonical ID로 저장하지 않는다.
3. INDD Adobe bridge가 생성한 manifest에 page index, textFrame bounds, graphic bounds, linkPath, source hash를 필수화하고, 하나라도 없는 링크는 build 실패가 아니라 명시적 unresolved 상태로 저장한다.
4. Illustrator bridge는 artboard/textFrame/placedItem을 직접 내보내고, PDF-compatible open/render 성공과 DOM manifest 성공을 별도 지표로 기록한다.
5. READY gate를 본문 참조 → manifest page/artboard → graphic/placedItem → linkPath → 원본 hash 전체 체인으로 변경하고, 이번 기준인 도판 0/5·도면 0/2를 재실행해 0%가 해소됐는지 확인한다.
6. 도판 패널은 871개 insufficient 사례를 포함한 실제 fixture 없이 임의 bbox를 만들지 말고, Adobe manifest bounds 또는 명시적 review queue로 보낸다.
