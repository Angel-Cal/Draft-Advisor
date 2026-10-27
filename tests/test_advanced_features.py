import numpy as np
import pandas as pd
import pytest
from src.features import advanced as adv


def test_xfp_features_ignore_playoff_weeks():
    # regular seasons ran 17 weeks through 2020 and 18 from 2021: weeks beyond that are playoff games
    opp = pd.DataFrame({"player_id": ["a"] * 5, "season": [2020, 2020, 2021, 2021, 2021], "week": [17, 18, 18, 19, 22],
                        "total_fantasy_points": [10.0, 99.0, 5.0, 99.0, 99.0], "total_fantasy_points_exp": [12.0, 99.0, 6.0, 99.0, 99.0]})
    out = adv.build_xfp_features(opp).set_index("season")
    assert out.loc[2021, "xfp_ppr_prev"] == 12.0 and out.loc[2021, "fp_over_exp_prev"] == -2.0 and out.loc[2021, "xfp_pg_prev"] == 12.0
    assert out.loc[2022, "xfp_ppr_prev"] == 6.0 and out.loc[2022, "xfp_pg_prev"] == 6.0


def test_xfp_features_are_lagged_one_season():
    opp = pd.DataFrame({"player_id": ["a", "a", "a"], "season": [2020, 2020, 2021], "week": [1, 2, 1],
                        "total_fantasy_points": [10.0, 20.0, 5.0], "total_fantasy_points_exp": [12.0, 14.0, 6.0]})
    out = adv.build_xfp_features(opp).set_index("season")
    assert list(out.index) == [2021, 2022]                      # stats from 2020 are keyed to 2021
    assert out.loc[2021, "xfp_ppr_prev"] == 26.0 and out.loc[2021, "fp_over_exp_prev"] == 4.0
    assert out.loc[2021, "xfp_pg_prev"] == 13.0


def test_volatility_features_use_played_regular_season_weeks_and_lag_one_season():
    points = [10.0, 30.0, 10.0, 30.0]
    weekly = pd.DataFrame({"player_id": ["a"] * 5 + ["short"] * 3, "season": 2020,
                           "week": [1, 2, 3, 4, 19, 1, 2, 3], "season_type": ["REG"] * 4 + ["POST"] + ["REG"] * 3,
                           "fantasy_points_ppr": points + [99.0] + [5.0, 15.0, 25.0]})
    out = adv.build_volatility_features(weekly).set_index("player_id")
    assert out.loc["a", "season"] == 2021                                          # 2020 weeks describe the player entering 2021
    assert out.loc["a", "weekly_sd_prev"] == pytest.approx(np.std(points, ddof=1))
    assert out.loc["a", "weekly_cv_prev"] == pytest.approx(np.std(points, ddof=1) / 20.0)
    assert out.loc["a", "weekly_boom_prev"] == 0.5                                   # 30-point weeks; the playoff 99 is ignored
    assert out.loc["short", adv.ADVANCED_GROUPS["volatility"]].isna().all()          # 3 games: too few for a spread


def test_role_features_count_plays_on_the_field():
    participation = pd.DataFrame({
        "nflverse_game_id": ["g1"] * 4, "play_id": [1, 2, 3, 4], "possession_team": ["KC"] * 4,
        "offense_players": ["a;b", "a;b", "a", "a;b"]})
    pbp = pd.DataFrame({"game_id": ["g1"] * 4, "play_id": [1, 2, 3, 4], "season": 2020, "season_type": "REG",
                        "pass": [1, 1, 0, 0], "rush": [0, 0, 1, 1]})
    out = adv.build_role_features(participation, pbp).set_index("player_id")
    assert out.loc["a", "pass_snap_share_prev"] == 1.0 and out.loc["a", "rush_snap_share_prev"] == 1.0
    assert out.loc["b", "pass_snap_share_prev"] == 1.0 and out.loc["b", "rush_snap_share_prev"] == 0.5
    assert set(out["season"]) == {2021}


def test_depth_tiers_match_across_chart_formats():
    old = pd.DataFrame({"season": [2024.0] * 3, "depth_position": ["HB", "WR", "WR"], "depth_team": ["1", "1", "2"],
                        "gsis_id": ["rb", "wr1", "wr3"]})
    new = pd.DataFrame({"dt": ["2025-09-01T00:00:00Z"] * 5 + ["2025-09-10T00:00:00Z"],
                        "pos_abb": ["RB", "WR", "WR", "WR", "WR", "RB"], "pos_rank": [1, 1, 2, 3, 9, 1],
                        "gsis_id": ["rb2", "w1", "w2", "w3", "w9", "late"]})
    out = adv.build_depth_features(old, {2025: new}).set_index(["player_id", "season"])["depth_tier_wk1"]
    assert out[("rb", 2024)] == 1 and out[("wr1", 2024)] == 1 and out[("wr3", 2024)] == 2
    assert out[("rb2", 2025)] == 1 and out[("w1", 2025)] == 1 and out[("w2", 2025)] == 1 and out[("w3", 2025)] == 2
    assert ("w9", 2025) not in out.index            # tier beyond the old charts' depth is dropped
    assert ("late", 2025) not in out.index          # snapshots after the opener are not pre-season information


def test_team_epa_features_use_prior_season_of_the_starting_team():
    pbp = pd.DataFrame({"season": [2020] * 4, "season_type": "REG", "posteam": ["OAK"] * 4,
                        "play_type": ["pass", "pass", "run", "run"], "epa": [0.4, 0.2, -0.1, 0.1], "success": [1, 0, 0, 1]})
    roster = pd.DataFrame({"gsis_id": ["p"], "season": [2021], "week": [1], "team": ["LV"], "position": ["WR"]})
    out = adv.build_team_epa_features(pbp, roster).iloc[0]
    assert out["season"] == 2021 and out["team_pass_epa_prev"] == pytest.approx(0.3)
    assert out["team_rush_epa_prev"] == pytest.approx(0.0) and out["team_success_prev"] == pytest.approx(0.5)
