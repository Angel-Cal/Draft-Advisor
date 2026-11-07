import json
import numpy as np
import pandas as pd
import pytest
from src.paths import LIVE
from src.data import validate as v
from src.data import export_projections
from src.data.export_projections import attach_injury_history, build_backtest, games_history, injury_flag, to_document, weekly_lists, write
from src.data.major_injuries import season_ending_candidates
from src.data.market_fallback import fit_position_curves


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


# ---- injury flag ----------------------------------------------------------------------------------------------

def test_games_history_is_the_last_three_seasons_with_lost_seasons_as_zero():
    s = seasonal_rows([("vet", 2019, 16, "RB", 0), ("vet", 2021, 17, "RB", 0), ("vet", 2023, 4, "RB", 0),
                       ("rookie", 2023, 9, "WR", 0), ("traded", 2023, 18, "WR", 0)])
    h = games_history(s, before_season=2024)
    assert h["vet"] == [{"season": 2021, "games": 17, "of": 17}, {"season": 2022, "games": 0, "of": 17},
                        {"season": 2023, "games": 4, "of": 17}]          # 2022 had no stats: lost to injury
    assert h["rookie"] == [{"season": 2023, "games": 9, "of": 17}]       # newer players have fewer seasons
    assert h["traded"][0]["games"] == 17                                 # capped at the season length
    assert games_history(s, before_season=2020)["vet"] == [{"season": 2019, "games": 16, "of": 16}]   # point-in-time


def test_injury_flag_needs_four_missed_games_a_season_or_a_major_injury():
    def h(*games):
        return [{"season": 2021 + i, "games": g, "of": 17} for i, g in enumerate(games)]
    assert injury_flag(h(13, 13, 13), None)            # 4 missed a season: flagged
    assert not injury_flag(h(14, 13, 13), None)        # 3.67: not flagged
    assert not injury_flag(h(17, 17, 17), None) and not injury_flag(None, None)
    assert injury_flag(h(17, 17, 17), {"season": 2023, "week": 15, "injury": "torn ACL"})


def test_attach_injury_history_reads_the_major_injury_from_last_season_only():
    s = seasonal_rows([("a", 2023, 17, "WR", 0), ("b", 2023, 17, "WR", 0)])
    df = pd.DataFrame({"player_id": ["a", "b", "market:c"]})
    major = {("a", 2023): {"season": 2023, "week": 16, "injury": "torn ACL"},
             ("b", 2022): {"season": 2022, "week": 3, "injury": "torn Achilles"}}
    out = attach_injury_history(df, s, 2024, major).set_index("player_id")
    assert out.loc["a", "injury_flag"] and out.loc["a", "major_injury"]["injury"] == "torn ACL"
    assert not out.loc["b", "injury_flag"] and out.loc["b", "major_injury"] is None   # two seasons ago does not count
    assert out.loc["market:c", "games_history"] is None and not out.loc["market:c", "injury_flag"]


def test_season_ending_candidates():
    weekly = pd.DataFrame([("early", 2023, w, "REG") for w in (1, 2, 3, 4)] + [("late_acl", 2023, w, "REG") for w in range(1, 16)] +
                          [("full", 2023, w, "REG") for w in range(1, 19)] + [("rested", 2023, w, "REG") for w in range(1, 18)] +
                          [("lost", 2022, 1, "REG")],
                          columns=["player_id", "season", "week", "season_type"])
    injuries = pd.DataFrame({"season": [2023, 2023], "week": [16, 18], "gsis_id": ["late_acl", "rested"],
                             "report_primary_injury": ["Knee", "Not injury related - resting player"], "report_secondary_injury": [None, None]})
    roster = pd.DataFrame({"gsis_id": [], "season": [], "week": [], "status": []})
    pools = {2024: {"early", "late_acl", "full", "rested", "lost", "never"}}
    found = season_ending_candidates(injuries, weekly, roster, pools).set_index("player_id")
    assert set(found.index) == {"early", "late_acl", "lost"}
    assert found.loc["late_acl", "why"] == "knee/Achilles report" and found.loc["lost", "why"] == "missed the whole season"


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


def test_validator_checks_games_history():
    players = valid_doc()["players"]
    ok = [{**players[0], "games_history": [{"season": 2025, "games": 12, "of": 17}]}, {**players[1], "games_history": None}]
    v.check_projection_file(valid_doc(players=ok))
    with pytest.raises(v.DataIntegrityError, match="games_history"):
        v.check_projection_file(valid_doc(players=[{**ok[0], "games_history": [{"season": 2025, "games": 18, "of": 17}]}, ok[1]]))


def test_backtest_document_passes_validation():
    oos, adp, training, seasonal = backtest_inputs()
    df = build_backtest(2024, oos, adp, training, seasonal, curves())
    v.check_projection_file(to_document(df, 2024, "backtest", "fantasypros"))



def test_write_replaces_the_file_in_one_step_and_leaves_no_temporary_file(tmp_path):
    path = write(valid_doc(), tmp_path)
    assert json.loads(path.read_text())["players"][0]["player_id"] == "a"
    assert [f.name for f in tmp_path.iterdir()] == ["projections_2026_v1.json"]


def test_a_write_that_fails_before_the_rename_leaves_the_old_file_whole(tmp_path, monkeypatch):
    # the app reads this file at startup (STATE_MACHINES.md, ISSUE-2): it must never see a half-written one
    path = write(valid_doc(), tmp_path)
    before = path.read_bytes()

    def interrupted(source, target):
        raise OSError("interrupted")
    monkeypatch.setattr(export_projections.os, "replace", interrupted)
    with pytest.raises(OSError):
        write(valid_doc(season=2026, players=valid_doc()["players"][:1]), tmp_path)

    assert path.read_bytes() == before

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
    path = LIVE / f"projections_{season}_v1.json"
    if not path.exists():
        pytest.skip("projection files not exported")
    v.check_projection_file(json.loads(path.read_text()))
