# Codex-first Drawing Evidence v3 Design

Date: 2026-08-26
Status: Approved design, awaiting implementation plan
Branch: `feature/adobe-free-provenance-20260823`

## 1. Purpose

The current drawing evidence v2 resolver is safe but not operationally accurate enough. On the local `/src` revalidation set it achieved blinded Top-1 9/35 (25.7%) and Top-3 14/35 (40.0%). It correctly avoids unsafe promotion, but it leaves too much work unresolved or incorrectly ranked.

v3 must become an operational resolver rather than a rule-matching experiment.

The chosen operating model is:

- automatically resolve 75-85% of source drawings;
- require human review for no more than 15-25%;
- keep precision of automatically verified matches at or above 99%;
- use Codex for every source-level AI decision;
- keep local code responsible for extraction, candidate preparation, deterministic safety checks, provenance, and review workflow;
- send only the required drawing crop plus minimal candidate crop/context to the external Codex call;
- keep `/src` read-only.

The design intentionally avoids a multi-model cascade. There is no separate VLM, LLM judge, cross-encoder, embedding service, or learned calibration model in the first v3 implementation. Codex is the only AI decision engine.

## 2. Design principles

### 2.1 Codex is the single AI authority, not the only authority

Every source drawing is submitted to Codex. Codex performs semantic and visual candidate comparison, but its answer is accepted only if deterministic safety rules pass.

A Codex answer can never override:

- an explicit publication-kind contradiction;
- an explicit site/grid contradiction when both sides are known;
- an explicit feature-type + feature-number contradiction when both sides are known;
- one-source-to-conflicting-target constraints;
- invalid or invented candidate/evidence identifiers.

### 2.2 Fail closed

If evidence is insufficient, Codex must return `ambiguous` or `none`. The system must not force a match merely to increase coverage.

### 2.3 Candidate recall before automatic coverage

The local candidate generator is not required to rank the correct drawing first. Its primary requirement is to retain the true answer in a sufficiently broad candidate pool.

The first operational retrieval target is:

- candidate Recall@10 >= 99% on the gold benchmark;
- if Top-10 recall is not sufficient, candidate generation must be improved before tuning Codex thresholds.

### 2.4 Explainability and provenance

Every final decision must retain:

- source asset identity and SHA-256;
- candidate drawing identity;
- structured facts used;
- body reference/caption context identifiers;
- source and candidate image/crop identifiers;
- Codex request/run identifier;
- Codex model name;
- Codex verdict, confidence, reason codes, and cited evidence identifiers;
- deterministic contradictions;
- final system decision and reason.

## 3. High-level architecture

```text
/src source AI and body PDF
          |
          v
Local evidence extraction
  - PDF-compatible AI text
  - source render
  - structured archaeology facts
  - body drawing/reference contexts
  - body drawing crops
          |
          v
Local candidate preparation
  - publication-kind partition
  - deterministic contradiction filtering
  - structured/token/sequence ranking
  - retain broad Top-K
          |
          v
Codex decision for EVERY source
  - source crop/render
  - candidate crops
  - captions/minimal body context
  - structured evidence
  - candidate/evidence IDs
          |
          v
Strict response validation
          |
          v
Deterministic safety gate
          |
     +----+----------------+
     |                     |
AUTO_VERIFIED       REVIEW_REQUIRED / UNRESOLVED
     |                     |
     +----------+----------+
                v
         Neo4j provenance
                |
                v
        Human review feedback
```

## 4. Local evidence extraction

### 4.1 Source drawing observation

Extend the current Adobe-free source observer rather than replacing it.

For every source AI file, produce a `DrawingSourceEvidencePacket` containing:

- source asset ID;
- SHA-256;
- relative source path;
- original filename;
- extracted PDF-compatible text;
- explicit internal drawing identifiers, if any;
- publication kind when explicitly present in internal content;
- normalized archaeology facts;
- rendered preview image path/reference;
- source image dimensions and render metadata.

