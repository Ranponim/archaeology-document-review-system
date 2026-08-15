# Neo4j 기반 고고학 검수 MVP 설계

## 목적

한 명의 고고학 전문가가 Windows PC 한 대에서 대형 보고서와 사진·도면을 검수할 수 있는 로컬 웹 MVP를 만든다. 시스템은 교정 후보와 근거를 생성하지만 원본을 자동 수정하지 않는다. 전문가가 전수 승인한 결과만 교정 목록과 근거 보고서에 반영한다.

## 확정된 범위

- 배포: Windows + Docker Desktop + Docker Compose
- 사용자: 단일 전문가 한 명
- 데이터: PDF, HWP/HWPX, 사진, Illustrator 도면과 파생 렌더
- 그래프: Neo4j를 문서·고고학 개체·사진·도면·검수 이력의 시스템 기록으로 사용
- 검색: Neo4j 벡터 인덱스, 전문·정확 검색, 그래프 탐색을 결합
- 모델: 외부 LLM/VLM/임베딩 API 호출 허용. 공급자는 설정으로 교체 가능
- 출력: 승인된 교정 목록, 근거 보고서, 감사 이력. HWP/PDF 자동 재편집은 제외
- 원본: 읽기 전용 보존. 원본 파일·페이지·영역의 해시와 위치를 추적

다중 사용자, 기관 인증 연동, 원격 동시 검토, 독립 벡터 DB, 자동 문서 재생성은 MVP 범위에서 제외한다.

## 배포 구조

```text
Windows PC
└─ Docker Desktop
   └─ Docker Compose
      ├─ web      검수 웹 UI와 REST API
      ├─ worker   변환·추출·그래프 적재·AI 분석 비동기 작업자
      ├─ neo4j    그래프 DB와 벡터·전문 인덱스
      └─ volume   원본, 파생물, 보고서, Neo4j 데이터, 작업 로그

브라우저 → http://localhost:8080 → web → Neo4j / worker / 외부 AI API
```

사용자는 Docker Desktop 설치 후 `start.ps1` 또는 `start.bat`으로 서비스를 실행하고 브라우저에서 로컬 주소에 접속한다. API 키는 `.env`에만 보관하며 Git, 브라우저 JavaScript, 보고서에 노출하지 않는다.

## 파일 저장 정책

대용량 파일과 이미지 바이트는 Neo4j에 넣지 않는다. Compose 관리 볼륨에 다음을 저장한다.

- 업로드 원본과 SHA-256
- 페이지 렌더와 이미지·도면 미리보기
- 본문·영역 추출 JSON
- AI API 요청에 사용한 최소 문단·이미지 영역의 식별자와 해시
- 생성된 교정 목록과 근거 보고서

Neo4j에는 파일 URI, 해시, 페이지와 영역 좌표, 메타데이터, 임베딩, 관계, 검수 결정을 저장한다. 원본은 UI와 분석기에서 수정하지 않으며, 파생물은 원본 해시와 처리 도구·버전에 연결한다.

## 그래프 모델

### 핵심 노드

| 노드 | 핵심 속성 |
|---|---|
| `Project` | 이름, 내부 관리번호, 생성 시각 |
| `Document` | 보고서 식별자, 제목 |
| `DocumentVersion` | 단계, 작성일, 원본 해시, 변환 상태 |
| `Page` | 물리 페이지, 인쇄 페이지, 렌더 URI, 좌표 체계 |
| `TextBlock` | 원문, 정규화문, 좌표, 언어, 텍스트 임베딩 |
| `Caption` | 원문, 번호, 좌표, 텍스트 임베딩 |
| `Image` / `ImageRegion` | 원본 URI, 해시, 촬영 메타데이터, 이미지 임베딩 |
| `Drawing` / `DrawingRegion` | 원본 URI, 해시, 레이어·영역·미리보기 정보, 이미지 임베딩 |
| `ArchaeologyObject` | 유적, 지점, 구역, 유구, 유물 식별자와 유형 |
| `CorrectionCandidate` | 유형, 원문, 제안문, 상태, 근거 완전성, 신뢰도 |
| `Evidence` | 파일·버전·페이지·영역·규칙·모델·해시 |
| `ReviewDecision` | 전문가 결정, 사유, 시각, 이전 결정 참조 |
| `AnalysisRun` | 도구·모델·프롬프트 버전, API 호출 요약, 비용, 상태 |

