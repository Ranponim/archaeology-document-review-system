# Adobe-free real panel to JPG acceptance

Measurement was run on commit `217858174161e6441876eb4a7ebca0c8280d39ef`
against the real read-only source root:
`D:/Coding/archaeology-document-review-system/src`.

## Corpus

- Plate PDFs: 3
- JPG candidates: 1,032; decodable: 1,032; undecodable: 0
- Total parsed panels: 2,804
- Safely segmented panels: 2,750
- Insufficient panels: 54
- Production API: `VisualAssetMatcher.match_panels()`
- Minimum score: `0.97`
- Minimum margin: `0.03`
- Collision scope: per PDF

## Measured result

| Metric | Count | Rate |
|---|---:|---:|
| Local high-confidence matches | 87 | 3.16% of segmented |
| Final DERIVED_VERIFIED panels | 68 | 2.47% of segmented; 2.43% of total |
| Collision-selected panels rejected | 19 | 3 source/PDF pairs |
| Unresolved segmented panels | 2,682 | 97.53% of segmented |
| Unresolved total panels | 2,736 | 97.57% of total |

## Per-PDF result

| PDF | Total | Segmented | Local matches | Collision | Final verified |
|---|---:|---:|---:|---:|---:|
| PDF 1 | 934 | 916 | 24 | 7 | 17 |
| PDF 2 | 934 | 916 | 23 | 7 | 16 |
| PDF 3 | 936 | 918 | 40 | 5 | 35 |

## Status counts

```text
DERIVED_VERIFIED: 68
UNRESOLVED_COLLISION: 19
UNRESOLVED_NO_LOCAL_MATCH: 2663
UNRESOLVED (insufficient bbox): 54
```

All collisions were fail-closed. No filename-only, path-only, or caption-only
promotion occurred. Threshold bypasses were zero, source-root mutation was false,
and `safety_pass=true`.

The complete per-panel record contains bbox, local score, final score, selected
source path, and final status:
`local_adobe_free_panel_acceptance_2178581.json`.

This is the actual corpus performance result, separate from the code regression
result (`60 passed` for the latest matcher/reference/drawing test set).
