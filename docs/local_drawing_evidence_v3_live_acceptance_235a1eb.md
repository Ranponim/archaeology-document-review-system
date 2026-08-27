# PR #47 live Codex acceptance — blocked

일시: 2026-08-27 (Asia/Seoul)
HEAD: `235a1eb9085aefa4325ad0747b1e19a8a50c9c4b`
원격 PR 브랜치 HEAD: 동일 SHA

## 결론

코드는 수정하지 않았으며, 실제 `D:/Coding/archaeology-document-review-system/src`의 AI 56개를 대상으로 최신 PR HEAD에서 acceptance evaluator를 실행했다. 그러나 live Codex 호출은 첫 HTTP 요청 전에 인증 설정에서 중단됐다.

재현된 실패:

```text
ValueError: OPENAI_API_KEY is required for drawing-evidence-v3
exit code: 1
HTTP/API calls completed: 0
```

Codex CLI가 ChatGPT 로그인 상태인 것과 이 애플리케이션 resolver가 사용하는 OpenAI Responses API Bearer 키는 별개다. 따라서 CLI 로그인만으로 앱의 `--live-codex` acceptance를 성공으로 처리하지 않았다.

## Gold 검토

기존 `docs/local_drawing_evidence_v3_gold_template.json`은 56행 전부 `verification: unknown`이었다. 실제 `/src` AI 내용, 렌더된 source/body 영역, 최신 본문 PDF의 도면·삽도 제목을 대조해 56행을 검토했고, 단일 identity가 방어 가능한 50행과 한 AI 안에 여러 도면이 합쳐져 단일 identity를 고를 수 없는 6행을 별도 기록했다.

- 검토: 56/56
- 단일 identity 확인 가능: 50
- unresolved: 6
- 파일명만으로 판정: 0
- 기존 evaluator gold에 반영된 known row: 0 (원본 template은 변경하지 않음)
- 외부 human sign-off: 없음

상세 검토 결과는 [local_drawing_evidence_v3_manual_review.json](local_drawing_evidence_v3_manual_review.json)에 있다. unresolved 6건은 `도면16/18/21/23/25/27` 편집본으로, 각각 여러 본문 도면을 포함하므로 단일 gold identity로 축약하지 않았다.

## 실행 명령

```powershell
python tools/evaluate_drawing_evidence_v3.py --source-root src --gold docs/local_drawing_evidence_v3_gold_template.json --output-json docs/local_drawing_evidence_v3_live_acceptance_attempt_235a1eb.json --output-report docs/local_drawing_evidence_v3_live_acceptance_attempt_235a1eb.md --live-codex --render-dir docs/local_drawing_evidence_v3_live_acceptance_render_235a1eb
```

재현 로그: [local_drawing_evidence_v3_live_acceptance_attempt_235a1eb.log](local_drawing_evidence_v3_live_acceptance_attempt_235a1eb.log)

## 환경

- branch: `feature/adobe-free-provenance-20260823`
- source root: `D:/Coding/archaeology-document-review-system/src` (read-only)
- AI files: 56
- resolver: `CodexDrawingResolverClient`
- endpoint: `https://api.openai.com/v1/responses`
- model: `gpt-5.3-codex`
- OS: Windows NT 10.0.26200.0
- Python: 3.13.3
- Docker: 28.0.4
- Node/npm: 22.23.1 / 11.18.0
- `OPENAI_API_KEY`: process/user/machine 모두 없음
- Adobe InDesign/Illustrator, COM, ExtendScript: 사용하지 않음

## Acceptance metrics

실제 live decision이 0건이고 evaluator gold known denominator가 0이므로 아래 값은 0이 아니라 `not_measured`다.

| 지표 | 결과 |
|---|---:|
| Recall@10 | not measured |
| Codex Top-1 accuracy | not measured |
| auto coverage | not measured |
| auto precision | not measured |
| review rate | not measured |
| invalid response | not measured |
| hard contradiction promoted | not measured |
| filename-only promoted | not measured |
| kind collision | not measured |
| API-unsafe promotion | not measured |

JSON 원본: [local_drawing_evidence_v3_live_acceptance_235a1eb.json](local_drawing_evidence_v3_live_acceptance_235a1eb.json)

이 결과만으로 v3 acceptance 또는 auto-promote를 승인하지 않았다.
