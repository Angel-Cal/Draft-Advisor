import pandas as pd
import sys
from pathlib import Path
from scipy.stats import spearmanr
import numpy as np
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.data.run_manifest import check_freshness, update_manifest

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

    last_year = pd.read_parquet(PROCESSED_DIR / "training_data.parquet")[["player_id", "season", "fantasy_points_ppr"]]
    oos = oos.merge(last_year.rename(columns={"fantasy_points_ppr": "last_year_ppr"}), on=["player_id", "season"], how="left")
    df = oos.merge(adp[["player_id", "adp"]], on="player_id", how="left")
    df["in_top_adp"] = df["adp"].rank(method="first") <= TOP_N_ADP  # top N by ADP among modeled players
    unranked = df["adp"].isna()
    keep_unranked = (df[unranked].nlargest(N_UNRANKED, "actual_ppr").index
                     .union(df[unranked].nlargest(N_UNRANKED, "oos_pred_ppr").index))
    df = df[~unranked | df.index.isin(keep_unranked)].copy()
    df["adp"] = df["adp"].fillna(adp["adp"].max() + 1)
    return df


def spearman_rows(df, season, scope):
    """One row per position. Pooling positions is not reported: ADP prices positional scarcity, raw PPR does not."""
    seed_cols = [c for c in df.columns if c.startswith("oos_pred_s")]
    rows = []
    for position, group in df.groupby("position"):
        if len(group) < 3:
            continue
        per_seed = [spearmanr(group[c], group["actual_ppr"])[0] for c in seed_cols]
        rows.append({
            "season": season, "scope": scope, "position": position, "n": len(group),
            "model_spearman": np.mean(per_seed), "model_seed_sd": np.std(per_seed),
            "adp_spearman": spearmanr(-group["adp"], group["actual_ppr"])[0],
            "last_year_spearman": spearmanr(group["last_year_ppr"], group["actual_ppr"])[0],
        })
    return rows


if __name__ == "__main__":
    check_freshness(inputs=[PROCESSED_DIR / "training_data.parquet", *(ROOT / "models" / f"{p}_params" for p in ("qb", "rb", "wr", "te"))],
                    outputs=[PROCESSED_DIR / f"season_{s}.parquet" for s in SEASONS], label="out-of-sample predictions", strict=False)
    rows = []
    for season in SEASONS:
        df = load_season(season)
        rows += spearman_rows(df, season, "overall")
        rows += spearman_rows(df[df["in_top_adp"]], season, f"top{TOP_N_ADP}_adp")

    results = pd.DataFrame(rows)
    mean = results.groupby(["scope", "position"], as_index=False)[
        ["n", "model_spearman", "model_seed_sd", "adp_spearman", "last_year_spearman"]].mean()
    mean.insert(0, "season", "mean")
    results = pd.concat([results.astype({"season": str}), mean], ignore_index=True)
    results["model_minus_adp"] = results["model_spearman"] - results["adp_spearman"]
    results["model_minus_last_year"] = results["model_spearman"] - results["last_year_spearman"]

    results.to_csv(PROCESSED_DIR / "benchmark_v1.csv", index=False)
    print(results.round(3).to_string(index=False))
    top = mean[mean["scope"] == f"top{TOP_N_ADP}_adp"].set_index("position")
    update_manifest("benchmark", {"top150_model_spearman": top["model_spearman"].round(3).to_dict(),
                                  "top150_adp_spearman": top["adp_spearman"].round(3).to_dict(),
                                  "top150_last_year_spearman": top["last_year_spearman"].round(3).to_dict()})
