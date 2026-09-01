# Local FLANN Panel Provenance Acceptance

- Measurement HEAD: `b6b83e49959e4528a80ea0cd4e719d1c8b92faa8`
- Source root: `/Users/misyong2/Code/archaeology-document-review-system/src` (read-only: `True`)
- Evaluation date: 2026-09-01
- Elapsed: `17,902.24 s` (about 4 h 58 m)

## Command

```sh
uv run --directory backend python ../tools/evaluate_panel_provenance_hybrid.py \
  --source-root ../src \
  --geometric-matcher flann \
  --output-json ../tmp/flann-e2e-20260901/panel-provenance-flann.json \
  --output-report ../tmp/flann-e2e-20260901/panel-provenance-flann.md
```

The command is read-only with respect to `src`. The raw JSON is intentionally
kept in ignored `tmp/` because it is a 21 MB local measurement artifact.

## Corpus and retrieval result

| Metric | Result |
| --- | ---: |
| Plate PDFs | 3 |
| JPG candidates / decodable | 1,032 / 1,032 |
| Parsed panels / segmented panels | 2,804 / 2,750 |
| Tier-0 pixel matches | 75 |
| Tier-1 SIFT/RANSAC matches | 2,119 |
| Geometric attempts | 2,675 |
| Final `DERIVED_VERIFIED` panels | 2,107 |
| Verified physical geometries | 2,079 |
| Coverage over segmented panels | 76.6182% |
| Coverage over segmented geometries | 76.4619% |
| FLANN to BF fallback | 0 |

Final unresolved counts are `UNRESOLVED=610` and
`UNRESOLVED_COLLISION=87`. Collision rows are deliberately excluded from
automatic promotion.

## Safety gates

- Source root mutated: `False`
- Safety pass: `True`
- Filename-only, path-only, and caption-only promotion: 0
- Pixel-threshold and geometric-gate bypass: 0
- Within-revision collision promotion: 0
- VLM auto-promotion: disabled

No human gold set was supplied, so this run establishes deterministic coverage
and safety behavior only; it does not claim recall or precision.
