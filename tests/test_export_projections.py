import json
import numpy as np
import pandas as pd
import pytest
from src.data import validate as v
from src.data.export_projections import PROCESSED, build_backtest, durability_flag, to_document, weekly_lists
from src.draft.market_fallback import fit_position_curves


def seasonal_rows(rows):
    return pd.DataFrame(rows, columns=["player_id", "season", "games", "position", "fantasy_points_ppr"])


def curves():
    ranks = np.arange(1, 21)
    history = pd.concat([pd.DataFrame({"position": p, "position_rank": ranks, "actual_ppr": top - 10.0 * ranks})
                         for p, top in [("QB", 400.0), ("RB", 350.0), ("WR", 300.0), ("TE", 250.0)]])
    return fit_position_curves(history)


def valid_doc(**changes):
    player = {"player_id": "a", "player_name": "A", "position": "WR", "team": "KC", "projected_ppr": 200.0,
              "games": 16, "games_delta": 0, "adp": 5.0, "injury_flag": False, "market_estimate": False}
    doc = {"schema_version": "v1", "kind": "live", "season": 2026, "adp_source": "fantasypros",
           "position_rmse": {"QB": 84.0, "RB": 59.0, "WR": 53.0, "TE": 39.0},
           "players": [player, {**player, "player_id": "b", "player_name": "B"}]}
    return {**doc, **changes}


# ---- durability flag ------------------------------------------------------------------------------------------

def test_durability_flag_needs_two_qualifying_seasons_and_an_average_under_15():
    s = seasonal_rows([("fragile", 2022, 10, "RB", 0), ("fragile", 2023, 12, "RB", 0),
                       ("iron", 2022, 17, "RB", 0), ("iron", 2023, 16, "RB", 0),
                       ("one_year", 2023, 8, "RB", 0),
                       ("short_year_ignored", 2022, 2, "RB", 0), ("short_year_ignored", 2023, 17, "RB", 0)])
    flag = durability_flag(s, before_season=2024)
    assert flag["fragile"] and not flag["iron"]
    assert "one_year" not in flag.index or not flag["one_year"]                # a single season is not enough
    assert "short_year_ignored" not in flag.index or not flag["short_year_ignored"]   # <4 games does not count


def test_durability_flag_is_point_in_time():
    s = seasonal_rows([("p", 2021, 17, "WR", 0), ("p", 2022, 17, "WR", 0), ("p", 2023, 5, "WR", 0)])
    assert not durability_flag(s, before_season=2023)["p"]       # sees 17 and 17
    assert durability_flag(s, before_season=2024)["p"]           # 2023's 5 games now drags the average to 13


# ---- backtest builder -----------------------------------------------------------------------------------------

def backtest_inputs():
    oos = pd.DataFrame({"player_id": ["m1", "m2"], "player_name": ["M One", "M Two"], "position": ["WR", "WR"],
                        "season": 2024, "actual_ppr": [250.0, 100.0], "oos_pred_ppr": [260.0, 120.0]})
    adp = pd.DataFrame({"season": 2024, "player_id": ["m1", "r1", "z1", "m2", "k1"],
                        "name": ["M One", "Rookie", "Never Played", "M Two", "Some Kicker"],
                        "position": ["WR", "WR", "WR", "WR", "K"], "team": ["JAC", "LAR", "TBD", "DAL", "DAL"],
                        "rank": [1, 2, 3, 4, 5], "adp": [1.0, 2.5, 3.0, 4.0, 5.0]})
    training = pd.DataFrame({"player_id": ["m1", "m2"], "season": 2024, "games": [17.0, 8.0], "games_delta": [0.0, -7.0]})
    seasonal = seasonal_rows([("r1", 2024, 15, "WR", 180.0), ("m1", 2022, 17, "WR", 0), ("m1", 2023, 17, "WR", 0),
                              ("m2", 2022, 9, "WR", 0), ("m2", 2023, 8, "WR", 0)])
    return oos, adp, training, seasonal


def test_backtest_pool_is_model_rows_plus_market_rows_with_actuals():
    oos, adp, training, seasonal = backtest_inputs()
    df = build_backtest(2024, oos, adp, training, seasonal, curves()).set_index("player_id")
    assert set(df.index) == {"m1", "m2", "r1", "z1"}                       # the kicker never enters the pool
    assert df.loc["m1", "projected_ppr"] == 260.0 and df.loc["m1", "actual_ppr"] == 250.0
    assert not df.loc["m1", "market_estimate"] and df.loc["r1", "market_estimate"]
    assert df.loc["r1", "actual_ppr"] == 180.0
    assert df.loc["z1", "actual_ppr"] == 0.0                               # drafted, no stats row: scores zero
    assert df["actual_ppr"].notna().all() and df["projected_ppr"].notna().all()


