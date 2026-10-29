"""Ablation of WR1/WR2 rank features (by prior-season targets) added to the WR model, same protocol as advanced_features.py:
10 seeds, a random-noise control of the same size, top-150 Spearman as the headline.

Candidates: target_rank_now (the existing rank among all RB/WR/TE, total targets), wr_target_rank (WR only, total targets) and
wr_target_rank_pg (WR only, targets per game, falling back to the season before when last year had under 4 games).
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.models.train import split_positions
from src.features.team_context import build_team_context
from src.features.wr_rank import build_wr_rank_features, WR_RANK_FEATURES
from src.evaluation.rb_team_context import evaluate, top150_keys, N_SEEDS

ROOT = Path(__file__).parent.parent.parent
CANDIDATES = ["target_rank_now"] + WR_RANK_FEATURES
VARIANTS = {"all_receivers_total": ["target_rank_now"], "wr_total": ["wr_target_rank"], "wr_per_game": ["wr_target_rank_pg"],
            "wr_total+wr_per_game": WR_RANK_FEATURES, "all three": CANDIDATES}


def load_wr():
    train = pd.read_parquet(ROOT / "data" / "processed" / "training_data.parquet")
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")
    roster = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_roster_20_25.parquet")
    roster = roster[roster["gsis_id"].notna()]
    wr = split_positions(train)[2]
    wr = wr.merge(build_team_context(seasonal, roster)[["player_id", "season", "target_rank_now"]], on=["player_id", "season"], how="left")
    wr = wr.merge(build_wr_rank_features(seasonal, roster), on=["player_id", "season"], how="left")
    return wr.reset_index(drop=True)


if __name__ == "__main__":
    wr = load_wr()
    keys = top150_keys("WR")
    print(f"{len(wr)} WR rows; coverage " + ", ".join(f"{c} {wr[c].notna().mean():.2f}" for c in CANDIDATES), flush=True)

    def run(features, noise=0):
        return np.array([evaluate(wr, features, seed, keys, noise, "WR", CANDIDATES) for seed in range(N_SEEDS)])

    base = run([])
    rows = []
    for label, features, noise in [("random noise (3 columns)", [], 3)] + [(k, v, 0) for k, v in VARIANTS.items()]:
        r = run(features, noise)
        delta = r[:, 0] - base[:, 0]
        rows.append(dict(variant=label, n_features=len(features), base_top150=base[:, 0].mean(), top150=r[:, 0].mean(), seed_sd=r[:, 0].std(),
                         delta=delta.mean(), seeds_better=int((delta > 0).sum()), all_rho_delta=(r[:, 1] - base[:, 1]).mean(),
                         rmse_delta=(r[:, 2] - base[:, 2]).mean()))
        print(label, "done", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "data" / "processed" / "wr_target_rank_ablation.csv", index=False)
    pd.set_option("display.width", 200)
    print(out.round(4).to_string(index=False))
