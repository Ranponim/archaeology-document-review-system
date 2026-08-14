# 실제 교정본 샘플 검증 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 동일 본문 10페이지를 1·2·3차 교정본에서 비교하고 연결 사진·도면을 확인해, 실제 자료에 근거한 시스템 요구사항으로 `README.md`를 완성한다.

**Architecture:** PDF 입력을 읽기 전용으로 조사하고 페이지 텍스트·라벨·주석·렌더링을 임시 작업공간에 추출한다. 정규화 텍스트와 개체 식별자로 세 버전의 동일 구간을 대응시킨 뒤 규칙 기반 차이와 연결 자산 후보를 기록하고, 관찰 결과와 구현 요구사항을 구분해 README에 반영한다.

**Tech Stack:** Python 3, PyMuPDF, 표준 라이브러리(`pathlib`, `hashlib`, `json`, `difflib`, `re`), macOS 파일 도구, Markdown

## Global Constraints

- 검사 범위는 동일한 연속 본문 10페이지 × 3개 교정 단계, 총 30페이지다.
- `src`의 파일은 읽기 전용으로 유지하며 수정·이동·이름 변경하지 않는다.
- 중간 산출물은 `tmp/sample-validation/` 아래에만 저장하고 Git에 포함하지 않는다.
- 물리 PDF 페이지와 인쇄 페이지를 구분한다.
- 파일명 일치는 사진·도면의 의미적 동일성을 확정하는 근거로 사용하지 않는다.
- 확인된 사실, 분석상 추론, 향후 구현 요구사항을 README에서 구분한다.

---

### Task 1: 입력 조사와 원본 불변성 기준선

**Files:**
- Create: `tmp/sample-validation/inspect_inputs.py`
- Create: `tmp/sample-validation/verify_inventory.py`
- Create: `tmp/sample-validation/input-inventory.json`
- Create: `tmp/sample-validation/source-hashes.txt`
- Test: `tmp/sample-validation/verification/input-check.txt`

**Interfaces:**
- Consumes: `src/완성까지 가던 교정본들` 아래의 본문 1·2·3차 PDF
- Produces: 각 입력의 절대 경로, 크기, SHA-256, 페이지 수, 암호화 여부, 텍스트 추출 가능 여부, 페이지 라벨, 주석 수

- [ ] **Step 1: 세 입력 PDF의 정확한 경로와 파일 크기를 기록한다**

Run: `find 'src/완성까지 가던 교정본들' -type f -iname '*본문*교정.pdf' -print`

Expected: 1차·2차·3차 본문 PDF가 각각 하나씩 출력된다.

- [ ] **Step 2: PDF 읽기 도구를 준비한다**

Run: `python3 -m pip install --target tmp/sample-validation/vendor pymupdf`

Expected: `PYTHONPATH=tmp/sample-validation/vendor python3 -c 'import fitz; print(fitz.__version__)'`가 종료 코드 0을 반환한다. 설치가 실패하면 외부 패키지 설치 승인을 요청하고, 승인 후 같은 명령을 다시 실행한다.

- [ ] **Step 3: 입력 메타데이터와 SHA-256을 추출한다**

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/inspect_inputs.py`

Expected: `input-inventory.json`에 PDF 3개가 기록되고 각 파일의 `page_count`가 10 이상이며, `source-hashes.txt`에 3개 해시가 존재한다.

- [ ] **Step 4: 기준선 검증을 기록한다**

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/verify_inventory.py`

Expected: 종료 코드 0, `input-check.txt`에 `3 PDFs; all readable; all >= 10 pages`가 기록된다.

### Task 2: 동일 연속 10페이지 선정과 30페이지 추출

**Files:**
- Create: `tmp/sample-validation/extract_page_index.py`
- Create: `tmp/sample-validation/select_window.py`
- Create: `tmp/sample-validation/extract_window.py`
- Create: `tmp/sample-validation/verify_page_map.py`
- Create: `tmp/sample-validation/page-map.json`
- Create: `tmp/sample-validation/extracted/<version>/<physical-page>.json`
- Create: `tmp/sample-validation/rendered/<version>/<physical-page>.png`
- Test: `tmp/sample-validation/verification/page-map-check.txt`

**Interfaces:**
- Consumes: Task 1의 `input-inventory.json`
- Produces: 버전별 물리 페이지, 인쇄 페이지, 제목, 정규화 지문을 가진 10개 대응 행과 총 30페이지 추출물

