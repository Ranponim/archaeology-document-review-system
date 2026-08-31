# Local Drawing Evidence Graph v2 Revalidation

## Purpose

Run the real `/src` acceptance test for `drawing-evidence-v2` on the local workstation after pulling the feature branch. This test is intentionally not executed in GitHub CI because the real source assets are local-only.

The source tree is read-only. Do not rename, move, overwrite, or generate files under `src`.

## Accepted v1 baseline

The previous local v1 run recorded:

- AI files: 56
- filename-labeled AI: 35
- Direct: 1
- Derived verified: 3
- Heuristic-only: 23
- Ambiguous: 10
- Unresolved: 19
- Blinded Top-1: 8/35 (22.8571%)
- Blinded Top-3: 13/35 (37.1429%)
- Filename-only verified: 0
- Known reviewed false verified: 0

## Pull and focused verification

```powershell
git switch feature/adobe-free-provenance-20260823
git pull

cd backend
python -m compileall -q app
pytest -q `
  tests/test_drawing_context_normalizer_v2.py `
  tests/test_drawing_evidence_graph_resolver_v2.py `
  tests/test_drawing_evidence_repository_v2.py `
  tests/test_drawing_evidence_repository_v2_context.py `
  tests/test_drawing_evidence_corpus_service_v2.py `
  tests/test_drawing_evidence_resolver_config.py `
  tests/test_drawing_evidence_graph_evaluator_contract.py
cd ..
```

Do not continue to the real-data run if the focused suite is red.

## Run v1 again for same-machine comparison

```powershell
python tools/evaluate_drawing_evidence_graph.py `
  --source-root src `
  --resolver-version v1 `
  --output-json docs/local_drawing_evidence_v1_compare_metrics.json `
  --output-report docs/local_drawing_evidence_v1_compare_report.md `
  --blinded
```

This catches dataset or package-version drift before comparing v2.

## Run v2

```powershell
python tools/evaluate_drawing_evidence_graph.py `
  --source-root src `
  --resolver-version v2 `
  --output-json docs/local_drawing_evidence_v2_metrics.json `
  --output-report docs/local_drawing_evidence_v2_report.md `
  --blinded
```

The evaluator refuses output paths inside `src`.

## v2 acceptance gate

All of these conditions must be satisfied:

- Blinded Top-1 > 8/35
- Blinded Top-3 > 13/35
- Derived verified > 3/56
- Direct >= 1/56
- `filename_only_verified_count == 0`
- `kind_collision_count == 0`
- `hard_contradiction_promoted_count == 0`
- the existing direct identifier remains direct
- no Adobe/COM/ExtendScript is used

Do not lower thresholds only to satisfy this gate.

### Interpretation

If all acceptance conditions pass, v2 is eligible for explicit production opt-in.

If recall does not improve, or any safety counter is non-zero, keep v1 as production default and treat v2 as experimental. Commit the report anyway; a failed acceptance result is useful evidence and must not be hidden.

## Production opt-in after acceptance only

The application defaults to v1. After the local v2 report passes the gate, v2 can be selected explicitly:

```powershell
$env:DRAWING_EVIDENCE_RESOLVER_VERSION = "v2"
```

To return to the accepted default:

```powershell
Remove-Item Env:DRAWING_EVIDENCE_RESOLVER_VERSION -ErrorAction SilentlyContinue
```

An unknown resolver value is rejected at startup rather than silently choosing a resolver.

## Required local commit after running `/src`

Commit these generated outputs so the result can be reviewed remotely:

- `docs/local_drawing_evidence_v1_compare_metrics.json`
- `docs/local_drawing_evidence_v1_compare_report.md`
- `docs/local_drawing_evidence_v2_metrics.json`
- `docs/local_drawing_evidence_v2_report.md`

Suggested commit message:

```text
test: record local drawing evidence v2 revalidation
```

The completion report should state the commit SHA, v1/v2 Top-1 and Top-3, direct/derived/heuristic/ambiguous/unresolved counts, the three safety counters, and whether v2 passed the acceptance gate.
