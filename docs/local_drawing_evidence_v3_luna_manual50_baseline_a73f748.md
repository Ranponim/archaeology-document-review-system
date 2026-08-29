# Drawing evidence v3 local evaluation

- Resolver: **drawing-evidence-v3**
- Live Codex: **true**
- Gold known: **50**
- Gold unknown: **6**

## Retrieval and decision quality

- Recall@5: **76.00%**
- Recall@10: **88.00%**
- Recall@20: **92.00%**
- Codex Top-1 accuracy: **68.00%**
- Auto coverage: **36.00%**
- Auto precision: **88.89%**
- Review rate: **60.00%**
- Unresolved rate: **4.00%**

## Safety

- Invalid response: **0**
- Hard contradiction promoted: **0**
- Filename-only promoted: **0**
- Kind/assignment collision: **0**
- API unsafe promotion: **0**

## Acceptance gates

- Recall@10 >= 99%
- Auto coverage 75-85%
- Auto precision >= 99%
- Review <= 25%
- All safety counters = 0

> Unknown gold rows are excluded from accuracy, coverage, and precision denominators.
