from app.jobs.run_inputs import body_stages_for_round


def test_round_one_only_needs_current_body_stage():
    assert body_stages_for_round("1차") == ("1차",)


def test_round_four_uses_previous_and_current_without_fixed_stage_table():
    assert body_stages_for_round("4차") == ("3차", "4차")


def test_round_twenty_is_supported():
    assert body_stages_for_round("20차") == ("19차", "20차")


def test_non_round_legacy_stage_falls_back_to_single_stage():
    assert body_stages_for_round("legacy") == ("legacy",)
