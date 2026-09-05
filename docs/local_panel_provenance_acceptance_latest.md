# Local Panel Provenance Acceptance

- Measurement HEAD: `39a5ddc3b6302df26710e6d8ba9775dc075e8bc0`
- Source root: `D:\Coding\archaeology-document-review-system\src` (read-only: `True`)
- Plate PDFs: **3**
- JPG candidates: **1032** (decodable: 1032)
- Panels: **2804** total / **2750** segmented

## Deterministic results

- Local VERIFIED before batch uniqueness: **75**
- Final DERIVED_VERIFIED: **56**
- Coverage over segmented: **2.0364%**
- Within-revision collision groups: **3**
- Within-revision collision panels: **19**
- Cross-revision reused JPG sources: **12**

## Retrieval / gold

- No human gold supplied; Recall@K is intentionally not claimed.

## Safety

- filename-only promotion: **0**
- path-only promotion: **0**
- caption-only promotion: **0**
- threshold bypass: **0**
- within-revision collision promotion: **0**
- source root mutated: **False**
- Safety pass: **True**

> VLM auto-promotion is disabled. AI-supported decisions require separate gold-set precision validation.

## HEAD

- Requested and measured HEAD: `39a5ddc3b6302df26710e6d8ba9775dc075e8bc0`
- Worktree: detached read-only evaluation worktree at that exact commit.
- Production code was not modified.

## Command

```powershell
python tools/evaluate_panel_provenance.py `
  --source-root "D:/Coding/archaeology-document-review-system/src" `
  --output-json "docs/local_panel_provenance_acceptance_latest.json" `
  --output-report "docs/local_panel_provenance_acceptance_latest.md"
