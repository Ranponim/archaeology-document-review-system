# Drawing evidence v3 retrieval TDD report

## Scope and outcome

This report covers the retrieval-only TDD requested after the eight Recall@10 misses were audited against the actual AI originals and the actual body PDF. The original gold template and the read-only `/src` corpus were not modified. AUTO gate/resolver policy was not changed.

The audit confirmed seven of the eight former misses as valid retrieval targets. Source 36 was rejected as a gold assignment: its AI original says `3지점`, while the proposed body candidate `drawing:64` is explicitly `2지점`; therefore it is excluded from the confirmed denominator and was not used as a retrieval TDD target.

The live run completed against the actual 56 AI files and 828 body packets with Codex SDK `gpt-5.6-luna`, reasoning `high`, streaming, and a 180-second turn timeout.

## Before / after

| Metric | Baseline live acceptance | After live acceptance, raw manual gold (50 known) | After, gold-audit confirmed (49 known) |
|---|---:|---:|---:|
| Recall@5 | 80.00% (40/50) | 98.00% (49/50) | 100.00% (49/49) |
| Recall@10 | 84.00% (42/50) | 98.00% (49/50) | 100.00% (49/49) |
| Recall@20 | 86.00% (43/50) | 98.00% (49/50) | 100.00% (49/49) |
| Luna/Codex Top-1 | 86.00% (43/50) | 96.00% (48/50) | 97.96% (48/49) |
| AUTO coverage | 78.00% (39/50) | 86.00% (43/50) | 87.76% (43/49) |
| AUTO precision | 100.00% (39/39) | 100.00% (43/43) | 100.00% (43/43) |
| REVIEW rate | 20.00% (10/50) | 12.00% (6/50) | 12.24% (6/49) |
| UNRESOLVED rate | 2.00% (1/50) | 2.00% (1/50) | 0.00% (0/49) |

Safety counters in the after run were all zero: invalid response 0, hard-contradiction promotion 0, filename-only promotion 0, kind collision 0, and API-unsafe promotion 0. `safety_pass = true`.

Recall@10 and AUTO precision meet the requested targets. The raw evaluator's AUTO coverage is 86.00%, one percentage point above the requested 75–85% band; the confirmed-49 denominator is 87.76%. This is reported as measured, not normalized away. The one-point increase is not a gate-policy change; it is the live result of the retrieval changes plus nondeterministic Luna decisions on unchanged cases.

## Gold audit and retrieval diagnosis

The direct audit used the rendered AI originals and the actual body PDF. Body PDF SHA256: `32ec1e2f02e3b088b0b014ca0294823caec8531850d5b68e3ad99d16cfcc8e60`. The INDD file exists, but Adobe InDesign was unavailable for direct extraction; the body-PDF comparison is the authoritative completed comparison.

| Source | Audited target | Gold audit | Baseline retrieval state | Baseline reason | After offline retrieval |
|---:|---|---|---|---|---|
| 7 | `drawing:54` | confirmed | generated, then hard-filtered | `disjoint_feature_pair`; pre rank 1, score 15.987288 | survives; rank 1 |
| 25 | `drawing:12` | confirmed | alive but rank 11 | pre/post rank 11, score 2.120370 | rank 1 |
| 30 | `drawing:23` | confirmed | alive but rank 15 | pre/post rank 15, score 13.945122 | rank 1 |
| 36 | `drawing:64` | rejected gold | generated, then hard-filtered | `disjoint_site_point`; pre rank 53, score 2.128571 | excluded; no fix applied |
| 50 | `illustration:2` panel 1968 | confirmed | alive but tied at rank 134 | score 0.0; drawing 1–10 won the tie | parent identity; rank 3 |
| 51 | `illustration:2` panel 1989 | confirmed | alive but tied at rank 134 | score 0.0; drawing 1–10 won the tie | parent identity; rank 3 |
| 52 | `illustration:2` panel 2007 | confirmed | alive but tied at rank 134 | score 0.0; drawing 1–10 won the tie | parent identity; rank 3 |
| 53 | `illustration:2` panel 2012 | confirmed | alive but tied at rank 134 | score 0.0; drawing 1–10 won the tie | parent identity; rank 3 |

The three root causes were addressed independently:

