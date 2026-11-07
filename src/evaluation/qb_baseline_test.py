"""QB test 2: a linear baseline carries the stable components, the tree learns only the corrections (LightGBM init_score).

Mechanism under test: rushing points per game carry over at r 0.84, passing at 0.41, but one tree on season totals
weighs them about equally (+22 vs +18 for a consistent +4 points per game). A linear term can give rushing its weight
and extrapolate to the 30+ yards-a-game tail the tree cannot split out (about 40 training rows). Arms (10 seeds,
same walk-forward as oos_predictions.py, ridge fitted on each fold's training seasons only):
  base       current QB model
  lin_skill  baseline = ridge(season total ~ last season's rushing and passing points per game)
  lin_full   baseline adds games, qb_att_share_prev, age, age^2
  lin_pg     baseline = ridge(points per game ~ rushing, passing pts/game; rows with 4+ games, weighted by games) x mean games
  lin_noise  baseline on two N(0,1) columns (control: an uninformative baseline)
Scored as in qb_rushing_test.py, plus the consistent rushing and passing bump responses and the fitted weights.
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.paths import PIPELINE
from src.models.train import Model, split_positions, drop_non_features
from src.evaluation.oos_predictions import load_params
from src.evaluation.benchmark import SEASONS, load_season
from src.evaluation.qb_rushing_test import components, score, FIRST_TEST

SEEDS = range(10)
SKILL = ["rush_pg", "pass_pg"]
FULL = SKILL + ["games", "share", "age", "age2"]
NOISE = ["noise_a", "noise_b"]


def baseline_inputs(x, share_fill):
    """Baseline columns derived from the model's own feature frame, so a bump to x flows into the baseline too."""
    return pd.DataFrame({
        "rush_pg": x["rushing_yards_pg"] * 0.1 + x["rushing_tds_pg"] * 6,
        "pass_pg": x["passing_yards_pg"] * 0.04 + x["passing_tds_pg"] * 4 - x["passing_interceptions_pg"] * 2,
        "games": x["games"], "share": x["qb_att_share_prev"].fillna(share_fill), "age": x["age"], "age2": x["age"] ** 2,
    }, index=x.index)


class Baseline:
    """Standardized ridge on a few columns; `per_game` fits points per game and scales by the training mean games."""

    def __init__(self, cols, per_game=False):
        self.cols, self.per_game = cols, per_game

    def fit(self, b, y, games_target=None):
        """b: baseline inputs; y: season totals; games_target: target-season games (per-game arm only)."""
        self.mu, self.sd = b[self.cols].mean(), b[self.cols].std().replace(0, 1)
        z = (b[self.cols] - self.mu) / self.sd
        if self.per_game:
            keep = games_target >= 4
            self.ridge = Ridge(alpha=1.0).fit(z[keep], (y / games_target)[keep], sample_weight=games_target[keep])
            self.scale = games_target.mean()
        else:
            self.ridge, self.scale = Ridge(alpha=1.0).fit(z, y), 1.0
        return self

    def predict(self, b):
        return self.ridge.predict((b[self.cols] - self.mu) / self.sd) * self.scale

    def weights(self):
        """Season points per extra point per game of each input (raw units)."""
        return {c: self.ridge.coef_[i] / self.sd[c] * self.scale for i, c in enumerate(self.cols)}


def bump(x, kind):
    """A consistent +4 fantasy points per game from rushing or passing: per-game, season-total and fantasy-total columns."""
    x, g = x.copy(), x["games"].clip(lower=1)
    if kind == "rush":
        x["rushing_yards_pg"] += 25; x["rushing_tds_pg"] += 0.25; x["carries_pg"] += 4; x["rushing_first_downs_pg"] += 1.5
        x["carries"] += 4 * g
    else:
        x["passing_yards_pg"] += 50; x["passing_tds_pg"] += 0.5; x["completions_pg"] += 4; x["attempts_pg"] += 6
        x["passing_first_downs_pg"] += 2.5; x["attempts"] += 6 * g
    x["fantasy_points"] += 4 * g; x["fantasy_points_ppr"] += 4 * g
    return x


