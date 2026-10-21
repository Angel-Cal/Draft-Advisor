import pandas as pd
import pytest
from src.features import advanced as adv


def inputs():
    """KC plays 10 offensive plays in 2020: OL a-d start all 10, e starts 8, f replaces e for 2."""
    plays = pd.DataFrame({"nflverse_game_id": "g1", "play_id": range(10), "possession_team": "KC",
                          "offense_players": ["a;b;c;d;e;qb"] * 8 + ["a;b;c;d;f;qb"] * 2})
    pbp = pd.DataFrame({"game_id": "g1", "play_id": range(10), "season": 2020, "season_type": "REG",
                        "pass": [1] * 5 + [0] * 5, "rush": [0] * 5 + [1] * 5})
    last_year = pd.DataFrame({"gsis_id": ["a", "b", "c", "d", "e", "f"], "season": 2020, "week": 1,
                              "position": "OL", "team": "KC"})
    this_year = pd.DataFrame({"gsis_id": ["a", "b", "c", "d", "e", "f", "qb"], "season": 2021, "week": 1,
                              "position": ["OL"] * 6 + ["QB"], "team": ["KC", "KC", "KC", "KC", "DEN", "KC", "KC"]})
    return plays, pbp, pd.concat([last_year, this_year])


def qb_row(out):
    return out[(out["player_id"] == "qb") & (out["season"] == 2021)].iloc[0]


def test_continuity_counts_returning_starters_and_snaps():
    row = qb_row(adv.build_ol_features(*inputs()))
    assert row["ol_returning_starters"] == 4                       # e left for DEN
    assert row["ol_snap_continuity"] == pytest.approx((4 * 10 + 2) / (4 * 10 + 2 + 8))
    assert row["ol_incoming_starters"] == 0


def test_incoming_starters_are_proven_linemen_from_other_teams():
    plays, pbp, roster = inputs()
    denver = pd.DataFrame({"nflverse_game_id": "g2", "play_id": range(600), "possession_team": "DEN",
                           "offense_players": ["x;x1;x2;x3;x4;q2"] * 600})
    denver_pbp = pd.DataFrame({"game_id": "g2", "play_id": range(600), "season": 2020, "season_type": "REG",
                               "pass": 1, "rush": 0})
    roster = pd.concat([roster, pd.DataFrame({"gsis_id": ["x"], "season": [2020], "week": [1], "position": ["OL"],
                                              "team": ["DEN"]}),
                        pd.DataFrame({"gsis_id": ["x"], "season": [2021], "week": [1], "position": ["OL"], "team": ["KC"]})])
    row = qb_row(adv.build_ol_features(pd.concat([plays, denver]), pd.concat([pbp, denver_pbp]), roster))
    assert row["ol_incoming_starters"] == 1                        # x played 600 snaps for DEN last year
