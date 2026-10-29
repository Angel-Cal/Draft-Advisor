"""Does the model under-project players coming off an injury-shortened season?

Out-of-sample rows 2021-2025, draftable players (top 150 by ADP). `games` in the training data is the PRIOR season's games (build_features.add_lag).
Residual = actual PPR minus the projection. For a short prior season (<= 9 games) and for a big drop (games fell 5+ and <= 12 games) the report gives
the model's mean residual, the ADP curve's residual on the same rows (2022-2025, curve fit on earlier seasons), a bootstrap interval resampling players,
a permutation control (the same number of random draftable rows, so the size of a chance gap is visible) and the per-season means (no single season
carries the result). Writes nothing; run: python src/evaluation/short_season_check.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.draft.market_fallback import load_history
from src.evaluation.benchmark import SEASONS, load_season
from src.evaluation.blend_test import curve_points

ROOT = Path(__file__).parent.parent.parent
N_BOOT = 2000
N_PERM = 5000
SEED = 0

GROUPS = {
    "prior games <= 9": lambda d: d["games"] <= 9,
    "games fell 5+ and <= 12": lambda d: (d["games_delta"] <= -5) & (d["games"] <= 12),
    "everyone else": lambda d: (d["games"] > 9) & ~((d["games_delta"] <= -5) & (d["games"] <= 12)),
}


def load_rows():
    """Draftable player-seasons 2021-2025 with the model residual, the prior games and (2022 on) the ADP-curve residual."""
    history = load_history()
    features = pd.read_parquet(ROOT / "data" / "processed" / "training_data.parquet")[["player_id", "season", "games", "games_delta"]]
    rows = []
    for season in SEASONS:
        df = load_season(season)
        df["season"] = season
        df["curve"] = df["player_id"].map(curve_points(season, history)) if season > SEASONS.start else np.nan
        rows.append(df[df["in_top_adp"]])
    d = pd.concat(rows, ignore_index=True).merge(features, on=["player_id", "season"], how="left")
    d["model_resid"] = d["actual_ppr"] - d["oos_pred_ppr"]
    d["curve_resid"] = d["actual_ppr"] - d["curve"]
    return d


def boot_mean(g, column, rng):
    """Mean of `column` with a 90% bootstrap interval that resamples whole players."""
    g = g.dropna(subset=[column])
    by_player = [x[column].to_numpy() for _, x in g.groupby("player_id")]
    means = []
    for _ in range(N_BOOT):
        pick = rng.integers(0, len(by_player), len(by_player))
        means.append(np.concatenate([by_player[i] for i in pick]).mean())
    return g[column].mean(), np.percentile(means, 5), np.percentile(means, 95), len(g)


def chance_gap(d, size, column, rng):
    """SD of the mean of `column` over random draftable subsets of `size` rows: how far from the rest a chance group lands."""
    values = d[column].dropna().to_numpy()
    return float(np.std([rng.choice(values, size, replace=False).mean() for _ in range(N_PERM)]))


def report(d, rng):
    for label, scope in [("all positions", d)] + [(p, d[d["position"] == p]) for p in ["QB", "RB", "WR", "TE"]]:
        print(f"\n== {label} ==")
        print(f"{'group':<26}{'n':>5}{'model resid':>13}{'90% interval':>17}{'chance SD':>11}{'curve resid':>13}{'(n)':>5}")
        for name, rule in GROUPS.items():
            g = scope[rule(scope)]
            if len(g) < 5:
                continue
            m, lo, hi, n = boot_mean(g, "model_resid", rng)
            c, _, _, nc = boot_mean(g, "curve_resid", rng) if g["curve_resid"].notna().any() else (np.nan, 0, 0, 0)
            print(f"{name:<26}{n:>5}{m:>13.1f}{f'{lo:.1f} to {hi:.1f}':>17}{chance_gap(scope, n, 'model_resid', rng):>11.1f}{c:>13.1f}{nc:>5}")
    short = d[GROUPS["prior games <= 9"](d)]
    print("\nPer season, prior games <= 9 (mean model residual, n):")
    print(short.groupby("season")["model_resid"].agg(["mean", "count"]).round(1).T.to_string())


if __name__ == "__main__":
    report(load_rows(), np.random.default_rng(SEED))
