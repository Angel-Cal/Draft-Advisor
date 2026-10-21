"""Ablation of RB team-context features: does each feature/group beat seed noise and random columns?"""

import sys
import time
import numpy as np
import pandas as pd
import nflreadpy as nflread
from pathlib import Path
from scipy.stats import spearmanr
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.models.train import Model, split_positions
from src.features.team_context import build_team_context, FEATURE_GROUPS
from src.evaluation.oos_predictions import position_oos, load_params
from src.evaluation.benchmark import load_season, SEASONS

ROOT = Path(__file__).parent.parent.parent
N_SEEDS = 10
ALL_FEATURES = [c for group in FEATURE_GROUPS.values() for c in group]


def load_rb():
    train = pd.read_parquet(ROOT / "data" / "processed" / "training_data.parquet")
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")
    roster = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_roster_20_25.parquet")
    schedules = nflread.load_schedules(list(range(2014, 2026))).to_pandas()
    context = build_team_context(seasonal, roster, schedules)
    rb = split_positions(train)[1].drop(columns=ALL_FEATURES, errors="ignore")  # wired-in columns are rebuilt here
    return rb.merge(context, on=["player_id", "season"], how="left").reset_index(drop=True)


def top150_rb_keys():
    keys = []
    for season in SEASONS:
        d = load_season(season)
        keys.append(d[d["in_top_adp"] & (d["position"] == "RB")][["player_id", "season"]])
    return pd.concat(keys)


def evaluate(rb, features, seed, top_keys, noise_cols=0):
    df = rb.drop(columns=[c for c in ALL_FEATURES if c not in features])
    if noise_cols:
        rng = np.random.default_rng(seed)
        for i in range(noise_cols):
            df[f"noise_{i}"] = rng.normal(size=len(df))
    params = dict(load_params("RB"), random_state=seed)
    oos = position_oos(df, "RB", Model(), params)
    top = oos.merge(top_keys, on=["player_id", "season"])
    top_rho = np.mean([spearmanr(g["oos_pred_ppr"], g["actual_ppr"])[0] for _, g in top.groupby("season")])
    all_rho = np.mean([spearmanr(g["oos_pred_ppr"], g["actual_ppr"])[0] for _, g in oos.groupby("season")])
    rmse = np.sqrt(((oos["oos_pred_ppr"] - oos["actual_ppr"]) ** 2).mean())
    return top_rho, all_rho, rmse


def variants():
    yield "baseline", [], 0
    yield "all_features", ALL_FEATURES, 0
    yield "baseline+random_noise", [], len(ALL_FEATURES)
    for group, cols in FEATURE_GROUPS.items():
        yield f"add_group:{group}", cols, 0
    for group, cols in FEATURE_GROUPS.items():
        yield f"drop_group:{group}", [c for c in ALL_FEATURES if c not in cols], 0
    for col in ALL_FEATURES:
        yield f"drop_feature:{col}", [c for c in ALL_FEATURES if c != col], 0


if __name__ == "__main__":
    rb = load_rb()
    top_keys = top150_rb_keys()
    rows = []
    for name, features, noise in variants():
        start = time.time()
        for seed in range(N_SEEDS):
            top_rho, all_rho, rmse = evaluate(rb, features, seed, top_keys, noise)
            rows.append({"variant": name, "seed": seed, "top150_rb_spearman": top_rho,
                         "all_rb_spearman": all_rho, "rmse": rmse})
        print(f"{name}: {time.time() - start:.0f}s", flush=True)
    runs = pd.DataFrame(rows)
    runs.to_csv(ROOT / "data" / "processed" / "rb_team_context_runs.csv", index=False)

    base = runs[runs["variant"] == "baseline"].set_index("seed")
    summary = []
    for name, group in runs.groupby("variant", sort=False):
        group = group.set_index("seed")
        delta = group["top150_rb_spearman"] - base["top150_rb_spearman"]
        summary.append({"variant": name,
                        "top150_rho": group["top150_rb_spearman"].mean(),
                        "top150_sd": group["top150_rb_spearman"].std(),
                        "delta_vs_base": delta.mean(),
                        "seeds_improved": int((delta > 0).sum()),
                        "all_rb_rho": group["all_rb_spearman"].mean(),
                        "rmse": group["rmse"].mean()})
    summary = pd.DataFrame(summary)
    summary.to_csv(ROOT / "data" / "processed" / "rb_team_context_ablation.csv", index=False)
    print(summary.round(4).to_string(index=False))
