"""Candidate fixes for under-projecting players coming off a short season (see short_season_check.py for the problem).

Same walk-forward as oos_predictions (train <= s-2, early-stop on s-1, test s, seasons 2021-2025) with 10 seeds per arm. Arms:
  base                 the current features
  noise                +3 random columns (what a same-size useless addition does)
  ppg                  +ppg_prev (last season's PPR per game)
  ppg2                 +ppg_prev, ppg_prev2, games_prev2 (the season before that)
  ppg2-totals          the same, with last season's raw PPR totals dropped (the total is what reads a short season as low talent)
  per-game x E[games]  the target is PPR per game, multiplied by expected games (a line on last season's games fit on earlier seasons)
  shift (reference)    base plus the mean base residual of games <= 9 rows in the other seasons, per position (leave one season out; not a model)
Scored on the draftable rows (top 150 by ADP): top-150 Spearman per position (mean over seasons), RMSE, and the mean residual (actual - projection) of
the prior-games <= 9 rows and of everyone else. `--rates` runs the second round (every season-total input replaced by rates). A change counts only if it beats the noise arm's spread. Writes data/processed/short_season_fixes.csv;
run: python src/evaluation/short_season_fixes.py
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.benchmark import SEASONS, load_season
from src.evaluation.oos_predictions import load_params
from src.models.short_season import EPA_TOTALS, SHORT_SEASON_GAMES, VOLUME_TOTALS
from src.models.train import drop_non_features, split_positions

ROOT = Path(__file__).parent.parent.parent
N_SEEDS = 10
SHORT = SHORT_SEASON_GAMES
ELITE_ADP = 80  # the short-season gap lives in the first 80 picks (short_season_curve notes, LOG 2026-10-29)
POSITIONS = ["QB", "RB", "WR", "TE"]
RAW_TOTALS = ["fantasy_points", "fantasy_points_ppr"]
ARMS = ["base", "noise", "ppg", "ppg2", "ppg2-totals", "per-game x E[games]", "shift (reference)"]
RATE_ARMS = ["rates", "rates no games"]
ROUTED = "routed (rates no games if games <= 9)"
STRUCTURAL_ARMS = ["pg x E[g] calibrated", "pg x E[g] calibrated, blended with base"]
# Ablations on "rates no games": arm "rates no games|drop=a+b" removes those columns (role features that also shrink when a player misses games)
ABLATIONS = {"QB": ["qb_att_share_prev", "implied_total"],
             "RB": ["vacated_carry_share+vacated_target_share+competing_rb_carries+incoming_rb_carries", "depth_tier_wk1", "xfp_pg_prev", "implied_total"]}


def load_positions():
    """Per-position training frames plus the extra columns: last season's rate, the season before it, and this season's actual games."""
    train = pd.read_parquet(ROOT / "data" / "processed" / "training_data.parquet")
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")[["player_id", "season", "games", "fantasy_points_ppr"]]
    prev2 = seasonal.assign(season=seasonal["season"] + 2).rename(columns={"games": "games_prev2", "fantasy_points_ppr": "ppr_prev2"})
    now = seasonal.rename(columns={"games": "games_actual"})[["player_id", "season", "games_actual"]]
    frames = []
    for df in split_positions(train):
        df = df.merge(prev2[["player_id", "season", "games_prev2", "ppr_prev2"]], on=["player_id", "season"], how="left")
        df = df.merge(now, on=["player_id", "season"], how="left")
        df["ppg_prev"] = df["fantasy_points_ppr"] / df["games"].replace(0, np.nan)
        df["ppg_prev2"] = df["ppr_prev2"] / df["games_prev2"].replace(0, np.nan)
        for column in EPA_TOTALS:
            if column in df:
                df[f"{column}_pg"] = df[column] / df["games"].replace(0, np.nan)
        frames.append(df.drop(columns="ppr_prev2").reset_index(drop=True))
    return frames


def fit_predict(train, val, test, features, params, target="total", extra=None):
    """One early-stopped LightGBM fit; the per-game target trains on rows with games and weights each by its games. With `extra`, also predicts that frame."""
    if target == "per_game":
        train, val = train[train["games_actual"] >= 1], val[val["games_actual"] >= 1]
        y_tr, y_va = train["target_ppr"] / train["games_actual"], val["target_ppr"] / val["games_actual"]
        w_tr, w_va = train["games_actual"], val["games_actual"]
    else:
        y_tr, y_va, w_tr, w_va = train["target_ppr"], val["target_ppr"], None, None
    model = lgb.LGBMRegressor(**params)
    model.fit(train[features], y_tr, sample_weight=w_tr, eval_set=[(val[features], y_va)], eval_sample_weight=None if w_va is None else [w_va],
              eval_metric="rmse", callbacks=[lgb.early_stopping(50, verbose=False)])
    return model.predict(test[features]) if extra is None else (model.predict(test[features]), model.predict(extra[features]))


def expected_games(history, test):
    """Games this season from last season's and the one before (least squares on the seasons already played; missing earlier season = last season's)."""
    x = lambda d: np.column_stack([np.ones(len(d)), d["games"], d["games_prev2"].fillna(d["games"])])
    coef = np.linalg.lstsq(x(history), history["games_actual"].fillna(0), rcond=None)[0]
    return np.clip(x(test) @ coef, 1, 17)


def oos(df, position, arm, seed):
    """Walk-forward predictions for one arm; one row per player-season in 2021-2025."""
    base = list(drop_non_features(df.drop(columns=["games_actual", "games_prev2", "ppg_prev", "ppg_prev2"] + [f"{c}_pg" for c in EPA_TOTALS if f"{c}_pg" in df])).columns)
    features = {"base": base, "noise": base, "ppg": base + ["ppg_prev"], "ppg2": base + ["ppg_prev", "ppg_prev2", "games_prev2"],
                "ppg2-totals": [c for c in base if c not in RAW_TOTALS] + ["ppg_prev", "ppg_prev2", "games_prev2"]}.get(arm, base)
    df = df.copy()
    arm, _, drops = arm.partition("|drop=")
    if arm in RATE_ARMS:
        base = [c for c in base if c not in VOLUME_TOTALS]
        base += [f"{c}_pg" for c in EPA_TOTALS if c in df] + ["ppg_prev"]
        if "no games" in arm:
            base = [c for c in base if c not in ("games", "games_delta")]
        features = [c for c in base if c not in drops.split("+")]
    if arm == "noise":
        rng = np.random.default_rng(1000 + seed)
        for i in range(3):
            df[f"noise_{i}"] = rng.normal(size=len(df))
        features = base + [f"noise_{i}" for i in range(3)]
    params = dict(load_params(position), random_state=seed)
    rows = []
    for season in SEASONS:
        train, val, test = df[df["season"] <= season - 2], df[df["season"] == season - 1], df[df["season"] == season]
        if arm == "per-game x E[games]":
            pred = fit_predict(train, val, test, base, params, target="per_game") * expected_games(df[df["season"] < season], test)
        elif arm in STRUCTURAL_ARMS:  # scale so the structural model is unbiased on the validation season, then optionally average with the base model
            hist = df[df["season"] < season]
            raw_test, raw_val = fit_predict(train, val, test, base, params, target="per_game", extra=val)
            raw_val, raw_test = raw_val * expected_games(hist[hist["season"] == season - 1], val), raw_test * expected_games(hist, test)
            pred = raw_test * (val["target_ppr"].sum() / raw_val.sum())
            if "blended" in arm:
                pred = 0.5 * pred + 0.5 * fit_predict(train, val, test, base, params)
        else:
            pred = fit_predict(train, val, test, features, params)
        out = test[["player_id", "season", "games", "target_ppr"]].rename(columns={"target_ppr": "actual"})
        out["pred"] = pred
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def add_shift(runs):
    """Reference arm: add the base residual's mean over games <= SHORT rows of the other seasons (one position)."""
    out = runs.copy()
    short = out["games"] <= SHORT
    for season in SEASONS:
        other = short & (out["season"] != season)
        shift = (out.loc[other, "actual"] - out.loc[other, "pred"]).mean()
        out.loc[short & (out["season"] == season), "pred"] += shift
    return out


