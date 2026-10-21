import pandas as pd
import pytest
from src.features.team_context import build_team_context, add_rb_features, RB_FEATURES


def stat(player_id, season, team, position, carries=0, targets=0, attempts=0):
    return dict(player_id=player_id, season=season, recent_team=team, position=position,
                carries=carries, targets=targets, attempts=attempts, games=16)


def roster_row(player_id, season, team, position, week=1):
    return dict(gsis_id=player_id, season=season, week=week, team=team, position=position)


@pytest.fixture
def seasonal():
    return pd.DataFrame([
        stat("rb1", 2020, "AAA", "RB", carries=100, targets=20),
        stat("rb2", 2020, "AAA", "RB", carries=50, targets=10),
        stat("wr1", 2020, "AAA", "WR", targets=70),
        stat("rb3", 2020, "BBB", "RB", carries=80, targets=5),
        stat("rb1", 2021, "AAA", "RB", carries=999, targets=999),  # same-season stats must not leak
    ])


@pytest.fixture
def roster():
    return pd.DataFrame([
        roster_row("rb1", 2021, "AAA", "RB"),
        roster_row("rb3", 2021, "AAA", "RB"),   # arrives from BBB
        roster_row("wr1", 2021, "AAA", "WR"),   # rb2 is gone
        roster_row("rb1", 2021, "ZZZ", "RB", week=9),  # mid-season move must not change the start-of-season team
    ])


def row(context, player_id, season=2021):
    return context[(context["player_id"] == player_id) & (context["season"] == season)].iloc[0]


def test_vacated_share_counts_players_who_left(seasonal, roster):
    # AAA 2020: 150 carries / 100 targets; rb2 left with 50 carries and 10 targets
    r = row(build_team_context(seasonal, roster), "rb1")
    assert r["vacated_carry_share"] == pytest.approx(50 / 150)
    assert r["vacated_target_share"] == pytest.approx(10 / 100)


def test_competing_and_incoming_rb_carries_exclude_self(seasonal, roster):
    context = build_team_context(seasonal, roster)
    assert row(context, "rb1")["competing_rb_carries"] == 80
    assert row(context, "rb1")["incoming_rb_carries"] == 80
    assert row(context, "rb3")["competing_rb_carries"] == 100
    assert row(context, "rb3")["incoming_rb_carries"] == 0


def test_features_ignore_same_season_stats(seasonal, roster):
    changed = seasonal.copy()
    changed.loc[changed["season"] == 2021, ["carries", "targets"]] = 0
    pd.testing.assert_frame_equal(build_team_context(seasonal, roster), build_team_context(changed, roster))


def test_schedules_are_optional(seasonal, roster):
    assert "team_ppg_prev" not in build_team_context(seasonal, roster).columns


def test_add_rb_features_offsets_prediction_season(seasonal, roster):
    context = build_team_context(seasonal, roster)
    prediction_rows = pd.DataFrame({"player_id": ["rb1"], "season": [2020]})
    merged = add_rb_features(prediction_rows, context, season_offset=1)
    assert merged.loc[0, "competing_rb_carries"] == 80
    assert set(RB_FEATURES) <= set(merged.columns)
