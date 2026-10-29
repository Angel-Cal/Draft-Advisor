"""ADP-derived projections for players the model cannot score (rookies, players with no prior NFL season).

An isotonic curve per position maps rank-within-position (by ADP) to expected season PPR, fit on 2021-2025
FantasyPros ADP and actual results. Rank within position, not overall ADP, is the input because sources price
positions differently (Underdog's top 100 holds ~60 WRs; FantasyPros ~43), while the order within a position agrees (the live ADP is FantasyPros too, so this guards against a source change).
"""

import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).parent.parent.parent
POSITIONS = ["QB", "RB", "WR", "TE"]
HISTORY_SEASONS = range(2021, 2026)
MAX_FIT_ADP = 250
SYNTHETIC_PREFIX = "market:"


def load_history():
    """One row per player-season with a position-rank by ADP and the actual season PPR (>= 4 games)."""
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")
    seasonal = seasonal[seasonal["player_id"].notna()]
    frames = []
    for season in HISTORY_SEASONS:
        adp = pd.read_csv(ROOT / "data" / "external" / f"adp_{season}.csv")[["player_id", "position", "adp"]]
        actual = seasonal[seasonal["season"] == season][["player_id", "fantasy_points_ppr", "games"]]
        frame = adp.merge(actual, on="player_id")
        frame["season"] = season
        frame["position_rank"] = frame.groupby("position")["adp"].rank(method="first")
        frames.append(frame[(frame["games"] >= 4) & (frame["adp"] <= MAX_FIT_ADP)])
    return pd.concat(frames).rename(columns={"fantasy_points_ppr": "actual_ppr"})


def fit_position_curves(history):
    """{position: monotone-decreasing map from position rank to expected PPR}."""
    return {position: IsotonicRegression(increasing=False, out_of_bounds="clip").fit(group["position_rank"],
                                                                                    group["actual_ppr"])
            for position, group in history.groupby("position")}


def market_projections(adp_table, model_player_ids, curves):
    """Fallback rows for every skill player in the ADP table the model has no projection for.

    adp_table needs: Player, merge_name, Position (first two letters = position, e.g. 'WR'), ADP, player_id (NaN if unknown).
    """
    table = adp_table.copy()
    table["position"] = table["Position"].str[:2]
    table = table[table["position"].isin(POSITIONS)].drop_duplicates(["Player", "Position"])
    # rank within position is taken over everyone in the table, modeled or not, so rookies slot in correctly
    table["position_rank"] = table.groupby("position")["ADP"].rank(method="first")
    table = table[~table["player_id"].isin(model_player_ids)].copy()

    table["projected_ppr"] = [float(curves[p].predict([r])[0]) for p, r in zip(table["position"], table["position_rank"])]
    table["player_id"] = table["player_id"].fillna(SYNTHETIC_PREFIX + table["merge_name"])
    return pd.DataFrame({
        "player_name": table["Player"], "player_id": table["player_id"], "games": 17.0, "games_delta": 0.0,
        "injury_flag": False, "projected_ppr": table["projected_ppr"], "position": table["position"],
        "adp": table["ADP"], "market_estimate": True,
    }).reset_index(drop=True)
