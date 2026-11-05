"""Why is the model above the ADP curve, and do some reasons end below the curve more often? (user's question, 2026-11-04)

Mechanism: the market sees the same stat line. When the model is bullish because of last season's stat line, the market has usually discounted
that line on purpose (who else is in the room, why the volume came), so those likes should end below the curve more often than likes driven by
things the market weighs less (efficiency, trend, profile, team context). Prediction: among bullish calls (model - curve > +20 PPR), the share
that finish below the curve is higher when the stat line drives the gap. Kill: the difference is inside the spread of the same difference with
the driver labels shuffled within season and position. The target is direction (finishing below the curve), not over-projection: bullish calls
miss their projection almost always (selection), and only the ones that end below the market cost the advisor picks.

How: the walk-forward models are retrained exactly as `oos_predictions.py` (train through s-2, early-stop on s-1, 5 seeds, test 2019-2025; the
predictions are checked against season_<year>.parquet) and LightGBM's per-feature contributions (pred_contrib) are averaged over seeds. A
group's contribution is compared with its typical value for players at the same market price (quadratic in the curve value, per position,
fit on all modeled rows with an ADP), so the excess contributions add up to how far the model sits above a typical projection at that
price. A bullish call's driver is the group with the largest positive excess. The curve is the isotonic ADP position-rank curve fit on
earlier seasons (2015 on). Draftable = top 150 by ADP among modeled players. Writes nothing; run: python src/evaluation/gap_attribution.py
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.paths import OOS, PIPELINE
from src.draft.market_fallback import load_history
from src.evaluation.blend_test import curve_points
from src.evaluation.oos_predictions import FIRST_TRAIN_SEASON, N_SEEDS, load_params
from src.models.train import Model, split_positions

ROOT = Path(__file__).parent.parent.parent
FIRST_TEST = 2019
POSITIONS = ["QB", "RB", "WR", "TE"]
BULLISH = 20.0
TOP_N = 150
N_PERM = 5000
SEED = 0

PROFILE = {"age", "years_exp", "rookie_year", "draft_number", "height", "weight", "position"}
CONTEXT = {"implied_total", "vacated_carry_share", "vacated_target_share", "competing_rb_carries", "incoming_rb_carries", "depth_tier_wk1", "qb_att_share_prev"}
VOLUME = {"games", "targets", "carries", "attempts", "targets_pg", "carries_pg", "attempts_pg", "target_share", "air_yards_share", "wopr",
          "receiving_air_yards_pg", "passing_air_yards_pg", "late_target_pct", "late_snap_pct", "pass_snap_share_prev", "rush_snap_share_prev",
          "xfp_ppr_prev", "xfp_pg_prev"}


def group_of(feature, split_stat_line=False):
    """Driver family of a feature: stat line (or volume / production when split), efficiency, trend, profile, context."""
    if feature.endswith("_delta"):
        return "trend"
    if feature in PROFILE:
        return "profile"
    if feature in CONTEXT:
        return "context"
    if "epa" in feature or feature in {"pacr", "racr", "passing_cpoe", "fp_over_exp_prev"} or feature.startswith("ngs_"):
        return "efficiency"
    if split_stat_line:
        return "volume" if feature in VOLUME else "production"
    return "stat line"


def contributions():
    """Walk-forward test rows 2019-2025 with the seed-averaged prediction and per-feature contributions."""
    df = pd.read_parquet(PIPELINE / "training_data.parquet")
    model = Model()
    frames = []
    for position, pos_df in zip(POSITIONS, split_positions(df)):
        folds = model.rolling_splits(pos_df, min_train_seasons=FIRST_TEST - FIRST_TRAIN_SEASON)
        for x_train, x_val, x_test, y_train, y_val, y_test in folds:
            contrib = np.zeros((len(x_test), x_test.shape[1] + 1))
            for seed in range(N_SEEDS):
                m = lgb.LGBMRegressor(**dict(load_params(position), random_state=seed))
                m.fit(x_train, y_train, eval_set=[(x_val, y_val)], eval_metric="rmse", callbacks=[lgb.early_stopping(50, verbose=False)])
                contrib += m.predict(x_test, pred_contrib=True) / N_SEEDS
            out = pd.DataFrame(contrib[:, :-1], columns=[f"c_{c}" for c in x_test.columns], index=x_test.index)
            out["base"] = contrib[:, -1]
            out["pred"] = contrib.sum(axis=1)
            out[["player_id", "player_name", "position", "season"]] = pos_df.loc[x_test.index, ["player_id", "player_name", "position", "season"]]
            out["actual_ppr"] = y_test
            frames.append(out)
    c = pd.concat(frames, ignore_index=True)
    c["position"] = c["position"].astype(str)
    drift = []
    for season, g in c.groupby("season"):
        old = pd.read_parquet(OOS / f"season_{season}.parquet").set_index(["player_id", "position"])["oos_pred_ppr"]
        drift.append((g.set_index(["player_id", "position"])["pred"] - old.reindex(g.set_index(["player_id", "position"]).index)).abs().max())
    print(f"reproduced the walk-forward predictions: max drift against season_<year>.parquet {max(drift):.4f} PPR")
    return c


def add_market(c):
    history = load_history(range(2015, 2026))
    frames = []
    for season, g in c.groupby("season"):
        adp = pd.read_csv(ROOT / "data" / "external" / f"adp_{season}.csv")[["player_id", "adp"]].drop_duplicates("player_id")
        g = g.merge(adp, on="player_id", how="left")
        g["curve"] = g["player_id"].map(curve_points(season, history))
        g["draftable"] = g["adp"].rank(method="first") <= TOP_N
        frames.append(g)
    d = pd.concat(frames, ignore_index=True)
    return d[d["adp"].notna() & d["curve"].notna()].copy()


def excess_by_group(d, split_stat_line=False):
    """Per-row excess contribution of each driver group over its typical value at the same curve value (per position)."""
    features = [c for c in d.columns if c.startswith("c_")]
    groups = sorted({group_of(f[2:], split_stat_line) for f in features})
    out = pd.DataFrame(index=d.index, columns=groups, dtype=float)
    for g in groups:
        cols = [f for f in features if group_of(f[2:], split_stat_line) == g]
        value = d[cols].fillna(0).sum(axis=1)
        for position, rows in d.groupby("position"):
            fit = np.polyfit(rows["curve"], value[rows.index], 2)
            out.loc[rows.index, g] = value[rows.index] - np.polyval(fit, rows["curve"])
    return out


def report(d, excess, label, rng):
    b = d[d["draftable"] & (d["gap"] > BULLISH)].copy()
    ex = excess.loc[b.index]
    b["driver"] = ex.idxmax(axis=1)
    b["below"] = b["actual_ppr"] < b["curve"]
    print(f"\n=== {label}: {len(b)} bullish calls (draftable, model - curve > +{BULLISH:.0f}), 2019-{d['season'].max()}")
    print(f"all bullish: below the curve {b['below'].mean():.0%}, actual minus curve {b['resid'].mean():+.1f}, model over-projection {(b['pred'] - b['actual_ppr']).mean():+.1f}")
    share = ex.clip(lower=0).div(ex.clip(lower=0).sum(axis=1), axis=0).mean()
    print("mean share of the positive excess by group: " + ", ".join(f"{k} {v:.0%}" for k, v in share.items()))
    print(f"{'driver':<12}{'n':>5}{'below curve':>13}{'actual-curve':>14}{'over-proj':>11}{'slope':>8}   by position (n, below)")
    for k, g in b.groupby("driver"):
        slope = (g["gap"] * g["resid"]).sum() / (g["gap"] ** 2).sum()
        pos = ", ".join(f"{p} {len(x)}/{x['below'].mean():.0%}" for p, x in g.groupby("position"))
        print(f"{k:<12}{len(g):>5}{g['below'].mean():>13.0%}{g['resid'].mean():>+14.1f}{(g['pred'] - g['actual_ppr']).mean():>+11.1f}{slope:>8.2f}   {pos}")
    return b


def test(b, focus, rng):
    """Below-curve rate of `focus`-driven bullish calls minus the rest, with labels shuffled within season and position."""
    def stat(x):
        return x.loc[x["driver"] == focus, "below"].mean() - x.loc[x["driver"] != focus, "below"].mean()
    observed = stat(b)
    null = []
    for _ in range(N_PERM):
        s = b.copy()
        s["driver"] = s.groupby(["season", "position"])["driver"].transform(lambda v: rng.permutation(v.values))
        null.append(stat(s))
    null = np.array(null)
    by_season = {s: round(stat(g), 2) if (g["driver"] == focus).any() and (g["driver"] != focus).any() else None for s, g in b.groupby("season")}
    print(f"TEST {focus}-driven minus other bullish calls, share below the curve: {observed:+.1%}; shuffled SD {null.std():.1%}, "
          f"one-sided p {np.mean(null >= observed):.3f}, two-sided p {np.mean(np.abs(null) >= abs(observed)):.3f}")
    print(f"by season: {by_season}")


if __name__ == "__main__":
    rng = np.random.default_rng(SEED)
    d = add_market(contributions())
    d["gap"] = d["pred"] - d["curve"]
    d["resid"] = d["actual_ppr"] - d["curve"]
    b5 = report(d, excess_by_group(d), "five groups (primary)", rng)
    test(b5, "stat line", rng)
    for position in ["RB", "WR"]:
        sub = b5[b5["position"] == position]
        print(f"  {position} only: ", end="")
        test(sub, "stat line", rng)
    b6 = report(d, excess_by_group(d, split_stat_line=True), "six groups (side view: volume vs production)", rng)
    test(b6, "volume", rng)
    test(b6, "production", rng)
    misses = b5[b5["below"]].assign(miss=lambda x: x["curve"] - x["actual_ppr"]).nlargest(15, "miss")
    print("\nlargest bullish misses (finished furthest below the curve):")
    print(misses[["season", "player_name", "position", "adp", "pred", "curve", "actual_ppr", "driver"]].round(0).to_string(index=False))