1. Source 7 had multiple contextual feature pairs from labels inside a composite figure. The hard feature-pair filter now applies only when the source has exactly one explicit pair. A single-pair contradiction remains a hard filter.
2. `유구현황도` was added to map-type normalization, and an exact filename/body map-type match is an ordering signal only. It does not create strong evidence or change the AUTO gate.
3. `삽도2-1` through `삽도2-4` are normalized to the canonical weak identity `illustration:2`. Panel/year information remains weak; no panel was promoted from filename-only evidence.

## Live Luna cases

The final live output shows:

- Source 7: `drawing:54`, rank 1, `AUTO_VERIFIED`, confidence 0.99, `auto_verified`.
- Source 25: `drawing:12` rank 1, but Luna selected `drawing:13`; `REVIEW_REQUIRED`, confidence 0.98, `assignment_conflict`. This is a resolver/assignment outcome, not a Recall@10 miss.
- Source 30: `drawing:23`, rank 1, `AUTO_VERIFIED`, confidence 0.99, `auto_verified`.
- Source 36: `UNRESOLVED`, as expected for the rejected gold assignment; no retrieval fix was applied.
- Sources 50–53: all selected `illustration:2` at rank 3. Source 50 was `AUTO_VERIFIED`; sources 51–53 were `REVIEW_REQUIRED` with `assignment_conflict`, because the four audited panels share one canonical parent identity. They are not filename-only promotions and do not create a safety counter.

No confirmed gold case was an incorrect AUTO decision. The only confirmed known Top-1 miss was source 25, which remained review-required. The six unknown gold rows were not used in the confirmed precision/recall denominator.

## TDD evidence

RED tests were added before the production changes:

```text
python -m pytest backend/tests/test_drawing_candidate_generator_v3.py -q
9 passed, 3 failed
```

The three failures covered contextual multi-pair filtering, semantic map filename retrieval, and illustration-panel parent identity. After the minimal retrieval fixes:

```text
python -m pytest backend/tests/test_drawing_candidate_generator_v3.py -q
12 passed

python -m pytest backend/tests/test_drawing_candidate_generator_v3.py backend/tests/test_drawing_context_normalizer_v2.py backend/tests/test_drawing_evidence_v3_models.py backend/tests/test_drawing_evidence_v3_evaluator_contract.py backend/tests/test_drawing_evidence_v3_evaluator_safety.py backend/tests/test_drawing_visual_support_gate.py -q
29 passed
```

The offline generator measurement over the actual source corpus was 56 AI files / 828 body packets, with 49 confirmed known cases and Recall@10 49/49. The live result is recorded separately in the JSON/MD acceptance artifacts linked below.

The full Windows backend collection was also attempted. Collection stopped at the pre-existing platform incompatibility `os.O_DIRECTORY` in `backend/app/services/file_store.py`; this was not changed as part of retrieval TDD. The targeted regression suite above passed.

## Reproduction and artifacts

Run from `D:/Coding/adobe-free-provenance-revalidation-20260824`:

```powershell
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
$env:DRAWING_CODEX_MODEL='gpt-5.6-luna'
$env:DRAWING_CODEX_REASONING_EFFORT='high'
$env:DRAWING_CODEX_TURN_TIMEOUT_SECONDS='180'
python tools/evaluate_drawing_evidence_v3.py --source-root "D:/Coding/archaeology-document-review-system/src" --gold docs/local_drawing_evidence_v3_manual_verified_50_gold.json --output-json docs/local_drawing_evidence_v3_luna_retrieval_tdd_2656d.json --output-report docs/local_drawing_evidence_v3_luna_retrieval_tdd_2656d.md --live-codex --render-dir docs/local_drawing_evidence_v3_luna_retrieval_tdd_2656d_render
```

The live evaluator recorded `live_codex=true`, `model=gpt-5.6-luna`, `reasoning_effort=high`, `turn_timeout_seconds=180`, `ai_files=56`, and `body_packets=828`. The run used the working tree based on HEAD `2656d189cec72300c9ef3c1b01a936ce50887a7d`; the committed retrieval-TDD SHA is recorded in the final Git history.

Artifacts:

- `docs/local_drawing_evidence_v3_recall_miss_gold_audit.json` and `.md`: direct gold audit and pre-filter diagnostics.
- `docs/local_drawing_evidence_v3_luna_retrieval_tdd_2656d.json` and `.md`: complete live 56-source result.
- `docs/local_drawing_evidence_v3_retrieval_tdd_report.json`: machine-readable summary of this report.
