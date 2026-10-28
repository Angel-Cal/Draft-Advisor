"""'Process' features from public nflverse sources. Every frame is keyed (player_id, season=t) and uses season t-1
data, except depth_tier_wk1, which is the depth chart published before the opener of season t.

Groups: xfp (expected fantasy points), role (share of team pass/rush plays on the field), depth (week-1 depth tier),
team_epa (prior-season offensive EPA/success of the player's season-t team), ngs (Next Gen Stats).
"""

import numpy as np
import pandas as pd
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.features.team_context import _norm, _roster_start

RAW = Path(__file__).parent.parent.parent / "data" / "raw"
MAX_DEPTH_TIER = 3
OPENERS = {2025: "2025-09-04", 2026: "2026-09-09"}   # snapshots after this are not pre-season information

NGS_COLUMNS = {
    "receiving": ["avg_separation", "avg_cushion", "avg_yac_above_expectation", "percent_share_of_intended_air_yards",
                  "catch_percentage"],
    "rushing": ["efficiency", "rush_yards_over_expected_per_att", "percent_attempts_gte_eight_defenders", "avg_time_to_los"],
    "passing": ["avg_time_to_throw", "aggressiveness", "completion_percentage_above_expectation",
                "avg_air_yards_differential"],
}
ADVANCED_GROUPS = {
    "xfp": ["xfp_ppr_prev", "fp_over_exp_prev", "xfp_pg_prev"],
    "role": ["pass_snap_share_prev", "rush_snap_share_prev"],
    "depth": ["depth_tier_wk1"],
    "team_epa": ["team_pass_epa_prev", "team_rush_epa_prev", "team_success_prev"],
    "ngs": [f"ngs_{kind[:4]}_{col}" for kind, cols in NGS_COLUMNS.items() for col in cols],
    "ol": ["ol_returning_starters", "ol_snap_continuity", "ol_incoming_starters"],
    "ol_quality": ["ol_aly_prev", "ol_asr_prev"],
    "ol_interaction": ["ol_aly_x_cont", "ol_asr_x_cont"],
    "volatility": ["weekly_sd_prev", "weekly_cv_prev", "weekly_boom_prev"],
    "rookie_comp": ["rookie_r1_teammate", "rookie_top_pick"],
}
BOOM_PPR = 20.0            # a week at or above this many PPR points counts as a boom week
MIN_VOLATILITY_GAMES = 4   # fewer games than this give a meaningless spread, left missing
OL_STARTERS = 5            # the unit
FIRST_ROUND_PICKS = 32      # a rookie taken this early is a receiving competitor for the incumbents
TWO_WAY_PLAYERS = {"00-0040718"}   # listed WR but plays mostly defense (Travis Hunter, JAX 2025): not a receiving competitor
OL_STARTER_SNAPS = 500     # plays on the field that mark an OL as a starter-level player


def _shift_to_next_season(df):
    return df.assign(season=df["season"] + 1)


def last_regular_season_week(season):
    """Regular seasons ran 17 weeks through 2020 and 18 from 2021; ff_opportunity also carries the playoffs after that."""
    return np.where(season <= 2020, 17, 18)


def build_xfp_features(opportunity):
    """Expected PPR from opportunity (ff_opportunity) and how far actual PPR was above it. Regular season only, like the other features."""
    opportunity = opportunity[opportunity["week"] <= last_regular_season_week(opportunity["season"])]
    g = opportunity.groupby(["player_id", "season"]).agg(
        xfp=("total_fantasy_points_exp", "sum"), fp=("total_fantasy_points", "sum"), weeks=("week", "nunique")).reset_index()
    g["xfp_ppr_prev"] = g["xfp"]
    g["fp_over_exp_prev"] = g["fp"] - g["xfp"]
    g["xfp_pg_prev"] = g["xfp"] / g["weeks"]
    return _shift_to_next_season(g[["player_id", "season"] + ADVANCED_GROUPS["xfp"]])


def build_volatility_features(weekly):
    """Spread of last season's weekly PPR over the games a player played: SD, SD per point of mean, and the share of boom weeks."""
    played = weekly[(weekly["season_type"] == "REG")].dropna(subset=["fantasy_points_ppr"])
    played = played.assign(boom=(played["fantasy_points_ppr"] >= BOOM_PPR).astype(float))
    g = played.groupby(["player_id", "season"]).agg(
        games=("week", "size"), mean=("fantasy_points_ppr", "mean"), weekly_sd_prev=("fantasy_points_ppr", "std"),
        weekly_boom_prev=("boom", "mean")).reset_index()
    g["weekly_cv_prev"] = g["weekly_sd_prev"] / g["mean"].clip(lower=1)
    g.loc[g["games"] < MIN_VOLATILITY_GAMES, ADVANCED_GROUPS["volatility"]] = np.nan
    return _shift_to_next_season(g[["player_id", "season"] + ADVANCED_GROUPS["volatility"]])


