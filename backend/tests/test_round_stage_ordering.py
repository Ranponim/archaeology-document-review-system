import pytest

from app.services.round_stage_ordering import ordered_round_stage_versions


def test_orders_arbitrary_numbered_rounds():
    pages = {"19차": [], "20차": []}
    ids = {"19차": "v19", "20차": "v20"}
    assert ordered_round_stage_versions(pages, ids) == [("v19", "19차"), ("v20", "20차")]


def test_rejects_missing_numbered_round_gap():
    pages = {"3차": [], "5차": []}
    ids = {"3차": "v3", "5차": "v5"}
    with pytest.raises(ValueError):
        ordered_round_stage_versions(pages, ids)


def test_single_round_has_no_gap_requirement():
    assert ordered_round_stage_versions({"40차": []}, {"40차": "v40"}) == [("v40", "40차")]
