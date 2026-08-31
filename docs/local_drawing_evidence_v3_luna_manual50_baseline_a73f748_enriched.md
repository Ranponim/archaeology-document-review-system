# Drawing evidence v3 live Codex acceptance baseline

- HEAD: `a73f7486093b770998debfe0a213482c97a867b7`
- Model: `gpt-5.6-luna`; reasoning: `high`; turn timeout: `180s`
- Source: `D:/Coding/archaeology-document-review-system/src` (read-only)
- Evaluated: **56**; known gold: **50**; unknown gold: **6**
- Unknown source indices: `29, 31, 35, 37, 39, 41`
- Gold construction: the 50 manually verified single-identity rows are known; the six unresolved rows remain `unknown`; the original template was preserved.

## Execution

```text
python tools/evaluate_drawing_evidence_v3.py --source-root "D:/Coding/archaeology-document-review-system/src" --gold docs/local_drawing_evidence_v3_manual_verified_50_gold.json --output-json docs/local_drawing_evidence_v3_luna_manual50_baseline_a73f748.json --output-report docs/local_drawing_evidence_v3_luna_manual50_baseline_a73f748.md --live-codex --render-dir docs/local_drawing_evidence_v3_luna_manual50_baseline_a73f748_render
```

- API key was unset, so the local Codex SDK path was used.
- Log footer: `ELAPSED_SECONDS=2183.487`, `EXIT_CODE=0`.
- Raw result: `docs/local_drawing_evidence_v3_luna_manual50_baseline_a73f748.json`
- Execution log: `docs/local_drawing_evidence_v3_luna_manual50_baseline_a73f748.log`

## Metrics

All accuracy, coverage, precision, review, and unresolved rates below use the 50 known rows as denominator. The six unknown gold rows are not forced into accuracy.

| Metric | Result |
|---|---:|
| Recall@5 | 76.00% |
| Recall@10 | 88.00% |
| Recall@20 | 92.00% |
| Luna/Codex Top-1 accuracy | 68.00% |
| AUTO coverage | 36.00% (18/50) |
| AUTO precision | 88.8889% (16/18) |
| REVIEW rate | 60.00% (30/50 known rows) |
| UNRESOLVED rate | 4.00% (2/50 known rows) |

Status across all 56 rows: `AUTO_VERIFIED=18`, `REVIEW_REQUIRED=36`, `UNRESOLVED=2`. Visual support was cited in 9 of the 50 known rows.

## Acceptance gates

| Gate | Requirement | Result |
|---|---:|---:|
| Recall@10 | >=99% | **FAIL** (88.00%) |
| AUTO coverage | 75-85% | **FAIL** (36.00%) |
| AUTO precision | >=99% | **FAIL** (88.8889%) |
| REVIEW rate | <=25% | **FAIL** (60.00%) |
| Safety counters | all zero | **PASS** |

## Safety counters

- `invalid_response_count=0`
- `hard_contradiction_promoted_count=0`
- `filename_only_promoted_count=0`
- `kind_collision_count=0`
- `api_unsafe_promotion_count=0`
- `safety_pass=true`

## Wrong Top-1 (16 known rows)

| Source index | Gold rank | Gold | Luna selection | Status | Gate reason |
|---:|---:|---|---|---|---|
| 3 | 2 | drawing:36 | drawing:38 | AUTO_VERIFIED | auto_verified |
| 6 | 2 | drawing:53 | - | UNRESOLVED | verdict_none |
| 11 | 3 | drawing:74 | drawing:56 | REVIEW_REQUIRED | confidence_below_threshold |
| 12 | 7 | drawing:71 | drawing:69 | REVIEW_REQUIRED | confidence_below_threshold |
| 16 | 2 | drawing:115 | drawing:56 | REVIEW_REQUIRED | insufficient_support_families |
| 19 | 4 | drawing:119 | drawing:114 | REVIEW_REQUIRED | insufficient_support_families |
| 20 | 6 | drawing:120 | drawing:119 | AUTO_VERIFIED | auto_verified |
| 23 | 2 | drawing:10 | - | REVIEW_REQUIRED | verdict_not_match |
| 33 | 3 | drawing:2 | drawing:1 | REVIEW_REQUIRED | confidence_below_threshold |
| 36 | 1 | drawing:64 | - | UNRESOLVED | verdict_none |
| 48 | 2 | drawing:9 | - | REVIEW_REQUIRED | verdict_not_match |
| 50 | - | illustration:2 | drawing:1 | REVIEW_REQUIRED | insufficient_support_families |
| 51 | - | illustration:2 | drawing:1 | REVIEW_REQUIRED | insufficient_support_families |
| 52 | - | illustration:2 | drawing:1 | REVIEW_REQUIRED | confidence_below_threshold |
| 53 | - | illustration:2 | drawing:1 | REVIEW_REQUIRED | insufficient_support_families |
| 56 | 3 | illustration:5 | illustration:6 | REVIEW_REQUIRED | confidence_below_threshold |

## Wrong AUTO (2 rows)

| Source index | Gold | Luna selection | Confidence | Visual support | Support families | Non-weak count |
|---:|---|---|---:|---|---|---:|
| 3 | drawing:36 | drawing:38 | 0.99 | true | lexical_support, visual_signature | 2 |
| 20 | drawing:120 | drawing:119 | 0.97 | true | lexical_support, visual_signature | 2 |

These are the two incorrect AUTO approvals behind AUTO precision `16/18=88.8889%`. Both passed the current `auto_verified` gate despite selecting a non-gold candidate.

## REVIEW_REQUIRED cause classification

| Cause | All rows | Known rows | Unknown-gold rows | Source indices |
|---|---:|---:|---:|---|
| assignment_conflict | 1 | 1 | 0 | 2 |
| insufficient_support_families | 15 | 15 | 0 | 4, 10, 13, 14, 16, 19, 22, 42, 44, 47, 49, 50, 51, 53, 54 |
| confidence_below_threshold | 12 | 12 | 0 | 5, 9, 11, 12, 17, 18, 21, 33, 43, 45, 52, 56 |
| verdict_not_match | 8 | 2 | 6 | 23, 29, 31, 35, 37, 39, 41, 48 |

The 36 review rows contain 30 known rows and the six intentionally unknown gold rows.

## Runtime unresolved

| Source index | Gold | Gold rank | Gate reason |
|---:|---|---:|---|
| 6 | drawing:53 | 2 | verdict_none |
| 36 | drawing:64 | 1 | verdict_none |

## Per-source evidence

`docs/local_drawing_evidence_v3_luna_manual50_baseline_a73f748_enriched.json` contains all 56 rows. Each row records source index, manual gold, top-N candidates, gold rank, Luna selection, confidence, verdict, status, `auto_gate_reason`, cited support families, cited visual-support IDs, `cited_nonweak_count`, and safety flags. The raw evaluator JSON additionally retains full support IDs and Codex summaries.
