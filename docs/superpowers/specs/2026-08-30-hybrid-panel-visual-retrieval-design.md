# Hybrid Panel Visual Retrieval Design

## Context

The current real-corpus acceptance is not useful as a primary matching system: 2,804 parsed panels / 2,750 segmented panels produced only 56 final `DERIVED_VERIFIED` matches (2.0364% segmented coverage). The current engine is therefore retained only as a very-high-precision Tier-0 shortcut.

The approved redesign is retrieval-first. The system must try to locate the original JPG for every safely segmented PDF panel, while keeping canonical provenance safety fail-closed.

## Goal

Introduce a hybrid visual retrieval path that materially broadens candidate matching beyond pixel-near-identity without weakening existing canonical provenance invariants.

## Architecture

```text
PDF panel
  -> Tier 0 pixel matcher (existing 0.97 score / 0.03 margin unchanged)
  -> if unresolved: pixel candidate shortlist
  -> SIFT local-feature matching
  -> RANSAC homography verification
  -> strong geometric winner => visual match
  -> otherwise unresolved / review
```

The first implementation is deliberately model-free and hermetic. It uses OpenCV SIFT/RANSAC rather than downloading DINO/SigLIP model weights in CI. The interface leaves room for a later embedding candidate generator if local Recall@K proves the pixel shortlist is insufficient.

## Tier 0 invariant

The existing deterministic pixel threshold remains unchanged:

- `minimum_score = 0.97`
- `minimum_margin = 0.03`

A Tier-0 verified result keeps method `pixel_thumbnail_similarity`.

## Tier 1 geometric retrieval

For a Tier-0 unresolved panel:

1. retain a ranked pixel shortlist of up to 50 source JPG candidates;
2. compute SIFT keypoints/descriptors for the panel once;
3. cache SIFT descriptors for candidate JPGs;
4. use KNN descriptor matching with Lowe ratio `0.75`;
5. estimate a homography with RANSAC;
6. accept a geometric match only when all gates pass:
   - at least 12 RANSAC inliers;
   - inlier ratio at least 0.55;
   - at least 8 percentage points of geometric-score separation from the runner-up.

Geometric score is bounded to `[0, 1]` and combines inlier ratio with inlier support. A geometric result is explicitly tagged `sift_ransac`; it must never be confused with the pixel score.

## Collision / duplicate geometry

The same source JPG used by genuinely distinct panels in one PDF revision remains fail-closed.

However, parser aliases that have the same revision scope, physical page and numerically identical bbox represent the same physical panel geometry. Repeated aliases for that exact geometry must not manufacture a collision. Collision uniqueness is therefore counted by distinct geometry keys, not raw panel IDs.

Reuse of one JPG across distinct PDF revisions remains allowed.

## Safety

The following never become verification evidence:

- filename numbers;
- source path text;
- captions;
- publication sequence numbers.

No score threshold is lowered. VLM auto-promotion remains disabled. Geometric verification is based only on image content.

## Local acceptance

Local `/src` remains the real-corpus acceptance gate. CI is responsible for hermetic correctness/regression.

The updated local runner must report separately:

- Tier-0 pixel verified count;
- Tier-1 `sift_ransac` verified count;
- final unique verified count;
- coverage over segmented;
- geometric candidate-pool misses when a supplied gold file is available;
- duplicate-geometry aliases;
- true same-revision source collisions;
- Recall@1/3/5 when gold is supplied.

The current baseline to beat is 56 / 2,750 = 2.0364% final coverage. A higher coverage number alone is not sufficient evidence of correctness; gold Recall/precision must be measured before broad auto-promotion is treated as production-ready.

## Definition of Done

- CI RED first proves SIFT/RANSAC can recover a crop/resize/rotation case that the Tier-0 threshold rejects.
- CI RED first proves identical panel geometry aliases do not create a false collision while genuinely distinct panels still do.
- Minimal production implementation makes those tests green.
- Existing Drawing Gold/safety, backend hermetic, frontend, and real Neo4j CI remain green.
- A read-only local hybrid E2E runner is committed for the user to execute on `/src`.
- No claim is made about real-corpus improvement until that local run is completed.
