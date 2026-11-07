"""RB split test: projection = expected games x expected points per game, as QB test 3, with RB-specific halves.

Mechanism under test (LOG 2026-11-06, "Would the split help RB/WR/TE?"): among RBs who stayed on their team the model
ranks points per game no better than last season's rate (0.57 vs 0.55) while ADP is at 0.70, and a 3-year weighted
rate (5/4/3, regressed) reaches 0.61; at WR/TE no history measure beat last season's rate. If RB's per-game gap is
missing career memory, a per-game half boosted from that rate should lift the stayers' per-game rank to 0.62+ and
top-150 by 0.03+; if not, RB's gap is information we do not have, like WR/TE. The games half is mostly injury at RB
(rank 0.20 for model and ADP), so the last arm gives it the last three seasons' games. Arms (10 seeds, paired):
  base          current RB model on season totals
  comp_tree     games = LightGBM(games with a touch ~ RB features); per game = LightGBM(PPR per game, rows with 4+
                games, weighted by games); no baseline (structural control)
  comp_marcel   per-game tree boosted from ridge(PPR per game ~ 3-year weighted rate, last season's rate)
  comp_mar_inj  comp_marcel + games in each of the last three seasons, their mean and minimum, for the games half only
  comp_noise    ridge on two N(0,1) columns, which both trees also see (control)
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
from src.evaluation.qb_rushing_test import FIRST_TEST
from src.evaluation.qb_baseline_test import Baseline
from src.evaluation.qb_component_test import fit_tree
from src.features.team_context import TEAM_MAP

ROOT = Path(__file__).parent.parent.parent
SEEDS = range(10)
MIN_GAMES = 4
MARCEL_WEIGHTS = (5, 4, 3)
REGRESS_GAMES = 30          # weighted games of the RB mean added to the 3-year rate (= 6 games at weight 5)
RATE_COLS = ["marcel_ppg", "last_ppg"]
GAMES_HIST = ["g_m1", "g_m2", "g_m3", "g_mean3", "g_min3"]
NOISE = ["noise_a", "noise_b"]


def season_history():
    """(player_id, season) -> RB games with a touch, PPR, PPR per game and last team, from weekly regular-season stats."""
    w = pd.read_parquet(ROOT / "data" / "raw" / "weekly_20_25.parquet",
                        columns=["player_id", "season", "week", "season_type", "position", "team", "attempts", "carries", "targets", "fantasy_points_ppr"])
    w = w[(w["season_type"] == "REG") & ((w["attempts"].fillna(0) + w["carries"].fillna(0) + w["targets"].fillna(0)) >= 1)]
    h = (w.sort_values("week").groupby(["player_id", "season"])
         .agg(G=("week", "count"), P=("fantasy_points_ppr", "sum"), pos=("position", "first"), team_last=("team", "last")).reset_index())
    h["team_last"] = h["team_last"].replace(TEAM_MAP)
    return h.assign(ppg=h["P"] / h["G"])


def rate_and_games_inputs(rows, hist):
    """Per (player_id, season t): last season's rate, the regressed 3-year weighted rate and the last three seasons' games."""
    out = rows[["player_id", "season"]].copy()
    for k in (1, 2, 3):
        prior = hist.assign(season=hist["season"] + k)[["player_id", "season", "G", "P"]].rename(columns={"G": f"G{k}", "P": f"P{k}"})
        out = out.merge(prior, on=["player_id", "season"], how="left")
    rb = hist[(hist["pos"] == "RB") & (hist["G"] >= MIN_GAMES)]
    league = {t: rb.loc[rb["season"] < t, "P"].sum() / rb.loc[rb["season"] < t, "G"].sum() for t in out["season"].unique()}
    num = sum(w * out[f"P{k}"].fillna(0) for k, w in zip((1, 2, 3), MARCEL_WEIGHTS))
    den = sum(w * out[f"G{k}"].fillna(0) for k, w in zip((1, 2, 3), MARCEL_WEIGHTS))
    mean = out["season"].map(league)
    out["marcel_ppg"] = (num + mean * REGRESS_GAMES) / (den + REGRESS_GAMES)
    out["last_ppg"] = (out["P1"] / out["G1"]).fillna(mean)
    for k in (1, 2, 3):
        out[f"g_m{k}"] = out[f"G{k}"]
    out["g_mean3"] = out[["g_m1", "g_m2", "g_m3"]].mean(axis=1)
    out["g_min3"] = out[["g_m1", "g_m2", "g_m3"]].min(axis=1)
    return out.set_index(rows.index)[RATE_COLS + GAMES_HIST]


def run_arm(rb, extra, g1, arm, params, seed):
    """Walk-forward predictions (total, games part, per-game part) for one arm and seed."""
    model, parts = Model(), []
    data = rb.join(extra) if arm in ("comp_marcel", "comp_mar_inj") else rb
    for x_tr, x_va, x_te, y_tr, y_va, y_te in model.rolling_splits(data, min_train_seasons=FIRST_TEST - 2015):
        tree_cols = [c for c in x_tr.columns if c not in RATE_COLS + GAMES_HIST]
        if arm == "base":
            m = fit_tree(x_tr[tree_cols], y_tr, x_va[tree_cols], y_va, params, seed)
            parts.append(pd.DataFrame({"pred": m.predict(x_te[tree_cols]), "g_hat": np.nan, "ppg_hat": np.nan}, index=x_te.index))
            continue
        games_cols = tree_cols + (GAMES_HIST if arm == "comp_mar_inj" else [])
        g_tr, g_va = g1.reindex(x_tr.index), g1.reindex(x_va.index)
        games = fit_tree(x_tr[games_cols], g_tr, x_va[games_cols], g_va, params, seed)
        k_tr, k_va = g_tr >= MIN_GAMES, g_va >= MIN_GAMES
        ppg_tr, ppg_va = y_tr[k_tr] / g_tr[k_tr], y_va[k_va] / g_va[k_va]
        base_cols = NOISE if arm == "comp_noise" else RATE_COLS if arm != "comp_tree" else None
        if base_cols:
            bl = Baseline(base_cols).fit(x_tr.loc[k_tr, base_cols], ppg_tr)
            b = lambda x: bl.predict(x[base_cols])
            ppg = fit_tree(x_tr.loc[k_tr, tree_cols], ppg_tr, x_va.loc[k_va, tree_cols], ppg_va, params, seed,
                           w_tr=g_tr[k_tr], w_va=g_va[k_va], b_tr=b(x_tr[k_tr]), b_va=b(x_va[k_va]))
        else:
            b = lambda x: np.zeros(len(x))
            ppg = fit_tree(x_tr.loc[k_tr, tree_cols], ppg_tr, x_va.loc[k_va, tree_cols], ppg_va, params, seed, w_tr=g_tr[k_tr], w_va=g_va[k_va])
        g_hat = np.clip(games.predict(x_te[games_cols]), 0, 17)
        p_hat = ppg.predict(x_te[tree_cols]) + b(x_te)
        parts.append(pd.DataFrame({"pred": g_hat * p_hat, "g_hat": g_hat, "ppg_hat": p_hat}, index=x_te.index))
    p = pd.concat(parts)
    return rb.loc[p.index, ["player_id", "season"]].join(p)


def score(preds, bench):
    """Per-season-mean Spearman: totals (top-150, all), and on top-150 the total's rank vs points per game (8+ games),
    vs points per game for stayers (8+ games both seasons, same team as last season's last game), vs games played."""
    d = preds.merge(bench, on=["player_id", "season"])
    rho = lambda sub, a, b: np.mean([spearmanr(g[a], g[b], nan_policy="omit")[0] for _, g in sub.groupby("season")])
    top = d[d["in_top_adp"]]
    full = top[top["G"] >= 8]
    stay = full[(full["G1"] >= 8) & full["stayed"]]
    out = {"top150": rho(top, "pred", "actual_ppr"), "all": rho(d, "pred", "actual_ppr"), "pts_pg": rho(full, "pred", "ppg"),
           "stayers_pg": rho(stay, "pred", "ppg"), "games": rho(top, "pred", "G"),
           "rmse_top150": float(np.sqrt(np.mean((top["pred"] - top["actual_ppr"]) ** 2)))}
    if top["g_hat"].notna().any():
        out.update({"g_part_vs_games": rho(top, "g_hat", "G"), "ppg_part_vs_ppg": rho(full, "ppg_hat", "ppg"),
                    "ppg_part_stayers": rho(stay, "ppg_hat", "ppg")})
    return out


def benchmark_rows(hist):
    """Benchmark RBs with actual games, per game, last season's games and whether he stayed on his team."""
    r1 = pd.read_parquet(ROOT / "data" / "raw" / "roster_wk1_14_25.parquet", columns=["gsis_id", "season", "team"])
    r1 = r1.rename(columns={"gsis_id": "player_id", "team": "team_wk1"}).assign(team_wk1=lambda r: r["team_wk1"].replace(TEAM_MAP))
    prev = hist.assign(season=hist["season"] + 1)[["player_id", "season", "G", "team_last"]].rename(columns={"G": "G1", "team_last": "team_prev"})
    bench = pd.concat([load_season(s)[lambda d: d["position"] == "RB"][["player_id", "season", "actual_ppr", "in_top_adp"]] for s in SEASONS])
    bench = (bench.merge(hist[["player_id", "season", "G", "ppg"]], on=["player_id", "season"], how="left")
                  .merge(prev, on=["player_id", "season"], how="left").merge(r1, on=["player_id", "season"], how="left"))
    bench["stayed"] = bench["team_wk1"].notna() & (bench["team_wk1"] == bench["team_prev"])
    return bench


if __name__ == "__main__":
    rb = split_positions(pd.read_parquet(PIPELINE / "training_data.parquet"))[1]
    hist = season_history()
    extra = rate_and_games_inputs(rb, hist)
    g1 = rb[["player_id", "season"]].merge(hist[["player_id", "season", "G"]], how="left")["G"].fillna(0)
    g1.index = rb.index
    rng = np.random.default_rng(0)
    rb_noise = rb.assign(noise_a=rng.standard_normal(len(rb)), noise_b=rng.standard_normal(len(rb)))
    params = load_params("RB")
    bench = benchmark_rows(hist)
    rows, ensembles = [], {}
    for arm in ["base", "comp_tree", "comp_marcel", "comp_mar_inj", "comp_noise"]:
        runs = []
        for seed in SEEDS:
            preds = run_arm(rb_noise if arm == "comp_noise" else rb, extra, g1, arm, params, seed)
            rows.append({"arm": arm, "seed": seed, **score(preds, bench)})
            runs.append(preds.set_index(["player_id", "season"])["pred"])
        ensembles[arm] = pd.concat(runs, axis=1).mean(axis=1)
        print(arm, "done", flush=True)
    res = pd.DataFrame(rows)
    base = res[res["arm"] == "base"].set_index("seed")
    for col in ["top150", "all", "stayers_pg"]:
        res[f"d_{col}"] = res[col].values - base.loc[res["seed"], col].values   # paired by seed
    summary = res.groupby("arm", sort=False).agg(["mean", "std"]).drop(columns="seed")
    print(summary.xs("mean", axis=1, level=1).round(3).to_string())
    print("\nseed SD"); print(summary.xs("std", axis=1, level=1)[["top150", "d_top150", "stayers_pg"]].round(3).to_string())
    d = bench.set_index(["player_id", "season"]).join(pd.DataFrame(ensembles)).reset_index()
    t = d[d["in_top_adp"]]
    per = pd.DataFrame({a: t.groupby("season").apply(lambda g, a=a: spearmanr(g[a], g["actual_ppr"])[0], include_groups=False) for a in ensembles})
    for a in [a for a in ensembles if a != "base"]:
        per[f"{a}-base"] = per[a] - per["base"]
    print("\nper season, top-150 (10-seed mean projection)"); print(per.round(3).to_string())
