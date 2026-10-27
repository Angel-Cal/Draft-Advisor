"""Is player-level risk predictable? Tests whether prior-season weekly volatility predicts how far a season lands from the projection.

Every draftable player (top N by ADP, at least MIN_GAMES played the season before) gets prior-season weekly features. Targets are the
absolute miss |actual - projection|, its downside (projection - actual) and upside (actual - projection) parts, and the weekly spread
inside the season. Each is checked as a partial Spearman correlation after removing position, the projection level and games played.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
EXTERNAL_DIR = ROOT / "data" / "external"
SEASONS = range(2021, 2026)
TOP_N_ADP = 150
MIN_GAMES = 6
BOOM, BUST = 20.0, 5.0
FEATURES = ["sd_prev", "cv_prev", "boom_prev", "bust_prev", "missed_prev"]
TARGETS = ["abs_miss", "downside", "upside", "sd_now"]


def weekly_features(weekly, season, suffix):
    """Per-player weekly PPR summary for one regular season (games played only)."""
    w = weekly[(weekly["season"] == season) & (weekly["season_type"] == "REG")].dropna(subset=["fantasy_points_ppr"])
    grouped = w.groupby("player_id")["fantasy_points_ppr"]
    out = pd.DataFrame({f"games_{suffix}": grouped.size(), f"ppg_{suffix}": grouped.mean(), f"sd_{suffix}": grouped.std(),
                        f"boom_{suffix}": grouped.apply(lambda x: (x >= BOOM).mean()), f"bust_{suffix}": grouped.apply(lambda x: (x <= BUST).mean())})
    out[f"cv_{suffix}"] = out[f"sd_{suffix}"] / out[f"ppg_{suffix}"].clip(lower=1)
    return out.reset_index()


def load_season(season, weekly):
    """Draftable veterans for one season with prior-season features and the realised misses."""
    oos = pd.read_parquet(PROCESSED_DIR / f"season_{season}.parquet")
    adp = pd.read_csv(EXTERNAL_DIR / f"adp_{season}.csv")[["player_id", "adp"]]
    df = oos.merge(adp, on="player_id").nsmallest(TOP_N_ADP, "adp")
    df = df.merge(weekly_features(weekly, season - 1, "prev"), on="player_id").merge(weekly_features(weekly, season, "now")[["player_id", "sd_now", "games_now"]], on="player_id", how="left")
    df = df[df["games_prev"] >= MIN_GAMES].copy()
    df["missed_prev"] = 17 - df["games_prev"]
    miss = df["actual_ppr"] - df["oos_pred_ppr"]
    df["abs_miss"], df["downside"], df["upside"] = miss.abs(), (-miss).clip(lower=0), miss.clip(lower=0)
    df.loc[df["games_now"] < MIN_GAMES, "sd_now"] = np.nan
    return df


def residualize(values, controls):
    """Residuals of an ordinary least squares fit of rank(values) on the controls."""
    y = pd.Series(values).rank().to_numpy()
    X = np.column_stack([np.ones(len(y)), controls])
    return y - X @ np.linalg.lstsq(X, y, rcond=None)[0]


def partial_spearman(df, feature, target):
    """Correlation of feature and target after removing the projection level and prior games (rank-based)."""
    d = df.dropna(subset=[feature, target])
    if len(d) < 15:
        return np.nan, len(d)
    controls = np.column_stack([d["oos_pred_ppr"].rank(), d["games_prev"].rank()])
    return np.corrcoef(residualize(d[feature], controls), residualize(d[target], controls))[0, 1], len(d)


if __name__ == "__main__":
    weekly = pd.read_parquet(ROOT / "data" / "raw" / "weekly_20_25.parquet", columns=["player_id", "season", "week", "season_type", "fantasy_points_ppr"])
    frames = [load_season(s, weekly).assign(season=s) for s in SEASONS]
    data = pd.concat(frames, ignore_index=True)
    rows = []
    for position, group in data.groupby("position"):
        for feature in FEATURES:
            for target in TARGETS:
                r, n = partial_spearman(group, feature, target)
                per_season = [partial_spearman(group[group["season"] == s], feature, target)[0] for s in SEASONS]
                rows.append({"position": position, "feature": feature, "target": target, "n": n, "partial_r": r,
                             "seasons_same_sign": int(sum(np.sign(x) == np.sign(r) for x in per_season if not np.isnan(x))), "seasons": int(sum(not np.isnan(x) for x in per_season))})
    results = pd.DataFrame(rows)
    results.to_csv(PROCESSED_DIR / "risk_predictability.csv", index=False)
    print(f"{len(data)} player-seasons, {data['season'].nunique()} seasons, top {TOP_N_ADP} by ADP, >= {MIN_GAMES} prior games")
    for target in TARGETS:
        print(f"\n{target}: partial Spearman with prior-season feature (same-sign seasons in brackets)")
        signs =results[results["target"] == target].assign(cell=lambda x: x["partial_r"].round(2).astype(str) + " (" + x["seasons_same_sign"].astype(str) + "/" + x["seasons"].astype(str) + ")").pivot(index="feature", columns="position", values="cell")
        print(signs.to_string())
