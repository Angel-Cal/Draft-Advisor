import pandas as pd
import sys
from pathlib import Path
from scipy.stats import spearmanr
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
EXTERNAL_DIR = ROOT / "data" / "external"
SEASONS = range(2021, 2026)
TOP_N_ADP = 150
N_UNRANKED = 50


def load_season(season):
    """Model out-of-sample predictions joined to ADP; unranked players tied at last."""
    oos = pd.read_parquet(PROCESSED_DIR / f"season_{season}.parquet")
    adp = pd.read_csv(EXTERNAL_DIR / f"adp_{season}.csv")

    df = oos.merge(adp[["player_id", "adp"]], on="player_id", how="left")
    df["in_top_adp"] = df["adp"].rank(method="first") <= TOP_N_ADP  # top N by ADP among modeled players
    unranked = df["adp"].isna()
    keep_unranked = (df[unranked].nlargest(N_UNRANKED, "actual_ppr").index
                     .union(df[unranked].nlargest(N_UNRANKED, "oos_pred_ppr").index))
    df = df[~unranked | df.index.isin(keep_unranked)].copy()
    df["adp"] = df["adp"].fillna(adp["adp"].max() + 1)
    return df


def spearman_rows(df, season, scope):
    rows = []
    for position, group in [("ALL", df)] + list(df.groupby("position")):
        if len(group) < 3:
            continue
        rows.append({
            "season": season, "scope": scope, "position": position, "n": len(group),
            "model_spearman": spearmanr(group["oos_pred_ppr"], group["actual_ppr"])[0],
            "adp_spearman": spearmanr(-group["adp"], group["actual_ppr"])[0],
        })
    return rows


if __name__ == "__main__":
    rows = []
    for season in SEASONS:
        df = load_season(season)
        rows += spearman_rows(df, season, "overall")
        rows += spearman_rows(df[df["in_top_adp"]], season, f"top{TOP_N_ADP}_adp")

    results = pd.DataFrame(rows)
    mean = results.groupby(["scope", "position"], as_index=False)[["n", "model_spearman", "adp_spearman"]].mean()
    mean.insert(0, "season", "mean")
    results = pd.concat([results.astype({"season": str}), mean], ignore_index=True)
    results["model_minus_adp"] = results["model_spearman"] - results["adp_spearman"]

    results.to_csv(PROCESSED_DIR / "benchmark_v1.csv", index=False)
    print(results.round(3).to_string(index=False))