Filename number remains weak metadata and must not independently verify an identity.

### 4.2 Body drawing evidence

For every canonical body drawing/reference identity, retain:

- publication kind;
- drawing number;
- each individual mention context;
- caption/reference text;
- nearby minimal context;
- physical/printed page;
- normalized archaeology facts;
- drawing visual region/crop when detectable;
- previous/next body drawing identity where known.

Mention contexts remain separate. Neighbor text may be attached to a mention but must not be counted as an independent consensus mention.

### 4.3 Drawing crop extraction

The body PDF must expose a visual candidate for Codex.

Preferred extraction order:

1. use embedded image/vector bounds when the PDF exposes a reliable region near the matching caption/reference;
2. otherwise render the page at high resolution and derive a graphic region relative to the caption/reference bbox;
3. if one region cannot be identified confidently, retain multiple crop candidates for that body drawing rather than inventing a single precise crop.

Crop extraction confidence is evidence, not an identity decision.

## 5. Candidate preparation

The first v3 implementation deliberately avoids a complex retrieval stack.

### 5.1 Candidate partition

Candidates are first partitioned by explicit publication kind when known. Unknown kind does not create a contradiction.

### 5.2 Hard contradiction filtering

Remove candidates only when both sides contain explicit contradictory values for a hard field:

- publication kind;
- site point;
- grid;
- feature type + feature number pair.

Period, map type, and year remain strong negative evidence but should not remove a candidate when extraction quality is uncertain; they can instead lower local rank and be shown to Codex as contradictions.

### 5.3 Broad local ranking

Use existing v2 normalized facts as a baseline and add simple retrieval signals without introducing another AI model:

- exact structured fact overlap;
- normalized token overlap;
- exact specialist identifiers such as grid, feature number, section label, year;
- source-folder/site grouping;
- previous/next source order and previous/next body order as weak sequence evidence;
- filename/path only as weak diagnostics/tie-breakers.

The scoring implementation may change internally, but it must expose per-signal evidence rather than a single opaque score.

### 5.4 Candidate pool size and fallback

Default candidate pool: Top 10.

If Codex returns `none`, `ambiguous`, or a response that fails validation because the correct candidate may be outside the pool, the resolver may perform one bounded expansion using the next same-kind candidates (up to 20 total) and call Codex again.

The system must measure whether the gold target was present in Top 5, Top 10, and expanded Top 20.

This bounded expansion is preferred over introducing more models in v3.

## 6. Codex decision service

### 6.1 One AI implementation

Introduce a dedicated `CodexDrawingResolverClient` using the OpenAI Responses API and a configurable Codex model that supports image input.

Configuration must be separate from the existing OpenRouter review service so current document-review behavior is not silently changed.

Required configuration:

- `OPENAI_API_KEY`;
- `DRAWING_CODEX_MODEL`;
- request timeout;
- maximum candidate count;
- maximum retry/expansion count;
- automatic-verification confidence threshold.

The model name is configuration, not hard-coded business logic.

### 6.2 Every source is sent to Codex

v3 must invoke Codex for every source drawing, including cases that look obvious deterministically. Deterministic evidence still controls safety, but it does not bypass the Codex call.

This gives one consistent measurable decision path for the initial operational release.

### 6.3 Minimal external payload

The Codex request contains only what is needed to decide the current identity:

Source:

- source render/crop;
- extracted source text;
- normalized structured facts;
- relative folder context where useful;
- source evidence IDs.

For each candidate:

- candidate ID;
- candidate drawing crop(s), limited to the necessary region;
- caption/reference text;
- minimal nearby context;
- normalized structured facts;
- local evidence/contradiction IDs;
- weak sequence relation summary.

Do not upload the complete 24+ GB source tree, whole unrelated PDFs, or unrelated pages.

### 6.4 Codex prompt contract

Codex receives a closed-world matching task:

- compare only the supplied candidates;
- do not invent another drawing identity;
- inspect visual structure and textual/archaeological evidence together;
- explicitly prefer `ambiguous` when two candidates remain plausible;
- explicitly prefer `none` when no supplied candidate is supported;
- cite only supplied evidence IDs;
- report contradictions;
- return JSON matching the response schema.

### 6.5 Response schema

The required response is logically equivalent to:

```json
{
  "verdict": "match | ambiguous | none",
  "candidate_id": "drawing:... | null",
  "confidence": 0.0,
  "cited_support_ids": [],
  "cited_contradiction_ids": [],
  "reason_codes": [],
  "summary": "short explanation"
}
```

Validation rules:

- `match` requires exactly one supplied candidate ID;
- `ambiguous` and `none` cannot create a canonical target;
- all cited IDs must exist in the submitted packet;
- confidence must be in [0, 1];
- malformed JSON or an invented candidate/evidence ID invalidates the decision;
- one retry for transport/format failure is allowed; repeated failure becomes `REVIEW_REQUIRED`, not an unsafe promotion.

## 7. Final decision policy

### 7.1 AUTO_VERIFIED

A candidate can become `AUTO_VERIFIED` only when all are true:

1. Codex verdict is `match`;
2. selected candidate is from the submitted candidate set;
3. Codex confidence meets the configured threshold determined from the gold benchmark;
4. at least two independent supporting evidence families are cited, and one must be non-filename/non-path;
5. no hard contradiction exists;
6. cited evidence IDs validate;
7. global source/target constraints are satisfied.

### 7.2 REVIEW_REQUIRED

Use `REVIEW_REQUIRED` when:

- Codex returns `ambiguous`;
- confidence is below the automatic threshold;
- Codex and deterministic safety evidence disagree;
- response validation fails after the allowed retry;
- multiple global assignments conflict;
- candidate pool expansion still does not produce a safe automatic match.

### 7.3 UNRESOLVED

Use `UNRESOLVED` when:

- Codex returns `none` after the bounded candidate expansion;
- no candidate survives deterministic hard filtering;
- required visual/text evidence cannot be produced sufficiently for a meaningful comparison.

## 8. Human review

Human review is an intentional production path, not a failure mode.

Target review workload: 15-25% of sources.

For each review case, the UI should show:

- source render;
- Codex-selected candidate when one exists;
- the top alternatives;
- candidate crops;
- captions;
- key structured matches/contradictions;
- short Codex rationale;
- actions: approve candidate, choose another candidate, or mark none.

Human resolution must be persisted as gold feedback with algorithm/model version and timestamp.

## 9. Gold benchmark

The current filename-derived 35 labels are silver labels and are insufficient to certify a 99% automatic precision target.

Before enabling v3 automatic promotion as the production default, create a human-verified gold mapping for the current 56 source AI files where possible.

Each gold row records:

- source asset/path;
- correct publication kind;
- correct body drawing identity;
- verification source (`human`);
- optional notes;
- `unknown` when a defensible truth cannot be established.

The gold set must never infer truth merely from the filename number.

Later operational validation should accumulate at least several hundred independently verified auto-eligible cases across multiple reports before claiming statistically strong 99% production precision.

## 10. Evaluation and acceptance

### 10.1 Retrieval metrics

Measure on gold-known rows:

- Recall@5;
- Recall@10;
- Recall@20 after bounded expansion;
- mean candidate count.

Primary gate:

- Recall@10 >= 99%.

If this gate fails, improve candidate generation before changing Codex auto thresholds.

### 10.2 Codex decision metrics

Measure:

- Top-1 accuracy among gold-known rows;
- ambiguous rate;
- none rate;
- accuracy by confidence bucket;
- accuracy with and without visual crop availability;
- retry/invalid-response rate.

Targets:

- Codex Top-1 >= 90% as a development goal;
- correct answer represented in the final review/automatic path >= 99%.