### 핵심 관계

```text
(:Project)-[:HAS_DOCUMENT]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)
(:DocumentVersion)-[:HAS_PAGE]->(:Page)-[:HAS_BLOCK]->(:TextBlock)
(:Page)-[:HAS_CAPTION]->(:Caption)
(:TextBlock|Caption)-[:MENTIONS]->(:ArchaeologyObject)
(:ImageRegion|DrawingRegion)-[:DEPICTS]->(:ArchaeologyObject)
(:Caption)-[:CAPTION_OF]->(:Image|Drawing)
(:DocumentVersion)-[:PRECEDES]->(:DocumentVersion)
(:CorrectionCandidate)-[:ABOUT]->(:ArchaeologyObject)
(:CorrectionCandidate)-[:SUPPORTED_BY]->(:Evidence)
(:CorrectionCandidate)-[:HAS_DECISION]->(:ReviewDecision)
(:AnalysisRun)-[:GENERATED]->(:CorrectionCandidate)
```

모든 관계에는 생성 근거, 신뢰도, 처리 버전, 생성 시각을 기록한다. 관계의 의미가 불확실하면 `semantic_review`, 복수 후보면 `multiple`, 대응 자료가 없으면 `missing`으로 표현하며 확정 관계로 저장하지 않는다.

## 하이브리드 검색

검색은 다음 순서로 수행한다.

1. 문서·버전·지점·시대·유구 등 명시적 그래프 조건으로 후보를 제한한다.
2. 번호, 명칭, 수치, 방향, 도면·도판 번호는 정확·전문 검색으로 찾는다.
3. 제한된 후보 안에서 문단·캡션·사진·도면 영역의 벡터 검색을 실행한다.
4. 정확 검색, 벡터 검색, 그래프 경로 검색의 순위를 RRF로 결합한다.
5. 상위 5~10개만 규칙 검사와 LLM/VLM 재평가에 전달한다.
6. 근거 경로가 부족하거나 상위 후보가 경쟁하면 확정하지 않고 보류 상태를 만든다.

임베딩은 처음에는 `TextBlock`, `Caption`, `ImageRegion`, `DrawingRegion`에만 저장한다. 벡터 검색 공급자는 Neo4j 내장 인덱스를 사용하며, 별도 벡터 DB가 필요한 규모가 확인될 때만 검색 어댑터 뒤에서 교체한다.

## 교정 파이프라인

```text
업로드
→ 원본 해시·변환 가능성 검사
→ 페이지·문단·캡션·사진·도면 영역 추출
→ 고고학 개체와 그래프 관계 후보 생성
→ 임베딩·인덱스 생성
→ 기계 교정
→ 문서 내부 일관성 검사
→ 문맥 LLM 검사
→ 사진·도면 VLM 교차 검사
→ 근거 완전성 검사
→ 전문가 전수 검토
→ 교정 목록·근거 보고서
```

### 1. 입력·추출 품질 검사

`raw_text`, `normalized_text`, `proposed_text`를 분리한다. OCR·인코딩·PDF 추출·레이아웃 오류는 저자 오탈자와 분리해 `extraction_error` 또는 `conversion_error`로 기록한다.

### 2. 기계 교정

오탈자, 띄어쓰기, 문장부호, 숫자·단위, 괄호 짝, 중복어, 전문용어 표기, 그림·표·도판 번호를 검사한다. 생성형 모델은 이 단계에서 문장을 재작성하지 않는다.

### 3. 문서 일관성·문맥

그래프를 따라 같은 개체의 다른 문단·캡션·표를 비교해 명칭, 수량, 치수, 고도, 방향, 시대, 참조번호의 충돌을 찾는다. LLM은 대상 문단, 앞뒤 문맥, 관련 개체의 근거만 입력받는다.

### 4. 사진·도면 교차 검사

본문·캡션·그래프 관계로 후보를 좁힌 뒤 VLM이 구조, 방향, 조사 단계, 토층, 축척·표찰, 누락 가능성을 평가한다. 파일명 일치만으로 사진·도면 동일성을 확정하지 않는다.

## 후보와 전문가 승인

