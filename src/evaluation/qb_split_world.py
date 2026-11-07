"""Backtest world with the split QB model: the validated files with every model-scored QB's projected_ppr replaced.

The split model (LOG 2026-11-06): games = LightGBM(all QB features + depth_tier_wk1), points per game = LightGBM boosted
from ridge(rushing, passing points per game), projection = product; walk-forward from 2019 (every season before the
validation season trains), mean of seeds 0-4 like the validated recipe. Market rows and every other field are copied
unchanged, so plain ADP drafts and scores the same in both worlds. Writes data/processed/experiments/worlds/qb_split/.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.paths import LIVE, PIPELINE
from src.evaluation.oos_predictions import load_params
from src.evaluation.qb_component_test import games_played
from src.evaluation.qb_games_test import prepare, run_arm

ROOT = Path(__file__).parent.parent.parent
WORLD = ROOT / "data" / "processed" / "experiments" / "worlds" / "qb_split"
SEASONS = range(2019, 2026)
SEEDS = range(5)


def split_predictions():
    """(player_id, season) -> 5-seed mean split-model QB projection, test seasons 2019-2025."""
    qb = prepare(pd.read_parquet(PIPELINE / "training_data.parquet"))
    g1 = qb[["player_id", "season"]].merge(games_played(), how="left")["G1"].fillna(0).set_axis(qb.index)
    params = load_params("QB")
    runs = [run_arm(qb, g1, ["depth_tier_wk1"], params, seed, first_test=min(SEASONS)).set_index(["player_id", "season"])["pred"]
            for seed in SEEDS]
    return pd.concat(runs, axis=1).mean(axis=1)


if __name__ == "__main__":
    preds = split_predictions()
    WORLD.mkdir(parents=True, exist_ok=True)
    for season in SEASONS:
        doc = json.loads((LIVE / f"projections_{season}_v1.json").read_text())
        changed, moves = 0, []
        for p in doc["players"]:
            key = (p["player_id"], season)
            if p["position"] == "QB" and not p["market_estimate"] and key in preds.index:
                new = round(float(preds[key]), 2)
                moves.append((p["player_name"], p["projected_ppr"], new))
                p["projected_ppr"], changed = new, changed + 1
        (WORLD / f"projections_{season}_v1.json").write_text(json.dumps(doc, indent=1, allow_nan=False))
        top = sorted(moves, key=lambda m: -abs(m[2] - m[1]))[:4]
        print(f"{season}: {changed} QBs replaced; biggest moves", ", ".join(f"{n} {a:.0f}->{b:.0f}" for n, a, b in top))