def _on_field_counts(participation, pbp):
    """Per (player, team, season): offensive plays on the field, split into pass and rush, plus team totals."""
    plays = pbp[(pbp["season_type"] == "REG") & (pbp["pass"] == 1) | (pbp["season_type"] == "REG") & (pbp["rush"] == 1)]
    plays = plays[["game_id", "play_id", "season", "pass"]].rename(columns={"game_id": "nflverse_game_id"})
    on_field = participation.merge(plays, on=["nflverse_game_id", "play_id"], how="inner")
    on_field["team"] = _norm(on_field["possession_team"])
    on_field["is_pass"] = on_field["pass"] == 1

    team_totals = on_field.groupby(["team", "season"]).agg(team_pass=("is_pass", "sum"), team_plays=("is_pass", "size"))
    team_totals["team_rush"] = team_totals["team_plays"] - team_totals["team_pass"]

    players = on_field[["team", "season", "is_pass", "offense_players"]].copy()
    players["player_id"] = players["offense_players"].str.split(";")
    players = players.explode("player_id")
    counts = players.groupby(["player_id", "team", "season"]).agg(
        pass_plays=("is_pass", "sum"), plays=("is_pass", "size")).reset_index()
    counts["rush_plays"] = counts["plays"] - counts["pass_plays"]
    return counts.merge(team_totals.reset_index()[["team", "season", "team_pass", "team_rush"]], on=["team", "season"])


def build_role_features(participation, pbp):
    """Share of the team's pass and rush plays a player was on the field for, last season."""
    counts = _on_field_counts(participation, pbp)
    counts["pass_snap_share_prev"] = counts["pass_plays"] / counts["team_pass"]
    counts["rush_snap_share_prev"] = counts["rush_plays"] / counts["team_rush"]
    # a traded player keeps the team where he was on the field most; equal plays go to the alphabetically first team
    # (an unstable sort let the winner change with the pandas version, e.g. M.Sanu 2019: 379 plays each for ATL and NE)
    counts = counts.sort_values(["plays", "team"], ascending=[False, True]).drop_duplicates(["player_id", "season"])
    return _shift_to_next_season(counts[["player_id", "season"] + ADVANCED_GROUPS["role"]])


def build_rookie_competition_features(roster):
    """Per skill player and season t: is a first-round rookie WR/TE on his start roster (other than himself), and how early was the earliest one taken?

    rookie_r1_teammate: 1 if there is one, else 0. rookie_top_pick: the draft pick number of the earliest such rookie (missing when none).
    Known before the season starts: it uses the start roster and the draft, not the season's results.
    """
    r = roster[roster["position"].isin(["QB", "RB", "WR", "TE"]) & roster["gsis_id"].notna()].copy()
    r["draft_number"] = pd.to_numeric(r["draft_number"], errors="coerce")
    r["years_exp"] = pd.to_numeric(r["years_exp"], errors="coerce")
    first = (r.sort_values(["season", "week"]).groupby(["gsis_id", "season"], as_index=False).first()
             .rename(columns={"gsis_id": "player_id"}))
    first["team_now"] = _norm(first["team"])
    rookies = first[first["position"].isin(["WR", "TE"]) & (first["years_exp"] == 0) & (first["draft_number"] <= FIRST_ROUND_PICKS)
                    & ~first["player_id"].isin(TWO_WAY_PLAYERS)]
    by_team = {k: g[["player_id", "draft_number"]] for k, g in rookies.groupby(["team_now", "season"])}
    flag, pick = [], []
    for player, team, season in zip(first["player_id"], first["team_now"], first["season"]):
        others = by_team.get((team, season))
        others = others[others["player_id"] != player] if others is not None else None
        has = others is not None and len(others) > 0
        flag.append(float(has))
        pick.append(float(others["draft_number"].min()) if has else np.nan)
    first["rookie_r1_teammate"], first["rookie_top_pick"] = flag, pick
    return first[["player_id", "season", "rookie_r1_teammate", "rookie_top_pick"]]


