"""Train the model on what ADP misses? (LOG.md, 2026-10-29)

Three models on identical rows (players with a FantasyPros ADP, seasons 2015 on, walk-forward like oos_predictions: train through s-2, early-stop on s-1, test s, 5 seeds averaged, params as saved):
  plain    the usual features, target = season points (the control for "fewer rows than the main model")
  adpfeat  the same plus ADP, ADP position rank and the ADP-curve value as inputs, target = season points
  resid    the same inputs, target = season points minus the ADP-curve value; the projection is curve + prediction
The curve is the isotonic map from ADP position rank to expected points (market_fallback.fit_position_curves). A training row's curve leaves its own season out; validation and test rows use only earlier seasons.
Writes backtest files with the projections under data/processed/adpres/<model> (`backtest --data data/processed/adpres/resid --seasons 2019-2025`) and prints accuracy against the main model on the draftable rows.

Run: python src/evaluation/adp_residual.py [--tests 2019,2020,2021,2022,2023,2024,2025] [--models plain,adpfeat,resid]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.draft.market_fallback import fit_position_curves, load_history
from src.evaluation.oos_predictions import N_SEEDS, load_params
from src.evaluation.refit_oos import POSITIONS, write_backtest_files
from src.models.train import Model, drop_non_features, split_positions

ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
FIRST_SEASON = 2015
ALL_SEASONS = range(2015, 2026)


def adp_table():
    """player_id, season, adp, ADP position and position rank, for the seasons with an ADP file."""
    frames = []
    for season in ALL_SEASONS:
        adp = pd.read_csv(ROOT / "data" / "external" / f"adp_{season}.csv")[["player_id", "position", "adp"]]
        adp = adp.sort_values("adp").drop_duplicates("player_id").rename(columns={"position": "adp_position"})
        adp["season"] = season
        adp["position_rank"] = adp.groupby("adp_position")["adp"].rank(method="first")
        frames.append(adp)
    return pd.concat(frames, ignore_index=True)


def curve_values(rows, history, fit_seasons):
    """The ADP-curve value of each row, from a curve fitted on `fit_seasons` of the history."""
    curves = fit_position_curves(history[history["season"].isin(fit_seasons)])
    return np.array([curves[p].predict([r])[0] for p, r in zip(rows["adp_position"], rows["position_rank"])])


def with_curve(rows, history, fit_for_season):
    """rows plus a `curve` column; `fit_for_season(season)` gives the seasons the curve of that season's rows is fitted on."""
    out = rows.copy()
    out["curve"] = 0.0
    for season in out["season"].unique():
        mask = out["season"] == season
        out.loc[mask, "curve"] = curve_values(out[mask], history, fit_for_season(season))
    return out


def features(rows, model_name):
    x = drop_non_features(rows).drop(columns=["adp_position", "curve"], errors="ignore")
    if model_name == "plain":
        return x.drop(columns=["adp", "position_rank"], errors="ignore")
    return x.assign(curve=rows["curve"])


def predictions(tests, model_names):
    df = pd.read_parquet(PROCESSED_DIR / "training_data.parquet")
    adp = adp_table()
    history = load_history(ALL_SEASONS)
    model = Model()
    rows = []
    for position, pos_df in zip(POSITIONS, split_positions(df)):
        data = pos_df.merge(adp, on=["player_id", "season"], how="inner")       # only players with an ADP
        for season in tests:
            train_seasons = list(range(FIRST_SEASON, season - 1))
            train = with_curve(data[data["season"].isin(train_seasons)], history, lambda s: [t for t in train_seasons if t != s])
            val = with_curve(data[data["season"] == season - 1], history, lambda s: train_seasons)
            test = with_curve(data[data["season"] == season], history, lambda s: train_seasons + [season - 1])
            out = test[["player_id", "player_name", "position", "season"]].copy()
            out["actual_ppr"] = test["target_ppr"]
            out["curve"] = test["curve"]
            for name in model_names:
                shift = (lambda d: d["curve"]) if name == "resid" else (lambda d: 0.0)
                y_train, y_val = train["target_ppr"] - shift(train), val["target_ppr"] - shift(val)
                x_train, x_val, x_test = features(train, name), features(val, name), features(test, name)
                preds = [model.train_model(x_train, x_val, y_train, y_val, dict(load_params(position), random_state=seed, verbose=-1)).predict(x_test) for seed in range(N_SEEDS)]
                out[f"{name}_pred_ppr"] = sum(preds) / N_SEEDS + shift(test)
            rows.append(out)
        print(f"{position} done", flush=True)
    return pd.concat(rows, ignore_index=True)


def report(d, model_names):
    rows = []
    for season, g in d.groupby("season"):
        base = pd.DataFrame(json.load(open(PROCESSED_DIR / f"projections_{season}_v1.json"))["players"])
        base = base[(~base["market_estimate"]) & (base["adp"] <= 150)][["player_id", "projected_ppr", "adp"]].rename(columns={"projected_ppr": "main_pred_ppr"})
        rows.append(g.merge(base, on="player_id"))
    m = pd.concat(rows)
    rmse = lambda p, a: float(np.sqrt(((p - a) ** 2).mean()))
    cols = ["main", "curve"] + model_names
    column_of = lambda c: "curve" if c == "curve" else f"{c}_pred_ppr"
    print("\nRMSE / top-150 Spearman (mean over seasons) on the draftable rows, by position")
    for position, g in m.groupby("position"):
        cells = []
        for c in cols:
            rho = np.mean([spearmanr(s[column_of(c)], s["actual_ppr"])[0] for _, s in g.groupby("season")])
            cells.append(f"{c} {rmse(g[column_of(c)], g['actual_ppr']):.1f}/{rho:.3f}")
        print(f"  {position}: " + "   ".join(cells))
    print("  all RMSE: " + "   ".join(f"{c} {rmse(m[column_of(c)], m['actual_ppr']):.1f}" for c in cols))


if __name__ == "__main__":
    arg = lambda name, default: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default
    tests = [int(x) for x in arg("--tests", "2019,2020,2021,2022,2023,2024,2025").split(",")]
    names = arg("--models", "plain,adpfeat,resid").split(",")
    d = predictions(tests, names)
    d.to_parquet(PROCESSED_DIR / "adp_residual_oos.parquet")
    report(d, names)
    for name in names:
        write_backtest_files(d, f"{name}_pred_ppr", PROCESSED_DIR / "adpres" / name, f"{name} model on ADP-ranked rows (adp_residual.py)", seasons=tests)
    print(f"\nwrote backtest files under {PROCESSED_DIR / 'adpres'}")