- [ ] **Step 1: 모든 페이지의 텍스트 지문과 식별자를 계산한다**

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/extract_page_index.py`

Expected: 세 PDF 각각에 대해 페이지별 정규화 텍스트, 첫 문장, 제목 후보, 개체·그림·표·사진 번호가 생성된다.

- [ ] **Step 2: 대응 가능한 연속 구간 후보를 점수화한다**

점수는 세 버전 텍스트 유사도 50%, 그림·표·사진·도면 참조 존재 20%, 유적 개체 식별자 존재 15%, 교정 주석 존재 10%, 페이지 간 문맥 연속성 5%로 계산한다.

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/select_window.py`

Expected: 가장 높은 점수의 10페이지 연속 구간 하나가 선택되고 세 버전의 대응 페이지가 `page-map.json`에 기록된다.

- [ ] **Step 3: 선택된 30페이지를 텍스트·주석 JSON과 PNG로 추출한다**

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/extract_window.py`

Expected: 버전별 JSON 10개와 PNG 10개, 합계 JSON 30개와 PNG 30개가 생성된다.

- [ ] **Step 4: 대응·추출 완전성을 검증한다**

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/verify_page_map.py`

Expected: 종료 코드 0, `page-map-check.txt`에 `10 aligned rows; 30 extracted pages; 30 rendered pages`가 기록된다.

### Task 3: 버전 차이와 규칙 기반 오류 후보 분석

**Files:**
- Create: `tmp/sample-validation/compare_versions.py`
- Create: `tmp/sample-validation/check_rules.py`
- Create: `tmp/sample-validation/verify_differences.py`
- Create: `tmp/sample-validation/version-differences.json`
- Create: `tmp/sample-validation/version-differences.md`
- Test: `tmp/sample-validation/verification/difference-check.txt`

**Interfaces:**
- Consumes: Task 2의 `page-map.json`과 30개 페이지 JSON
- Produces: 페이지·문단별 추가, 삭제, 수정, 이동 후보와 명칭·참조번호·수치·표기·주석 반영 결과

- [ ] **Step 1: 레이아웃 잡음과 본문 변경을 분리한다**

공백, 줄바꿈, 반복 머리말·꼬리말만 다른 경우 `layout_noise`로 분류하고 원문 문자열을 함께 보존한다.

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/compare_versions.py`

Expected: 각 대응 페이지에 `1_to_2`, `2_to_3`, `1_to_3` 비교 결과가 존재한다.

- [ ] **Step 2: 명시적 규칙 검사를 실행한다**

검사 키는 `site_or_area_name`, `feature_or_artifact_id`, `figure_plate_table_photo_ref`, `numeric_value`, `direction_period_term`, `annotation_resolution`으로 고정한다.

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/check_rules.py`

Expected: 모든 후보에 파일 버전, 물리·인쇄 페이지, 원문, 비교문, 규칙명, 신뢰도와 판정 상태가 포함된다.

- [ ] **Step 3: 렌더링 30페이지를 시각 확인한다**

각 페이지에서 텍스트 추출 순서, 캡션 위치, 주석 표시, 그림·표 배치를 확인하고 자동 비교의 오탐을 `layout_noise` 또는 `manual_review`로 재분류한다.

Expected: 검토되지 않은 후보가 없고 모든 후보 상태가 `confirmed`, `layout_noise`, `manual_review`, `unresolved` 중 하나다.

- [ ] **Step 4: 차이 결과의 근거 완전성을 검증한다**

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/verify_differences.py`

Expected: 종료 코드 0, 근거 필드가 비어 있는 후보 0개, `difference-check.txt`에 분류별 건수가 기록된다.

### Task 4: 캡션·사진·도면 연결 가능성 검사

**Files:**
- Create: `tmp/sample-validation/extract_asset_refs.py`
- Create: `tmp/sample-validation/match_assets.py`
- Create: `tmp/sample-validation/verify_asset_links.py`
- Create: `tmp/sample-validation/asset-links.json`
- Create: `tmp/sample-validation/asset-links.md`
- Test: `tmp/sample-validation/verification/asset-link-check.txt`

**Interfaces:**
- Consumes: 선택 구간의 캡션·참조번호와 `src/도판(사진들)/Links`, `src/본문 도면`, `src/환경 도면`
- Produces: 참조별 `exact`, `multiple`, `missing`, `semantic_review` 연결 상태와 후보 파일 목록

- [ ] **Step 1: 표본에서 캡션과 자산 참조를 추출한다**

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/extract_asset_refs.py`

Expected: 캡션 원문, 참조 유형·번호, 지점·유구·유물 식별자가 보존된다.