### 10.3 Operational metrics

Production acceptance targets:

- auto-verified coverage: 75-85%;
- auto-verified precision: >= 99%;
- human review rate: <= 25%;
- hard-contradiction auto-promotions: 0;
- filename-only auto-promotions: 0;
- publication-kind collisions: 0;
- invalid Codex response promoted: 0;
- external API failure causing unsafe promotion: 0.

The auto confidence threshold must be selected from measured gold results, not guessed in code.

## 11. Neo4j provenance

Extend the current drawing evidence graph rather than replacing it.

Persist at minimum:

- `CodexDecision` or equivalent resolution run node;
- model/version;
- request/run ID;
- verdict and confidence;
- candidate set identity;
- cited support/contradiction evidence edges;
- visual crop identity;
- final status;
- human override when applicable.

`TARGETS` may still be created only for direct evidence or safely auto/human verified derived evidence. `ambiguous`, `review_required`, and `unresolved` must not silently create canonical targets.

## 12. Versioning and rollout

- Keep v1/v2 available for regression comparison.
- Add v3 as an explicit resolver version, e.g. `drawing-evidence-v3`.
- Production default remains the existing safe version until local `/src` v3 acceptance passes.
- Run v3 in shadow/evaluation mode first: create candidates and Codex decisions without changing existing canonical targets.
- After the gold acceptance gates pass, enable v3 automatic target creation explicitly.
- Do not lower safety thresholds to achieve the 75-85% coverage target.

## 13. Failure handling

- OpenAI API timeout/rate limit: retry only according to bounded client policy, then route to review.
- Missing source render: send available text evidence but do not auto-promote unless the measured gold policy explicitly proves the evidence combination is safe.
- Missing candidate crop: keep candidate with text/structured evidence and mark visual evidence unavailable.
- Malformed Codex output: reject and retry once; repeated failure routes to review.
- Candidate not in packet: reject response.
- Evidence ID not in packet: reject response.
- Hard contradiction: never auto-promote.
- `/src` mutation attempt: fail the evaluator/run.

## 14. Testing strategy

Implementation must follow TDD and include:

- source evidence packet tests;
- body crop association tests;
- candidate hard-filter tests;
- candidate Top-K contract tests;
- Codex request serialization tests with image and evidence references;
- Codex closed-world response validation tests;
- invented candidate/evidence rejection tests;
- ambiguous/none routing tests;
- confidence threshold routing tests;
- API failure fail-closed tests;
- Neo4j provenance persistence tests;
- v1/v2 compatibility tests;
- evaluator tests for gold, silver, Recall@K, Codex accuracy, coverage, and precision.

Network calls in normal CI must use deterministic fakes/mocks. Real Codex/API evaluation is a local `/src` acceptance step and must not be required for hermetic CI.

## 15. Non-goals for first v3 implementation

The first v3 release will not add:

- a separate VLM service;
- a separate LLM judge;
- cross-encoder reranking;
- dense embedding infrastructure;
- vector database retrieval;
- GNN/Node2Vec training;
- learned confidence calibration;
- domain fine-tuning;
- automatic modification of `/src`.

These may be reconsidered only if the simple Codex-first design cannot meet the measured operational gates.

## 16. Definition of done

The implementation is complete only when:

1. every source can be packaged and sent through the single Codex decision path;
2. the resolver is fail-closed for invalid, ambiguous, contradictory, and unavailable-AI cases;
3. human-reviewed gold truth exists for the current evaluable source set;
4. local `/src` evaluation reports candidate Recall@K, Codex accuracy, auto coverage, auto precision, and safety counters;
5. Recall@10 reaches at least 99%;
6. automatic coverage reaches 75-85% while measured automatic precision is at least 99%, or v3 remains shadow/review-only if those gates are not met;
7. unsafe promotion counters remain zero;
8. v1/v2 behavior remains available for regression and rollback;
9. the current PR remains unmerged until explicit user approval.
