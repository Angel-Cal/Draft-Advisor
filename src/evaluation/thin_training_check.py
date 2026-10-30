"""How does the length and recency of the training window change the advisor's edge? (LOG.md, 2026-10-29)

Predicts test seasons the walk-forward way (early-stop on the season before, 5 seeds averaged, params as saved) but with a different training window, and writes backtest files with those
projections (`backtest --data <out> --seasons ...`):
  --fixed 2015-2017:2018   train on 2015-2017, early-stop on 2018, for every test season (the shape of the 2019 fold; thin training)
  --window 6               train on the 6 seasons ending two before the test season, early-stop on the season before (a rolling window instead of all earlier seasons; 99 = all of them, the walk-forward itself)
  --seed-offset 5          seeds 5-9 instead of 0-4: the same recipe with other model seeds, to see how much the edge moves from seeds alone
Default: --fixed 2015-2017:2018 --tests 2021,2022,2023 --out thin.

Run: python src/evaluation/thin_training_check.py [--fixed A-B:V | --window W] [--tests 2022,2023,2024,2025] [--out NAME]
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.oos_predictions import N_SEEDS, load_params
from src.evaluation.refit_oos import POSITIONS, write_backtest_files
from src.models.train import Model, drop_non_features, split_positions

ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"


def windows(season, fixed=None, window=None):
    """(train seasons, validation season) for a test season: the fixed span, or the `window` seasons ending two before it."""
    if fixed:
        return fixed
    return range(max(2015, season - 1 - window), season - 1), season - 1


def window_predictions(tests, fixed=None, window=None, seed_offset=0):
    """One row per player-season in `tests` with the early-stopped, 5-seed projection from the chosen training window."""
    df = pd.read_parquet(PROCESSED_DIR / "training_data.parquet")
    model = Model()
    rows = []
    for position, pos_df in zip(POSITIONS, split_positions(df)):
        for season in tests:
            train, val = windows(season, fixed, window)
            in_train, in_val = pos_df[pos_df["season"].isin(train)], pos_df[pos_df["season"] == val]
            test = pos_df[pos_df["season"] == season]
            out = test[["player_id", "player_name", "position", "season"]].copy()
            x_test = drop_non_features(test)
            preds = [model.train_model(drop_non_features(in_train), drop_non_features(in_val), in_train["target_ppr"], in_val["target_ppr"],
                                       dict(load_params(position), random_state=seed)).predict(x_test) for seed in range(seed_offset, seed_offset + N_SEEDS)]
            out["window_pred_ppr"] = sum(preds) / N_SEEDS
            rows.append(out)
        print(f"{position} done", flush=True)
    return pd.concat(rows, ignore_index=True)


if __name__ == "__main__":
    arg = lambda name, default: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default
    tests = [int(x) for x in arg("--tests", "2021,2022,2023").split(",")]
    window = int(arg("--window", 0)) or None
    fixed = None
    if not window:
        span, val = arg("--fixed", "2015-2017:2018").split(":")
        fixed = (range(int(span.split("-")[0]), int(span.split("-")[1]) + 1), int(val))
    name = arg("--out", "thin")
    d = window_predictions(tests, fixed, window, int(arg("--seed-offset", 0)))
    write_backtest_files(d, "window_pred_ppr", PROCESSED_DIR / name, f"training window {'rolling ' + str(window) if window else arg('--fixed', '2015-2017:2018')} (thin_training_check.py)", seasons=tests)
    print(f"wrote {PROCESSED_DIR / name}")