def build_ol_features(participation, pbp, roster):
    """Offensive-line continuity of the team a player starts season t with, measured in last season's snaps.

    returning_starters: how many of last season's five most-used OL are on the start-of-season roster.
    snap_continuity:    share of last season's OL snaps played by players still on that roster.
    incoming_starters:  OL on the roster who were starter-level (>= OL_STARTER_SNAPS plays) for another team.
    """
    ol_roster = roster[roster["position"] == "OL"].sort_values(["season", "week"])
    roster_ol = (ol_roster.groupby(["gsis_id", "season"], as_index=False).first()
                 .rename(columns={"gsis_id": "player_id"}))
    roster_ol["team_now"] = _norm(roster_ol["team"])
    roster_ol = roster_ol[["player_id", "season", "team_now"]]
    counts = _on_field_counts(participation, pbp)
    ol = counts[counts["player_id"].isin(set(roster_ol["player_id"]))][["player_id", "team", "season", "plays"]]

    prior = ol.assign(season=ol["season"] + 1)                                        # last season's usage, keyed to t
    start = _roster_start(roster)                                                      # skill players receive the features
    on_roster = prior.merge(roster_ol, on=["player_id", "season"], how="left")
    on_roster["stayed"] = on_roster["team_now"] == on_roster["team"]

    top5 = on_roster.sort_values("plays", ascending=False).groupby(["team", "season"]).head(OL_STARTERS)
    returning = top5.groupby(["team", "season"])["stayed"].sum().rename("ol_returning_starters")
    total = on_roster.groupby(["team", "season"])["plays"].sum()
    kept = on_roster[on_roster["stayed"]].groupby(["team", "season"])["plays"].sum()
    continuity = (kept / total).reindex(total.index).fillna(0).rename("ol_snap_continuity")
    arrived = on_roster[(on_roster["plays"] >= OL_STARTER_SNAPS) & on_roster["team_now"].notna() & ~on_roster["stayed"]]
    incoming = arrived.groupby(["team_now", "season"]).size().rename("ol_incoming_starters")
    incoming.index = incoming.index.set_names(["team", "season"])

    team = pd.concat([returning, continuity], axis=1).join(incoming).reset_index()
    team["ol_incoming_starters"] = team["ol_incoming_starters"].fillna(0)
    team = team.rename(columns={"team": "team_now"})
    return start.merge(team, on=["team_now", "season"], how="left")[["player_id", "season"] + ADVANCED_GROUPS["ol"]]


def _line_yard_credit(yards):
    """Football Outsiders' adjusted-line-yards weights: losses x1.2, 0-4 yards x1, 5-10 yards x0.5, beyond 10 nothing."""
    return np.where(yards < 0, 1.2 * yards, np.where(yards <= 4, yards, 4 + 0.5 * (np.minimum(yards, 10) - 4)))


def _situation(plays):
    """Down and distance bucket used to adjust for how hard the situation is."""
    return plays["down"].astype(int).astype(str) + "_" + pd.cut(plays["ydstogo"], [-1, 2, 5, 9, 99], labels=False).astype(str)


def build_ol_quality_features(pbp, roster, ol_features):
    """Prior-season team adjusted line yards (run) and adjusted sack rate (pass), relative to the league in the same
    down and distance, for the team a player starts season t with, plus both crossed with that team's OL continuity.

    Rebuilt from play-by-play in the spirit of Football Outsiders; no opponent adjustment. Both are outcomes shared
    with the back and the quarterback, so they are noisy measures of the line.
    """
    plays = pbp[(pbp["season_type"] == "REG") & pbp["down"].notna()].copy()
    plays["team"] = _norm(plays["posteam"])
    plays["situation"] = _situation(plays)

    runs = plays[(plays["play_type"] == "run") & (plays["qb_scramble"] != 1) & (plays["qb_kneel"] != 1)
                 & plays["yards_gained"].notna()].copy()
    runs["credit"] = _line_yard_credit(runs["yards_gained"].values)
    runs["aly"] = runs["credit"] - runs.groupby("situation")["credit"].transform("mean")

    dropbacks = plays[plays["qb_dropback"] == 1].copy()
    dropbacks["asr"] = 100 * (dropbacks["sack"] - dropbacks.groupby("situation")["sack"].transform("mean"))

    team = pd.concat([runs.groupby(["team", "season"])["aly"].mean().rename("ol_aly_prev"),
                      dropbacks.groupby(["team", "season"])["asr"].mean().rename("ol_asr_prev")], axis=1).reset_index()
    team = _shift_to_next_season(team).rename(columns={"team": "team_now"})
    out = _roster_start(roster).merge(team, on=["team_now", "season"], how="left")
    out = out.merge(ol_features[["player_id", "season", "ol_snap_continuity"]], on=["player_id", "season"], how="left")
    out["ol_aly_x_cont"] = out["ol_aly_prev"] * out["ol_snap_continuity"]
    out["ol_asr_x_cont"] = out["ol_asr_prev"] * out["ol_snap_continuity"]
    return out[["player_id", "season"] + ADVANCED_GROUPS["ol_quality"] + ADVANCED_GROUPS["ol_interaction"]]


def _depth_tier(position, rank):
    """Old charts list WRs in pairs per tier; newer snapshots rank every player sequentially."""
    return np.where(position == "WR", np.ceil(rank / 2), rank)


