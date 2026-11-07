"""QB rushing test 1: does the QB model rank rushing better with one combined rushing column and/or linear leaves?

Mechanism under test: rushing points per game carry over year to year at r 0.84 (passing 0.41), yet the QB model
moves only ~12 points for a ~68-point rushing bump, because the signal is split across ~11 columns and only ~40
training rows rush 30+ yards a game (= min_child_samples). Arms, same walk-forward as oos_predictions.py, 10 seeds:
  base       current QB features and params
  combined   + rush_pts_pg_prev and pass_pts_pg_prev (last season's fantasy points per game from each)
  noise      + two N(0,1) columns instead (control for adding two columns)
  linear     base with linear_tree=True (leaves fit a line, so the tree can extrapolate)
  comb_lin   combined + linear_tree
Scored on the benchmark's top-150-by-ADP QBs, 2021-2025: season-total Spearman, the component ranks (rushing and
passing points per game, games played; from weekly data) and the rushing-bump response.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.paths import PIPELINE
from src.models.train import Model, split_positions
from src.evaluation.oos_predictions import load_params
from src.evaluation.benchmark import SEASONS, load_season

ROOT = Path(__file__).parent.parent.parent
SEEDS = range(10)
FIRST_TEST = 2021
BUMP = {"rushing_yards_pg": 25, "rushing_tds_pg": 0.25, "carries_pg": 4, "rushing_first_downs_pg": 1.5}
BUMP_PTS = 25 * 0.1 + 0.25 * 6   # per game, before any regression


def add_combined(df):
    """Last season's rushing and passing fantasy points per game as single columns."""
    return df.assign(rush_pts_pg_prev=df["rushing_yards_pg"] * 0.1 + df["rushing_tds_pg"] * 6,
                     pass_pts_pg_prev=df["passing_yards_pg"] * 0.04 + df["passing_tds_pg"] * 4 - df["passing_interceptions_pg"] * 2)


def bump(x):
    """The rushing bump applied to every rushing column, the combined one included when present."""
    x = x.copy()
    for col, add in BUMP.items():
        x[col] += add
    if "rush_pts_pg_prev" in x:
        x["rush_pts_pg_prev"] += BUMP_PTS
    return x


def run_arm(df, params, seed):
    """Walk-forward test-season predictions for one arm and seed, plus the mean rushing-bump response."""
    model, preds, resp = Model(), [], []
    for fold in model.rolling_splits(df, min_train_seasons=FIRST_TEST - 2015):
        x_tr, x_va, x_te, y_tr, y_va, y_te = fold
        fit = model.train_model(x_tr, x_va, y_tr, y_va, dict(params, random_state=seed))
        p = fit.predict(x_te)
        preds.append(pd.Series(p, index=x_te.index))
        resp.append(np.mean(fit.predict(bump(x_te)) - p))
    out = df.loc[pd.concat(preds).index, ["player_id", "season"]].assign(pred=pd.concat(preds).values)
    return out, np.mean(resp)


def components():
    """Actual target-season games played, passing and rushing fantasy points per game, from weekly regular-season data."""
    w = pd.read_parquet(ROOT / "data" / "raw" / "weekly_20_25.parquet")
    w = w[(w["season_type"] == "REG") & (w["position"] == "QB")].copy()
    w["played"] = (w["attempts"].fillna(0) + w["carries"].fillna(0)) >= 5
    w["pass_pts"] = w["passing_yards"] * 0.04 + w["passing_tds"] * 4 - w["passing_interceptions"] * 2
    w["rush_pts"] = w["rushing_yards"] * 0.1 + w["rushing_tds"] * 6
    a = w.groupby(["player_id", "season"]).agg(G=("played", "sum"), pass_pts=("pass_pts", "sum"), rush_pts=("rush_pts", "sum")).reset_index()
    g = a["G"].where(a["G"] > 0)
    return a.assign(pass_pg=a["pass_pts"] / g, rush_pg=a["rush_pts"] / g)


def score(preds, bench, comps):
    """Per-season-mean Spearman of predictions vs actual total (top-150 and all QBs) and vs each component (top-150)."""
    d = preds.merge(bench, on=["player_id", "season"]).merge(comps, on=["player_id", "season"], how="left")
    def rho(sub, target):
        return np.mean([spearmanr(g["pred"], g[target], nan_policy="omit")[0] for _, g in sub.groupby("season")])
    top = d[d["in_top_adp"]]
    full = top[top["G"] >= 8]
    return {"top150": rho(top, "actual_ppr"), "all": rho(d, "actual_ppr"), "pts_pg": rho(full.assign(ppg=full["pass_pg"] + full["rush_pg"]), "ppg"),
            "rush_pg": rho(full, "rush_pg"), "pass_pg": rho(full, "pass_pg"), "games": rho(top, "G"),
            "rmse_top150": float(np.sqrt(np.mean((top["pred"] - top["actual_ppr"]) ** 2)))}


if __name__ == "__main__":
    qb = split_positions(pd.read_parquet(PIPELINE / "training_data.parquet"))[0]
    params = load_params("QB")
    rng = np.random.default_rng(0)
    noise = qb.assign(noise_a=rng.standard_normal(len(qb)), noise_b=rng.standard_normal(len(qb)))
    arms = {"base": (qb, params), "combined": (add_combined(qb), params), "noise": (noise, params),
            "linear": (qb, dict(params, linear_tree=True)), "comb_lin": (add_combined(qb), dict(params, linear_tree=True))}
    bench = pd.concat([load_season(s)[lambda d: d["position"] == "QB"][["player_id", "season", "actual_ppr", "in_top_adp"]] for s in SEASONS])
    comps = components()
    rows = []
    for name, (df, p) in arms.items():
        for seed in SEEDS:
            preds, resp = run_arm(df, p, seed)
            rows.append({"arm": name, "seed": seed, "bump_response": resp, **score(preds, bench, comps)})
        print(name, "done", flush=True)
    res = pd.DataFrame(rows)
    base = res[res["arm"] == "base"].set_index("seed")
    for col in ["top150", "all", "pts_pg", "rush_pg"]:
        res[f"d_{col}"] = res[col].values - base.loc[res["seed"], col].values   # paired by seed
    summary = res.groupby("arm", sort=False).agg(["mean", "std"]).drop(columns="seed")
    print(f"\nbump = +{BUMP_PTS:.1f} rushing pts/game (~{BUMP_PTS * 17:.0f} PPR over 17 games at face value)")
    print(summary.xs("mean", axis=1, level=1).round(3).to_string())
    print("\nseed SD"); print(summary.xs("std", axis=1, level=1)[["top150", "d_top150", "rush_pg", "bump_response"]].round(3).to_string())
