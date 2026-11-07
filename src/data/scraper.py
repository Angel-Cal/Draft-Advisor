"""Raw nflverse downloads into data/raw: season and weekly stats, rosters, play-by-play, snap counts, advanced sources and injury reports (pipeline step 1)."""

import sys
from pathlib import Path
import nflreadpy as nflread
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.paths import ROOT

DATA_DIR = ROOT / "data" / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)
# roster statuses of a player who is on the team (active, reserve/IR, inactive, practice squad, PUP, suspended, exempt,
# non-football lists); the rest (CUT, UFA, RFA, RET, UDF, trade codes) are listed under a team they are not on
ON_TEAM_STATUSES = {"ACT", "RES", "INA", "DEV", "PUP", "SUS", "EXE", "RSN", "RSR", "NWT"}


def _import_data():
    file_path = DATA_DIR/ "seasonal_20_25.parquet"
    raw_seasonal = nflread.load_player_stats(list(range(2014, 2026)), summary_level="reg").to_pandas()
    raw_seasonal.to_parquet(file_path)

    file_path = DATA_DIR/ "seasonal_roster_20_25.parquet"
    raw_roster = nflread.load_rosters(list(range(2014, 2026))).to_pandas()
    for col in ['jersey_number', 'draft_number', 'draft_club']:    #older data has mixed-type cols
        raw_roster[col] = raw_roster[col].astype(str)
    raw_roster.to_parquet(file_path)

    file_path = DATA_DIR/ "ids.parquet"
    raw_id = nflread.load_ff_playerids().to_pandas()
    raw_id.to_parquet(file_path)

    file_path = DATA_DIR/ "weekly_20_25.parquet"
    raw_weekly = nflread.load_player_stats(list(range(2014, 2026)), summary_level="week").to_pandas()
    raw_weekly.to_parquet(file_path)

    file_path = DATA_DIR/ "pbp_20_25.parquet"
    raw_pbp = nflread.load_pbp(list(range(2014, 2026))).to_pandas()
    raw_pbp.to_parquet(file_path)

    file_path = DATA_DIR/ "snap_counts_20_25.parquet"
    raw_snap_counts = nflread.load_snap_counts(list(range(2014, 2026))).to_pandas()
    raw_snap_counts.to_parquet(file_path)

    


def _import_advanced_sources():
    """Expected fantasy points, participation, Next Gen Stats and depth charts (nflverse, public)."""
    seasons = list(range(2014, 2026))
    opp_cols = ["season", "week", "posteam", "player_id", "position", "total_fantasy_points", "total_fantasy_points_exp",
                "rush_fantasy_points_exp", "rec_fantasy_points_exp", "pass_fantasy_points_exp"]
    opp = nflread.load_ff_opportunity(seasons=seasons).to_pandas()[opp_cols]
    opp["season"] = opp["season"].astype(int)
    opp.to_parquet(DATA_DIR / "ff_opportunity_14_25.parquet")

    part = nflread.load_participation(seasons=list(range(2016, 2026))).to_pandas()
    part[["nflverse_game_id", "play_id", "possession_team", "offense_players"]].to_parquet(DATA_DIR / "participation_16_25.parquet")

    for stat_type in ["passing", "rushing", "receiving"]:
        ngs = nflread.load_nextgen_stats(seasons=list(range(2016, 2026)), stat_type=stat_type).to_pandas()
        ngs[ngs["week"] == 0].to_parquet(DATA_DIR / f"ngs_{stat_type}_16_25.parquet")   # week 0 = season totals

    skill = ["QB", "RB", "HB", "FB", "WR", "TE"]
    old = nflread.load_depth_charts(seasons=list(range(2014, 2025))).to_pandas()
    old = old[old["season"].notna() & (old["week"] == 1) & old["depth_position"].isin(skill)]
    old[["season", "club_code", "depth_team", "depth_position", "gsis_id"]].to_parquet(DATA_DIR / "depth_old_14_24.parquet")
    for season in (2025, 2026):   # newer snapshots: timestamped, rank within position
        new = nflread.load_depth_charts(seasons=[season]).to_pandas()
        new[new["pos_abb"].isin(skill)][["dt", "team", "pos_abb", "pos_rank", "gsis_id"]].to_parquet(DATA_DIR / f"depth_new_{season}.parquet")


def _import_injuries():
    """Weekly official injury reports 2018-2025 (nflverse): body part only, the candidate source for the major-injury list."""
    injuries = nflread.load_injuries(seasons=list(range(2018, 2026))).to_pandas()
    injuries = injuries[injuries["game_type"] == "REG"]
    injuries[["season", "week", "gsis_id", "full_name", "position", "team", "report_primary_injury",
              "report_secondary_injury", "report_status"]].to_parquet(DATA_DIR / "injuries_18_25.parquet")


def week1_rosters(seasons):
    """Week-1 regular-season rosters: who is on each team when the season starts.

    load_rosters keeps each player's LAST week (17-22), so its team and roster mates include in-season trades and
    signings of the season being predicted; every start-of-season feature reads these week-1 rows instead.
    """
    raw = nflread.load_rosters_weekly(list(seasons)).to_pandas()
    raw = raw[(raw["week"] == 1) & (raw["game_type"] == "REG") & raw["status"].isin(ON_TEAM_STATUSES)].copy()
    raw = raw.sort_values("status", key=lambda s: s != "ACT").drop_duplicates(["gsis_id", "season"])   # two rows: the active one
    for col in ['jersey_number', 'draft_number', 'draft_club']:
        raw[col] = raw[col].astype(str)
    return raw


def _import_start_rosters():
    """Week-1 rosters 2014-2025 (start-of-season context features for training and backtests)."""
    week1_rosters(range(2014, 2026)).to_parquet(DATA_DIR / "roster_wk1_14_25.parquet")


def _import_roster_2026():
    """Week-1 roster of the prediction season (its start-of-season context features and team)."""
    week1_rosters([2026]).to_parquet(DATA_DIR / "roster_2026.parquet")


if __name__ == "__main__":
    _import_data()
    _import_start_rosters()
    _import_roster_2026()
    _import_advanced_sources()
    _import_injuries()

