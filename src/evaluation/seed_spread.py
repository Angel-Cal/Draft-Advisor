"""How much of the simulator edge is the projection file's luck? Builds backtest projection files from different seed sets for both recipes.

The draft-level standard error in `backtest` covers only draft randomness; the projections themselves (five LightGBM seeds averaged) are one more draw.
For each seed set (0-4 is the one already measured; 5-9 and 10-14 are new) this writes, to data/processed/seedtest/<recipe>_<first seed>/:
  val_*    validated recipe: early-stopped on the previous season, trained through the season before it (as `oos_predictions.py`)
  refit_*  refit recipe: `Model.refit_predict`, trained through the previous season
Headers keep the original position RMSE (no rescaling), which also tests whether the rescaling in data/processed/refit mattered.
Then run `backtest --data data/processed/seedtest/<name> --seasons 2021-2025 --seeds 100` on each.

Run: python src/evaluation/seed_spread.py
"""
import contextlib
import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.oos_predictions import load_params, position_oos
from src.evaluation.refit_oos import POSITIONS, PROCESSED_DIR, write_backtest_files
from src.models.train import Model, split_positions

SEED_SETS = {"0": range(0, 5), "5": range(5, 10), "10": range(10, 15)}


def seed_set_predictions(frames, seeds):
    """Per-row mean prediction of both recipes over `seeds`, one row per player-season in 2021-2025."""
    model = Model()
    rows = []
    for position, pos_df in zip(POSITIONS, frames):
        params = load_params(position)
        with contextlib.redirect_stdout(io.StringIO()):  # train_model logs every 50 rounds
            runs = [position_oos(pos_df, position, model, dict(params, random_state=seed)) for seed in seeds]
        base = runs[0][["player_id", "season"]].copy()
        base["val_pred"] = pd.concat([run["oos_pred_ppr"] for run in runs], axis=1).mean(axis=1)
        refit = [pd.Series(model.refit_predict(x_train, y_train, x_val, y_val, x_test, params, seeds=seeds), index=x_test.index)
                 for x_train, x_val, x_test, y_train, y_val, y_test in model.rolling_splits(pos_df)]
        base["refit_pred"] = pd.concat(refit).loc[base.index]
        rows.append(base)
    return pd.concat(rows, ignore_index=True)


if __name__ == "__main__":
    frames = split_positions(pd.read_parquet(PROCESSED_DIR / "training_data.parquet"))
    for first, seeds in SEED_SETS.items():
        preds = seed_set_predictions(frames, seeds)
        for recipe in ["val", "refit"]:
            out = write_backtest_files(preds, f"{recipe}_pred", PROCESSED_DIR / "seedtest" / f"{recipe}_{first}",
                                       f"{recipe} recipe, seeds {seeds.start}-{seeds.stop - 1} (seed_spread.py)")
            print(f"wrote {out}", flush=True)