def test_backtest_flags_and_team_spelling():
    oos, adp, training, seasonal = backtest_inputs()
    df = build_backtest(2024, oos, adp, training, seasonal, curves()).set_index("player_id")
    assert df.loc["m1", "team"] == "JAX" and df.loc["r1", "team"] == "LA" and df.loc["z1", "team"] == "FA"
    assert not df.loc["m1", "injury_flag"] and df.loc["m2", "injury_flag"]  # avg 8.5 games before 2024
    assert df.loc["m2", "games"] == 8 and df.loc["m2", "games_delta"] == -7
    assert df["adp"].is_monotonic_increasing                                # sorted by ADP


def weekly_frame():
    rows = [("m1", 2024, w, "REG", 10.0) for w in range(1, 18) if w != 9] + [("r1", 2024, 3, "REG", 180.0),
            ("m1", 2024, 19, "POST", 50.0)]                           # playoff rows are not part of the season
    return pd.DataFrame(rows, columns=["player_id", "season", "week", "season_type", "fantasy_points_ppr"])


def test_weekly_lists_are_regular_season_with_gaps_where_the_player_did_not_play():
    weekly = weekly_lists(weekly_frame(), 2024)

    assert len(weekly["m1"]) == 18 and weekly["m1"][8] is None and weekly["m1"][0] == 10.0
    assert weekly["m1"][17] is None                                     # nothing in week 18, and the playoff week is ignored
    assert weekly["r1"][2] == 180.0 and weekly["r1"].count(None) == 17


def test_backtest_carries_weekly_points_and_a_player_who_never_played_has_none():
    oos, adp, training, seasonal = backtest_inputs()
    oos = oos.assign(actual_ppr=[160.0, 100.0])                          # m1's weekly points sum to 16 x 10
    df = build_backtest(2024, oos, adp, training, seasonal, curves(), weekly_frame()).set_index("player_id")

    assert df.loc["m1", "weekly_ppr"][0] == 10.0 and sum(x for x in df.loc["m1", "weekly_ppr"] if x is not None) == 160.0
    assert df.loc["z1", "weekly_ppr"] == [None] * 18


def test_validator_checks_weekly_points_against_the_season_total():
    players = [{**p, "actual_ppr": 20.0, "weekly_ppr": [10.0, 10.0] + [None] * 16} for p in valid_doc()["players"]]
    v.check_projection_file(valid_doc(kind="backtest", players=players))
    with pytest.raises(v.DataIntegrityError, match="add up"):
        v.check_projection_file(valid_doc(kind="backtest", players=[{**players[0], "actual_ppr": 25.0}, players[1]]))
    with pytest.raises(v.DataIntegrityError, match="18 weeks"):
        v.check_projection_file(valid_doc(kind="backtest", players=[{**players[0], "weekly_ppr": [20.0]}, players[1]]))


def test_backtest_document_passes_validation():
    oos, adp, training, seasonal = backtest_inputs()
    df = build_backtest(2024, oos, adp, training, seasonal, curves())
    v.check_projection_file(to_document(df, 2024, "backtest", "fantasypros"))


# ---- validator ------------------------------------------------------------------------------------------------

def test_projection_validator_accepts_a_clean_file():
    v.check_projection_file(valid_doc())


@pytest.mark.parametrize("change, message", [
    ({"schema_version": "v2"}, "schema_version"),
    ({"kind": "other"}, "kind"),
    ({"position_rmse": {"QB": 84.0}}, "position_rmse"),
    ({"players": []}, "no players"),
])
def test_projection_validator_rejects_bad_headers(change, message):
    with pytest.raises(v.DataIntegrityError, match=message):
        v.check_projection_file(valid_doc(**change))


def test_projection_validator_rejects_bad_rows():
    base = valid_doc()["players"]
    bad = {
        "duplicate player_id": [base[0], {**base[1], "player_id": "a"}],
        "unexpected positions": [base[0], {**base[1], "position": "K"}],
        "unknown team": [base[0], {**base[1], "team": "XXX"}],
        "nulls in projected_ppr": [base[0], {**base[1], "projected_ppr": None}],
        "outside": [base[0], {**base[1], "projected_ppr": 9000.0}],
        "synthetic": [base[0], {**base[1], "player_id": "market:b"}],
    }
    for message, players in bad.items():
        with pytest.raises(v.DataIntegrityError, match=message):
            v.check_projection_file(valid_doc(players=players))


def test_projection_validator_allows_no_team_and_requires_actuals_in_backtests():
    players = valid_doc()["players"]
    v.check_projection_file(valid_doc(players=[{**players[0], "team": v.NO_TEAM}, players[1]]))
    with pytest.raises(v.DataIntegrityError, match="actual_ppr"):
        v.check_projection_file(valid_doc(kind="backtest"))
    with_actuals = [{**p, "actual_ppr": 100.0} for p in players]
    v.check_projection_file(valid_doc(kind="backtest", players=with_actuals))


# ---- real files (skip when data/ is absent) -------------------------------------------------------------------

@pytest.mark.parametrize("season", range(2021, 2027))
def test_exported_files_are_valid(season):
    path = PROCESSED / f"projections_{season}_v1.json"
    if not path.exists():
        pytest.skip("projection files not exported")
    v.check_projection_file(json.loads(path.read_text()))
