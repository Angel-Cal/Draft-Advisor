import pandas as pd
import pytest
from src.data.pipeline import advance_to_prediction_season


@pytest.fixture
def inputs():
    prediction_df = pd.DataFrame({
        "player_id": ["a", "b"], "age": [24, 30], "years_exp": [2, 8], "implied_total": [20.0, 21.0]})
    roster = pd.DataFrame({
        "gsis_id": ["a", "a"], "week": [1, 5], "position": ["WR", "WR"], "team": ["OAK", "KC"],
        "birth_date": [pd.Timestamp("2001-08-15")] * 2, "years_exp": [3, 3]})
    totals = pd.DataFrame({"team": ["LV", "KC"], "season": [2026, 2026], "implied_total": [22.5, 27.0]})
    return prediction_df, roster, totals


def test_roster_player_gets_prediction_season_values(inputs):
    row = advance_to_prediction_season(*inputs).set_index("player_id").loc["a"]
    assert row["age"] == 25                 # born 2001-08-15, age on 2026-09-01
    assert row["years_exp"] == 3
    assert row["implied_total"] == 22.5     # week-1 team (legacy OAK -> LV), not the later KC listing


def test_player_missing_from_roster_is_advanced_by_one(inputs):
    row = advance_to_prediction_season(*inputs).set_index("player_id").loc["b"]
    assert row["age"] == 31 and row["years_exp"] == 9
    assert pd.isna(row["implied_total"])
