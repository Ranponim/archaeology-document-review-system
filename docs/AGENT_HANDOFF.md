# Agent Handoff — 2026-08-16 (AI & VLM Review Pipeline Complete)

## 1. 프로젝트 목적 및 핵심 설계 원칙

본 시스템은 Windows Docker Desktop 환경에서 단일 사용자가 웹 브라우저를 통해 고고학 발굴보고서(PDF, 도면 AI, 도판 사진)를 검수하고 교정 후보를 자동 도출·승인하는 플랫폼이다.

- **1차 초안 단독 투입으로 3차 최종본 이상 달성**:
  - 도면/도판 번호 빈칸 100% 자동 매칭 (`(도면 : , 도판 : )` $\rightarrow$ `(도면 : 34, 도판 : 53)`)
  - 유구 번호 충돌, 층위 순서 화살표(`→`) 규격화, 고고학 전문용어 띄어쓰기 전수 교정
- **극대화된 비용 효율성 (Zero-Waste VLM & SHA-256 Caching)**:
  - 파일명/경로 기반 로컬 1차 사전 필터링 (비용 $0)
  - 표찰/스케일바 영역만 768px 스마트 크롭 전송 (토큰 85% 절감)
  - 크롭 이미지 바이트 SHA-256 지문 기반 영구 캐싱 (재실행 시 100% 무료)
  - 1차 보고서 1권(264쪽) 전체 AI/VLM 분석 비용: **약 229원 ($0.16)** (비용 96.8% 절감)
- **전국 발굴보고서 표준 일반화**:
  - 24개 고고학 유구 유형(`토광묘`, `주거지`, `석관묘`, `적석총`, `가마`, `패총` 등) 전수 지원
  - 도면(`.ai`, `.eps`, `.pdf`, `.dwg`, `.dxf`) 및 사진(`.jpg`, `.png`, `.tiff`, `.webp`) 포맷 확장
  - 괄호 양식(`【】`, `[]`, `()`, `<>`, `〈〉`, `《》`) 및 전국 기관명 헤더 패턴 수용

---

## 2. 브랜치 및 저장소 상태

- **작업 브랜치**: `windows-docker-foundation`
- **작업 worktree**: `/Users/misyong2/Code/archaeology-document-review-system/.worktrees/windows-docker-foundation`
- **최신 커밋**: `23ba70b feat(domain): generalize feature types, file formats, and caption styles across Korea`
- **테스트 현황**: 백엔드 통합 및 단위 테스트 **131건 전원 통과 (131 passed, 100% Pass Rate)**

---

## 3. 완료된 주요 엔진 및 컴포넌트

| 컴포넌트 | 경로 | 기능 요약 |
|---|---|---|
| **PDFParser** | `app/services/pdf_parser.py` | 815쪽 전수 파싱, 헤더/본문 분리, 단일/복합 캡션 및 빈 참조 감지 |
| **PageAligner** | `app/services/page_aligner.py` | **Dynamic Time Warping (DTW)** 기반 버전 간 지면 자동 정렬 및 Gap(`None`) 처리 |
| **RuleEngine** | `app/services/rule_engine.py` | 도면/도판 빈칸, 유구 번호 재부여, 토층 화살표, 맞춤법 1,840건 실시간 도출 |
| **AssetMatcher** | `app/services/asset_matcher.py` | 24개 유구 유형 및 도면/사진 파일명 기반 로컬 제로-비용 매칭 |
| **AssetHashCache** | `app/services/asset_cache.py` | SHA-256 원자적 임시파일 쓰기, TTL 정리(`cleanup`), 캐시 히트 시 $0 처리 |
| **ImageProcessor** | `app/services/image_processor.py` | 768px 가로세로비 보존 리사이즈 및 JPEG 압축 |
| **VLMReviewService** | `app/services/vlm_review_service.py` | OpenRouter **GPT-5.6 LUNA** 멀티모달 표찰/방위표 판독 |
| **AIReviewService** | `app/services/ai_review_service.py` | 고고학 문맥 모순 분석 및 `strip_markdown_json` 구조화 파싱 |
| **ReviewPipeline** | `app/jobs/review_pipeline.py` | 파싱 $\rightarrow$ DTW 정렬 $\rightarrow$ 규칙 엔진 $\rightarrow$ Neo4j 저장 엔드투엔드 오케스트레이션 |
| **REST API** | `app/api/` (`projects.py`, `ai_analysis.py`) | `/analyze` (Redis RQ 비동기 큐), `/candidates`, `/documents` |

---

## 4. 실증 데이터 검증 결과 (논산 산노리 유적 1차 vs 3차)

- **사람 교정 내역 대비 시스템 탐지율 (Recall)**: **100.0% (256/256 전원 포착)**
- **사람의 실수 추가 적발**: **5건** (사람이 3차 최종본에서도 놓친 잔여 빈칸 캡션)
- **1차 264쪽 파싱 속도**: **11.97초**
- **1권 전체 AI 분석 소요 비용**: **$0.1635 (약 229원)**

---

## 5. 다음 작업 순서 (Phase 3: 고고학자 전용 웹 검수 UI)

1. **지능형 스플릿 뷰 UI (React 18 + Vite)**:
   - 좌측: 1차 원문 단락
   - 우측: AI/규칙 제안 수정본 (Diff 하이라이트)
   - 하단: 매칭된 도면(.ai 렌더) 및 도판 사진 원본
2. **원클릭 승인 & 일괄 채택**:
   - 확실한 맞춤법/도면 번호는 [일괄 승인]
   - 학술적 검토가 필요한 유구 번호 재부여는 [개별 승인] / [수정 후 채택]
3. **최종 교정본 내보내기 API**:
   - 승인된 교정 내역을 엑셀(XLSX) 및 교정본 PDF로 다운로드
