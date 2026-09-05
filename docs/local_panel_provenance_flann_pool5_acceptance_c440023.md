# Local FLANN Panel Provenance Acceptance (candidate pool 5)

- Measurement HEAD: `c440023fd6211dd12e15c77227b656a41356b2ca`
- Source root: `/Users/misyong2/Code/archaeology-document-review-system/src` (read-only: `True`)
- Elapsed: `3,079.313 s` (about 51 m 19 s)

## Command

```sh
uv run --directory backend python ../tools/evaluate_panel_provenance_hybrid.py \
  --source-root ../src \
  --geometric-candidate-pool 5 \
  --geometric-matcher flann \
  --output-json ../tmp/flann-pool5/panel-provenance-flann-pool5.json \
  --output-report ../tmp/flann-pool5/panel-provenance-flann-pool5.md
```

The raw JSON remains in ignored `tmp/` and is not committed because it is a
large local measurement artifact. The source corpus was not modified.

## Result

| Metric | Result |
| --- | ---: |
| Plate PDFs | 3 |
| JPG candidates / decodable | 1,032 / 1,032 |
| Parsed panels / segmented panels | 2,804 / 2,750 |
| Tier-0 pixel matches | 75 |
| Tier-1 SIFT/RANSAC matches | 1,710 |
| Geometric attempts | 2,675 |
| Final `DERIVED_VERIFIED` panels | 1,745 |
| Verified physical geometries | 1,717 |
| Coverage over segmented panels | 63.4545% |
| Coverage over segmented geometries | 63.1482% |
| FLANN to BF fallback | 0 |

Final unresolved counts are `UNRESOLVED=1,019` and
`UNRESOLVED_COLLISION=40`. Collision rows are excluded from automatic
promotion. No human gold set was supplied, so this run does not claim recall
or precision.

## Safety

- Safety pass: `True`
- Source root mutated: `False`
- Filename-only, path-only, and caption-only promotion: 0
- Pixel-threshold and geometric-gate bypass: 0
- Within-revision collision promotion: 0
- VLM auto-promotion: disabled