def score(runs, keys):
    """Top-150 Spearman (mean over seasons), RMSE and mean residual of short-season rows / the rest, on the draftable rows."""
    top = runs.merge(keys, on=["player_id", "season"])
    resid = top["actual"] - top["pred"]
    short = top["games"] <= SHORT
    elite = short & (top["adp"] <= ELITE_ADP)
    return dict(resid_elite=float(resid[elite].mean()), n_elite=int(elite.sum()), rho=np.mean([spearmanr(g["pred"], g["actual"])[0] for _, g in top.groupby("season")]),
                rmse=float(np.sqrt((resid ** 2).mean())), resid_short=float(resid[short].mean()), resid_rest=float(resid[~short].mean()),
                n_short=int(short.sum()))


if __name__ == "__main__":
    keys = {}
    for season in SEASONS:
        d = load_season(season)
        keys[season] = d[d["in_top_adp"]][["player_id", "position", "season", "adp"]]
    keys = pd.concat(keys.values())
    rates_only = any(a in sys.argv for a in ("--rates", "--ablate", "--structural", "--route"))  # later rounds: base, noise and the rate arms, written to a separate file

    def arms_for(position):
        if "--route" in sys.argv:
            return ["base", ROUTED]
        if "--structural" in sys.argv:
            return ["base", "noise"] + STRUCTURAL_ARMS
        if "--ablate" in sys.argv:
            return ["base", "rates no games"] + [f"rates no games|drop={d}" for d in ABLATIONS.get(position, [])]
        return ["base", "noise"] + RATE_ARMS if rates_only else ARMS

    results, routed = [], []
    for position, df in zip(POSITIONS, load_positions()):
        pos_keys = keys[keys["position"] == position][["player_id", "season", "adp"]]
        for seed in range(N_SEEDS):
            base_runs = oos(df, position, "base", seed)
            for arm in arms_for(position):
                if arm == ROUTED:  # the rates-only model for players off a short season, the current model for everyone else
                    runs = base_runs.copy()
                    rates = oos(df, position, "rates no games", seed)
                    use = runs["games"] <= SHORT
                    runs.loc[use, "pred"] = rates.loc[use, "pred"].to_numpy()
                    routed.append(runs.assign(position=position, seed=seed, base_pred=base_runs["pred"]))
                else:
                    runs = base_runs if arm == "base" else add_shift(base_runs) if arm.startswith("shift") else oos(df, position, arm, seed)
                results.append(dict(position=position, arm=arm, seed=seed, **score(runs, pos_keys)))
        print(f"{position}: done", flush=True)
    if routed:  # seed-averaged predictions, for write_backtest_files (the simulator judges them)
        routed = pd.concat(routed).groupby(["player_id", "season"], as_index=False)[["pred", "base_pred"]].mean()
        routed.rename(columns={"pred": "routed_pred_ppr"}).to_parquet(ROOT / "data" / "processed" / "short_season_routed.parquet")
    results = pd.DataFrame(results)
    results.to_csv(ROOT / "data" / "processed" / ("short_season_route.csv" if "--route" in sys.argv else "short_season_structural.csv" if "--structural" in sys.argv else "short_season_ablate.csv" if "--ablate" in sys.argv else "short_season_rates.csv" if rates_only else "short_season_fixes.csv"), index=False)
    summary = results.groupby(["position", "arm"], sort=False)[["rho", "rmse", "resid_short", "resid_elite", "resid_rest"]].agg(["mean", "std"])
    for position in POSITIONS:
        s = summary.loc[position].loc[arms_for(position)]
        s["d_rho"] = s[("rho", "mean")] - s.loc["base", ("rho", "mean")]
        print(f"\n== {position} (n short rows {int(results[(results.position == position) & (results.arm == 'base')]['n_short'].iloc[0])}) ==")
        print(s.round(3).to_string())
