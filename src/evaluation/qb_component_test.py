"""QB test 3: projection = expected games x expected points per game, two models so availability and skill stop competing.

Mechanism under test: on one season-total target, giving rushing its weight (test 2) raised the points-per-game rank
0.35 -> 0.41 but cut the games rank 0.18 -> 0.10, so the total barely moved. With separate targets each part can be
fitted on its own. The games model keeps every job-security input (the 2026-10-30 games prior used only age and
workload and lost at QB). Arms (10 seeds, walk-forward as oos_predictions.py, each sub-model early-stops on the
validation season's own target):
  base       current QB model on season totals
  comp_tree  games = LightGBM(games played ~ all features); per game = LightGBM(PPR per game ~ all features, rows with
             4+ games, weighted by games)
  comp_lin   as comp_tree, but the per-game tree boosts from ridge(PPR per game ~ rushing, passing points per game)
Games played = regular-season games with at least one pass attempt or carry, so games x per game = the season total.
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.paths import PIPELINE
from src.models.train import Model, split_positions
from src.evaluation.oos_predictions import load_params
from src.evaluation.benchmark import SEASONS, load_season
from src.evaluation.qb_rushing_test import components, score, FIRST_TEST
from src.evaluation.qb_baseline_test import Baseline, SKILL, baseline_inputs, bump

ROOT = Path(__file__).parent.parent.parent
SEEDS = range(10)
MIN_GAMES = 4


def games_played():
    """(player_id, season) -> regular-season games with at least one pass attempt or carry."""
    w = pd.read_parquet(ROOT / "data" / "raw" / "weekly_20_25.parquet", columns=["player_id", "season", "season_type", "attempts", "carries"])
    w = w[w["season_type"] == "REG"]
    w = w[(w["attempts"].fillna(0) + w["carries"].fillna(0)) >= 1]
    return w.groupby(["player_id", "season"]).size().rename("G1").reset_index()


def fit_tree(x_tr, y_tr, x_va, y_va, params, seed, w_tr=None, w_va=None, b_tr=None, b_va=None):
    """LightGBM early-stopped on the validation season, optionally weighted and boosted from a baseline."""
    m = lgb.LGBMRegressor(**dict(params, random_state=seed))
    m.fit(x_tr, y_tr, sample_weight=w_tr, init_score=b_tr, eval_set=[(x_va, y_va)],
          eval_sample_weight=None if w_va is None else [w_va], eval_init_score=None if b_va is None else [b_va],
          eval_metric="rmse", callbacks=[lgb.early_stopping(50, verbose=False)])
    return m


def run_arm(qb, g1, arm, params, seed):
    """Walk-forward predictions for one arm and seed, with the games and per-game parts and the bump responses."""
    model, parts, rush, pas = Model(), [], [], []
    for x_tr, x_va, x_te, y_tr, y_va, y_te in model.rolling_splits(qb, min_train_seasons=FIRST_TEST - 2015):
        if arm == "base":
            m = fit_tree(x_tr, y_tr, x_va, y_va, params, seed)
            predict = lambda x: (m.predict(x), np.full(len(x), np.nan), np.full(len(x), np.nan))
        else:
            g_tr, g_va = g1.reindex(x_tr.index), g1.reindex(x_va.index)
            games = fit_tree(x_tr, g_tr, x_va, g_va, params, seed)
            k_tr, k_va = g_tr >= MIN_GAMES, g_va >= MIN_GAMES
            ppg_tr, ppg_va = y_tr[k_tr] / g_tr[k_tr], y_va[k_va] / g_va[k_va]
            if arm == "comp_lin":
                fill = x_tr["qb_att_share_prev"].median()
                base = Baseline(SKILL, per_game=False).fit(baseline_inputs(x_tr[k_tr], fill), ppg_tr)
                b = lambda x, f=fill, bl=base: bl.predict(baseline_inputs(x, f))
            else:
                b = lambda x: np.zeros(len(x))
            ppg = fit_tree(x_tr[k_tr], ppg_tr, x_va[k_va], ppg_va, params, seed, w_tr=g_tr[k_tr], w_va=g_va[k_va],
                           b_tr=b(x_tr[k_tr]) if arm == "comp_lin" else None, b_va=b(x_va[k_va]) if arm == "comp_lin" else None)
            def predict(x, gm=games, pm=ppg, bf=b):
                g_hat = np.clip(gm.predict(x), 0, 17)
                p_hat = pm.predict(x) + bf(x)
                return g_hat * p_hat, g_hat, p_hat
        total, g_hat, p_hat = predict(x_te)
        parts.append(pd.DataFrame({"pred": total, "g_hat": g_hat, "ppg_hat": p_hat}, index=x_te.index))
        rush.append(np.mean(predict(bump(x_te, "rush"))[0] - total))
        pas.append(np.mean(predict(bump(x_te, "pass"))[0] - total))
    p = pd.concat(parts)
    return qb.loc[p.index, ["player_id", "season"]].join(p), np.mean(rush), np.mean(pas)


def part_ranks(preds, bench, comps):
    """Rank of the games part vs games played and of the per-game part vs points per game (top-150, 8+ games for per game)."""
    d = preds.merge(bench, on=["player_id", "season"]).merge(comps, on=["player_id", "season"], how="left")
    top = d[d["in_top_adp"]]
    full = top[top["G"] >= 8].assign(ppg=lambda t: t["pass_pg"] + t["rush_pg"])
    rho = lambda sub, a, b: np.mean([spearmanr(g[a], g[b], nan_policy="omit")[0] for _, g in sub.groupby("season")])
    return {"g_part_vs_games": rho(top, "g_hat", "G"), "ppg_part_vs_ppg": rho(full, "ppg_hat", "ppg")}


if __name__ == "__main__":
    qb = split_positions(pd.read_parquet(PIPELINE / "training_data.parquet"))[0]
    g1 = qb[["player_id", "season"]].merge(games_played(), how="left")["G1"].fillna(0)
    g1.index = qb.index
    params = load_params("QB")
    comps = components()
    bench = pd.concat([load_season(s)[lambda d: d["position"] == "QB"][["player_id", "season", "actual_ppr", "in_top_adp"]] for s in SEASONS])
    rows, ensembles = [], {}
    for arm in ["base", "comp_tree", "comp_lin"]:
        runs = []
        for seed in SEEDS:
            preds, r, p = run_arm(qb, g1, arm, params, seed)
            row = {"arm": arm, "seed": seed, "rush_bump": r, "pass_bump": p, **score(preds, bench, comps)}
            if arm != "base":
                row.update(part_ranks(preds, bench, comps))
            rows.append(row)
            runs.append(preds.set_index(["player_id", "season"])["pred"])
        ensembles[arm] = pd.concat(runs, axis=1).mean(axis=1)
        print(arm, "done", flush=True)
    res = pd.DataFrame(rows)
    base = res[res["arm"] == "base"].set_index("seed")
    for col in ["top150", "all", "rush_pg", "games"]:
        res[f"d_{col}"] = res[col].values - base.loc[res["seed"], col].values   # paired by seed
    summary = res.groupby("arm", sort=False).agg(["mean", "std"]).drop(columns="seed")
    print("\nbumps = +4 fantasy points per game from rushing or from passing")
    print(summary.xs("mean", axis=1, level=1).round(3).to_string())
    print("\nseed SD"); print(summary.xs("std", axis=1, level=1)[["top150", "d_top150", "rush_pg"]].round(3).to_string())
    # per season, 10-seed mean projection
    d = bench.set_index(["player_id", "season"]).join(pd.DataFrame(ensembles)).reset_index()
    t = d[d["in_top_adp"]]
    per = t.groupby("season").apply(lambda g: pd.Series({a: spearmanr(g[a], g["actual_ppr"])[0] for a in ensembles}))
    for a in ["comp_tree", "comp_lin"]:
        per[f"{a}-base"] = per[a] - per["base"]
    print("\nper season, top-150 (10-seed mean projection)"); print(per.round(3).to_string())
