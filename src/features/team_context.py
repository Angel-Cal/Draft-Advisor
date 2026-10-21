"""Team-context features for RBs. Every feature uses prior-season (t-1) production, plus the
season-t roster as known at the start of the season (earliest available roster week)."""

import pandas as pd

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]
TEAM_MAP = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "OAK": "LV",
            "SD": "LAC", "SL": "LA", "STL": "LA"}

FEATURE_GROUPS = {
    "depth": ["carry_rank_prev", "carry_rank_now", "target_rank_now"],
    "vacated": ["vacated_carry_share", "vacated_target_share", "competing_rb_carries", "incoming_rb_carries"],
    "team_change": ["team_changed"],
    "team_rates": ["team_pass_rate_prev", "team_plays_pg_prev", "team_ppg_prev"],
}

RB_FEATURES = FEATURE_GROUPS["vacated"]
WR_COMPETITION = ["competing_pass_targets", "incoming_pass_targets"]
WR_FEATURES = ["vacated_target_share"] + WR_COMPETITION
QB_FEATURES = ["qb1_ypa_prev", "qb1_epa_per_att_prev", "qb1_unproven", "qb_changed"]
QB_DEPTH_FEATURES = ["qb_is_expected_starter", "qb_att_share_prev", "qb_rookie_competitor", "qb_proven_competitor"]
QB_MODEL_FEATURES = ["qb_att_share_prev"]  # the subset that survived ablation
RB_DEPTH_FEATURES = ["rb_carry_share_prev", "rb_is_expected_lead", "rb_proven_competitor", "rb_rookie_competitor"]
MIN_RB_CARRIES = 100   # a back with this many prior carries is a proven competitor for the job
EARLY_ROUND_PICKS = 64
MIN_QB_ATTEMPTS = 100  # below this a QB1 has no usable prior-season quality estimate
FIRST_ROUND_PICKS = 32


def _norm(team):
    return team.replace(TEAM_MAP)


def _prior_season_stats(seasonal):
    """One row per player-season, keyed by the season the stats will be used FOR (t = stats season + 1)."""
    s = seasonal[seasonal["position"].isin(SKILL_POSITIONS)].copy()
    s["team"] = _norm(s["recent_team"])
    return s[["player_id", "season", "team", "carries", "targets", "attempts", "games"]]


def _roster_start(roster):
    r = roster[roster["position"].isin(SKILL_POSITIONS)].copy()
    r = (r.sort_values(["season", "week"]).groupby(["gsis_id", "season"], as_index=False).first()
          .rename(columns={"gsis_id": "player_id"}))
    r["team_now"] = _norm(r["team"])
    return r[["player_id", "season", "position", "team_now"]]


def _roster_qbs(seasonal, roster):
    """Start-of-season roster QBs with their prior-season stats and whether they are first-round rookies."""
    stats = seasonal[seasonal["position"] == "QB"][["player_id", "season", "recent_team", "attempts",
                                                     "passing_yards", "passing_epa"]].copy()
    stats["team"] = _norm(stats["recent_team"])
    prev = stats.assign(season=stats["season"] + 1).rename(
        columns={"attempts": "prev_att", "passing_yards": "prev_yds", "passing_epa": "prev_epa"})

    qbs = roster[roster["position"] == "QB"].sort_values(["season", "week"])
    qbs = qbs.groupby(["gsis_id", "season"], as_index=False).first().rename(columns={"gsis_id": "player_id"})
    qbs["team_now"] = _norm(qbs["team"])
    qbs["first_round_rookie"] = ((qbs["rookie_year"] == qbs["season"])
                                 & (pd.to_numeric(qbs["draft_number"], errors="coerce") <= FIRST_ROUND_PICKS))
    qbs = qbs.merge(prev[["player_id", "season", "prev_att", "prev_yds", "prev_epa"]],
                    on=["player_id", "season"], how="left")
    qbs["prev_att"] = qbs["prev_att"].fillna(0)
    return stats, qbs


def _pick_qb1(qbs):
    return (qbs.sort_values(["first_round_rookie", "prev_att"], ascending=False)
               .groupby(["team_now", "season"], as_index=False).head(1))


def _qb_features(seasonal, roster):
    """Per team-season: the QB1 expected to start and how good he was last season.

    QB1 is a first-round rookie if the roster has one, otherwise the roster QB with the most prior-season attempts.
    """
    stats, qbs = _roster_qbs(seasonal, roster)
    qb1 = _pick_qb1(qbs).copy()
    proven = qb1["prev_att"] >= MIN_QB_ATTEMPTS
    qb1["qb1_unproven"] = (~proven).astype(float)
    qb1["qb1_ypa_prev"] = (qb1["prev_yds"] / qb1["prev_att"]).where(proven)
    qb1["qb1_epa_per_att_prev"] = (qb1["prev_epa"] / qb1["prev_att"]).where(proven)

    last_starter = (stats.sort_values("attempts", ascending=False).groupby(["team", "season"]).head(1)
                         [["team", "season", "player_id"]]
                    .assign(season=lambda d: d["season"] + 1)
                    .rename(columns={"team": "team_now", "player_id": "qb1_last_year"}))
    qb1 = qb1.merge(last_starter, on=["team_now", "season"], how="left")
    qb1["qb_changed"] = (qb1["player_id"] != qb1["qb1_last_year"]).astype(float).where(qb1["qb1_last_year"].notna())
    return qb1[["team_now", "season"] + QB_FEATURES]


