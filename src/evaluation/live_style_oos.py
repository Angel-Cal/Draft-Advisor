"""What if the validated backtests had been trained the way the live 2026 file is? `predict.py` fits each position once with the saved parameters
(a 1000-tree cap), no early stopping and one seed; `oos_predictions.py` early-stops on the previous season and averages five seeds.

For each test season 2021-2025 this trains on every earlier season (the walk-forward train and validation seasons together, as the live model sees all
past data) the live way, writes the predictions to data/processed/live_style_oos.parquet, and writes copies of the backtest projection files with
projected_ppr replaced to data/processed/live_style/ (position RMSE in each header scaled by the live-style/validated RMSE ratio, as in blend_test.py),
so `backtest --data data/processed/live_style --seasons 2021-2025` measures how much of the simulator edge survives the shipped recipe.

Run: python src/evaluation/live_style_oos.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.benchmark import load_season
from src.evaluation.oos_predictions import load_params
from src.models.train import Model, split_positions

ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
OUT_DIR = PROCESSED_DIR / "live_style"
POSITIONS = ["QB", "RB", "WR", "TE"]
SEASONS = range(2021, 2026)


def live_style_predictions():
    """One row per player-season in 2021-2025: predicted the live way (all earlier seasons, params as saved, no early stopping, one seed)."""
    df = pd.read_parquet(PROCESSED_DIR / "training_data.parquet")
    model = Model()
    rows = []
    for position, pos_df in zip(POSITIONS, split_positions(df)):
        params = load_params(position)
        for x_train, x_val, x_test, y_train, y_val, y_test in model.rolling_splits(pos_df):
            trained = model.train_final_model(pd.concat([x_train, x_val]), pd.concat([y_train, y_val]), params)
            out = pos_df.loc[x_test.index, ["player_id", "player_name", "position", "season"]].copy()
            out["actual_ppr"] = y_test
            out["live_pred_ppr"] = trained.predict(x_test)
            rows.append(out)
        print(f"{position} done ({params['n_estimators']} trees, seed {params['random_state']})", flush=True)
    return pd.concat(rows, ignore_index=True)


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


if __name__ == "__main__":
    live = live_style_predictions()
    live.to_parquet(PROCESSED_DIR / "live_style_oos.parquet")

    ratios, table = {}, []
    for season in SEASONS:
        df = load_season(season).merge(live[live["season"] == season][["player_id", "live_pred_ppr"]], on="player_id", how="left")
        df["season"] = season
        table.append(df.dropna(subset=["live_pred_ppr"]))
    d = pd.concat(table, ignore_index=True)

    print("\nValidated (early-stopped, 5 seeds) vs live-style (1000 trees, 1 seed), 2021-2025:")
    print(f"  {'position':<9}{'n':>5}{'RMSE val':>10}{'RMSE live':>11}{'top150 rho val':>16}{'top150 rho live':>17}{'ADP rho':>9}")
    for position, g in d.groupby("position"):
        top = g[g["in_top_adp"]]
        per_season = lambda col, frame: np.mean([spearmanr(s[col], s["actual_ppr"])[0] for _, s in frame.groupby("season")])
        adp_rho = np.mean([spearmanr(-s["adp"], s["actual_ppr"])[0] for _, s in top.groupby("season")])
        ratios[position] = rmse(g["live_pred_ppr"], g["actual_ppr"]) / rmse(g["oos_pred_ppr"], g["actual_ppr"])
        print(f"  {position:<9}{len(g):>5}{rmse(g['oos_pred_ppr'], g['actual_ppr']):>10.1f}{rmse(g['live_pred_ppr'], g['actual_ppr']):>11.1f}"
              f"{per_season('oos_pred_ppr', top):>16.3f}{per_season('live_pred_ppr', top):>17.3f}{adp_rho:>9.3f}")

    OUT_DIR.mkdir(exist_ok=True)
    for season in SEASONS:
        path = PROCESSED_DIR / f"projections_{season}_v1.json"
        data = json.loads(path.read_text())
        pred = live[live["season"] == season].set_index("player_id")["live_pred_ppr"]
        replaced = 0
        for player in data["players"]:
            if not player["market_estimate"] and player["player_id"] in pred.index:
                player["projected_ppr"] = round(float(pred[player["player_id"]]), 2)
                replaced += 1
        data["position_rmse"] = {p: round(v * ratios[p], 2) for p, v in data["position_rmse"].items()}
        data["adp_source"] = data["adp_source"] + "; projected_ppr = live-style training (live_style_oos.py)"
        (OUT_DIR / path.name).write_text(json.dumps(data))
        print(f"  {path.name}: replaced {replaced} of {len(data['players'])} projections")
    print(f"\nRMSE scaled by {({p: round(r, 3) for p, r in ratios.items()})}; wrote {OUT_DIR}")
