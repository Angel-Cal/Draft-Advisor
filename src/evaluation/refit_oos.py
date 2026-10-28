"""Does the refit recipe (`Model.refit_predict`) recover the validated walk-forward accuracy that the live-style training loses?

For each test season 2021-2025 and position: early-stop on the previous season (fit on the seasons before it), refit on every season before the test season
at the best iteration, 5 seeds averaged. Both refit tree counts are run: exactly the best iteration, and scaled by the data-size ratio.
Writes data/processed/refit_oos.parquet and prints RMSE and top-150 Spearman next to the validated (`season_<year>.parquet`) and live-style
(`live_style_oos.parquet`) numbers, and writes backtest projection files with the unscaled refit predictions to data/processed/refit/
(`backtest --data data/processed/refit --seasons 2021-2025 --seeds 100` measures the simulator edge).

Run: python src/evaluation/refit_oos.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.benchmark import load_season
from src.evaluation.live_style_oos import rmse
from src.evaluation.oos_predictions import load_params
from src.models.train import Model, split_positions

ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
POSITIONS = ["QB", "RB", "WR", "TE"]
SEASONS = range(2021, 2026)
VARIANTS = {"refit_pred_ppr": False, "refit_scaled_pred_ppr": True}


def refit_predictions():
    """One row per player-season in 2021-2025 with a prediction column per refit variant."""
    df = pd.read_parquet(PROCESSED_DIR / "training_data.parquet")
    model = Model()
    rows = []
    for position, pos_df in zip(POSITIONS, split_positions(df)):
        params = load_params(position)
        for x_train, x_val, x_test, y_train, y_val, y_test in model.rolling_splits(pos_df):
            out = pos_df.loc[x_test.index, ["player_id", "player_name", "position", "season"]].copy()
            out["actual_ppr"] = y_test
            for column, scale in VARIANTS.items():
                out[column] = model.refit_predict(x_train, y_train, x_val, y_val, x_test, params, scale_trees=scale)
            rows.append(out)
        print(f"{position} done", flush=True)
    return pd.concat(rows, ignore_index=True)


def write_backtest_files(predictions, column, out_dir, note, ratios=None):
    """Copies of the backtest projection files with projected_ppr replaced by `column` (`backtest --data <out_dir>` then scores them).

    ratios optionally scales each position's RMSE in the file header; market-estimate rows keep their projection.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for season in SEASONS:
        path = PROCESSED_DIR / f"projections_{season}_v1.json"
        data = json.loads(path.read_text())
        pred = predictions[predictions["season"] == season].set_index("player_id")[column]
        for player in data["players"]:
            if not player["market_estimate"] and player["player_id"] in pred.index:
                player["projected_ppr"] = round(float(pred[player["player_id"]]), 2)
        if ratios:
            data["position_rmse"] = {p: round(v * ratios[p], 2) for p, v in data["position_rmse"].items()}
        data["adp_source"] = data["adp_source"] + f"; projected_ppr = {note}"
        (out_dir / path.name).write_text(json.dumps(data))
    return out_dir


if __name__ == "__main__":
    refit = refit_predictions()
    refit.to_parquet(PROCESSED_DIR / "refit_oos.parquet")
    live = pd.read_parquet(PROCESSED_DIR / "live_style_oos.parquet")[["player_id", "season", "live_pred_ppr"]]

    frames = []
    for season in SEASONS:
        part = refit[refit["season"] == season][["player_id", *VARIANTS]]
        frames.append(load_season(season).merge(part, on="player_id", how="left")
                      .merge(live[live["season"] == season][["player_id", "live_pred_ppr"]], on="player_id", how="left")
                      .assign(season=season))
    d = pd.concat(frames, ignore_index=True).dropna(subset=[*VARIANTS, "live_pred_ppr"])

    columns = {"validated": "oos_pred_ppr", "live-style": "live_pred_ppr", "refit": "refit_pred_ppr", "refit x ratio": "refit_scaled_pred_ppr"}
    print("\nRMSE, 2021-2025")
    print(f"  {'position':<9}{'n':>5}" + "".join(f"{name:>15}" for name in columns))
    for position, g in d.groupby("position"):
        print(f"  {position:<9}{len(g):>5}" + "".join(f"{rmse(g[col], g['actual_ppr']):>15.1f}" for col in columns.values()))

    print("\nTop-150 Spearman (mean over seasons), 2021-2025")
    print(f"  {'position':<9}" + "".join(f"{name:>15}" for name in columns))
    for position, g in d.groupby("position"):
        top = g[g["in_top_adp"]]
        print(f"  {position:<9}" + "".join(
            f"{np.mean([spearmanr(s[col], s['actual_ppr'])[0] for _, s in top.groupby('season')]):>15.3f}" for col in columns.values()))

    # position RMSE in each header is scaled by the refit/validated ratio, as in live_style_oos.py
    ratios = {p: rmse(g["refit_pred_ppr"], g["actual_ppr"]) / rmse(g["oos_pred_ppr"], g["actual_ppr"]) for p, g in d.groupby("position")}
    out_dir = write_backtest_files(refit, "refit_pred_ppr", PROCESSED_DIR / "refit", "refit training (refit_oos.py)", ratios)
    print(f"\nRMSE scaled by {({p: round(r, 3) for p, r in ratios.items()})}; wrote {out_dir}")
