from __future__ import annotations

from app.services.panel_provenance_evaluation import (
    classify_revision_collisions,
    recall_at_k,
)


def test_recall_at_k_excludes_human_unresolved_rows():
    rows = [
        {
            "panel_id": "p1",
            "correct_source_asset_id": "a",
            "ranked_source_asset_ids": ["a", "b", "c"],
        },
        {
            "panel_id": "p2",
            "correct_source_asset_id": "c",
            "ranked_source_asset_ids": ["a", "b", "c"],
        },
        {
            "panel_id": "p3",
            "correct_source_asset_id": "f",
            "ranked_source_asset_ids": ["a", "b", "c", "d", "e", "f"],
        },
        {
            "panel_id": "p4",
            "correct_source_asset_id": "z",
            "ranked_source_asset_ids": ["a", "b", "c"],
        },
        {
            "panel_id": "p5",
            "correct_source_asset_id": None,
            "ranked_source_asset_ids": ["a"],
        },
    ]

    metrics = recall_at_k(rows, ks=(1, 3, 5))

    assert metrics["gold_resolved_count"] == 4
    assert metrics["recall_at_1"] == 0.25
    assert metrics["recall_at_3"] == 0.50
    assert metrics["recall_at_5"] == 0.50


def test_revision_collision_metrics_separate_valid_reuse_from_real_collision():
    verified_candidates = [
        {"panel_id": "a1", "uniqueness_scope_id": "pdf-a", "source_asset_id": "photo-x"},
        {"panel_id": "a2", "uniqueness_scope_id": "pdf-a", "source_asset_id": "photo-x"},
        {"panel_id": "b1", "uniqueness_scope_id": "pdf-b", "source_asset_id": "photo-x"},
        {"panel_id": "b2", "uniqueness_scope_id": "pdf-b", "source_asset_id": "photo-y"},
        {"panel_id": "c1", "uniqueness_scope_id": "pdf-c", "source_asset_id": "photo-y"},
    ]

    metrics = classify_revision_collisions(verified_candidates)

    assert metrics["within_revision_collision_group_count"] == 1
    assert metrics["within_revision_collision_panel_count"] == 2
    assert metrics["cross_revision_reuse_source_count"] == 2
    assert metrics["cross_revision_reuse_sources"] == ["photo-x", "photo-y"]
