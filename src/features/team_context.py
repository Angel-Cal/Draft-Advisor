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


def _team_points_per_game(schedules):
    sched = schedules[schedules["game_type"] == "REG"]
    home = sched[["season", "home_team", "home_score"]].set_axis(["season", "team", "points"], axis=1)
    away = sched[["season", "away_team", "away_score"]].set_axis(["season", "team", "points"], axis=1)
    pts = pd.concat([home, away])
    pts["team"] = _norm(pts["team"])
    return pts.groupby(["team", "season"])["points"].mean().rename("team_ppg_prev").reset_index()


def build_team_context(seasonal, roster, schedules):
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

    cols = [c for group in FEATURE_GROUPS.values() for c in group]
    return now[["player_id", "season"] + cols]