- [ ] **Step 2: 파일명과 디렉터리 문맥으로 후보를 검색한다**

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/match_assets.py`

Expected: 모든 참조가 `exact`, `multiple`, `missing`, `semantic_review` 중 하나로 분류되고 후보마다 상대 경로와 일치 근거가 존재한다.

- [ ] **Step 3: 이미지 후보를 시각 확인한다**

JPEG 후보는 원본 방향과 식별 가능한 표찰·축척·촬영 단계를 확인한다. AI 파일은 PDF 호환 미리보기가 있을 때만 렌더링하고, 렌더링 불가를 `input_conversion_required`로 기록한다.

Expected: 파일명 일치만으로 `exact`가 된 항목이 없고 시각·구조 검토가 필요한 후보는 `semantic_review`로 남는다.

- [ ] **Step 4: 연결 결과를 검증한다**

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/verify_asset_links.py`

Expected: 종료 코드 0, 모든 표본 참조에 상태가 있고 `asset-link-check.txt`에 상태별 건수가 기록된다.

### Task 5: README 요구사항 완성

**Files:**
- Modify: `README.md`
- Test: `tmp/sample-validation/verification/readme-check.txt`

**Interfaces:**
- Consumes: Tasks 1~4의 검증 결과
- Produces: 실제 자료 검증 결과, 확정 요구사항, 한계, 구현 우선순위와 합격 기준이 포함된 README

- [ ] **Step 1: 문서 상태와 실제 자료 현황을 갱신한다**

README에 검사일, 표본 파일 3개, 물리·인쇄 페이지 범위, 총 30페이지, 연결 자산 범위를 기록하고 `설계 검토 초안`과 `샘플 검증 완료` 상태를 구분한다.

- [ ] **Step 2: 샘플 검증 결과를 근거 수치와 함께 추가한다**

버전 대응 성공 여부, 변경 후보 분류별 건수, 주석 추출 가능 여부, 사진·도면 연결 상태별 건수, 변환 실패 또는 제약을 기록한다.

- [ ] **Step 3: 시스템 요구사항을 구체화한다**

공통 문서 모델의 필수 식별자, 버전 계보, 페이지 대응 키, 근거 필드, 오류 상태, 입력 변환 오류, 전문가 승인 흐름을 검증 결과에 맞춰 확정 표현으로 작성한다.

- [ ] **Step 4: 구현 우선순위와 합격 기준을 작성한다**

1단계는 PDF 입력·페이지 대응·규칙 검사, 2단계는 사진·도면 후보 연결, 3단계는 LLM/VLM 의미 판단으로 정의한다. 각 단계에는 재현 가능한 측정값과 전문가 확인 조건을 둔다.

- [ ] **Step 5: README 내용 일관성을 검사한다**

Run: `rg -n 'TBD|TODO|확인해야|좋다|가능하면' README.md`

Expected: 남은 표현은 명시적인 향후 요구사항 문맥에만 존재하고, 관찰 사실을 구현 완료처럼 서술한 문장이 없다. 결과를 `readme-check.txt`에 기록한다.

### Task 6: 최종 재현성·원본 불변성 검증

**Files:**
- Create: `tmp/sample-validation/final_verify.py`
- Modify: `README.md` (검증 중 발견한 사실 오류가 있을 때만)
- Test: `tmp/sample-validation/verification/final-check.txt`

**Interfaces:**
- Consumes: 모든 검증 결과와 Task 1의 원본 해시
- Produces: 완료 조건 5개와 원본 불변성을 증명하는 최종 검사 기록

- [ ] **Step 1: 원본 해시를 다시 계산해 기준선과 비교한다**

Expected: 세 PDF의 SHA-256이 Task 1의 값과 모두 일치한다.

- [ ] **Step 2: 완료 조건을 기계적으로 확인한다**

Run: `PYTHONPATH=tmp/sample-validation/vendor python3 tmp/sample-validation/final_verify.py`

Expected: `10 aligned rows`, `30 extracted pages`, 모든 차이 후보의 근거 필드, 모든 자산 참조의 상태, README의 표본 범위·결과·한계·요구사항 섹션이 확인된다.

- [ ] **Step 3: 변경 범위를 확인한다**

Run: `git status --short && git diff -- README.md docs/superpowers/plans/2026-08-14-sample-validation.md`

Expected: `src` 아래 변경이 없고 최종 추적 대상은 README와 승인된 Superpowers 문서뿐이다.

- [ ] **Step 4: 최종 결과를 커밋한다**

```bash
git add README.md docs/superpowers/plans/2026-08-14-sample-validation.md
git commit -m "docs: validate archaeology review requirements"
```

Expected: 커밋이 생성되고 작업 트리에서 `src` 변경이 없다.
