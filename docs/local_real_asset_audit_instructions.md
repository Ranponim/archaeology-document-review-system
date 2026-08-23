# Local Real Asset Audit Instructions

## 목적

이 문서는 로컬 개발 환경에 실제로 존재하는 고고학 보고서 원본 자료를 대상으로, **Adobe InDesign/Illustrator가 설치되지 않은 환경에서 INDD/AI/도판/본문 자료를 어느 수준까지 직접 해석하고 그래프로 만들 수 있는지**를 검증하기 위한 Codex 작업 지시서다.

이번 검증은 설계 추측이 아니라 **실제 `/src` 아래의 원본 파일**을 기준으로 수행해야 한다. 테스트 결과가 현재 구현 가정과 다르면 현재 구현을 정답으로 간주하지 말고 실제 파일에서 관측한 사실을 우선한다.

## 절대 조건

- 실제 샘플 루트는 `/src`이다.
- `/src` 아래 원본은 **읽기 전용**으로 취급한다. 이동, rename, overwrite, 재저장 금지.
- Adobe InDesign/Illustrator 설치를 전제로 하지 않는다.
- Adobe COM, ExtendScript, Windows Adobe bridge를 사용하지 않는다.
- 파일명만 보고 `도판 12`, `도면 8` 등의 canonical identity를 확정하지 않는다.
- 파일명/폴더명은 후보 탐색에는 사용할 수 있으나 graph authority가 되어서는 안 된다.
- 파싱 실패를 성공으로 포장하지 않는다. 무엇을 읽었고 무엇을 못 읽었는지 분리해서 기록한다.
- 대용량 원본 전체를 Git에 추가하지 않는다.
- 결과 보고서에는 개인정보/민감한 원문 전체를 복제하지 말고, 필요한 최소 예시와 경로/개수/해시만 기록한다.

---

# 1. 먼저 `/src` 전체 구조를 파악한다

Codex는 가장 먼저 `/src` 아래를 재귀적으로 조사하고 다음을 기록한다.

1. 전체 파일 수
2. 확장자별 파일 수
3. 디렉터리 구조
4. 각 파일의 상대경로
5. 파일 크기
6. SHA-256
7. 실제 MIME/signature와 확장자가 일치하는지

특히 다음 종류를 분리한다.

- 본문 PDF
- `.indd`
- `.idml`
- `.ai`
- Illustrator에서 나온 `.pdf` 또는 `.eps`
- 도판/사진: `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`, `.webp`
- `Links` 또는 유사 링크 폴더
- 기타 sidecar/metadata 파일

가능하면 산출물로 `/tmp` 등에 machine-readable inventory JSON/CSV를 만든 뒤, 최종 요약만 보고서에 기록한다.

예시 확인 명령은 환경에 맞게 선택한다.

```bash
find /src -type f
file <path>
sha256sum <path>
```

Python으로 inventory를 만들어도 된다.

## 이 단계에서 답해야 할 질문

- 실제 자료는 우리가 예상한 `본문 / 도판 / 도면` 구조와 같은가?
- INDD가 단일 파일인가, package 폴더인가?
- `Links`가 존재하는가?
- `.idml`이 이미 존재하는가?
- `.indd`와 같은 이름의 PDF가 존재하는가?
- AI와 같은 basename의 PDF가 존재하는가?
- 중복 파일이나 같은 SHA-256을 가진 복사본이 있는가?

---

# 2. 본문 PDF를 기준점으로 확인한다

본문 PDF는 이미 시스템의 가장 안정적인 입력이므로 다른 자산을 비교할 기준점으로 사용한다.

확인할 것:

- 페이지 수
- 텍스트 추출 가능 여부
- 페이지별 text block 수
- 페이지별 image block 수
- `【도판 N】`, `【도면 N】`, `(도판 : )`, `(도면 : )` 등 실제 보고서에 존재하는 표기 패턴
- 캡션과 본문 참조가 어떤 형태로 등장하는지
- 실제 도판/도면 번호 범위

가능하면 기존 `PDFParser`로 실제 파일을 읽고, raw PyMuPDF 결과와 비교한다.

보고서에는 최소한 다음을 남긴다.

```text
본문 PDF: <relative path>
페이지 수: N
텍스트 추출: PASS/PARTIAL/FAIL
발견 도판 번호 예: ...
발견 도면 번호 예: ...
```

---

# 3. INDD를 Adobe 없이 실제로 어디까지 읽을 수 있는지 조사한다

이 단계가 이번 감사의 핵심이다.

모든 `.indd` 파일에 대해 단순히 "지원 안 됨"이라고 결론내리지 말고 실제 바이너리를 조사한다.

## 3.1 기본 signature/metadata

