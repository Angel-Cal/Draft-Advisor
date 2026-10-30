import pandas as pd

from src.data.validate import check_projection_file
from src.evaluation.frozen_file_outcomes import with_outcomes

TEAMS = ["KC", "BUF"]


def player(player_id, position, team, adp):
    return {"player_id": player_id, "player_name": player_id, "position": position, "team": team, "projected_ppr": 200.0, "projected_half": None,
            "projected_standard": None, "games": 17, "games_delta": 0, "adp": adp, "injury_flag": False, "market_estimate": False, "actual_ppr": None}


def doc():
    return {"schema_version": "v1", "kind": "live", "season": 2026, "adp_source": "fantasypros", "position_rmse": {"QB": 80.0, "RB": 60.0, "WR": 50.0, "TE": 40.0},
            "players": [player("a", "RB", "KC", 1.0), player("b", "WR", "BUF", 2.0), player("c", "WR", "KC", 3.0)]}


def test_a_live_file_becomes_a_backtest_file_with_the_seasons_outcomes():
    seasonal = pd.DataFrame({"player_id": ["a", "b", "x"], "season": [2026, 2026, 2026], "fantasy_points_ppr": [250.456, 120.0, 99.0]})
    weekly = pd.DataFrame({"player_id": ["a", "a", "b", "b"], "season": [2026] * 4, "week": [1, 2, 1, 3], "season_type": ["REG"] * 4, "fantasy_points_ppr": [100.0, 150.456, 50.0, 70.0]})

    out = with_outcomes(doc(), seasonal, weekly, 2026)

    assert out["kind"] == "backtest" and doc()["kind"] == "live"                       # the input is not changed
    by_id = {p["player_id"]: p for p in out["players"]}
    assert by_id["a"]["actual_ppr"] == 250.46 and by_id["c"]["actual_ppr"] == 0.0         # drafted, never played: 0
    assert by_id["a"]["weekly_ppr"][:3] == [100.0, 150.46, None] and len(by_id["a"]["weekly_ppr"]) == 18
    assert by_id["b"]["weekly_ppr"][:3] == [50.0, None, 70.0]
    assert by_id["c"]["weekly_ppr"] == [None] * 18
    assert by_id["a"]["projected_ppr"] == 200.0 and by_id["a"]["adp"] == 1.0              # everything else is copied untouched
    check_projection_file(out)


def test_only_the_requested_season_counts():
    seasonal = pd.DataFrame({"player_id": ["a", "a"], "season": [2025, 2026], "fantasy_points_ppr": [300.0, 100.0]})
    weekly = pd.DataFrame({"player_id": ["a", "a"], "season": [2025, 2026], "week": [1, 1], "season_type": ["REG", "REG"], "fantasy_points_ppr": [300.0, 100.0]})

    out = with_outcomes(doc(), seasonal, weekly, 2026)

    assert out["players"][0]["actual_ppr"] == 100.0 and out["players"][0]["weekly_ppr"][0] == 100.0
