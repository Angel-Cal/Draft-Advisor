"""Does the routed projection (short_season.py) hold up under the live recipe, and what does it do to the simulator?

The same walk-forward as refit_oos.py (per test season 2021-2025: early-stop on the previous season, refit on every earlier season, 5 seeds averaged),
run once for the current model and once for the rate view of the features, then routed by prior games. Prints, on the draftable rows (top 150 by ADP),
top-150 Spearman (mean over seasons), RMSE and the residual (actual - projection) of the short-season rows and of the first 80 picks among them,
for the current and the routed projections. Writes data/processed/routed_oos.parquet and backtest files for both under data/processed/routed/
(`backtest --data data/processed/routed/<arm> --seasons 2022-2025 --seeds 100`).

Run: python src/evaluation/routed_oos.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.benchmark import load_season
from src.evaluation.live_style_oos import rmse
from src.evaluation.oos_predictions import load_params
from src.evaluation.refit_oos import POSITIONS, SEASONS, write_backtest_files
from src.models.short_season import SHORT_SEASON_GAMES, rate_refit, route
from src.models.train import Model, split_positions

ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
ELITE_ADP = 80


def routed_predictions(first_test=2021, only=None):
    """One row per player-season in 2021-2025 (from `first_test`, restricted to the seasons in `only`): the current refit projection, the rate-view projection and the routed one."""
    df = pd.read_parquet(PROCESSED_DIR / "training_data.parquet")
    model = Model()
    rows = []
    for position, pos_df in zip(POSITIONS, split_positions(df)):
        params = load_params(position)
        for x_train, x_val, x_test, y_train, y_val, y_test in model.rolling_splits(pos_df, min_train_seasons=first_test - 2015):
            if only is not None and int(pos_df.loc[x_test.index, "season"].iloc[0]) not in only:
                continue
            out = pos_df.loc[x_test.index, ["player_id", "player_name", "position", "season", "games"]].copy()
            out["actual_ppr"] = y_test
            out["base_pred_ppr"] = model.refit_predict(x_train, y_train, x_val, y_val, x_test, params)
            out["rate_pred_ppr"] = rate_refit(model, x_train, y_train, x_val, y_val, x_test, params)
            out["routed_pred_ppr"] = route(out["base_pred_ppr"], out["rate_pred_ppr"], out["games"])
            rows.append(out)
        print(f"{position} done", flush=True)
    return pd.concat(rows, ignore_index=True)


def report(d):
    short_all = d[d["games"] <= SHORT_SEASON_GAMES]
    print("All short-season rows (draftable or not), RMSE current -> routed")
    for p in POSITIONS:
        g = short_all[short_all["position"] == p]
        print(f"  {p}: n={len(g)}  {rmse(g['base_pred_ppr'], g['actual_ppr']):.1f} -> {rmse(g['routed_pred_ppr'], g['actual_ppr']):.1f}"
              f"   mean projection {g['base_pred_ppr'].mean():.0f} -> {g['routed_pred_ppr'].mean():.0f}, mean actual {g['actual_ppr'].mean():.0f}")
    print()
    frames = []
    for season in sorted(d["season"].unique()):
        adp = load_season(season)[["player_id", "adp", "in_top_adp"]]
        frames.append(d[d["season"] == season].merge(adp, on="player_id"))
    d = pd.concat(frames)
    top = d[d["in_top_adp"]]
    short = top["games"] <= SHORT_SEASON_GAMES
    elite = short & (top["adp"] <= ELITE_ADP)
    print(f"{len(top)} draftable rows, {int(short.sum())} short-season, {int(elite.sum())} of them in the first {ELITE_ADP} picks\n")
    print(f"{'':<9}" + "".join(f"{p:>16}" for p in POSITIONS))
    for label, column in [("current", "base_pred_ppr"), ("routed", "routed_pred_ppr")]:
        cells = {}
        for p in POSITIONS:
            g = top[top["position"] == p]
            rho = np.mean([spearmanr(s[column], s["actual_ppr"])[0] for _, s in g.groupby("season")])
            cells[p] = f"{rho:.3f}/{rmse(g[column], g['actual_ppr']):.1f}"
        print(f"{label:<9}" + "".join(f"{cells[p]:>16}" for p in POSITIONS) + "   (top-150 Spearman / RMSE)")
    print("\nMean residual (actual - projection), draftable rows")
    print(f"{'':<9}{'short, all':>12}{'short, elite':>14}{'others':>9}")
    for label, column in [("current", "base_pred_ppr"), ("routed", "routed_pred_ppr")]:
        resid = top["actual_ppr"] - top[column]
        print(f"{label:<9}{resid[short].mean():>12.1f}{resid[elite].mean():>14.1f}{resid[~short].mean():>9.1f}")
    for p in POSITIONS:
        g = top[top["position"] == p]
        s, e = g["games"] <= SHORT_SEASON_GAMES, (g["games"] <= SHORT_SEASON_GAMES) & (g["adp"] <= ELITE_ADP)
        print(f"  {p}: short n={int(s.sum())}, elite n={int(e.sum())}, elite residual current {(g['actual_ppr'] - g['base_pred_ppr'])[e].mean():.1f}"
              f" -> routed {(g['actual_ppr'] - g['routed_pred_ppr'])[e].mean():.1f}")


if __name__ == "__main__":
    # `--first-test 2019 --only 2019,2020` computes just those earlier seasons (less training data) and adds their files next to the existing ones
    first_test = int(sys.argv[sys.argv.index("--first-test") + 1]) if "--first-test" in sys.argv else 2021
    only = [int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")] if "--only" in sys.argv else None
    d = routed_predictions(first_test, only)
    d.to_parquet(PROCESSED_DIR / ("routed_oos.parquet" if only is None else "routed_oos_ext.parquet"))
    if only is None:
        report(d)
    for arm, column in [("current", "base_pred_ppr"), ("routed", "routed_pred_ppr")]:
        write_backtest_files(d, column, PROCESSED_DIR / "routed" / arm, f"{arm} refit (routed_oos.py)", seasons=only or SEASONS)
    print(f"\nwrote backtest files under {PROCESSED_DIR / 'routed'}")
