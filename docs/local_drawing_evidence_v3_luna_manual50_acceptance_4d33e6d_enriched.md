# Latest HEAD Luna full acceptance report

## Execution

- HEAD: 4d33e6d700e76e75e663e8d05e049e9d4eaaff70
- Model: gpt-5.6-luna
- Reasoning effort: high
- Turn timeout: 180 seconds
- Live Codex: true (Codex SDK path; OPENAI_API_KEY unset)
- Source root: D:/Coding/archaeology-document-review-system/src (read-only)
- Evaluated: 56 sources; known gold 50; unknown gold 6
- Unknown gold source indices: 29, 31, 35, 37, 39, 41
- Elapsed: 1886.144 seconds; exit code: 0

Exact command:

~~~powershell
python tools/evaluate_drawing_evidence_v3.py --source-root "D:/Coding/archaeology-document-review-system/src" --gold docs/local_drawing_evidence_v3_manual_verified_50_gold.json --output-json docs/local_drawing_evidence_v3_luna_manual50_acceptance_4d33e6d.json --output-report docs/local_drawing_evidence_v3_luna_manual50_acceptance_4d33e6d.md --live-codex --render-dir docs/local_drawing_evidence_v3_luna_manual50_acceptance_4d33e6d_render
~~~

## Metrics

| Metric | Result | Denominator / note |
|---|---:|---|
| Recall@5 | 80.00% | known gold 50 |
| Recall@10 | 84.00% | known gold 50 |
| Recall@20 | 86.00% | known gold 50 |
| Luna Top-1 accuracy | 86.00% | known gold 50 |
| AUTO coverage | 78.00% | 39/50 known |
| AUTO precision | 100.00% | 39 AUTO known; wrong AUTO 0 |
| REVIEW rate | 20.00% | 10/50 known |
| UNRESOLVED rate | 2.00% | 1/50 known |

Unknown gold rows were excluded from accuracy, coverage, precision, review, and unresolved denominators.

## Acceptance gates

| Gate | Result |
|---|---|
| Recall@10 >= 99% | FAIL (84%) |
| AUTO coverage 75-85% | PASS (78%) |
| AUTO precision >= 99% | PASS (100%) |
| REVIEW <= 25% | PASS (20%) |
| All safety counters zero | PASS |
| Overall acceptance | FAIL (Recall@10 gate) |

## Safety counters

| Counter | Count |
|---|---:|
| invalid response | 0 |
| hard contradiction promoted | 0 |
| filename-only promoted | 0 |
| kind/assignment collision | 0 |
| API unsafe promotion | 0 |

safety_pass = true.

## Wrong known Top-1

| Source index | Gold | Luna identity | Status | Gate reason | Confidence |
|---:|---|---|---|---|---:|
| 7 | ["drawing","54"] | null | UNRESOLVED | verdict_none | 0.98 |
| 25 | ["drawing","12"] | ["drawing","11"] | REVIEW_REQUIRED | confidence_below_threshold | 0.88 |
| 36 | ["drawing","64"] | null | REVIEW_REQUIRED | verdict_not_match | 0.99 |
| 50 | ["illustration","2"] | ["drawing","1"] | REVIEW_REQUIRED | assignment_conflict | 0.98 |
| 51 | ["illustration","2"] | ["drawing","1"] | REVIEW_REQUIRED | assignment_conflict | 0.99 |
| 52 | ["illustration","2"] | ["drawing","3"] | REVIEW_REQUIRED | assignment_conflict | 0.96 |
| 53 | ["illustration","2"] | ["drawing","3"] | REVIEW_REQUIRED | confidence_below_threshold | 0.94 |

Wrong AUTO: none. Every known row promoted to AUTO was gold-correct.

## REVIEW_REQUIRED and unresolved cause classification

| Gate reason | All rows | Known rows | Source indices |
|---|---:|---:|---|
| assignment_conflict | 6 | 6 | 2,5,16,50,51,52 |
| confidence_below_threshold | 2 | 2 | 25,53 |
| invalid_support_evidence | 1 | 1 | 12 |
| verdict_none | 1 | 1 | 7 |
| verdict_not_match | 5 | 1 | 29,31,36,37,39 |

- REVIEW_REQUIRED: 14 total = 10 known + 4 unknown; indices 2,5,12,16,25,29,31,36,37,39,50,51,52,53.
- Runtime UNRESOLVED: 1 known row, source index 7 (verdict_none).
- The 6 unknown gold rows remain unknown; no guessed gold identity was introduced.

## Per-source evidence

The raw result JSON contains all 56 source paths, Top-N candidates, Luna selection, confidence, status, gate reason, cited support families/IDs, and visual-support flags. The enriched JSON provides the same per-source acceptance view keyed by source index and was independently recomputed against the 50 verified gold rows.

## Reproducibility and integrity

- metrics_match_recomputed = true.
- The original docs/local_drawing_evidence_v3_gold_template.json was not modified; the manual 50-known/6-unknown gold file was used separately.
- /src and body PDFs were not modified by this acceptance run.
- Full streaming execution log is retained in docs/local_drawing_evidence_v3_luna_manual50_acceptance_4d33e6d.log.
