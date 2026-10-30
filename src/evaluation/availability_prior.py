"""Does a games-played prior fitted on a long window beat the totals target? (LOG.md, 2026-10-30; user's idea: injury base rates do not go stale, usage does.)

Same walk-forward as short_season_fixes (train <= s-2, early-stop on s-1, test s, seasons 2021-2025, 10 seeds, scored on the top-150 ADP rows). The usage model gets a points-per-game target
(each row weighted by its games); the projection is rate x expected games, where expected games come from a separate prior that does NOT see last season's games (the log found that
conditioning on them assumes injuries persist, wrong for short-season players). The prior is a per-position least-squares line of games / schedule on age, age squared and last season's
workload (carries + targets per game; passing attempts per game for QB), fitted on every earlier transition (a player with 4+ games in s-1 who played in s), as the main model's rows are.
Arms:
  base               the current totals model
  noise              +3 random columns (what a same-size useless addition does)
  pg x prior 2000+   the idea: rate x prior fitted on 2000..s-1 (all QB/RB/WR/TE, not only draftable players)
  pg x prior 2015+   the same prior fitted on the model's own window (transitions into 2015..s-1): isolates what the long window adds
  pg x position mean the same rate model x each position's mean games fraction (2000..s-1): isolates what conditioning on age and workload adds
  per-game x E[games]  the arm already rejected (expected games from last season's games), for reference
Scored: top-150 Spearman (mean over seasons), RMSE, mean residual of all / short-season / healthy rows. A change counts only if it beats the noise arm's spread. Writes data/processed/availability_prior.csv.
Run: python src/evaluation/availability_prior.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.benchmark import SEASONS, load_season
from src.evaluation.oos_predictions import load_params
from src.models.short_season import EPA_TOTALS
from src.evaluation.short_season_fixes import N_SEEDS, POSITIONS, fit_predict, load_positions, oos, score
from src.models.train import drop_non_features

ROOT = Path(__file__).parent.parent.parent
ARMS = ["base", "noise", "pg x prior 2000+", "pg x prior 2015+", "pg x position mean", "per-game x E[games]"]
schedule = lambda season: 16 if season <= 2020 else 17


def load_history():
    """One row per player-season 2000-2025 (QB/RB/WR/TE): games, workload per game and age."""
    cols = ["player_id", "position", "season", "games", "carries", "targets", "attempts"]
    old = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_00_13.parquet")[cols]
    new = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")
    new = new[new["position"].isin(POSITIONS) & new["player_id"].notna()][cols]
    hist = pd.concat([old, new], ignore_index=True).drop_duplicates(["player_id", "season"])
    born = pd.read_parquet(ROOT / "data" / "raw" / "players_birth.parquet").dropna(subset=["birth_date"])
    born = born.assign(born=pd.to_datetime(born["birth_date"]).dt.year).drop_duplicates("gsis_id").rename(columns={"gsis_id": "player_id"})
    hist = hist.merge(born[["player_id", "born"]], on="player_id", how="inner")
    hist["workload"] = (hist["carries"] + hist["targets"]) / hist["games"]
    hist["attempts_pg"] = (hist["attempts"] / hist["games"]).fillna(0)
    return hist


def transitions(hist):
    """A player with 4+ games in s-1 who played in s: last season's workload and this season's age -> this season's games as a share of the schedule."""
    prev = hist[hist["games"] >= 4].assign(season=lambda d: d["season"] + 1)
    cur = hist[["player_id", "season", "games"]].rename(columns={"games": "games_now"})
    t = prev.merge(cur, on=["player_id", "season"])
    t["age"] = t["season"] - t["born"]
    t["share"] = t["games_now"].clip(upper=t["season"].map(schedule)) / t["season"].map(schedule)
    return t[["player_id", "position", "season", "age", "workload", "attempts_pg", "share"]]


def design(d):
    return np.column_stack([np.ones(len(d)), d["age"], d["age"] ** 2, d["workload"], d["attempts_pg"]])


def prior_games(trans, test, position, season, first):
    """Expected games of the `test` rows from the transitions into first..season-1."""
    h = trans[(trans["position"] == position) & (trans["season"] >= first) & (trans["season"] < season)]
    coef = np.linalg.lstsq(design(h), h["share"], rcond=None)[0]
    return np.clip(design(test) @ coef, 0.2, 1.0) * schedule(season)


def mean_games(trans, position, season):
    h = trans[(trans["position"] == position) & (trans["season"] < season)]
    return h["share"].mean() * schedule(season)


def test_frame(df, season, hist):
    """The test rows with the inputs the prior needs (the row's per-game columns are last season's; a position frame may lack some)."""
    test = df[df["season"] == season].copy()
    col = lambda name: test[name].fillna(0) if name in test else 0.0
    test["workload"] = col("carries_pg") + col("targets_pg")
    test["attempts_pg"] = col("attempts_pg")
    return test


def run_arm(df, position, arm, seed, trans, hist):
    """Walk-forward predictions for one new arm; one row per player-season in 2021-2025."""
    base = list(drop_non_features(df.drop(columns=["games_actual", "games_prev2", "ppg_prev", "ppg_prev2"] + [f"{c}_pg" for c in EPA_TOTALS if f"{c}_pg" in df])).columns)
    params = dict(load_params(position), random_state=seed)
    rows = []
    for season in SEASONS:
        train, val, test = df[df["season"] <= season - 2], df[df["season"] == season - 1], test_frame(df, season, hist)
        rate = fit_predict(train, val, test, base, params, target="per_game")
        if arm == "pg x prior 2000+":
            games = prior_games(trans, test, position, season, 2000)
        elif arm == "pg x prior 2015+":
            games = prior_games(trans, test, position, season, 2015)
        else:
            games = mean_games(trans, position, season)
        out = test[["player_id", "season", "games", "target_ppr"]].rename(columns={"target_ppr": "actual"})
        out["pred"] = rate * games
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def summarize(runs, keys):
    s = score(runs, keys)
    top = runs.merge(keys, on=["player_id", "season"])
    s["resid_all"] = float((top["actual"] - top["pred"]).mean())
    return s


if __name__ == "__main__":
    hist = load_history()
    trans = transitions(hist)
    print(f"transitions {len(trans)}; into 2015+: {(trans.season >= 2015).sum()}; birth-date coverage ok", flush=True)
    keys = pd.concat(load_season(s).query("in_top_adp")[["player_id", "position", "season", "adp"]] for s in SEASONS)
    results = []
    for position, df in zip(POSITIONS, load_positions()):
        pos_keys = keys[keys["position"] == position][["player_id", "season", "adp"]]
        for seed in range(N_SEEDS):
            for arm in ARMS:
                runs = oos(df, position, arm, seed) if arm in ("base", "noise", "per-game x E[games]") else run_arm(df, position, arm, seed, trans, hist)
                results.append(dict(position=position, arm=arm, seed=seed, **summarize(runs, pos_keys)))
        print(f"{position}: done", flush=True)
    results = pd.DataFrame(results)
    results.to_csv(ROOT / "data" / "processed" / "availability_prior.csv", index=False)
    summary = results.groupby(["position", "arm"], sort=False)[["rho", "rmse", "resid_all", "resid_short", "resid_rest"]].agg(["mean", "std"])
    for position in POSITIONS:
        s = summary.loc[position].copy()
        s["d_rho"] = s[("rho", "mean")] - s.loc["base", ("rho", "mean")]
        print(f"\n== {position} ==")
        print(s.round(3).to_string())