def build_qb_depth_features(seasonal, roster):
    """Per QB-season: is he the expected starter, his share of the roster's prior attempts, and his competition."""
    _, qbs = _roster_qbs(seasonal, roster)
    qbs = qbs.merge(_pick_qb1(qbs)[["team_now", "season", "player_id"]].assign(qb_is_expected_starter=1.0),
                    on=["team_now", "season", "player_id"], how="left")
    qbs["qb_is_expected_starter"] = qbs["qb_is_expected_starter"].fillna(0.0)
    by_team = qbs.groupby(["team_now", "season"])
    team_att = by_team["prev_att"].transform("sum")
    qbs["qb_att_share_prev"] = (qbs["prev_att"] / team_att).where(team_att > 0)
    rookies = by_team["first_round_rookie"].transform("sum") - qbs["first_round_rookie"].astype(int)
    qbs["qb_rookie_competitor"] = (rookies > 0).astype(float)
    proven = (qbs["prev_att"] >= MIN_QB_ATTEMPTS)
    others_proven = proven.groupby([qbs["team_now"], qbs["season"]]).transform("sum") - proven.astype(int)
    qbs["qb_proven_competitor"] = (others_proven > 0).astype(float)
    return qbs[["player_id", "season"] + QB_DEPTH_FEATURES]


def _team_points_per_game(schedules):
    sched = schedules[schedules["game_type"] == "REG"]
    home = sched[["season", "home_team", "home_score"]].set_axis(["season", "team", "points"], axis=1)
    away = sched[["season", "away_team", "away_score"]].set_axis(["season", "team", "points"], axis=1)
    pts = pd.concat([home, away])
    pts["team"] = _norm(pts["team"])
    return pts.groupby(["team", "season"])["points"].mean().rename("team_ppg_prev").reset_index()


def build_team_context(seasonal, roster, schedules=None):
    stats = _prior_season_stats(seasonal)
    roster_now = _roster_start(roster)

    # previous-season stats re-keyed to the season they predict
    prev = stats.assign(season=stats["season"] + 1).rename(
        columns={"team": "team_prev", "carries": "carries_prev", "targets": "targets_prev"})
    prev["carry_rank_prev"] = (stats.groupby(["team", "season"])["carries"].rank(ascending=False, method="min")
                               .values)

    now = roster_now.merge(prev[["player_id", "season", "team_prev", "carries_prev", "targets_prev",
                                 "carry_rank_prev"]], on=["player_id", "season"], how="left")
    now["carries_filled"] = now["carries_prev"].fillna(0)
    now["targets_filled"] = now["targets_prev"].fillna(0)
    now["team_changed"] = (now["team_prev"].notna() & (now["team_prev"] != now["team_now"])).astype(float)
    now.loc[now["team_prev"].isna(), "team_changed"] = float("nan")

    # depth-chart rank among the players on the team's season-t roster
    rbs = now[now["position"] == "RB"]
    now["carry_rank_now"] = rbs.groupby(["team_now", "season"])["carries_filled"].rank(ascending=False, method="min")
    receivers = now[now["position"].isin(["RB", "WR", "TE"])]
    now["target_rank_now"] = receivers.groupby(["team_now", "season"])["targets_filled"].rank(ascending=False, method="min")

    # competing RB volume: other RBs on the season-t roster, and the subset that arrived from other teams
    rbs = now[now["position"] == "RB"]
    team_rb_carries = rbs.groupby(["team_now", "season"])["carries_filled"].transform("sum")
    incoming = rbs["carries_filled"].where(rbs["team_prev"] != rbs["team_now"], 0)
    team_incoming = incoming.groupby([rbs["team_now"], rbs["season"]]).transform("sum")
    now["competing_rb_carries"] = (team_rb_carries - rbs["carries_filled"]).reindex(now.index)
    now["incoming_rb_carries"] = (team_incoming - incoming).reindex(now.index)

    # competing pass-catcher volume: other WR/TE on the season-t roster, and the subset that arrived from other teams
    catchers = now[now["position"].isin(["WR", "TE"])]
    team_catcher_targets = catchers.groupby(["team_now", "season"])["targets_filled"].transform("sum")
    arrived = catchers["targets_filled"].where(catchers["team_prev"] != catchers["team_now"], 0)
    team_arrived = arrived.groupby([catchers["team_now"], catchers["season"]]).transform("sum")
    now["competing_pass_targets"] = (team_catcher_targets - catchers["targets_filled"]).reindex(now.index)
    now["incoming_pass_targets"] = (team_arrived - arrived).reindex(now.index)

    # vacated volume: prior-season production of the team's players who are not on its season-t roster
    prior = prev.merge(roster_now[["player_id", "season", "team_now"]], on=["player_id", "season"], how="left")
    prior["left_team"] = prior["team_now"] != prior["team_prev"]
    by_team = prior.groupby(["team_prev", "season"])
    team_prev_totals = by_team[["carries_prev", "targets_prev"]].sum()
    vacated = (prior[prior["left_team"]].groupby(["team_prev", "season"])[["carries_prev", "targets_prev"]].sum()
               .reindex(team_prev_totals.index, fill_value=0))
    vac = (vacated / team_prev_totals).rename(columns={"carries_prev": "vacated_carry_share",
                                                       "targets_prev": "vacated_target_share"}).reset_index()
    vac = vac.rename(columns={"team_prev": "team_now"})
    now = now.merge(vac, on=["team_now", "season"], how="left")

    now = now.merge(_qb_features(seasonal, roster), on=["team_now", "season"], how="left")

    cols = [c for group in FEATURE_GROUPS.values() for c in group] + WR_COMPETITION + QB_FEATURES
    if schedules is None:
        cols = [c for c in cols if c not in FEATURE_GROUPS["team_rates"]]
        return now[["player_id", "season"] + cols]

    # team pass rate / pace / scoring of the team the player is on now, last season
    team_games = stats.groupby(["team", "season"]).agg(
        attempts=("attempts", "sum"), carries=("carries", "sum"), games=("games", "max")).reset_index()
    team_games["season"] += 1
    team_games["team_pass_rate_prev"] = team_games["attempts"] / (team_games["attempts"] + team_games["carries"])
    team_games["team_plays_pg_prev"] = (team_games["attempts"] + team_games["carries"]) / team_games["games"]
    ppg = _team_points_per_game(schedules)
    ppg["season"] += 1
    team_rates = team_games.merge(ppg, on=["team", "season"], how="left").rename(columns={"team": "team_now"})
    now = now.merge(team_rates[["team_now", "season", "team_pass_rate_prev", "team_plays_pg_prev", "team_ppg_prev"]],
                    on=["team_now", "season"], how="left")

    return now[["player_id", "season"] + cols]


