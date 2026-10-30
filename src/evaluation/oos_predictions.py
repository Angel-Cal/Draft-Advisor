import pandas as pd
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.models.train import Model, split_positions

ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
MODELS_DIR = ROOT / "models"
FIRST_TEST_SEASON = 2021
FIRST_TRAIN_SEASON = 2015      # Model.rolling_splits trains on every season from here to two before the test season
N_SEEDS = 5  # the benchmark reports score and spread across model seeds, not one lucky draw


def load_params(position):
    with open(MODELS_DIR / f"{position.lower()}_params", "r") as f:
        return json.load(f)


def position_oos(df, position, model, params=None, first_test=FIRST_TEST_SEASON):
    """Walk-forward predictions for one position; one row per player-season from `first_test` (2021) to 2025."""
    params = params or load_params(position)
    rows = []
    for i, fold in enumerate(model.rolling_splits(df, min_train_seasons=first_test - FIRST_TRAIN_SEASON)):
        x_train, x_val, x_test, y_train, y_val, y_test = fold
        trained = model.train_model(x_train, x_val, y_train, y_val, params)
        out = df.loc[x_test.index, ["player_id", "player_name", "position", "season"]].copy()
        out["actual_ppr"] = y_test
        out["oos_pred_ppr"] = trained.predict(x_test)
        rows.append(out)
    return pd.concat(rows)


if __name__ == "__main__":
    # `--first-test 2019 --only 2019,2020` adds earlier test seasons (less training data) without touching the existing season files:
    # seasons outside --only are recomputed and compared with their file (max drift printed) but not written.
    first_test = int(sys.argv[sys.argv.index("--first-test") + 1]) if "--first-test" in sys.argv else FIRST_TEST_SEASON
    only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")} if "--only" in sys.argv else None
    df = pd.read_parquet(PROCESSED_DIR / "training_data.parquet")
    if "player_id" not in df.columns:
        sys.exit("training_data.parquet has no player_id; re-run src/data/pipeline.py")

    model = Model()
    results = []
    for pos, pos_df in zip(["QB", "RB", "WR", "TE"], split_positions(df)):
        runs = [position_oos(pos_df, pos, model, dict(load_params(pos), random_state=seed), first_test) for seed in range(N_SEEDS)]
        combined = runs[0].drop(columns="oos_pred_ppr")
        for seed, run in enumerate(runs):
            combined[f"oos_pred_s{seed}"] = run["oos_pred_ppr"]
        combined["oos_pred_ppr"] = combined[[f"oos_pred_s{seed}" for seed in range(N_SEEDS)]].mean(axis=1)
        results.append(combined)
    oos = pd.concat(results)
    oos["position"] = oos["position"].astype(str)

    for season, season_df in oos.groupby("season"):
        path = PROCESSED_DIR / f"season_{season}.parquet"
        if only is not None and season not in only:
            if path.exists():
                old = pd.read_parquet(path).set_index(["player_id", "position"])["oos_pred_ppr"]
                new = season_df.set_index(["player_id", "position"])["oos_pred_ppr"]
                print(f"season_{season}.parquet: not written; max drift against the existing file {(new.reindex(old.index) - old).abs().max():.4f}")
            continue
        season_df.reset_index(drop=True).to_parquet(path)
        print(f"season_{season}.parquet: {len(season_df)} rows")
