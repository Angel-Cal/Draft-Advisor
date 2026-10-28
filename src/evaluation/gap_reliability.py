"""Is the model's disagreement with the ADP curve equally trustworthy for every kind of player?

The 50/50 model + ADP-curve blend was more accurate but made the recommender worse (LOG 2026-10-25), so a uniform shrink throws away good disagreements.
Here the slope b in `actual - curve = b x (model - curve)` is estimated by player type on the walk-forward predictions (2022-2025, curve fit on earlier
seasons only, draftable players): b = 1 means the model is right about the gap, b = 0 means the ADP curve is. Groups: position, last season's games,
age, experience, and the sign and size of the gap. Slopes come with a bootstrap interval (resampling players) and the number of rows.

Then a leave-one-season-out check: slopes fit on the other seasons are applied to the held-out season (clipped to 0-1, a group is only shrunk when its
interval excludes 1), and RMSE and top-150 Spearman are compared with the model alone and the uniform blend. Writes nothing; run:
python src/evaluation/gap_reliability.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.draft.market_fallback import load_history
from src.evaluation.benchmark import load_season
from src.evaluation.blend_test import SEASONS, blended, curve_points, rmse
from src.evaluation.refit_oos import write_backtest_files

ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
N_BOOT = 2000
SEED = 0


def load_rows():
    """Ranked player-seasons 2022-2025 with the model, the ADP curve, the outcome and the player-type columns."""
    history = load_history()
    features = pd.read_parquet(PROCESSED_DIR / "training_data.parquet")[["player_id", "season", "games", "games_delta", "age", "years_exp"]]
    rows = []
    for season in SEASONS:
        df = load_season(season)
        df["curve"] = df["player_id"].map(curve_points(season, history))
        df["season"] = season
        rows.append(df.dropna(subset=["curve"]))
    d = pd.concat(rows, ignore_index=True).merge(features, on=["player_id", "season"], how="left")
    d["gap"] = d["oos_pred_ppr"] - d["curve"]
    d["resid"] = d["actual_ppr"] - d["curve"]
    return d


GROUPS = {
    "all": lambda d: d["gap"].notna(),
    "missed 5+ games last season": lambda d: d["games"] <= 12,
    "healthy last season (13+ games)": lambda d: d["games"] >= 13,
    "age 30+": lambda d: d["age"] >= 30,
    "age under 25": lambda d: d["age"] < 25,
    "years of experience 0-2": lambda d: d["years_exp"] <= 2,
    "years of experience 7+": lambda d: d["years_exp"] >= 7,
    "games fell 4+ vs the year before": lambda d: d["games_delta"] <= -4,
    "model above the curve": lambda d: d["gap"] > 0,
    "model below the curve": lambda d: d["gap"] < 0,
    "large gap (over 1.5x median)": lambda d: d["gap_size"] > 1.5,
    "small gap (under 0.5x median)": lambda d: d["gap_size"] < 0.5,
}


def slope(g):
    """Least squares through the origin: how much of the model's gap shows up in the outcome."""
    return float((g["gap"] * g["resid"]).sum() / (g["gap"] ** 2).sum())


def slope_interval(g, rng):
    """Slope with a bootstrap 90% interval that resamples whole players (a player appears in several seasons)."""
    players = g["player_id"].unique()
    by_player = {p: x for p, x in g.groupby("player_id")}
    boots = []
    for _ in range(N_BOOT):
        pick = rng.choice(players, size=len(players))
        boots.append(slope(pd.concat([by_player[p] for p in pick])))
    return slope(g), np.percentile(boots, 5), np.percentile(boots, 95)


def report(d, rng):
    d = d[d["in_top_adp"]].copy()
    d["gap_size"] = d["gap"].abs() / d.groupby("position")["gap"].transform(lambda g: g.abs().median())
    print(f"{len(d)} draftable player-seasons, {SEASONS.start}-{SEASONS.stop - 1}\n")
    print(f"{'group':<36}{'position':<9}{'n':>5}{'slope':>8}{'90% interval':>16}")
    for name, rule in GROUPS.items():
        for position in ["ALL", "QB", "RB", "WR", "TE"]:
            g = d if position == "ALL" else d[d["position"] == position]
            g = g[rule(g)].dropna(subset=["gap"])
            if len(g) < 25:
                continue
            b, lo, hi = slope_interval(g, rng)
            flag = "  <- interval excludes 1" if hi < 1 else ("  <- interval excludes 0" if lo > 0 and name == "all" else "")
            print(f"{name:<36}{position:<9}{len(g):>5}{b:>8.2f}{f'{lo:.2f} to {hi:.2f}':>16}{flag}")
        print()


CANDIDATES = {
    "by position": lambda d: d["position"],
    "position x gap sign": lambda d: d["position"] + np.where(d["gap"] > 0, "+", "-"),
    "RB fades only": lambda d: pd.Series(np.where((d["position"] == "RB") & (d["gap"] < 0), "RB-", "keep"), index=d.index),
}
CANDIDATE_DIR = PROCESSED_DIR / "gap_shrink"


def adjusted(d, key):
    """curve + b x (model - curve), with b per group fit on the draftable rows of the other seasons only (clipped to 0-1; groups named 'keep' stay at 1)."""
    out = pd.Series(index=d.index, dtype=float)
    for season in SEASONS:
        held = d["season"] == season
        fit = d[~held & d["in_top_adp"]]
        groups = key(fit)
        slopes = {k: float(np.clip(slope(g), 0, 1)) for k, g in fit.groupby(groups) if k != "keep"}
        b = key(d[held]).map(slopes).fillna(1.0)
        out[held] = d.loc[held, "curve"] + b * d.loc[held, "gap"]
    return out


def compare(d):
    """Held-out accuracy of each candidate: top-150 Spearman (mean over seasons) and RMSE over all ranked players, per position."""
    arms = {"model": d["oos_pred_ppr"], "50/50 blend": pd.Series(blended(d["oos_pred_ppr"], d["curve"]), index=d.index)}
    arms.update({name: adjusted(d, key) for name, key in CANDIDATES.items()})
    print("Held-out (leave one season out) accuracy, 2022-2025")
    for label, metric in [("top-150 Spearman", lambda g, c: np.mean([spearmanr(s[c], s["actual_ppr"])[0] for _, s in g[g["in_top_adp"]].groupby("season")])),
                          ("RMSE, all ranked players", lambda g, c: rmse(g[c], g["actual_ppr"]))]:
        table = {name: {position: metric(g.assign(arm=arms[name]), "arm") for position, g in d.groupby("position")} for name in arms}
        print(f"\n{label}\n" + pd.DataFrame(table).T.round(3 if "Spearman" in label else 1).to_string())
    return arms


if __name__ == "__main__":
    d = load_rows()
    if "--report" in sys.argv:
        report(d, np.random.default_rng(SEED))
    arms = compare(d)
    for name in CANDIDATES:
        column = f"adj_{name}"
        d[column] = arms[name]
        ratios = {p: rmse(g[column], g["actual_ppr"]) / rmse(g["oos_pred_ppr"], g["actual_ppr"]) for p, g in d.groupby("position")}
        folder = CANDIDATE_DIR / name.replace(" ", "_")
        write_backtest_files(d, column, folder, f"{name} gap shrink (gap_reliability.py)", ratios)
    print(f"\nwrote candidate projection files under {CANDIDATE_DIR}")
