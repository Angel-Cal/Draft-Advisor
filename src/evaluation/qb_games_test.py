"""QB games model (the weak half of test 3's games x points-per-game projection): which inputs say who holds the job?

Mechanism: among draftable QBs, games played = holding the job (week-1 starter, not benched) x staying healthy (mostly
luck). The market knows week-1 starters; the games model sees them only through qb_att_share_prev, which a veteran
backup dilutes (2025 L.Jackson 0.52 with C.Rush), and not at all through the week-1 depth chart (declined for the
season-total model on 2026-10-21 because it blurred the ordering among starters, a cost the games half does not pay).
The per-game half is fixed at test 3's comp_lin. Games-model arms (10 seeds):
  g_all     all QB features (test 3)
  g_depth   + depth_tier_wk1 (chart published before the opener)
  g_margin  + att_margin_prev = his prior attempts / the most prior attempts of any QB on his week-1 roster
  g_both    + both
  g_job     a compact job set: both + games, attempts, qb_att_share_prev, age, years_exp, draft_number,
            passing and rushing points per game, passing_epa
  g_noise   + two N(0,1) columns (control)
Scored on the games part's rank vs games played and the product's top-150 / all-QB Spearman.
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
from src.evaluation.qb_rushing_test import components, score, FIRST_TEST
from src.evaluation.qb_baseline_test import Baseline, SKILL, baseline_inputs
from src.evaluation.qb_component_test import games_played, fit_tree, part_ranks, MIN_GAMES
from src.features.team_context import _roster_qbs
from src.data.validate import drop_junk_rows

ROOT = Path(__file__).parent.parent.parent
SEEDS = range(10)
EXTRA = ["depth_tier_wk1", "att_margin_prev", "noise_a", "noise_b"]
JOB = ["games", "attempts", "qb_att_share_prev", "age", "years_exp", "draft_number", "passing_epa",
       "depth_tier_wk1", "att_margin_prev", "pass_pts_pg", "rush_pts_pg"]
ARMS = {"g_all": [], "g_depth": ["depth_tier_wk1"], "g_margin": ["att_margin_prev"],
        "g_both": ["depth_tier_wk1", "att_margin_prev"], "g_job": None, "g_noise": ["noise_a", "noise_b"]}


def attempt_margin():
    """(player_id, season t) -> his season t-1 attempts / the most season t-1 attempts of any QB on his week-1 roster of t."""
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")
    roster = pd.concat([drop_junk_rows(pd.read_parquet(ROOT / "data" / "raw" / "roster_wk1_14_25.parquet"), "gsis_id"),
                        pd.read_parquet(ROOT / "data" / "raw" / "roster_2026.parquet")], ignore_index=True)
    _, qbs = _roster_qbs(seasonal, roster)
    qbs["prev_att"] = qbs["prev_att"].fillna(0)
    top = qbs.groupby(["team_now", "season"])["prev_att"].transform("max")
    qbs["att_margin_prev"] = (qbs["prev_att"] / top).where(top > 0)
    return qbs[["player_id", "season", "att_margin_prev"]].drop_duplicates(["player_id", "season"])


def prepare(training):
    """The QB frame with the games-model extras (depth tier, attempt margin, per-game points, two noise columns)."""
    qb = split_positions(training)[0]
    qb = qb.merge(training[["player_id", "season", "depth_tier_wk1"]], on=["player_id", "season"], how="left").set_axis(qb.index)
    qb = qb.merge(attempt_margin(), on=["player_id", "season"], how="left").set_axis(qb.index)
    qb["pass_pts_pg"] = qb["passing_yards_pg"] * 0.04 + qb["passing_tds_pg"] * 4 - qb["passing_interceptions_pg"] * 2
    qb["rush_pts_pg"] = qb["rushing_yards_pg"] * 0.1 + qb["rushing_tds_pg"] * 6
    rng = np.random.default_rng(0)
    return qb.assign(noise_a=rng.standard_normal(len(qb)), noise_b=rng.standard_normal(len(qb)))


def run_arm(qb, g1, extra, params, seed, first_test=FIRST_TEST):
    """Walk-forward games x per-game predictions; `extra` columns go to the games model only (None = the compact job set)."""
    model, parts = Model(), []
    base_feats = [c for c in qb.columns if c not in EXTRA + ["target_ppr", "season", "player_id", "player_name", "pass_pts_pg", "rush_pts_pg"]]
    games_feats = JOB if extra is None else base_feats + extra
    for x_tr, x_va, x_te, y_tr, y_va, y_te in model.rolling_splits(qb, min_train_seasons=first_test - 2015):
        g_tr, g_va = g1.reindex(x_tr.index), g1.reindex(x_va.index)
        games = fit_tree(x_tr[games_feats], g_tr, x_va[games_feats], g_va, params, seed)
        k_tr, k_va = g_tr >= MIN_GAMES, g_va >= MIN_GAMES
        fill = x_tr["qb_att_share_prev"].median()
        bl = Baseline(SKILL).fit(baseline_inputs(x_tr[k_tr], fill), y_tr[k_tr] / g_tr[k_tr])
        b = lambda x: bl.predict(baseline_inputs(x, fill))
        ppg = fit_tree(x_tr.loc[k_tr, base_feats], y_tr[k_tr] / g_tr[k_tr], x_va.loc[k_va, base_feats], y_va[k_va] / g_va[k_va],
                       params, seed, w_tr=g_tr[k_tr], w_va=g_va[k_va], b_tr=b(x_tr[k_tr]), b_va=b(x_va[k_va]))
        g_hat = np.clip(games.predict(x_te[games_feats]), 0, 17)
        p_hat = ppg.predict(x_te[base_feats]) + b(x_te)
        parts.append(pd.DataFrame({"pred": g_hat * p_hat, "g_hat": g_hat, "ppg_hat": p_hat}, index=x_te.index))
    p = pd.concat(parts)
    return qb.loc[p.index, ["player_id", "season"]].join(p)


if __name__ == "__main__":
    qb = prepare(pd.read_parquet(PIPELINE / "training_data.parquet"))
    print("coverage: depth", round(qb["depth_tier_wk1"].notna().mean(), 3), " margin", round(qb["att_margin_prev"].notna().mean(), 3))
    g1 = qb[["player_id", "season"]].merge(games_played(), how="left")["G1"].fillna(0).set_axis(qb.index)
    params, comps = load_params("QB"), components()
    bench = pd.concat([load_season(s)[lambda d: d["position"] == "QB"][["player_id", "season", "actual_ppr", "in_top_adp"]] for s in SEASONS])
    rows, ensembles = [], {}
    for arm, extra in ARMS.items():
        runs = []
        for seed in SEEDS:
            preds = run_arm(qb, g1, extra, params, seed)
            rows.append({"arm": arm, "seed": seed, **score(preds, bench, comps), **part_ranks(preds, bench, comps)})
            runs.append(preds.set_index(["player_id", "season"])["pred"])
        ensembles[arm] = pd.concat(runs, axis=1).mean(axis=1)
        print(arm, "done", flush=True)
    res = pd.DataFrame(rows)
    ref = res[res["arm"] == "g_all"].set_index("seed")
    for col in ["top150", "all", "g_part_vs_games"]:
        res[f"d_{col}"] = res[col].values - ref.loc[res["seed"], col].values   # paired by seed, against test 3
    keep = ["top150", "all", "g_part_vs_games", "ppg_part_vs_ppg", "games", "rmse_top150", "d_top150", "d_all", "d_g_part_vs_games"]
    summary = res.groupby("arm", sort=False)[keep].agg(["mean", "std"])
    print("\nmeans (current single model: top150 0.268, all 0.686; test 3 = g_all)")
    print(summary.xs("mean", axis=1, level=1).round(3).to_string())
    print("\nseed SD"); print(summary.xs("std", axis=1, level=1)[["top150", "d_top150", "g_part_vs_games"]].round(3).to_string())
    d = bench.set_index(["player_id", "season"]).join(pd.DataFrame(ensembles)).reset_index()
    t = d[d["in_top_adp"]]
    per = pd.DataFrame({a: {s: spearmanr(g[a], g["actual_ppr"])[0] for s, g in t.groupby("season")} for a in ensembles})
    print("\nper season, top-150 (10-seed mean projection)"); print(per.round(3).to_string())