확인:

- `file` 판정
- 파일 크기
- embedded XMP/metadata 존재 여부
- 문자열 검색으로 문서명, 링크 파일명, `Links`, `.jpg`, `.tif`, `.ai`, `.pdf` 등의 흔적이 발견되는지
- `도판`, `도면`, `①`, `②` 같은 실제 caption 문자열이 raw string 수준에서 보이는지
- embedded preview 또는 PDF-like stream 흔적이 있는지

사용 가능한 도구가 있으면 `exiftool`, `strings`, `xxd` 등을 활용한다. 도구가 없다고 테스트 전체를 중단하지 말고 Python binary scan으로 대체한다.

## 3.2 Link provenance 가능성

INDD 내부에서 다음 중 무엇을 실제로 얻을 수 있는지 확인한다.

- linked asset basename
- linked asset relative/full path
- link ID 같은 stable identifier
- page/spread와 link의 관계
- placed graphic의 bbox/geometric bounds

그리고 추출된 link 이름/경로를 `/src` 실제 파일과 비교한다.

판정은 반드시 다음처럼 나눈다.

- `PASS`: 특정 INDD placement -> 특정 `/src` 원본 자산까지 강하게 연결 가능
- `PARTIAL`: 파일명/문자열 후보만 확인 가능하고 placement/page/bbox는 불명확
- `FAIL`: 링크 provenance에 쓸 수 있는 데이터 추출 불가

## 3.3 Text/page/frame 구조 가능성

현재 graph-first canonicalizer가 Adobe DOM에서 기대하는 정보는 사실상 다음이다.

```text
page.index
page.label
textFrame.text
textFrame.bounds
graphic.bounds
graphic.linkPath
```

실제 INDD만으로 위 필드를 각각 어느 정도 복구할 수 있는지 표로 작성한다.

| 필드 | 실제 INDD에서 추출 | 신뢰도 | 방법/근거 |
|---|---|---|---|
| page index | PASS/PARTIAL/FAIL | high/medium/low | ... |
| page label | ... | ... | ... |
| text | ... | ... | ... |
| text bbox | ... | ... | ... |
| graphic bbox | ... | ... | ... |
| link path | ... | ... | ... |

이 표가 **Adobe 없는 INDD parser를 계속 개발할지, IDML/PDF sidecar를 권장할지 결정하는 핵심 근거**가 된다.

---

# 4. IDML이 실제로 있다면 INDD와 교차 검증한다

`/src`에 `.idml`이 있다면 반드시 열어본다. IDML은 ZIP/XML 구조이므로 다음을 확인한다.

- package가 정상적으로 unzip 가능한지
- Spread/Page 정보
- Story/text content
- text frame 위치/bounds
- placed graphic 위치/bounds
- Link resource 경로
- page/frame/link 관계

그리고 같은 문서의 `.indd`에서 추출할 수 있었던 정보와 비교한다.

핵심 질문:

> 실제 샘플에서는 IDML이 있으면 현재 `AdobeManifestV1`에 필요한 정보를 Adobe 없이 거의 그대로 재구성할 수 있는가?

가능하다면 변환 경로를 다음과 같이 제안할 수 있다.

```text
INDD = original provenance
IDML = structural authority
PDF = visual render verification
Links = source provenance
```

단, 실제 `/src`에 IDML이 없으면 "있다고 가정"하지 말고 결과에 명확하게 적는다.

---

# 5. AI 파일을 Adobe 없이 실제로 조사한다

모든 `.ai`에 대해 파일 형식을 직접 판별한다.

## 5.1 PDF-compatible AI 여부

확인할 것:

- 파일 시작부/구조가 PDF-compatible인지
- `%PDF-` signature 또는 PDF object/xref를 정상 인식하는지
- PyMuPDF가 직접 open 가능한지
- `pdfinfo`, `mutool`, `qpdf` 등이 있다면 정상 인식하는지
- 텍스트 추출 가능한지
- text bbox 추출 가능한지
- page/artboard에 해당하는 단위가 몇 개인지
- raster render 가능한지

한두 개만 확인하지 말고 **AI 전체 중 몇 %가 PDF-compatible인지**를 계산한다.

예:

```text
AI 총 87개
PyMuPDF 직접 open: 81/87
PDF-compatible: 81/87
텍스트 포함: 64/87
도면 identifier 직접 발견: 52/87
```

## 5.2 PDF-compatible이 아닌 AI

실패 파일은 별도로 조사한다.

- EPS/PostScript 기반인지
- 다른 embedded preview가 있는지
- strings 수준에서 도면 번호/caption이 나오는지
- 오픈소스 도구로 변환 가능한지
- 변환 실패 원인이 포맷 버전인지, font/resource 문제인지

