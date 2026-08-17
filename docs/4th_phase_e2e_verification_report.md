# 4차 실전 파이프라인 및 API 검증 보고서 — 역사 기록 / 대체됨

> **상태: SUPERSEDED (대체됨)**  
> 이 문서는 2026-08-17 당시 수행한 API smoke validation의 기록입니다. 이후 코드리뷰에서 아래 검증 공백이 확인되었으므로, 기존의 **“100% 합격” 표현은 현재 MVP 전체 합격 판정으로 사용하면 안 됩니다.** 최신 판정은 5차 remediation 검증 보고서와 GitHub Actions 결과를 기준으로 합니다.

## 당시 확인된 범위

- Docker Compose stack의 health/project/document/review API가 응답함.
- 본문·도판·도면 이름의 PDF 3종을 업로드할 수 있었음.
- `ReviewRound` 생성/조회/승인 API가 동작함.
- 분석 job enqueue 및 후보/결정 API smoke path가 동작함.
- Neo4j에 ReviewRound 관련 노드/관계를 작성하는 코드가 존재했음.

## 이후 코드리뷰에서 발견된 검증 공백

1. `ReviewRound`가 생성되어도 실제 `/runs`는 body/plate/drawing version id를 별도로 받아 Round와 다른 조합으로 실행할 수 있었습니다.
2. 개발 후보 10건 제한이 VLM/LLM 실행 **후** 적용되어 실제 AI 비용 상한이 아니었습니다.
3. live script의 `<=10 verified` 문구는 실제 `assert len(candidates) <= 10`을 수행하지 않았습니다.
4. analysis run이 `completed`가 아니거나 후보가 0건이어도 스크립트가 최종 성공 문구에 도달할 수 있었습니다.
5. 2차 Round가 실제 수정된 body v2를 사용하지 않고 body v1을 재사용했습니다.
6. plate/drawing version의 project/kind ownership 검증이 불충분했습니다.
7. `1차/2차/3차/final` 고정 stage 모델이 4차 이상 검수 흐름을 막을 수 있었습니다.
8. Candidate ID가 run-scoped가 아니어서 반복 분석 시 ReviewDecision 감사 이력이 섞일 수 있었습니다.
9. candidate 단건/trace/visual API의 project ownership 경계가 불충분했습니다.
10. 시각자산 bundle은 같은 ArchaeologyObject를 묘사하는 여러 자산 중 첫 번째를 고를 수 있어, 후보가 실제 참조한 도판/도면과 다른 자산을 표시할 위험이 있었습니다.
11. 당시 live script는 실제 visual-bundle/render endpoint를 검증하지 않았고 테스트 PDF의 도판/도면은 실질적으로 텍스트 중심 fixture였습니다.
12. 고고학자 피드백 Case 6 — `4. 조사 후_45.JPG` 같은 InDesign Links filename 숫자가 publication `도판 45` 정체성으로 사용되면 안 된다는 조건을 live gate로 검증하지 않았습니다.

## 현재 해석

이 4차 결과는 다음 정도로만 해석합니다.

> **API smoke test 및 초기 ReviewRound/Graph 구조 동작 확인. 전체 archaeology Document–Object–Evidence MVP 검증은 아님.**

후속 remediation에서는 다음을 별도로 검증하도록 변경했습니다.

- ReviewRound-authoritative run execution
- project/kind-scoped DocumentVersion resolution
- unbounded `ReviewRound.sequence`
- pre-AI/VLM development budget
- raw/deduped/selected finding counters
- run-scoped immutable Candidate
- project-scoped Candidate/Evidence/Decision
- explicit `Reference -> RESOLVES_TO -> Plate/Drawing` visual identity
- real Neo4j 5.26 integration path
- actual PDF render bytes
- Case 6 Links filename trap regression

따라서 이 문서의 과거 `100% 합격` 표현은 폐기하며, 이후 구현/검증 문서를 최신 기준으로 사용합니다.
