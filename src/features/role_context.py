"""Facts about a receiver's situation that are known before the season starts and say whether last year's workload may not carry over.

Used for the role caution in the draft advisor (LOG.md, 2026-10-28: WR seasons that follow a high absence share AND a new situation were over-projected
by about 24 PPR, and the ADP curve made the same error). They are exported to the projection files as optional fields; nothing here enters a model.

  absence_share_prev  share of last season's targets earned in weeks the team's top rival (highest targets per game among teammates, 3+ games) did not play
  team_changed        the start-of-season team differs from the team he played most games for last season
  rookie_r1_teammate  a first-round rookie WR/TE (other than himself, two-way players excluded) is on his start roster
"""
import numpy as np
import pandas as pd

from src.features.advanced import build_rookie_competition_features

CATCHERS = ["WR", "TE", "RB"]
MIN_RIVAL_GAMES = 3
ROLE_CAUTION_ABSENCE = 0.5     # the draft advisor flags a WR at or above this absence share when he is also on a new team or a first-round rookie arrived (C# Explainer mirrors this)
# roster-file spellings -> the spellings of the weekly file
ROSTER_TEAMS = {"LAR": "LA", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "OAK": "LV", "SD": "LAC", "SL": "LA", "STL": "LA"}


def _catcher_weeks(weekly):
    w = weekly[(weekly["season_type"] == "REG") & weekly["position"].isin(CATCHERS)].copy()
    w["targets"] = w["targets"].fillna(0)
    return w


def main_team(weekly):
    """(player_id, season) -> the team he played the most games for."""
    w = _catcher_weeks(weekly)
    return (w.groupby(["player_id", "season", "team"])["week"].nunique().reset_index()
            .sort_values(["player_id", "season", "week"], ascending=[True, True, False]).drop_duplicates(["player_id", "season"])
            .set_index(["player_id", "season"])["team"])


def absence_share_prev(weekly):
    """(player_id, season t) -> share of his season t-1 targets earned while the team's top rival was out; keyed to the season it will be used for."""
    w = _catcher_weeks(weekly)
    main = main_team(weekly)
    rows = []
    for (team, season), room in w.groupby(["team", "season"]):
        team_weeks = set(room["week"])
        per_player = room.groupby("player_id").agg(targets=("targets", "sum"), games=("week", "nunique"))
        weeks = {p: set(g["week"]) for p, g in room.groupby("player_id")}
        for player, mine in room.groupby("player_id"):
            if main.get((player, season)) != team or per_player.loc[player, "targets"] <= 0:
                continue
            others = per_player.drop(player)
            others = others[others["games"] >= MIN_RIVAL_GAMES]
            if others.empty:
                continue
            rival = (others["targets"] / others["games"]).idxmax()
            away = mine[~mine["week"].isin(weeks[rival]) & mine["week"].isin(team_weeks)]
            rows.append((player, season + 1, float(away["targets"].sum() / per_player.loc[player, "targets"])))
    return pd.DataFrame(rows, columns=["player_id", "season", "absence_share_prev"])


def team_changed(weekly, roster):
    """(player_id, season t) -> 1.0 if his start-of-season team (earliest roster row of t) differs from last season's main team, 0.0 if not; missing without both."""
    r = roster[roster["gsis_id"].notna() & roster["position"].isin(CATCHERS)].sort_values(["season", "week"]).drop_duplicates(["gsis_id", "season"])
    now = pd.DataFrame({"player_id": r["gsis_id"], "season": r["season"], "team_now": r["team"].replace(ROSTER_TEAMS)})
    last = main_team(weekly).rename("team_prev").reset_index().assign(season=lambda d: d["season"] + 1)
    both = now.merge(last, on=["player_id", "season"], how="left")
    both["team_changed"] = np.where(both["team_prev"].isna(), np.nan, (both["team_prev"] != both["team_now"]).astype(float))
    return both[["player_id", "season", "team_changed"]]


def build_role_context(weekly, roster):
    """One row per player-season with the three facts above (missing where there is no history, e.g. rookies). weekly needs player_id, season, week, season_type, team, position, targets."""
    context = build_rookie_competition_features(roster).drop(columns="rookie_top_pick")
    context = context.merge(absence_share_prev(weekly), on=["player_id", "season"], how="outer")
    return context.merge(team_changed(weekly, roster), on=["player_id", "season"], how="outer")


def role_caution(df):
    """Boolean Series: absence share 0.5+ AND (changed teams OR a first-round rookie WR/TE on the roster). df needs the three columns above (nulls count as False)."""
    new_situation = (df["team_changed"].fillna(0).astype(float) == 1) | (df["rookie_r1_teammate"].fillna(0).astype(float) == 1)
    return (df["absence_share_prev"].fillna(0) >= ROLE_CAUTION_ABSENCE) & new_situation