def run_arm(qb, games_target, spec, params, seed):
    """Walk-forward predictions for one arm and seed, plus bump responses and the fitted baseline weights per fold."""
    model, preds, rush, pas, weights = Model(), [], [], [], []
    for x_tr, x_va, x_te, y_tr, y_va, y_te in model.rolling_splits(qb, min_train_seasons=FIRST_TEST - 2015):
        feats = [c for c in x_tr.columns if c not in NOISE]
        if spec is None:
            base = lambda x: np.zeros(len(x))
        else:
            fill = x_tr["qb_att_share_prev"].median()
            inputs = (lambda x: x[NOISE]) if spec.cols == NOISE else (lambda x, f=fill: baseline_inputs(x, f))
            spec.fit(inputs(x_tr), y_tr, games_target.reindex(x_tr.index))
            base = lambda x, i=inputs: spec.predict(i(x))
            weights.append(spec.weights())
        fit = lgb.LGBMRegressor(**dict(params, random_state=seed))
        fit.fit(x_tr[feats], y_tr, init_score=base(x_tr), eval_set=[(x_va[feats], y_va)], eval_init_score=[base(x_va)],
                eval_metric="rmse", callbacks=[lgb.early_stopping(50, verbose=False)])
        predict = lambda x: fit.predict(x[feats]) + base(x)
        p = predict(x_te)
        preds.append(pd.Series(p, index=x_te.index))
        rush.append(np.mean(predict(bump(x_te, "rush")) - p))
        pas.append(np.mean(predict(bump(x_te, "pass")) - p))
    s = pd.concat(preds)
    out = qb.loc[s.index, ["player_id", "season"]].assign(pred=s.values)
    w = pd.DataFrame(weights).mean().to_dict() if weights else {}
    return out, np.mean(rush), np.mean(pas), w


if __name__ == "__main__":
    qb = split_positions(pd.read_parquet(PIPELINE / "training_data.parquet"))[0]
    rng = np.random.default_rng(0)
    qb = qb.assign(noise_a=rng.standard_normal(len(qb)), noise_b=rng.standard_normal(len(qb)))
    comps = components()
    games_target = qb[["player_id", "season"]].merge(comps[["player_id", "season", "G"]], how="left")["G"].fillna(0)
    games_target.index = qb.index
    params = load_params("QB")
    arms = {"base": None, "lin_skill": Baseline(SKILL), "lin_full": Baseline(FULL),
            "lin_pg": Baseline(SKILL, per_game=True), "lin_noise": Baseline(NOISE)}
    bench = pd.concat([load_season(s)[lambda d: d["position"] == "QB"][["player_id", "season", "actual_ppr", "in_top_adp"]] for s in SEASONS])
    rows, weights = [], {}
    for name, spec in arms.items():
        for seed in SEEDS:
            preds, r, p, w = run_arm(qb, games_target, spec, params, seed)
            rows.append({"arm": name, "seed": seed, "rush_bump": r, "pass_bump": p, **score(preds, bench, comps)})
            weights[name] = w
        print(name, "done", flush=True)
    res = pd.DataFrame(rows)
    base = res[res["arm"] == "base"].set_index("seed")
    for col in ["top150", "all", "rush_pg", "games"]:
        res[f"d_{col}"] = res[col].values - base.loc[res["seed"], col].values   # paired by seed
    summary = res.groupby("arm", sort=False).agg(["mean", "std"]).drop(columns="seed")
    print("\nbumps = +4 fantasy points per game from rushing or from passing (consistent per-game and season-total columns)")
    print(summary.xs("mean", axis=1, level=1).round(3).to_string())
    print("\nseed SD"); print(summary.xs("std", axis=1, level=1)[["top150", "d_top150", "rush_pg", "rush_bump"]].round(3).to_string())
    print("\nbaseline weights (season points per +1 point per game; mean over folds)")
    for name, w in weights.items():
        if w:
            print(f"  {name:10s}", {k: round(v, 2) for k, v in w.items()})
