"""Ablation of QB depth-chart features: expected starter, share of roster attempts, competition for the job."""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.models.train import drop_non_features
from src.features.team_context import build_qb_depth_features, QB_DEPTH_FEATURES
from src.evaluation.qb_experiments import load_qb, run, score, N_SEEDS
from src.evaluation.rb_team_context import top150_keys

ROOT = Path(__file__).parent.parent.parent


def load_qb_with_depth():
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")
    roster = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_roster_20_25.parquet")
    qb = load_qb()
    return qb.merge(build_qb_depth_features(seasonal, roster), on=["player_id", "season"], how="left")


def variants(base_cols):
    yield "baseline", base_cols, 0
    yield "baseline+4 random-noise cols", base_cols, 4
    yield "all depth features", base_cols + QB_DEPTH_FEATURES, 0
    for col in QB_DEPTH_FEATURES:
        yield f"add {col}", base_cols + [col], 0
    for col in QB_DEPTH_FEATURES:
        yield f"drop {col}", base_cols + [c for c in QB_DEPTH_FEATURES if c != col], 0


if __name__ == "__main__":
    qb = load_qb_with_depth()
    print("NaN rate:", qb[QB_DEPTH_FEATURES].isna().mean().round(3).to_dict())
    base_cols = list(drop_non_features(qb.drop(columns=QB_DEPTH_FEATURES + ["games_actual", "ppr_pg_prev"])).columns)
    keys = top150_keys("QB")
    rows = []
    for name, features, noise in variants(base_cols):
        r = np.array([score(run(qb, features, seed, noise_cols=noise), keys) for seed in range(N_SEEDS)])
        rows.append(dict(variant=name, top150=r[:, 0].mean(), sd=r[:, 0].std(), all_qb=r[:, 1].mean(), rmse=r[:, 2].mean()))
    out = pd.DataFrame(rows)
    out["delta_vs_base"] = out["top150"] - out.loc[0, "top150"]
    out.to_csv(ROOT / "data" / "processed" / "qb_depth_ablation.csv", index=False)
    print(out.round(4).to_string(index=False))
