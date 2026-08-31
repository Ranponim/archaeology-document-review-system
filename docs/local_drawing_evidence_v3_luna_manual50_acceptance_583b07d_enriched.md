# Drawing evidence v3 latest-HEAD Luna acceptance

- Code HEAD: `583b07dbba883340e7bd8f45c637160df569aa70`
- Commit: `fix: isolate body anchor facts from context`
- Model: `gpt-5.6-luna`; reasoning: `high`; turn timeout: `180s`
- Source: `D:/Coding/archaeology-document-review-system/src` (read-only)
- Evaluated: **56**; known gold: **50**; unknown gold: **6**
- Unknown gold source indices: `29, 31, 35, 37, 39, 41`
- The original gold template was preserved. The six unresolved manual-review rows were not forced into known gold.

## Execution

```text
python tools/evaluate_drawing_evidence_v3.py --source-root "D:/Coding/archaeology-document-review-system/src" --gold docs/local_drawing_evidence_v3_manual_verified_50_gold.json --output-json docs/local_drawing_evidence_v3_luna_manual50_acceptance_583b07d.json --output-report docs/local_drawing_evidence_v3_luna_manual50_acceptance_583b07d.md --live-codex --render-dir docs/local_drawing_evidence_v3_luna_manual50_acceptance_583b07d_render
```

- `OPENAI_API_KEY` was unset; the local Codex SDK path was used.
- Log footer: `ELAPSED_SECONDS=1771.425`, `EXIT_CODE=0`.
- Raw result: `docs/local_drawing_evidence_v3_luna_manual50_acceptance_583b07d.json`
- Execution log: `docs/local_drawing_evidence_v3_luna_manual50_acceptance_583b07d.log`

## Metrics

Accuracy, coverage, precision, review, and unresolved rates use the 50 known rows as denominator. Unknown gold rows do not affect those rates.

| Metric | Result |
|---|---:|
| Recall@5 | 80.00% |
| Recall@10 | 84.00% |
| Recall@20 | 88.00% |
| Luna/Codex Top-1 accuracy | 88.00% (44/50) |
| AUTO coverage | 84.00% (42/50 known rows) |
| AUTO precision | 100.00% (42/42) |
| REVIEW rate | 12.00% (6/50 known rows) |
| UNRESOLVED rate | 4.00% (2/50 known rows) |

Status across all 56 rows: `AUTO_VERIFIED=43`, `REVIEW_REQUIRED=11`, `UNRESOLVED=2`. One of the 43 AUTO rows is intentionally unknown gold source 41 and is excluded from known-gold precision/coverage.

## Acceptance gates

| Gate | Requirement | Result |
|---|---:|---:|
| Recall@10 | >=99% | **FAIL** (84.00%) |
| AUTO coverage | 75-85% | **PASS** (84.00%) |
| AUTO precision | >=99% | **PASS** (100.00%) |
| REVIEW rate | <=25% | **PASS** (12.00%) |
| Safety counters | all zero | **PASS** |

## Safety counters

- `invalid_response_count=0`
- `hard_contradiction_promoted_count=0`
- `filename_only_promoted_count=0`
- `kind_collision_count=0`
- `api_unsafe_promotion_count=0`
- `safety_pass=true`

## Wrong Top-1 (6 known rows)

| Source index | Gold rank | Gold | Luna selection | Status | Gate reason |
|---:|---:|---|---|---|---|
| 7 | - | drawing:54 | - | UNRESOLVED | verdict_none |
| 36 | - | drawing:64 | - | UNRESOLVED | verdict_none |
| 50 | - | illustration:2 | drawing:1 | REVIEW_REQUIRED | confidence_below_threshold |
| 51 | - | illustration:2 | drawing:1 | REVIEW_REQUIRED | assignment_conflict |
| 52 | - | illustration:2 | drawing:3 | REVIEW_REQUIRED | assignment_conflict |
| 53 | - | illustration:2 | - | REVIEW_REQUIRED | verdict_not_match |

## Wrong AUTO

There are **no incorrect AUTO approvals among the 50 known gold rows**. AUTO precision is therefore `42/42=100%`.

## REVIEW_REQUIRED cause classification

| Cause | All rows | Known rows | Unknown-gold rows | Source indices |
|---|---:|---:|---:|---|
| assignment_conflict | 4 | 4 | 0 | 2, 16, 51, 52 |
| confidence_below_threshold | 1 | 1 | 0 | 50 |
| verdict_not_match | 6 | 1 | 5 | 29, 31, 35, 37, 39, 53 |

The 11 review rows consist of six known rows and five of the intentionally unknown rows. Unknown source 41 was AUTO_VERIFIED but excluded from precision and coverage denominators.

## Runtime unresolved

| Source index | Gold | Gate reason |
|---:|---|---|
| 7 | drawing:54 | verdict_none |
| 36 | drawing:64 | verdict_none |

## Per-source evidence

`docs/local_drawing_evidence_v3_luna_manual50_acceptance_583b07d_enriched.json` contains all 56 rows. Each row records source index, manual gold, top-N candidate list, gold rank, Luna selection, confidence, verdict, status, `auto_gate_reason`, cited support families, cited visual-support IDs, and `cited_nonweak_count`. The raw JSON additionally retains full support IDs and Codex summaries.
