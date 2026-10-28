import numpy as np
import pandas as pd
import pytest

from src.data import validate as v
from src.data.export_projections import attach_role_context
from src.features import role_context as rc
from tests.test_export_projections import valid_doc


def weekly_rows(rows):
    """rows: (player_id, season, week, team, position, targets)"""
    return pd.DataFrame(rows, columns=["player_id", "season", "week", "team", "position", "targets"]).assign(season_type="REG")


def roster_rows(rows):
    """rows: (gsis_id, season, week, team, position, years_exp, draft_number)"""
    return pd.DataFrame(rows, columns=["gsis_id", "season", "week", "team", "position", "years_exp", "draft_number"])


def test_absence_share_counts_targets_earned_in_weeks_the_top_rival_by_rate_did_not_play():
    # p plays weeks 1-4 with 5 targets each. The rival averages 10 a game but only plays weeks 1-2. x has a huge rate over 2 games and is ignored (3+ games needed)
    rows = [("p", 2023, w, "KC", "WR", 5) for w in (1, 2, 3, 4)]
    rows += [("rival", 2023, w, "KC", "WR", 10) for w in (1, 2)] + [("rival", 2023, 3, "KC", "WR", 10)]      # weeks 1-3: rival absent only in week 4
    rows += [("x", 2023, w, "KC", "TE", 30) for w in (1, 2)]

    out = rc.absence_share_prev(weekly_rows(rows)).set_index("player_id")

    assert out.loc["p", "season"] == 2024                                  # keyed to the season it will be used for
    assert out.loc["p", "absence_share_prev"] == pytest.approx(5 / 20)    # only week 4 came without the rival


def test_absence_share_is_high_when_the_star_misses_most_of_the_year_and_uses_his_rate_not_his_total():
    rows = [("p", 2025, w, "NYG", "WR", 8) for w in range(1, 11)]
    rows += [("star", 2025, w, "NYG", "WR", 9) for w in (1, 2, 3, 4)]                                         # 36 targets in 4 games: 9 a game
    rows += [("other", 2025, w, "NYG", "TE", 5) for w in range(1, 11)]                                         # 50 targets in 10 games: 5 a game, but more in total

    out = rc.absence_share_prev(weekly_rows(rows)).set_index("player_id")

    assert out.loc["p", "absence_share_prev"] == pytest.approx(6 / 10)    # star plays weeks 1-4, so weeks 5-10 are without him


def test_team_changed_compares_the_start_roster_team_with_last_seasons_main_team_and_normalizes_spellings():
    weekly = weekly_rows([("mover", 2023, 1, "KC", "WR", 5), ("stayer", 2023, 1, "LA", "WR", 5), ("new", 2023, 1, "LA", "WR", 5)])
    roster = roster_rows([("mover", 2024, 1, "BUF", "WR", 3, 50), ("stayer", 2024, 1, "LAR", "WR", 3, 50), ("rookie", 2024, 1, "KC", "WR", 0, 20)])

    out = rc.team_changed(weekly, roster).set_index("player_id")["team_changed"]

    assert out["mover"] == 1.0
    assert out["stayer"] == 0.0                                           # LAR on the roster file is LA in the weekly file
    assert np.isnan(out["rookie"])                                        # no last season: unknown, not False


def test_role_context_has_the_three_fields_and_exports_only_for_wrs():
    weekly = weekly_rows([("p", 2023, w, "KC", "WR", 5) for w in (1, 2, 3, 4)] + [("rival", 2023, w, "KC", "WR", 9) for w in (1, 2, 3)]
                         + [("back", 2023, w, "KC", "RB", 3) for w in (1, 2, 3, 4)])
    roster = roster_rows([("p", 2024, 1, "BUF", "WR", 3, 50), ("rival", 2024, 1, "KC", "WR", 4, 30), ("back", 2024, 1, "KC", "RB", 2, 60),
                          ("rook", 2024, 1, "BUF", "WR", 0, 9)])

    context = rc.build_role_context(weekly, roster)
    assert {"absence_share_prev", "team_changed", "rookie_r1_teammate"} <= set(context.columns)

    players = pd.DataFrame({"player_id": ["p", "back"], "position": ["WR", "RB"], "projected_ppr": [150.0, 120.0]})
    out = attach_role_context(players, context, 2024).set_index("player_id")
    assert out.loc["p", "team_changed"] == True and out.loc["p", "rookie_r1_teammate"] == True      # a #9 pick is on BUF
    assert out.loc["p", "absence_share_prev"] == pytest.approx(1 / 4)
    assert out.loc["back", ["absence_share_prev", "team_changed", "rookie_r1_teammate"]].isna().all()       # non-WR rows stay null


def test_projection_validator_accepts_and_checks_the_optional_role_fields():
    players = [{**p, "absence_share_prev": 0.8, "team_changed": True, "rookie_r1_teammate": None} for p in valid_doc()["players"]]
    v.check_projection_file(valid_doc(players=players))
    with pytest.raises(v.DataIntegrityError, match="absence_share_prev"):
        v.check_projection_file(valid_doc(players=[{**players[0], "absence_share_prev": 1.4}, players[1]]))
    with pytest.raises(v.DataIntegrityError, match="team_changed"):
        v.check_projection_file(valid_doc(players=[{**players[0], "team_changed": "yes"}, players[1]]))
