"""QB experiments, each measured against the same walk-forward baseline:
A) per-game PPR features, B) predict PPR per game then scale by games, C) lower-capacity models."""

import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.models.train import Model, split_positions, drop_non_features
from src.evaluation.oos_predictions import load_params
from src.evaluation.benchmark import SEASONS
from src.evaluation.rb_team_context import top150_keys

ROOT = Path(__file__).parent.parent.parent
N_SEEDS = 10
FULL_SEASON_GAMES = 16.0
SUBSET = ["games", "attempts_pg", "completions_pg", "passing_yards_pg", "passing_tds_pg", "passing_interceptions_pg",
          "passing_epa", "passing_cpoe", "carries_pg", "rushing_yards_pg", "rushing_tds_pg", "fantasy_points_ppr",
          "age", "years_exp", "draft_number", "implied_total"]
SIMPLE_PARAMS = {"max_depth": 2, "num_leaves": 4, "min_child_samples": 25, "learning_rate": 0.03, "reg_lambda": 5.0,
                 "subsample": 0.8, "colsample_bytree": 0.7, "n_estimators": 1000, "verbosity": -1,
                 "objective": "regression", "n_jobs": -1, "subsample_freq": 1, "min_child_weight": 1e-3}


def load_qb():
    train = pd.read_parquet(ROOT / "data" / "processed" / "training_data.parquet")
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")[["player_id", "season", "games"]]
    qb = split_positions(train)[0].merge(seasonal.rename(columns={"games": "games_actual"}),
                                         on=["player_id", "season"], how="left")
    qb["ppr_pg_prev"] = qb["fantasy_points_ppr"] / qb["games"].replace(0, np.nan)
    return qb.reset_index(drop=True)


def run(qb, features, seed, kind="lgbm", params=None, target="total", games="full", noise_cols=0):
    """Walk-forward out-of-sample predictions on the total-PPR scale."""
    qb = qb.copy()
    rng = np.random.default_rng(seed)
    for i in range(noise_cols):
        qb[f"noise_{i}"] = rng.normal(size=len(qb))
    features = features + [f"noise_{i}" for i in range(noise_cols)]
    rows = []
    for test in SEASONS:
        tr = qb[(qb.season <= test - 2)]; va = qb[qb.season == test - 1]; te = qb[qb.season == test]
        y = lambda d: d.target_ppr / d.games_actual if target == "per_game" else d.target_ppr
        if kind == "lgbm":
            p = dict(params or load_params("QB"), random_state=seed)
            m = Model().train_model(tr[features], va[features], y(tr), y(va), p)
        else:
            features = [f for f in features if f != "position"]  # constant for QBs, not numeric
            m = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=params["alpha"]))
            m.fit(tr[features], y(tr))
        pred = m.predict(te[features])
        if target == "per_game":
            if games == "full":
                scale = FULL_SEASON_GAMES
            else:  # expected games: halfway between last season's games and the training-set average
                scale = 0.5 * te["games"].values + 0.5 * tr["games_actual"].mean()
            pred = pred * scale
        out = te[["player_id", "season"]].copy(); out["actual"] = te.target_ppr.values; out["pred"] = pred
        rows.append(out)
    return pd.concat(rows)


def score(oos, top_keys):
    top = oos.merge(top_keys, on=["player_id", "season"])
    rho = lambda d: np.mean([spearmanr(g.pred, g.actual)[0] for _, g in d.groupby("season")])
    return rho(top), rho(oos), np.sqrt(((oos.pred - oos.actual) ** 2).mean())


if __name__ == "__main__":
    qb = load_qb()
    base_cols = list(drop_non_features(qb.drop(columns=["games_actual", "ppr_pg_prev"])).columns)
    totals = ["fantasy_points", "fantasy_points_ppr"]
    ridge = {"alpha": 30.0}
    variants = {
        "baseline": dict(features=base_cols),
        "baseline+4 random-noise cols": dict(features=base_cols, noise_cols=4),
        "A1 +ppr_pg_prev": dict(features=base_cols + ["ppr_pg_prev"]),
        "A2 +ppr_pg_prev, drop raw totals": dict(features=[c for c in base_cols if c not in totals] + ["ppr_pg_prev"]),
        "B1 per-game target x 16 games": dict(features=base_cols, target="per_game", games="full"),
        "B2 per-game target x expected games": dict(features=base_cols, target="per_game", games="expected"),
        "C1 16-feature subset": dict(features=SUBSET),
        "C2 simple LGBM params": dict(features=base_cols, params=SIMPLE_PARAMS),
        "C3 ridge, all features": dict(features=base_cols, kind="ridge", params=ridge),
        "C4 ridge, subset": dict(features=SUBSET, kind="ridge", params=ridge),
    }
    keys = top150_keys("QB")
    rows = []
    for name, kw in variants.items():
        seeds = range(N_SEEDS) if kw.get("kind", "lgbm") == "lgbm" else [0]
        r = np.array([score(run(qb, seed=s, **kw), keys) for s in seeds])
        rows.append(dict(variant=name, top150=r[:, 0].mean(), sd=r[:, 0].std(), all_qb=r[:, 1].mean(), rmse=r[:, 2].mean()))
        print(f"{name}: done", flush=True)
    out = pd.DataFrame(rows)
    out["delta_vs_base"] = out["top150"] - out.loc[0, "top150"]
    out.to_csv(ROOT / "data" / "processed" / "qb_experiments.csv", index=False)
    print(out.round(4).to_string(index=False))