모든 후보는 `pending_review`로 시작한다. 신뢰도는 자동 승인 권한이 아니다.

```text
pending_review
  → accepted
  → rejected
  → modified
  → deferred
```

- `accepted`: 제안문 그대로 채택
- `modified`: 전문가가 제안문을 변경해 채택
- `rejected`: 후보 또는 근거가 부정됨
- `deferred`: 추가 자료나 학술 판단이 필요함

후보에 `confirmed_mechanical` 분류가 있더라도 자동 반영하지 않는다. 모든 결정은 전문가 ID, 결정 사유, 결정 시각, 이전 결정 ID와 함께 append-only로 저장한다.

## 웹 UI

1. **프로젝트**: 파일 업로드, 원본 해시, 전송 동의, 분석 시작
2. **분석 현황**: 변환·추출·그래프 적재·AI 작업 단계, 재시도·취소, 실패 원인, API 비용
3. **검수**: 원문·제안문·페이지 이미지·관련 사진·도면·그래프 근거 경로를 함께 표시하고 전문가 결정을 기록
4. **결과**: 승인·기각·보류 목록, 근거, 분석 버전, 감사 이력을 Excel·HTML·PDF로 내보내기

## 외부 API와 보안

- 외부 API 호출은 worker만 수행한다.
- UI에는 API 키를 전달하지 않는다.
- 요청에는 필요한 문단, 캡션, 페이지 또는 이미지 영역만 포함한다.
- `AnalysisRun`에 모델명, 모델 버전, 프롬프트 버전, 요청·응답 해시, 토큰·이미지 수, 비용, 실패 원인을 남긴다.
- 업로드 시 외부 전송 동의와 전송 범위를 표시한다.
- API 시간 초과, 한도 초과, 안전 정책 거부는 재시도 가능 상태로 기록하고, 이미 끝난 추출·그래프 작업을 재실행하지 않는다.

## 작업 복구와 오류 상태

작업자는 단계별 산출물 해시를 확인해 완료된 단계를 재사용한다. 사용자는 작업을 취소하거나 실패 단계만 재시도할 수 있다.

최소 오류 상태는 다음과 같다.

`input_error`, `conversion_error`, `extraction_error`, `alignment_error`, `api_error`, `rate_limited`, `evidence_incomplete`, `asset_missing`, `asset_multiple`, `semantic_review`, `manual_review`, `unresolved`.

## 평가와 합격 기준

MVP는 기존 1·2·3차 교정본과 최종본에서 구축한 정답 데이터로 평가한다.

| 영역 | MVP 합격 기준 |
|---|---|
| 입력 무결성 | 원본 해시 불일치 0건, 원본 자동 수정 0건 |
| 페이지 대응 | 동일 표본 재실행 시 같은 대응 행과 근거 생성 |
| 기계 교정 | 정밀도 0.98 이상, 근거 누락 0건 |
| 내용 교정 | 보류 정답 데이터를 기준으로 정밀도 0.85 이상, 재현율 0.80 이상 |
| 검색 | 관련 정답의 Recall@5 0.95 이상, Precision@1 0.85 이상 |
| 사진·도면 | 잘못된 지점·시대 후보 혼입률 0.01 이하, 불확실 후보 자동 확정 0건 |
| 승인 | 승인 없는 자동 수정 0건, 모든 결정의 사유·근거·시각 보존 |
| 재현성 | 고정 입력·모델·프롬프트에서 후보 ID 집합 일치율 0.95 이상 |

## MVP 완료 조건

1. Windows Docker Compose에서 한 명의 사용자가 브라우저로 프로젝트를 생성하고 분석을 실행한다.
2. PDF·사진·도면을 Neo4j 그래프와 벡터 인덱스에 적재하고 관련 근거를 검색한다.
3. 오탈자·일관성·문맥·사진·도면 교차 후보를 구분해 표시한다.
4. 모든 후보는 전문가의 명시적 결정을 받아야 결과에 반영된다.
5. 결과 보고서는 승인·기각·보류와 각 근거·분석 버전을 포함한다.
6. 분석 중단·API 실패 후 완료된 단계부터 재개한다.
7. API 키·원본·전문가 결정은 브라우저 코드나 Git에 노출되지 않는다.
