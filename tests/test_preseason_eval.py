import pandas as pd
import pytest

from src.evaluation import preseason_eval as pe
from src.features.role_context import role_caution


def test_role_caution_needs_a_high_absence_share_and_a_new_team_or_a_first_round_rookie():
    df = pd.DataFrame({"absence_share_prev": [0.5, 0.49, 0.9, 0.9, None, 0.8, 0.8],
                       "team_changed":       [1.0, 1.0, 0.0, None, 1.0, 1.0, 0.0],
                       "rookie_r1_teammate": [0.0, 1.0, 0.0, None, 1.0, 0.0, 1.0]})

    assert role_caution(df).tolist() == [True, False, False, False, False, True, True]


def test_season_rows_sum_a_traded_players_results_keep_only_modeled_draftable_wrs_and_score_a_no_show_as_zero(tmp_path):
    snapshot = pd.DataFrame({
        "season": 2026, "player_id": ["a", "b", "c", "d", "e"], "player_name": list("ABCDE"), "position": ["WR", "WR", "WR", "WR", "RB"],
        "team": "KC", "adp": [10, 20, 200, 30, 5], "in_top_adp": [True, True, False, True, True], "projected_ppr": [200.0, 150.0, 100.0, 120.0, 250.0],
        "market_estimate": [False, True, False, False, False], "injury_flag": False, "curve": [180.0, 140.0, 90.0, 110.0, 240.0], "gap": [20.0, 10.0, 10.0, 10.0, 10.0],
        "absence_share_prev": [0.7, None, None, None, None], "team_changed": [1.0, None, None, None, None], "rookie_r1_teammate": [0.0, None, None, None, None],
        "role_caution": [True, False, False, False, False]})
    snapshot.to_csv(tmp_path / "snap.csv", index=False)
    pd.DataFrame({"player_id": ["a", "a", "c", "e", "a"], "season": [2026, 2026, 2026, 2026, 2025], "games": [8, 7, 17, 17, 17],
                  "fantasy_points_ppr": [60.0, 40.0, 90.0, 200.0, 999.0]}).to_parquet(tmp_path / "actuals.parquet")

    rows = pe.season_rows(tmp_path / "snap.csv", tmp_path / "actuals.parquet", 2026).set_index("player_id")

    assert sorted(rows.index) == ["a", "d"]                                    # b is a market row, c is outside the top 150, e is a RB
    assert rows.loc["a", "actual_ppr"] == 100.0 and rows.loc["a", "G"] == 15       # two teams add up, last season's row is ignored
    assert rows.loc["d", "actual_ppr"] == 0.0 and rows.loc["d", "G"] == 0           # drafted, no stats row: scored as zero, and excluded as unhealthy later
    assert bool(rows.loc["a", "flag"]) and not bool(rows.loc["d", "flag"])
    everyone = pe.season_rows(tmp_path / "snap.csv", tmp_path / "actuals.parquet", 2026, draftable_only=False)
    assert sorted(everyone["player_id"]) == ["a", "c", "d"]


def test_errors_are_projection_minus_actual_and_the_slope_residual_is_actual_minus_curve():
    d = pe.with_errors(pd.DataFrame({"oos_pred_ppr": [200.0], "actual_ppr": [150.0], "curve": [170.0]}))

    assert d.loc[0, "over"] == 50.0 and d.loc[0, "curve_over"] == 20.0 and d.loc[0, "resid"] == -20.0
