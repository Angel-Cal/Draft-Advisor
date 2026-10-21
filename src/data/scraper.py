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

    


def _import_roster_2026():
    """Start-of-season roster for the prediction season (vacated-volume features)."""
    raw_roster = nflread.load_rosters([2026]).to_pandas()
    for col in ['jersey_number', 'draft_number', 'draft_club']:
        raw_roster[col] = raw_roster[col].astype(str)
    raw_roster.to_parquet(DATA_DIR / "roster_2026.parquet")


if __name__ == "__main__":
    _import_data()
    _import_roster_2026()

