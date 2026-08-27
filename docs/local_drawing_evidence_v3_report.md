# Local drawing evidence v3 test report

검증일: 2026-08-27 (Asia/Seoul)  
브랜치: `feature/adobe-free-provenance-20260823`  
pull 후 HEAD: `9f649066355d189a99231f8c6262e9bced4e56e8`

## 결론

최신 v3 구현을 pull하고 focused/backend/Neo4j/frontend 시험을 완료했다. 코드와 hermetic 검증은 통과했지만, 실제 Codex acceptance는 측정하지 못했다. 현재 환경에 `OPENAI_API_KEY`가 없고 human-verified gold row가 0/56이므로, live Codex를 호출하거나 Recall/precision을 추측해 채우지 않았다.

따라서 v3는 acceptance 통과 또는 auto-promote 상태가 아니다. v1/v2 기본 동작을 유지하고 v3 자동 승격도 활성화하지 않았다.

## pull 및 source 안전성

- 기본 workspace의 `feature/source-provenance-remediation-20260818`는 `git pull --ff-only` 결과 이미 최신이었다. 기존 미커밋 변경은 보존했다.
- 최신 graph worktree `feature/adobe-free-provenance-20260823`는 `9324780`에서 `9f64906`으로 fast-forward pull했다.
- 실제 `/src`는 읽기 전용으로 사용했다. 이동/변경/생성 없음.
- Adobe InDesign/Illustrator, COM, ExtendScript를 사용하지 않았다.
- v3 gold template는 실제 AI 56개를 열거했으며 56개 모두 `verification: unknown`, 번호/종류 미지정이다. 파일명 숫자를 정답으로 복사하지 않았다.

## 시험 결과

| 영역 | 결과 |
|---|---:|
| v3 focused tests (Linux) | 68 passed |
| backend hermetic CI-equivalent (Linux) | 774 passed, 7 skipped |
| Neo4j E2E/repository (2 disposable DB) | 53 passed |
| frontend typecheck | passed |
| frontend unit | 15 files, 75 passed |
| frontend build | passed |
| gold template generation | 56 rows |

모든 Linux 시험은 최신 worktree 전체를 container에 mount하여 `tools/`와 backend가 함께 보이는 CI-equivalent 환경에서 실행했다. Neo4j는 application/isolated disposable instance를 사용한 뒤 제거했다. 경고는 기존 FastAPI/httpx deprecation 및 `fitz` API deprecation뿐이며 실패는 없다.

## v3 live acceptance 상태

v3 evaluator의 live 모드는 `--live-codex`와 `OPENAI_API_KEY`가 필요하다. 이번 실행에서는 key가 없고 gold template의 known truth도 0개라 live 호출을 실행하지 않았다.

| 운영 gate | 결과 |
|---|---|
| Recall@5/10/20 | 미측정 |
| Codex Top-1 | 미측정 |
| auto coverage 75–85% | 미측정 |
| auto precision ≥99% | 미측정 |
| review rate ≤25% | 미측정 |
| live safety counters | 미측정 |
| v3 auto-promote | 비활성 |

focused contract suite에서는 malformed/invented response, hard contradiction, filename-only promotion 금지, API failure fail-closed, human-review routing을 deterministic fake로 검증했고 통과했다. 그러나 이는 실제 Codex 결과의 acceptance 수치가 아니므로 live metrics로 세지 않았다.

## 미해결/추가 필요 항목

1. 실제 AI 56개 모두 human-verified gold mapping이 없어 accuracy denominator가 없다.
2. `OPENAI_API_KEY` 부재로 Codex source/candidate image decision 0건이다.
3. 따라서 Recall@10, Codex accuracy, auto coverage, auto precision, review rate는 모두 미측정이다.
4. 실제 Codex malformed response/API failure의 운영 횟수도 0이라고 주장하지 않고 미측정으로 남겼다.
5. v3는 shadow/review-only로 유지해야 하며, gold review와 local `--live-codex` 실행 후에만 auto-promote를 재검토할 수 있다.

기계 판독 결과와 동일한 판정은 [local_drawing_evidence_v3_metrics.json](local_drawing_evidence_v3_metrics.json), gold 작업지는 [local_drawing_evidence_v3_gold_template.json](local_drawing_evidence_v3_gold_template.json)에 기록했다.
