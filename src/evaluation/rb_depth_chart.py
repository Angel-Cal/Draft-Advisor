"""Ablation of RB depth-chart features on top of the current RB model (which already has the vacated features)."""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.models.train import split_positions
from src.features.team_context import build_rb_depth_features, RB_DEPTH_FEATURES, RB_FEATURES
from src.evaluation.rb_team_context import evaluate, top150_keys, N_SEEDS

ROOT = Path(__file__).parent.parent.parent
ALL = RB_FEATURES + RB_DEPTH_FEATURES


def load_rb_with_depth():
    train = pd.read_parquet(ROOT / "data" / "processed" / "training_data.parquet")
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")
    roster = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_roster_20_25.parquet")
    rb = split_positions(train)[1]
    return rb.merge(build_rb_depth_features(seasonal, roster), on=["player_id", "season"], how="left").reset_index(drop=True)


def variants():
    yield "baseline (current RB model)", RB_FEATURES, 0
    yield "baseline+4 random-noise cols", RB_FEATURES, 4
    yield "all depth features", ALL, 0
    for col in RB_DEPTH_FEATURES:
        yield f"add {col}", RB_FEATURES + [col], 0
    for col in RB_DEPTH_FEATURES:
        yield f"drop {col}", RB_FEATURES + [c for c in RB_DEPTH_FEATURES if c != col], 0


if __name__ == "__main__":
    rb = load_rb_with_depth()
    print("NaN rate:", rb[RB_DEPTH_FEATURES].isna().mean().round(3).to_dict())
    print("share of rows flagged:", rb[RB_DEPTH_FEATURES[1:]].mean().round(3).to_dict())
    keys = top150_keys("RB")
    rows = []
    for name, features, noise in variants():
        r = np.array([evaluate(rb, features, seed, keys, noise, "RB", ALL) for seed in range(N_SEEDS)])
        rows.append(dict(variant=name, top150=r[:, 0].mean(), sd=r[:, 0].std(), all_rb=r[:, 1].mean(), rmse=r[:, 2].mean()))
    out = pd.DataFrame(rows)
    out["delta_vs_base"] = out["top150"] - out.loc[0, "top150"]
    out.to_csv(ROOT / "data" / "processed" / "rb_depth_ablation.csv", index=False)
    print(out.round(4).to_string(index=False))
