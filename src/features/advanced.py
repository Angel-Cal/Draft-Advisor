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
}


def _shift_to_next_season(df):
    return df.assign(season=df["season"] + 1)


def build_xfp_features(opportunity):
    """Expected PPR from opportunity (ff_opportunity) and how far actual PPR was above it."""
    g = opportunity.groupby(["player_id", "season"]).agg(
        xfp=("total_fantasy_points_exp", "sum"), fp=("total_fantasy_points", "sum"), weeks=("week", "nunique")).reset_index()
    g["xfp_ppr_prev"] = g["xfp"]
    g["fp_over_exp_prev"] = g["fp"] - g["xfp"]
    g["xfp_pg_prev"] = g["xfp"] / g["weeks"]
    return _shift_to_next_season(g[["player_id", "season"] + ADVANCED_GROUPS["xfp"]])


def build_role_features(participation, pbp):
    """Share of the team's pass and rush plays a player was on the field for, last season."""
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
    counts = counts.merge(team_totals.reset_index()[["team", "season", "team_pass", "team_rush"]], on=["team", "season"])
    counts["pass_snap_share_prev"] = counts["pass_plays"] / counts["team_pass"]
    counts["rush_snap_share_prev"] = counts["rush_plays"] / counts["team_rush"]
    # a traded player keeps the team where he was on the field most
    counts = counts.sort_values("plays", ascending=False).drop_duplicates(["player_id", "season"])
    return _shift_to_next_season(counts[["player_id", "season"] + ADVANCED_GROUPS["role"]])


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
                                                               "play_type", "epa", "success", "pass", "rush"])
    ngs = {kind: pd.read_parquet(RAW / f"ngs_{kind}_16_25.parquet") for kind in NGS_COLUMNS}
    depth_new = {season: pd.read_parquet(RAW / f"depth_new_{season}.parquet") for season in OPENERS}
    return {
        "xfp": build_xfp_features(pd.read_parquet(RAW / "ff_opportunity_14_25.parquet")),
        "role": build_role_features(pd.read_parquet(RAW / "participation_16_25.parquet"), pbp),
        "depth": build_depth_features(pd.read_parquet(RAW / "depth_old_14_24.parquet"), depth_new),
        "team_epa": build_team_epa_features(pbp, roster),
        "ngs": build_ngs_features(ngs),
    }


def add_advanced_features(df, context, columns, season_offset=0):
    """Merge the requested advanced columns onto df; season_offset=1 maps a 2025 prediction row to 2026 context."""
    for group, frame in context.items():
        wanted = [c for c in ADVANCED_GROUPS[group] if c in columns]
        if wanted:
            keyed = frame[["player_id", "season"] + wanted].assign(season=lambda d: d["season"] - season_offset)
            df = df.merge(keyed, on=["player_id", "season"], how="left")
    return df
