import pandas as pd
import pytest
from src.features.team_context import build_team_context, add_rb_features, RB_FEATURES


def stat(player_id, season, team, position, carries=0, targets=0, attempts=0):
    return dict(player_id=player_id, season=season, recent_team=team, position=position,
                carries=carries, targets=targets, attempts=attempts, games=16,
                passing_yards=attempts * 7.0, passing_epa=attempts * 0.1)


def roster_row(player_id, season, team, position, week=1, rookie_year=2015, draft_number="100"):
    return dict(gsis_id=player_id, season=season, week=week, team=team, position=position,
                rookie_year=rookie_year, draft_number=draft_number)


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


@pytest.fixture
def qb_data():
    seasonal = pd.DataFrame([
        stat("vet", 2020, "AAA", "QB", attempts=500),
        stat("backup", 2020, "AAA", "QB", attempts=50),
        stat("old_starter", 2020, "BBB", "QB", attempts=400),
        stat("young", 2020, "CCC", "QB", attempts=60),
    ])
    roster = pd.DataFrame([
        roster_row("vet", 2021, "AAA", "QB"),
        roster_row("rookie1", 2021, "AAA", "QB", rookie_year=2021, draft_number="3"),   # first-round rookie
        roster_row("backup", 2021, "BBB", "QB"),                                         # BBB lost its starter
        roster_row("rookie2", 2021, "DDD", "QB", rookie_year=2021, draft_number="70"),  # day-2 rookie, no vets
        roster_row("young", 2021, "CCC", "QB"),
        roster_row("wr", 2021, "AAA", "WR"),
    ])
    return seasonal, roster


def qb_row(context, team_player, season=2021):
    return context[(context["player_id"] == team_player) & (context["season"] == season)].iloc[0]


def test_first_round_rookie_overrides_veteran_as_qb1(qb_data):
    r = qb_row(build_team_context(*qb_data), "wr")
    assert r["qb1_unproven"] == 1.0
    assert pd.isna(r["qb1_ypa_prev"]) and pd.isna(r["qb1_epa_per_att_prev"])
    assert r["qb_changed"] == 1.0


def test_veteran_qb1_quality_uses_prior_season(qb_data):
    seasonal, roster = qb_data
    roster = roster[roster["gsis_id"] != "rookie1"]
    r = qb_row(build_team_context(seasonal, roster), "wr")
    assert r["qb1_unproven"] == 0.0
    assert r["qb1_ypa_prev"] == pytest.approx(7.0)
    assert r["qb1_epa_per_att_prev"] == pytest.approx(0.1)
    assert r["qb_changed"] == 0.0


def test_qb_depth_features(qb_data):
    from src.features.team_context import build_qb_depth_features
    d = build_qb_depth_features(*qb_data).set_index("player_id")
    # AAA: first-round rookie1 is expected starter; vet (500 att) is a proven competitor, backup (50) is not
    assert d.loc["rookie1", "qb_is_expected_starter"] == 1.0 and d.loc["vet", "qb_is_expected_starter"] == 0.0
    assert d.loc["vet", "qb_rookie_competitor"] == 1.0 and d.loc["rookie1", "qb_rookie_competitor"] == 0.0
    assert d.loc["rookie1", "qb_proven_competitor"] == 1.0
    assert d.loc["vet", "qb_att_share_prev"] == pytest.approx(500 / 500)   # rookie1 has no prior attempts; backup is on BBB
    # BBB: the only roster QB is backup (50 att) and he has no proven competitor
    assert d.loc["backup", "qb_is_expected_starter"] == 1.0 and d.loc["backup", "qb_proven_competitor"] == 0.0


def test_rb_depth_features():
    from src.features.team_context import build_rb_depth_features
    seasonal = pd.DataFrame([
        stat("rb1", 2020, "AAA", "RB", carries=100),
        stat("rb2", 2020, "AAA", "RB", carries=50),
    ])
    roster = pd.DataFrame([
        roster_row("rb1", 2021, "AAA", "RB"),
        roster_row("rb2", 2021, "AAA", "RB"),
        roster_row("rb3", 2021, "AAA", "RB", rookie_year=2021, draft_number="20"),   # early-round rookie
    ])
    d = build_rb_depth_features(seasonal, roster).set_index("player_id")
    assert d.loc["rb1", "rb_carry_share_prev"] == pytest.approx(100 / 150)
    assert d.loc["rb2", "rb_carry_share_prev"] == pytest.approx(50 / 150) and d.loc["rb3", "rb_carry_share_prev"] == 0
    assert list(d["rb_is_expected_lead"]) == [1.0, 0.0, 0.0]
    assert d.loc["rb1", "rb_proven_competitor"] == 0.0 and d.loc["rb2", "rb_proven_competitor"] == 1.0
    assert d.loc["rb1", "rb_rookie_competitor"] == 1.0 and d.loc["rb3", "rb_rookie_competitor"] == 0.0
