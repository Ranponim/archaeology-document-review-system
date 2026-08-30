from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def recall_at_k(
    rows: Iterable[Mapping[str, Any]],
    *,
    ks: Sequence[int] = (1, 3, 5),
) -> dict[str, int | float]:
    """Compute retrieval recall over human-resolved gold rows only.

    Rows with no ``correct_source_asset_id`` are intentionally excluded from
    the denominator: they represent human-unresolved examples rather than a
    known retrieval target.
    """

    normalized_ks = tuple(sorted({int(k) for k in ks}))
    if not normalized_ks or normalized_ks[0] < 1:
        raise ValueError("ks must contain positive integers")

    resolved_rows: list[Mapping[str, Any]] = []
    for row in rows:
        correct = row.get("correct_source_asset_id")
        if correct is not None and str(correct).strip():
            resolved_rows.append(row)

    total = len(resolved_rows)
    result: dict[str, int | float] = {"gold_resolved_count": total}
    for k in normalized_ks:
        hits = 0
        for row in resolved_rows:
            correct = str(row["correct_source_asset_id"])
            ranked_raw = row.get("ranked_source_asset_ids") or ()
            ranked = [str(value) for value in ranked_raw]
            if correct in ranked[:k]:
                hits += 1
        result[f"recall_at_{k}"] = hits / total if total else 0.0
    return result


def classify_revision_collisions(
    verified_candidates: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Separate unsafe within-revision collisions from valid revision reuse."""

    scope_source_panels: dict[tuple[str, str], list[str]] = defaultdict(list)
    source_scopes: dict[str, set[str]] = defaultdict(set)

    for row in verified_candidates:
        source = str(row.get("source_asset_id") or "").strip()
        scope = str(row.get("uniqueness_scope_id") or "").strip()
        panel = str(row.get("panel_id") or "").strip()
        if not source or not scope or not panel:
            continue
        scope_source_panels[(scope, source)].append(panel)
        source_scopes[source].add(scope)

    collision_groups = {
        key: tuple(sorted(panel_ids))
        for key, panel_ids in scope_source_panels.items()
        if len(panel_ids) > 1
    }
    cross_revision_sources = sorted(
        source for source, scopes in source_scopes.items() if len(scopes) > 1
    )

    return {
        "within_revision_collision_group_count": len(collision_groups),
        "within_revision_collision_panel_count": sum(
            len(panel_ids) for panel_ids in collision_groups.values()
        ),
        "cross_revision_reuse_source_count": len(cross_revision_sources),
        "cross_revision_reuse_sources": cross_revision_sources,
    }
