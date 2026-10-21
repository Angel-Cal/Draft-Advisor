"""Ablation of WR team-context features, same protocol as rb_team_context."""

import sys
import time
import pandas as pd
import nflreadpy as nflread
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.models.train import split_positions
from src.features.team_context import build_team_context, WR_FEATURES
from src.evaluation.rb_team_context import evaluate, top150_keys, N_SEEDS

ROOT = Path(__file__).parent.parent.parent


def load_wr():
    train = pd.read_parquet(ROOT / "data" / "processed" / "training_data.parquet")
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")
    roster = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_roster_20_25.parquet")
    context = build_team_context(seasonal, roster)
    wr = split_positions(train)[2].drop(columns=WR_FEATURES, errors="ignore")
    return wr.merge(context[["player_id", "season"] + WR_FEATURES], on=["player_id", "season"],
                    how="left").reset_index(drop=True)


def variants():
    yield "baseline", [], 0
    yield "all_features", WR_FEATURES, 0
    yield "baseline+random_noise", [], len(WR_FEATURES)
    for col in WR_FEATURES:
        yield f"add_feature:{col}", [col], 0
    for col in WR_FEATURES:
        yield f"drop_feature:{col}", [c for c in WR_FEATURES if c != col], 0


if __name__ == "__main__":
    wr = load_wr()
    top_keys = top150_keys("WR")
    rows = []
    for name, features, noise in variants():
        start = time.time()
        for seed in range(N_SEEDS):
            top_rho, all_rho, rmse = evaluate(wr, features, seed, top_keys, noise, "WR", WR_FEATURES)
            rows.append({"variant": name, "seed": seed, "top150_spearman": top_rho,
                         "all_spearman": all_rho, "rmse": rmse})
        print(f"{name}: {time.time() - start:.0f}s", flush=True)
    runs = pd.DataFrame(rows)
    base = runs[runs["variant"] == "baseline"].set_index("seed")
    summary = []
    for name, group in runs.groupby("variant", sort=False):
        group = group.set_index("seed")
        delta = group["top150_spearman"] - base["top150_spearman"]
        summary.append({"variant": name, "top150_rho": group["top150_spearman"].mean(),
                        "top150_sd": group["top150_spearman"].std(), "delta_vs_base": delta.mean(),
                        "seeds_improved": int((delta > 0).sum()), "all_rho": group["all_spearman"].mean(),
                        "rmse": group["rmse"].mean()})
    summary = pd.DataFrame(summary)
    summary.to_csv(ROOT / "data" / "processed" / "wr_team_context_ablation.csv", index=False)
    print(summary.round(4).to_string(index=False))
