"""Ablation of the 'process' feature groups (expected points, role, depth chart, team EPA, Next Gen Stats) on every
position, each added to that position's current model, with a random-noise control of the same size."""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.models.train import split_positions
from src.features.advanced import ADVANCED_GROUPS, load_advanced_context
from src.features.registry import POSITION_FEATURES
from src.evaluation.rb_team_context import evaluate, top150_keys, N_SEEDS

ROOT = Path(__file__).parent.parent.parent
POSITIONS = ["QB", "RB", "WR", "TE"]
NGS_FOR = {"QB": ["ngs_pass_"], "RB": ["ngs_rush_", "ngs_rece_"], "WR": ["ngs_rece_"], "TE": ["ngs_rece_"]}


def group_columns(group, position):
    """Candidate columns of a group for a position: not already in that position's model."""
    columns = ADVANCED_GROUPS[group]
    if group == "ngs":
        columns = [c for c in columns if any(c.startswith(prefix) for prefix in NGS_FOR[position])]
    return [c for c in columns if c not in POSITION_FEATURES[position]]


def position_frame(position, train, context):
    frame = split_positions(train)[POSITIONS.index(position)]
    for group, features in context.items():
        new = [c for c in ADVANCED_GROUPS[group] if c not in frame.columns]
        if new:
            frame = frame.merge(features[["player_id", "season"] + new], on=["player_id", "season"], how="left")
    return frame.reset_index(drop=True)


if __name__ == "__main__":
    train = pd.read_parquet(ROOT / "data" / "processed" / "training_data.parquet")
    roster = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_roster_20_25.parquet")
    context = load_advanced_context(roster[roster["gsis_id"].notna()])
    groups = sys.argv[1:] or list(ADVANCED_GROUPS)        # e.g. `python advanced_features.py ol`
    rows = []
    for position in POSITIONS:
        frame = position_frame(position, train, context)
        candidates = [c for group in ADVANCED_GROUPS for c in group_columns(group, position)]
        keys = top150_keys(position)

        def run(features, noise=0):
            r = np.array([evaluate(frame, features, seed, keys, noise, position, candidates) for seed in range(N_SEEDS)])
            return r

        base = run([])
        for label, features, noise in [("random noise (3 columns)", [], 3)] + \
                [(group, group_columns(group, position), 0) for group in groups]:
            r = run(features, noise)
            delta = r[:, 0] - base[:, 0]
            coverage = float(frame[features[0]].notna().mean()) if features else np.nan
            rows.append(dict(position=position, variant=label, n_features=len(features), coverage=coverage,
                             base_top150=base[:, 0].mean(), top150=r[:, 0].mean(), seed_sd=r[:, 0].std(),
                             delta=delta.mean(), seeds_better=int((delta > 0).sum()),
                             rmse_delta=(r[:, 2] - base[:, 2]).mean()))
        print(f"{position} done", flush=True)
    out = pd.DataFrame(rows)
    name = "advanced_features_ablation.csv" if len(groups) == len(ADVANCED_GROUPS) else f"advanced_{'_'.join(groups)}_ablation.csv"
    out.to_csv(ROOT / "data" / "processed" / name, index=False)
    pd.set_option("display.width", 200)
    print(out.round(4).to_string(index=False))