def add_rb_features(df, context, season_offset=0):
    """Merge the RB feature set onto df; season_offset=1 maps a 2025 prediction row to the 2026 context."""
    keyed = context[["player_id", "season"] + RB_FEATURES].assign(season=lambda c: c["season"] - season_offset)
    return df.merge(keyed, on=["player_id", "season"], how="left")


def add_qb_features(df, depth, season_offset=0):
    """Merge the QB feature set onto df; season_offset=1 maps a 2025 prediction row to the 2026 context."""
    keyed = depth[["player_id", "season"] + QB_MODEL_FEATURES].assign(season=lambda d: d["season"] - season_offset)
    return df.merge(keyed, on=["player_id", "season"], how="left")


def build_rb_depth_features(seasonal, roster):
    """Per RB-season: his share of the roster RBs' prior carries, whether he is the lead back, and his competition."""
    stats = _prior_season_stats(seasonal)
    prev = (stats.assign(season=stats["season"] + 1)[["player_id", "season", "carries"]]
            .rename(columns={"carries": "prev_carries"}))
    rbs = roster[roster["position"] == "RB"].sort_values(["season", "week"])
    rbs = rbs.groupby(["gsis_id", "season"], as_index=False).first().rename(columns={"gsis_id": "player_id"})
    rbs["team_now"] = _norm(rbs["team"])
    rbs = rbs.merge(prev, on=["player_id", "season"], how="left")
    rbs["prev_carries"] = rbs["prev_carries"].fillna(0)
    rbs["early_rookie"] = ((rbs["rookie_year"] == rbs["season"])
                           & (pd.to_numeric(rbs["draft_number"], errors="coerce") <= EARLY_ROUND_PICKS))

    by_team = rbs.groupby(["team_now", "season"])
    team_carries = by_team["prev_carries"].transform("sum")
    rbs["rb_carry_share_prev"] = (rbs["prev_carries"] / team_carries).where(team_carries > 0)
    team_lead = by_team["prev_carries"].transform("max")
    rbs["rb_is_expected_lead"] = ((rbs["prev_carries"] == team_lead) & (team_lead > 0)).astype(float)
    proven = (rbs["prev_carries"] >= MIN_RB_CARRIES).astype(int)
    others_proven = proven.groupby([rbs["team_now"], rbs["season"]]).transform("sum") - proven
    rbs["rb_proven_competitor"] = (others_proven > 0).astype(float)
    rookies = rbs["early_rookie"].astype(int)
    others_rookies = rookies.groupby([rbs["team_now"], rbs["season"]]).transform("sum") - rookies
    rbs["rb_rookie_competitor"] = (others_rookies > 0).astype(float)
    return rbs[["player_id", "season"] + RB_DEPTH_FEATURES]