```

`--limit-panels` was omitted. No gold file was supplied. Runner defaults were retained: `minimum_score=0.97`, `minimum_margin=0.03`, `top_k=5`.

## Environment

- Windows PowerShell
- Python `3.13.3`
- Git `2.49.0.windows.1`
- PyMuPDF `1.28.2`, Pillow `11.2.1`, NumPy `2.3.0`
- Source root: `D:\Coding\archaeology-document-review-system\src`
- Full run elapsed: `349.072 s`
- Runner exit code: `0`

The first auxiliary direct-import probe omitted `PYTHONPATH` and returned `ModuleNotFoundError: No module named 'app'`. Repeating it with `PYTHONPATH=backend` returned `imports=ok`; the runner itself inserts `backend` into `sys.path`. This was an environment probe issue, not an E2E failure.

## Corpus Summary

| item | measured |
|---|---:|
| Plate PDFs | 3 |
| candidate JPG/JPEG | 1,032 |
| decodable candidates | 1,032 |
| undecodable candidates | 0 |
| total parsed panels | 2,804 |
| safely segmented panels | 2,750 |
| insufficient bbox/panel | 54 |

Each PDF produced 18 insufficient panels. The three PDF byte counts and SHA-256 values were:

| PDF revision | bytes | SHA-256 |
|---|---:|---|
| `11.19-2차 교정/...-도판-2차 교정.pdf` | 605,977,352 | `eec19ab01299928a66ae3b8cc1d62a3da5532bca864dea0550a5ccbb89f6d327` |
| `11.21-3차 교정/...-도판-3차 교정.pdf` | 606,386,769 | `aa43e1f21be6212026216a669d89714d8393471c7cf3c4014fb44a9e05eb1c46` |
| `11.8-본문-1차 교정/...-도판-1차 교정.pdf` | 584,303,711 | `0a7e9ff2950ffba373c563c2110614c1dffc50cbec45ab11e5f7025a3afc47d9` |

## Deterministic Result

| deterministic status | count | interpretation |
|---|---:|---|
| `VERIFIED` before revision uniqueness | 75 | score >= 0.97 and margin >= 0.03 |
| `DERIVED_VERIFIED` final | 56 | verified and unique within PDF revision |
| `BELOW_SCORE` | 2,565 | top-1 score < 0.97 |
| `AMBIGUOUS_MARGIN` | 110 | score >= 0.97 but margin < 0.03 |
| `INSUFFICIENT_PANEL` | 54 | parser emitted `bbox_status=insufficient`, `bbox=null` |
| `NO_CANDIDATE` | 0 | no empty candidate matrix/row recorded |
| `UNRESOLVED_COLLISION` | 19 | same source selected by multiple panels in one PDF revision |
| other final `UNRESOLVED` | 2,729 | below-score + ambiguous + insufficient |

- Coverage over segmented: `56 / 2,750 = 2.0364%`
- Coverage over total: `56 / 2,804 = 1.9971%`
- Scored unresolved panels: `2,694`; final unresolved including insufficient and collision: `2,748`
- No segmented row was recorded as a separate fingerprint-extraction failure. The 54 no-score rows all had `bbox_status=insufficient`; the runner does not expose a finer embedded-image extraction subreason.

## Score Distribution

Top-1 scores for all 2,750 segmented panels:

| percentile | score |
|---|---:|
| p50 | 0.949345129 |
| p75 | 0.958138978 |
| p90 | 0.966739813 |
| p95 | 0.973203891 |
| p99 | 0.998380055 |

Top-1 scores for the 2,694 scored final-unresolved panels:

| percentile | score |
|---|---:|
| p50 | 0.948897059 |
| p75 | 0.957402727 |
| p90 | 0.965319010 |
| p95 | 0.969798368 |
| p99 | 0.986406863 |

Score bands for scored final-unresolved panels are `[lower, upper)` except the final band:

| score band | count |
|---|---:|
| 0.95 <= score < 0.97 | 1,120 |
| 0.90 <= score < 0.95 | 1,394 |
| score < 0.90 | 51 |
| score >= 0.97 | 129 |

The `score >= 0.97` unresolved rows are 110 margin failures plus 19 collision rows. Among `BELOW_SCORE` rows, the 1,120 rows in 0.95--0.97 are 43.7%; 1,445 rows are below 0.95. Thus the threshold is the immediate gate for 2,565 rows, but the distribution is not concentrated only immediately below 0.97.

## Margin Distribution

Margin distribution for all segmented panels:

| percentile | margin |
|---|---:|
| p50 | 0.006181067 |
| p75 | 0.021127259 |
| p90 | 0.037601486 |
| p95 | 0.047466299 |
| p99 | 0.066088388 |

Margin distribution for scored final-unresolved panels:

| percentile | margin |
|---|---:|
| p50 | 0.005934053 |
| p75 | 0.019863473 |
| p90 | 0.035669424 |
| p95 | 0.045101103 |
| p99 | 0.064878217 |

- Direct margin-gate failures: **110** (`4.00%` of segmented).
- Raw margin `< 0.03`: **2,329** scored unresolved rows; 2,219 of these are also below score and are reported as `BELOW_SCORE` because the runner checks score first.
- Margin bands across segmented rows: `<0.01`: 1,661; `0.01--0.03`: 668; `0.03--0.05`: 312; `>=0.05`: 109.

## Collision Analysis

- Within-revision collision groups/pairs: **3**.
- Within-revision collision panel instances: **19**.
- Within-revision collision promotions: **0**.
- Cross-revision source JPGs reused: **12** source IDs.

The uniqueness scope is `plate-pdf:<relative PDF path>`. Therefore, reuse of the same JPG across different PDF revisions is allowed by the measured policy; reuse by multiple panels in the same PDF revision is rejected. The three exhaustive collision groups were:

| PDF revision | source JPG | panels |
|---|---|---:|
| `11.19-2차 교정` | `도판(사진들)/Links/65 (3).JPG` | 7 |
| `11.21-3차 교정` | `도판(사진들)/Links/65 (3).JPG` | 7 |
| `11.8-본문-1차 교정` | `도판(사진들)/Links/65 (3).JPG` | 5 |

The seven collision rows on the 2차 revision all carry the same measured bbox `[0.270985, 0.295455, 0.718802, 0.462963]` and the same top-1 score `0.998380055`, which is direct evidence of repeated panel geometry in the parsed input. No collision was promoted.

## Top-K / Gold Metrics

No human gold was supplied to this runner. Therefore:

> gold 미지정으로 Recall@K 미측정.

The raw JSON retains the top-5 ranked candidates for every scored panel, so a separately audited gold can be joined later without rerunning this corpus scan. No Recall@1, Recall@3, or Recall@5 value is claimed here.

## Failure Category Breakdown

The runner provides deterministic gate evidence, not human identity labels. The following categories are measured from the actual rows:

| category | count | data-grounded finding |
|---|---:|---|
| parser bbox unavailable | 54 | `bbox_status=insufficient`, `bbox=null`; no candidate ranking exists |
| below score | 2,565 | top-1 score is below the unchanged 0.97 threshold |
| margin gate | 110 | top-1 is at least 0.97 but top-2 separation is below 0.03 |
| same-revision collision | 19 | uniqueness scope rejects repeated top-1 source within one PDF |
| no candidate corpus | 0 | 1,032/1,032 JPG/JPEG candidates decoded; candidate matrix was nonempty |

The following requested visual root-cause labels cannot be counted from this run without a human gold or an explicit embedded-image-to-source identity audit: source JPG absent, crop mismatch, border mismatch, brightness/contrast mismatch, rotation, compression-only mismatch, wrong bbox, and VLM-required cases. Assigning those labels from filename or top-1 score would be speculation and was not done.

## Representative Failure Samples

The tables below contain actual rows. PDF paths are shown with the revision directory abbreviated (`2차`, `3차`, `1차`); the exact full path and panel identity are preserved in `panel_id` and in the JSON. `Top-2` is the second ranked candidate score.

### `BELOW_SCORE` (5 measured samples)

| PDF / page | panel_id | bbox | Top-1 source_asset_id | Top-1 | Top-2 | margin | final status | observed failure |
|---|---|---|---|---:|---:|---:|---|---|
| 2차 / p.5 | `...-2차 교정.pdf:3:1` | `[0.117743,0.101179,0.881524,0.478541]` | `Links/SIEI 북 트렌치 (3).JPG` | 0.953910080 | 0.938901654 | 0.015008426 | `UNRESOLVED` | measured below 0.97; visual identity unconfirmed |
| 2차 / p.7 | `...-2차 교정.pdf:5:1` | `[0.117360,0.101179,0.881141,0.478541]` | `Links/N1 E4 북 (3).JPG` | 0.955300245 | 0.935661765 | 0.019638480 | `UNRESOLVED` | measured below 0.97; visual identity unconfirmed |
| 2차 / p.5 | `...-2차 교정.pdf:3:2` | `[0.117992,0.485027,0.883445,0.862211]` | `Links/2. 조사 중_73.JPG` | 0.947284773 | 0.946940104 | 0.000344669 | `UNRESOLVED` | below score and near-tied top two |
| 2차 / p.6 | `...-2차 교정.pdf:4:1` | `[0.119286,0.099977,0.879989,0.287617]` | `Links/63 (10).JPG` | 0.932295496 | 0.930897672 | 0.001397824 | `UNRESOLVED` | below score; top two nearly tied |
| 2차 / p.30 | `...-2차 교정.pdf:28:1` | `[0.117335,0.483768,0.883082,0.863357]` | `Links/4-1. 출토 유물 세부 (2).JPG` | 0.882081036 | 0.881265319 | 0.000815717 | `UNRESOLVED` | materially below score; visual identity unconfirmed |

### `AMBIGUOUS_MARGIN` (5 measured samples)

| PDF / page | panel_id | bbox | Top-1 source_asset_id | Top-1 | Top-2 | margin | final status | observed failure |
|---|---|---|---|---:|---:|---:|---|---|
| 2차 / p.4 | `...-2차 교정.pdf:2:2` | `[0.119668,0.485017,0.881573,0.862201]` | `Links/2지점 그리드 전경.JPG` | 0.981364890 | 0.955330882 | 0.026034008 | `UNRESOLVED` | score passes, margin fails |
| 2차 / p.80 | `...-2차 교정.pdf:78:2` | `[0.117448,0.291698,0.883027,0.479713]` | `Links/64 (1).JPG` | 0.973563879 | 0.960926011 | 0.012637868 | `UNRESOLVED` | score passes, margin fails |
| 2차 / p.85 | `...-2차 교정.pdf:83:1` | `[0.117804,0.099918,0.497047,0.287687]` | `Links/조사 전 (1).JPG` | 0.970768229 | 0.962174479 | 0.008593750 | `UNRESOLVED` | score passes, margin fails |
| 2차 / p.95 | `...-2차 교정.pdf:93:1` | `[0.117507,0.099965,0.496738,0.287622]` | `Links/2. 조사 중_44.JPG` | 0.971940104 | 0.946717984 | 0.025222120 | `UNRESOLVED` | score passes, margin fails |
| 2차 / p.121 | `...-2차 교정.pdf:119:8` | `[0.505000,0.675697,0.880952,0.863417]` | `Links/2. 조사 중_61.JPG` | 0.976102941 | 0.965494792 | 0.010608149 | `UNRESOLVED` | score passes, margin fails |

### `UNRESOLVED_COLLISION` (5 of 19 measured samples)

| PDF / page | panel_id | bbox | Top-1 source_asset_id | Top-1 | Top-2 | margin | final status | observed failure |
|---|---|---|---|---:|---:|---:|---|---|
| 2차 / p.109 | `...-2차 교정.pdf:107:1` | `[0.270985,0.295455,0.718802,0.462963]` | `Links/65 (3).JPG` | 0.998380055 | 0.933501838 | 0.064878217 | `UNRESOLVED_COLLISION` | same revision/source selected repeatedly |
| 2차 / p.109 | `...-2차 교정.pdf:107:2` | `[0.270985,0.295455,0.718802,0.462963]` | `Links/65 (3).JPG` | 0.998380055 | 0.933501838 | 0.064878217 | `UNRESOLVED_COLLISION` | same revision/source selected repeatedly |
| 2차 / p.109 | `...-2차 교정.pdf:107:3` | `[0.270985,0.295455,0.718802,0.462963]` | `Links/65 (3).JPG` | 0.998380055 | 0.933501838 | 0.064878217 | `UNRESOLVED_COLLISION` | same revision/source selected repeatedly |
| 2차 / p.109 | `...-2차 교정.pdf:107:4` | `[0.270985,0.295455,0.718802,0.462963]` | `Links/65 (3).JPG` | 0.998380055 | 0.933501838 | 0.064878217 | `UNRESOLVED_COLLISION` | same revision/source selected repeatedly |
| 2차 / p.109 | `...-2차 교정.pdf:107:5` | `[0.270985,0.295455,0.718802,0.462963]` | `Links/65 (3).JPG` | 0.998380055 | 0.933501838 | 0.064878217 | `UNRESOLVED_COLLISION` | same revision/source selected repeatedly |

### `INSUFFICIENT_PANEL` (5 of 54 measured samples)

| PDF / page | panel_id | bbox | Top-1 source_asset_id | Top-1 | Top-2 | margin | final status | observed failure |
|---|---|---|---|---:|---:|---:|---|---|
| 2차 / p.63 | `...-2차 교정.pdf:61:4` | `null` | `null` | — | — | — | `UNRESOLVED` | parser `bbox_status=insufficient` |
| 2차 / p.107 | `...-2차 교정.pdf:105:1` | `null` | `null` | — | — | — | `UNRESOLVED` | parser `bbox_status=insufficient` |
| 2차 / p.107 | `...-2차 교정.pdf:105:2` | `null` | `null` | — | — | — | `UNRESOLVED` | parser `bbox_status=insufficient` |
| 2차 / p.107 | `...-2차 교정.pdf:105:3` | `null` | `null` | — | — | — | `UNRESOLVED` | parser `bbox_status=insufficient` |
| 2차 / p.134 | `...-2차 교정.pdf:132:5` | `null` | `null` | — | — | — | `UNRESOLVED` | parser `bbox_status=insufficient` |

## Evidence-Limited Visual Diagnosis

An auxiliary read-only recomputation of the representative top-1 candidates found both `original_full` and `original_center80` winning views. For example, the p.6 `63 (10).JPG` samples used `original_center80`, while the p.5 `SIEI 북 트렌치 (3).JPG` samples used `original_full`; the collision sample used `original_full`. This demonstrates that the existing fingerprint views are exercised on real data, but it does **not** prove crop, border, brightness, rotation, or source-identity correctness without gold. No such visual label is promoted to a root cause in this report.

Answers grounded in this run:

- A. The 0.97 threshold is the immediate rejection condition for 2,565 rows, but scores are broad: 1,394 are below 0.95 and 51 below 0.90. Threshold-only causality is not established.
- B. Source absence versus PDF/JPG representation difference is not measurable without gold/source identity audit. Candidate corpus absence is not observed: all 1,032 candidates decoded.
- C. The margin gate directly rejects 110 rows (`4.00%` of segmented); 2,219 additional below-score rows also have raw margin <0.03 but are classified by score first.
- D. Cross-revision reuse is allowed by the measured PDF-scoped uniqueness key; same-revision reuse is rejected with 19 collision rows and zero collision promotions.
- E. Deterministic gate failures are observable and reproducible, but deterministic recall/accuracy cannot be judged without gold. No matcher improvement is claimed.
- F. VLM need is not established by this run. The data shows unresolved score/margin/bbox gates, not a verified set of cases requiring VLM.

## Comparison With Previous Acceptance

Previous acceptance JSON: `local_adobe_free_panel_acceptance_2178581.json` (HEAD `217858174161e6441876eb4a7ebca0c8280d39ef`).

| metric | previous | current |
|---|---:|---:|
| plate PDFs | 3 | 3 |
| JPG candidates | 1,032 | 1,032 |
| total parsed panels | 2,804 | 2,804 |
| segmented panels | 2,750 | 2,750 |
| local verified/match | 87 | 75 |
| final `DERIVED_VERIFIED` | 68 | 56 |
| coverage over segmented | 2.4727% | 2.0364% |
| collision panels | 19 | 19 |
| unresolved segmented | 2,682 | 2,694 |

The corpus is the same: all three PDF sizes/SHA-256 values above match the previous acceptance JSON, and all 2,804 parsed panel bboxes compare exactly equal. Threshold and margin are also unchanged.

The change is therefore code-path/algorithmic, not corpus drift:

1. Previous acceptance used production `VisualAssetMatcher.match_panels` with its batch path and retained exposure-normalized/autocontrast fingerprint variants.
2. Current `39a5ddc` adds `tools/evaluate_panel_provenance.py`, which uses the read-only runner's vectorized candidate matrix and the current matcher contract.
3. The current matcher diff removes the autocontrast fingerprint variants and represents the PDF panel as one raw grayscale fingerprint; candidate scoring uses six crop/border views. Row comparison found 12 previous local matches now below score, and 28 previously scored local rows changed score; the largest observed decrease was `0.016919424`. This explains the 87→75 local-match difference while corpus and thresholds remain fixed.

## Source Root Mutation Check

- Runner compares a before/after recursive source snapshot of relative path, file size, and nanosecond mtime.
- Result JSON: `source_root_mutated=false`, `source_root_read_only=true`.
- `/src` remained outside the output paths; output JSON/Markdown were written under the evaluation worktree's `docs/` directory.
- No source file was modified, deleted, or moved.

## Conclusion

`NEXT: more local evidence required`

The deterministic E2E is reproducible and safety-pass, but the requested visual root-cause labels and Recall@K require an audited gold/source-identity mapping. No production code, threshold, matcher policy, or VLM fallback was changed in this run.