"AI는 다 된다" 또는 "AI는 다 안 된다"가 아니라 실제 표본 비율을 보고한다.

## 5.3 도면 identity

AI 내부 텍스트에서 다음과 같은 명시적 identifier를 찾는다.

- `【도면 N】`
- `도면 N`
- 실제 프로젝트에서 사용하는 변형

도면 번호를 basename에서만 얻을 수 있다면 canonical identity로 확정하지 말고 `candidate_from_filename` 정도로만 분류한다.

---

# 6. 도판/사진 원본을 조사한다

사진/도판 파일 전체에 대해:

- 크기(width x height)
- 포맷
- SHA-256
- EXIF 존재 여부
- 동일 이미지 중복 여부
- basename 중복 여부
- INDD/IDML에서 참조되는 파일과 실제 파일의 매칭률

특히 링크 경로가 다음처럼 달라지는 사례를 찾는다.

```text
Links/photo01.jpg
./Links/photo01.jpg
C:\project\Links\photo01.jpg
Macintosh HD/.../Links/photo01.jpg
```

경로 normalization 후 basename이 아닌 **staged relative path + SHA-256**로 강한 provenance를 만들 수 있는지 판단한다.

---

# 7. 실제 파일을 이용해 cross-source 연결을 시험한다

최소 5~10개의 실제 도판/도면 사례를 골라 다음 체인을 수동/자동으로 증명한다.

## 도판 사례

```text
본문 Page
  -> 도판 reference
  -> INDD/IDML page
  -> Plate identifier
  -> panel marker ①/②/...
  -> placed graphic
  -> Link path
  -> /src 실제 JPG/TIF
```

각 단계가 실제 데이터로 증명되는지 기록한다.

## 도면 사례

```text
본문 Page
  -> 도면 reference
  -> AI
  -> explicit drawing identifier
  -> PDF-compatible text/vector evidence
```

가능하면 성공 사례뿐 아니라 실패/애매 사례도 2개 이상 남긴다.

---

# 8. 현재 `AdobeManifestV1`을 Adobe 없이 재현 가능한지 평가한다

현재 코드의 manifest schema를 기준으로 실제 자산에서 다음을 채울 수 있는지 확인한다.

```text
application
sourceAssetId
sourceSha256
pages[]
  index
  label
  textFrames[]
    text
    bounds
  graphics[]
    bounds
    linkPath
artboards[]
  index
  name
  textFrames[]
  placedItems[]
artifacts[]
```

필드별로:

- 직접 추출 가능
- sidecar(IDML/PDF)가 있어야 가능
- heuristic만 가능
- 사실상 불가능

으로 나눈다.

그리고 실제 샘플 기준으로 다음 중 어느 아키텍처가 맞는지 추천한다.

### A. Adobe-free direct parser가 충분함

```text
INDD/AI -> open-source parser -> manifest -> canonical graph
```

### B. Hybrid가 최선

```text
INDD/AI direct parser -> provisional graph
IDML/PDF/Links -> graph verification/upgrade
```

### C. INDD는 sidecar가 사실상 필수

```text
INDD = provenance only
IDML/PDF/Links = structural/canonical authority
AI = direct parse where PDF-compatible
```

**추천은 이론이 아니라 `/src` 성공률을 근거로 선택한다.**

---

# 9. 현재 코드와 실제 파일의 mismatch를 찾아낸다

특히 다음 파일/설계를 읽고 실제 `/src` 결과와 비교한다.

- `backend/app/services/reference_corpus_service.py`
- `backend/app/services/adobe_conversion_client.py`
- `backend/app/domain/adobe_manifest.py`
- `backend/app/services/reference_canonicalizer.py`
- 기존 asset/drawing 관련 parser

찾아야 할 것:

1. 실제 데이터에는 있는데 schema가 버리는 정보
2. schema가 요구하지만 실제 raw INDD/AI에서 못 얻는 정보
3. Adobe DOM을 전제로 해서 필요 이상으로 강한 부분
4. filename heuristic이 graph authority로 숨어 들어간 부분
5. Links relative path가 실제 폴더 구조와 맞지 않는 부분
6. AI를 PDF처럼 직접 열 수 있는데 불필요하게 Adobe 경로로 보내는 부분
7. IDML/PDF가 이미 있는데 사용하지 않는 부분

코드를 바로 대규모 수정하지 말고 먼저 이 mismatch를 보고서에 남긴다.

---

# 10. 최소 실제 graph prototype을 만든다

전체 시스템을 바꾸기 전에, 실제 파일 몇 개로 Adobe 없는 최소 graph를 만들어 본다.

가능하면 임시 코드/테스트로 다음 노드/관계를 만든다.

