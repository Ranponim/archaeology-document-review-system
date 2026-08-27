# PR #47 v3 Codex SDK acceptance

결과: **BLOCKED — 실제 SDK API 호출 전 인증 설정에서 중단**

- HEAD: `235a1eb9085aefa4325ad0747b1e19a8a50c9c4b`
- 원격 branch HEAD: 동일 SHA
- branch: `feature/adobe-free-provenance-20260823`
- source: `D:/Coding/archaeology-document-review-system/src` (read-only)
- source AI 전수 검사: 56/56
- render 결과: 864 files

## SDK 변경 검증

`CodexDrawingResolverClient`는 raw `httpx` 호출 대신 공식 OpenAI Python SDK의 `OpenAI.responses.create` 경로를 사용하도록 연결했습니다. 요청의 이미지 입력·strict JSON schema·앱 자체 retry/fail-closed 동작은 유지했습니다.

- dependency: `openai>=2.14,<3.0`
- acceptance host SDK: `2.14.0`
- Docker 검증 이미지 SDK: `2.54.0`
- Docker build: passed
- SDK client tests: `10 passed`
- 관련 v3 tests: `39 passed`
- CI hermetic backend: `775 passed, 7 skipped, 1 warning`

## 실제 acceptance 실행

실행 명령:

```powershell
python tools/evaluate_drawing_evidence_v3.py --source-root "D:/Coding/archaeology-document-review-system/src" --gold docs/local_drawing_evidence_v3_gold_template.json --output-json docs/local_drawing_evidence_v3_sdk_acceptance_235a1eb.json --output-report docs/local_drawing_evidence_v3_sdk_acceptance_235a1eb.md --live-codex --render-dir docs/local_drawing_evidence_v3_sdk_acceptance_render_235a1eb
```

재현 결과:

```text
ValueError: OPENAI_API_KEY is required for drawing-evidence-v3
exit code: 1
API calls completed: 0
failure stage: CodexDrawingResolverConfig.from_env before resolver construction/SDK responses.create
```

`OPENAI_API_KEY` 존재 여부는 process/user/machine 모두 `false`였습니다. Codex CLI의 ChatGPT 로그인 상태는 이 애플리케이션이 사용하는 OpenAI API Bearer key를 제공하지 않으므로 SDK acceptance 성공으로 간주하지 않았습니다.

로그: [local_drawing_evidence_v3_sdk_acceptance_235a1eb.log](local_drawing_evidence_v3_sdk_acceptance_235a1eb.log)

## Gold 및 metrics

기존 56-row gold template은 `verification: unknown` 56건이며 known row가 0건입니다. 별도 실제 자료 검토 artifact에는 50건의 single identity 확인과 6건의 unresolved가 기록되어 있으나, 해당 artifact는 현재 evaluator gold template에 자동으로 truth로 승격하지 않았습니다.

unresolved source indices: `29, 31, 35, 37, 39, 41`.

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

분모는 0이며, 위 `null`/`not measured`는 0점이 아닙니다. 실제 API key를 설정한 뒤 같은 명령을 재실행해야 live Recall/accuracy/coverage/precision/review 및 safety counter를 산출할 수 있습니다.

전체 결과 JSON: [local_drawing_evidence_v3_sdk_acceptance_235a1eb.json](local_drawing_evidence_v3_sdk_acceptance_235a1eb.json)
