"""How much of the advisor's edge is luck in how the positions did against their ADP pricing? (LOG.md, 2026-10-30)

The advisor's gain is mostly cross-position choices in rounds 3-6, chiefly WR taken where ADP would take an RB, and that gain flips sign with the season's RB-minus-WR outcome (-0.64 across 7 seasons).
This builds copies of the backtest files in which each position's outcomes (actual_ppr and weekly_ppr) are rescaled so that, among the draftable players, no position beats or trails what its ADP
pricing implies relative to the other positions: the factor is (mean ADP-curve value / mean actual) of the position divided by the same ratio over all positions, so the overall level does not move.
The curve is fitted on the other seasons (leave-one-season-out, 2015-2025). Projections and ADP are untouched.
If the edge is mostly position luck it should fall toward the outcome-shuffled level (about +13 a season); if it stays near its usual size the allocation logic is doing real work.

Run: python src/evaluation/position_neutral.py   (writes data/processed/posneutral/validated and .../routed; `backtest --data <dir> --seasons 2019-2025`)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.draft.market_fallback import fit_position_curves, load_history

ROOT = Path(__file__).parent.parent.parent
PROCESSED = ROOT / "data" / "processed"
SEASONS = range(2019, 2026)
DRAFTABLE_ADP = 150
SOURCES = {"validated": PROCESSED, "routed": PROCESSED / "routed" / "routed"}


def position_factors(players, curves):
    """position -> factor that rescales its outcomes, from the draftable rows of one season's file."""
    df = pd.DataFrame(players)
    df = df[df["adp"] <= DRAFTABLE_ADP].copy()
    df["position_rank"] = df.groupby("position")["adp"].rank(method="first")
    df["curve"] = [curves[p].predict([r])[0] for p, r in zip(df["position"], df["position_rank"])]
    played = df[df["actual_ppr"] >= 40]                      # the curve is fitted on players with 4 or more games
    ratio = played.groupby("position")["curve"].mean() / played.groupby("position")["actual_ppr"].mean()
    overall = played["curve"].mean() / played["actual_ppr"].mean()
    return (ratio / overall).to_dict()


def neutralize(data, factors):
    for player in data["players"]:
        factor = factors.get(player["position"], 1.0)
        player["actual_ppr"] = round(player["actual_ppr"] * factor, 2)
        if player.get("weekly_ppr"):
            player["weekly_ppr"] = [None if w is None else round(w * factor, 2) for w in player["weekly_ppr"]]
    return data


if __name__ == "__main__":
    history = load_history(range(2015, 2026))
    table = {}
    for name, source in SOURCES.items():
        out = PROCESSED / "posneutral" / name
        out.mkdir(parents=True, exist_ok=True)
        for season in SEASONS:
            data = json.loads((source / f"projections_{season}_v1.json").read_text())
            factors = position_factors(data["players"], fit_position_curves(history[history["season"] != season]))
            table[(name, season)] = factors
            data["adp_source"] = data["adp_source"] + "; outcomes position-neutral (position_neutral.py)"
            (out / f"projections_{season}_v1.json").write_text(json.dumps(neutralize(data, factors)))
    print("factor applied to each position's outcomes (validated files): below 1 = the position beat its ADP pricing that season")
    print(pd.DataFrame({season: table[("validated", season)] for season in SEASONS}).round(3).to_string())
    print(f"\nwrote {PROCESSED / 'posneutral'}")