```text
SourceAsset
BodyPage
Plate
PlatePanel
Drawing
```

예시 관계:

```text
BodyPage -[:REFERENCES]-> Plate
Plate -[:HAS_PANEL]-> PlatePanel
PlatePanel -[:PLACED_FROM]-> SourceAsset
BodyPage -[:REFERENCES]-> Drawing
Drawing -[:DERIVED_FROM]-> SourceAsset
```

중요:

- graph identity는 explicit internal evidence가 있을 때만 canonical로 만든다.
- 파일명으로 추정한 것은 canonical edge와 분리한다.
- 각 edge가 어떤 evidence에서 왔는지 기록한다.

최소 5개 실제 사례가 만들어지는지 확인한다.

---

# 11. 결과 보고서 형식

Codex는 조사 후 아래 파일을 작성한다.

```text
docs/local_real_asset_audit_report.md
```

보고서는 다음 순서를 지킨다.

## 1. Executive Summary

다섯 줄 이내로 결론:

- INDD Adobe-free 처리 가능성
- AI Adobe-free 처리 가능성
- Links provenance 가능성
- IDML/PDF sidecar 필요성
- 추천 architecture A/B/C

## 2. 실제 `/src` inventory

확장자별 개수, 주요 디렉터리, 대표 샘플.

## 3. INDD 실제 결과

PASS/PARTIAL/FAIL과 근거.

## 4. AI 실제 결과

전체 파일 중 성공률과 실패 유형.

## 5. Links/도판 실제 결과

link matching 성공률과 path 문제.

## 6. Cross-source 실제 사례

최소 5개 chain.

## 7. AdobeManifestV1 재현 가능성 표

필드별 결과.

## 8. Current implementation mismatch

현재 코드에서 고쳐야 할 점.

## 9. 권장 architecture

A/B/C 중 하나를 실제 수치와 함께 추천.

## 10. Next implementation tasks

우선순위 순으로 구체적인 코드 변경 목록.

---

# 12. 보고할 때 반드시 포함할 수치

최종 보고서에는 최소 다음 숫자가 있어야 한다.

```text
/src 전체 파일 수
본문 PDF 수 / 총 페이지 수
INDD 수
IDML 수
AI 수
AI 중 PDF-compatible 수 및 비율
도판 이미지 수
INDD/IDML에서 발견한 link reference 수
실제 /src asset과 매칭된 link 수 및 비율
INDD에서 explicit plate identifier를 찾은 수
AI에서 explicit drawing identifier를 찾은 수
AdobeManifestV1 필드 중 direct 재현 가능한 필드 수
sidecar가 있어야 재현 가능한 필드 수
재현 불가능한 필드 수
cross-source chain 성공 수 / 시도 수
```

수치가 없으면 "검증 완료"라고 쓰지 않는다.

---

# 13. 중요한 판단 원칙

이번 검증의 목표는 특정 결론을 증명하는 것이 아니다.

다음 세 경우 모두 정상적인 결과다.

1. 실제 INDD/AI만으로 충분하다.
2. AI는 충분하지만 INDD는 IDML이 있어야 한다.
3. 대부분 직접 읽히지만 bbox/link provenance 일부만 sidecar가 필요하다.

**실제 `/src`가 답이다.**

현재 Windows Adobe bridge 구현이 이미 존재한다는 이유로 그 구조를 유지하지 말고, 반대로 Adobe를 없애고 싶다는 이유로 raw INDD에서 얻을 수 없는 정보를 있다고 가정해서도 안 된다.

실제 원본을 열고, 추출하고, 비교하고, 성공률을 측정한 뒤 architecture를 결정한다.

---

# Codex에게 바로 줄 작업 문구

아래 문구를 그대로 사용할 수 있다.

> `docs/local_real_asset_audit_instructions.md`를 먼저 읽어라. 실제 원본 자료는 `/src` 아래에 있으며 본문, 도면, 도판 및 관련 원본 파일이 들어 있다. `/src`는 읽기 전용으로 취급하고 Adobe InDesign/Illustrator 또는 Adobe COM/bridge를 사용하지 마라. 문서에 적힌 순서대로 실제 INDD/AI/PDF/Links/이미지를 조사하고, 특히 Adobe 없이 현재 AdobeManifestV1에 필요한 page/text/bbox/linkPath/artboard 정보를 어느 정도 복구할 수 있는지를 실제 파일 기준으로 검증하라. 추측하지 말고 성공률과 실패 사례를 수치화하라. 결과는 `docs/local_real_asset_audit_report.md`에 기록하라. 대규모 아키텍처 변경은 보고서를 작성하고 실제 데이터 근거가 나온 뒤에 결정하라.`