def build_depth_features(depth_old, depth_new_by_season):
    """Week-1 depth tier (1 = starter) for QB/RB/WR/TE in season t, from the chart published before the opener."""
    old = depth_old.copy()
    old["season"] = old["season"].astype(int)
    old["position"] = old["depth_position"].replace({"HB": "RB", "FB": "RB"})
    old["tier"] = pd.to_numeric(old["depth_team"], errors="coerce")
    frames = [old[["gsis_id", "season", "tier"]]]
    for season, snapshots in depth_new_by_season.items():
        before = snapshots[snapshots["dt"] < OPENERS[season]]
        chart = before[before["dt"] == before["dt"].max()].copy()
        chart["position"] = chart["pos_abb"].replace({"FB": "RB"})
        chart["tier"] = _depth_tier(chart["position"], chart["pos_rank"].astype(float))
        chart.loc[chart["tier"] > MAX_DEPTH_TIER, "tier"] = np.nan   # old charts stopped at tier 3; keep the scales alike
        chart["season"] = season
        frames.append(chart[["gsis_id", "season", "tier"]])
    depth = pd.concat(frames).dropna(subset=["gsis_id", "tier"])
    depth = depth.groupby(["gsis_id", "season"], as_index=False)["tier"].min()
    return depth.rename(columns={"gsis_id": "player_id", "tier": "depth_tier_wk1"})


def build_team_epa_features(pbp, roster):
    """Prior-season offensive EPA/play (pass, rush) and success rate of the team a player starts season t with."""
    plays = pbp[(pbp["season_type"] == "REG") & pbp["play_type"].isin(["pass", "run"]) & pbp["epa"].notna()].copy()
    plays["team"] = _norm(plays["posteam"])
    team = plays.groupby(["team", "season"]).apply(lambda g: pd.Series({
        "team_pass_epa_prev": g.loc[g["play_type"] == "pass", "epa"].mean(),
        "team_rush_epa_prev": g.loc[g["play_type"] == "run", "epa"].mean(),
        "team_success_prev": g["success"].mean()})).reset_index()
    team = _shift_to_next_season(team).rename(columns={"team": "team_now"})
    return _roster_start(roster).merge(team, on=["team_now", "season"], how="left")[
        ["player_id", "season"] + ADVANCED_GROUPS["team_epa"]]


def build_ngs_features(ngs_by_type):
    """Season-level Next Gen Stats (week 0 rows), one column per metric, prefixed by stat type."""
    merged = None
    for kind, columns in NGS_COLUMNS.items():
        frame = ngs_by_type[kind][["player_gsis_id", "season"] + columns].rename(columns={"player_gsis_id": "player_id"})
        frame = frame.rename(columns={c: f"ngs_{kind[:4]}_{c}" for c in columns})
        merged = frame if merged is None else merged.merge(frame, on=["player_id", "season"], how="outer")
    return _shift_to_next_season(merged)


def load_advanced_context(roster):
    """All groups from the cached raw files, as {group: frame}."""
    pbp = pd.read_parquet(RAW / "pbp_20_25.parquet", columns=["game_id", "play_id", "season", "season_type", "posteam",
                                                               "play_type", "epa", "success", "pass", "rush", "down",
                                                               "ydstogo", "yards_gained", "qb_scramble", "qb_kneel",
                                                               "qb_dropback", "sack"])
    participation = pd.read_parquet(RAW / "participation_16_25.parquet")
    ngs = {kind: pd.read_parquet(RAW / f"ngs_{kind}_16_25.parquet") for kind in NGS_COLUMNS}
    depth_new = {season: pd.read_parquet(RAW / f"depth_new_{season}.parquet") for season in OPENERS}
    ol = build_ol_features(participation, pbp, roster)
    ol_quality = build_ol_quality_features(pbp, roster, ol)
    return {
        "xfp": build_xfp_features(pd.read_parquet(RAW / "ff_opportunity_14_25.parquet")),
        "role": build_role_features(participation, pbp),
        "ol": ol,
        "ol_quality": ol_quality,
        "ol_interaction": ol_quality,
        "depth": build_depth_features(pd.read_parquet(RAW / "depth_old_14_24.parquet"), depth_new),
        "team_epa": build_team_epa_features(pbp, roster),
        "ngs": build_ngs_features(ngs),
        "rookie_comp": build_rookie_competition_features(roster),
        "volatility": build_volatility_features(pd.read_parquet(
            RAW / "weekly_20_25.parquet", columns=["player_id", "season", "week", "season_type", "fantasy_points_ppr"])),
    }


def add_advanced_features(df, context, columns, season_offset=0):
    """Merge the requested advanced columns onto df; season_offset=1 maps a 2025 prediction row to 2026 context."""
    for group, frame in context.items():
        wanted = [c for c in ADVANCED_GROUPS[group] if c in columns]
        if wanted:
            keyed = frame[["player_id", "season"] + wanted].assign(season=lambda d: d["season"] - season_offset)
            df = df.merge(keyed, on=["player_id", "season"], how="left")
    return df
