"""WR1/WR2 split by prior-season targets: each WR's rank among his season-t team's WRs, from stats only (no depth chart).

Players with no usable history (rookies, anyone out of the league) have no rank and do not count toward anyone else's.
"""

import pandas as pd
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.features.team_context import _roster_start

WR_RANK_FEATURES = ["wr_target_rank", "wr_target_rank_pg"]
MIN_RATE_GAMES = 4      # a season shorter than this says too little about a target rate (the same cut as the volatility features)


def _history(seasonal):
    """One row per skill player-season: targets, games and targets per game."""
    s = seasonal[seasonal["position"].isin(["RB", "WR", "TE"])].copy()
    s = s.groupby(["player_id", "season"], as_index=False).agg(targets=("targets", "sum"), games=("games", "sum"))
    s["rate"] = (s["targets"] / s["games"]).where(s["games"] >= MIN_RATE_GAMES)
    return s


def build_wr_rank_features(seasonal, roster):
    """Per WR and season t: wr_target_rank (by season t-1 targets) and wr_target_rank_pg (by targets per game in t-1, else t-2 when t-1 had < MIN_RATE_GAMES games).

    Rank 1 is the team's leader among the WRs on its start-of-season roster; ties share the better rank. Known before season t starts.
    """
    history = _history(seasonal)
    wrs = _roster_start(roster)
    wrs = wrs[wrs["position"] == "WR"].copy()
    for lag in (1, 2):
        lagged = history.assign(season=history["season"] + lag)[["player_id", "season", "targets", "rate"]]
        wrs = wrs.merge(lagged.rename(columns={"targets": f"targets_{lag}", "rate": f"rate_{lag}"}), on=["player_id", "season"], how="left")
    wrs["rate"] = wrs["rate_1"].fillna(wrs["rate_2"])
    for column, source in (("wr_target_rank", "targets_1"), ("wr_target_rank_pg", "rate")):
        wrs[column] = wrs.groupby(["team_now", "season"])[source].rank(ascending=False, method="min")
    return wrs[["player_id", "season"] + WR_RANK_FEATURES]
