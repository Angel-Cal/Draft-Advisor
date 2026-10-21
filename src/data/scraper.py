"""NFL data scraping and API integration module."""

import requests
from bs4 import BeautifulSoup
import pandas as pd
from pathlib import Path
from typing import Optional
import time
import logging
import nflreadpy as nflread
from pathlib import Path



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
DATA_DIR = Path("data/raw")
DATA_DIR.mkdir(parents=True, exist_ok=True)

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


def _import_roster_2026():
    """Start-of-season roster for the prediction season (vacated-volume features)."""
    raw_roster = nflread.load_rosters([2026]).to_pandas()
    for col in ['jersey_number', 'draft_number', 'draft_club']:
        raw_roster[col] = raw_roster[col].astype(str)
    raw_roster.to_parquet(DATA_DIR / "roster_2026.parquet")


if __name__ == "__main__":
    _import_data()
    _import_roster_2026()
    _import_advanced_sources()

