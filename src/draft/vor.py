import pandas as pd
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.data.pipeline import save
from src.data.validate import check_advisor_table
from src.draft.market_fallback import load_history, fit_position_curves, market_projections

# pooled walk-forward RMSE, test seasons 2021-2025, mean over 5 model seeds (tests/test_data_integrity.py keeps this honest)
RMSE = {"QB": 84.28, "RB": 58.86, "WR": 53.48, "TE": 38.69}
REPLACEMENT_RANK = {"QB": 12, "RB": 29, "WR": 41, "TE": 12}
filepath = Path(__file__).parent.parent.parent / "data" / "processed"


def load_predictions():
    qb_predictions = pd.read_parquet(filepath / "qb_predictions.parquet")
    qb_predictions['position'] = 'QB'
    rb_predictions = pd.read_parquet(filepath / "rb_predictions.parquet")
    rb_predictions['position'] = 'RB'
    wr_predictions = pd.read_parquet(filepath / "wr_predictions.parquet")
    wr_predictions['position'] = 'WR'
    te_predictions = pd.read_parquet(filepath / "te_predictions.parquet")
    te_predictions['position'] = 'TE'
    return qb_predictions, rb_predictions, wr_predictions, te_predictions

def add_adp(qb_predictions, rb_predictions, wr_predictions, te_predictions):
    """Attach FantasyPros ADP (data/external/adp_<season>.csv, written by adp_scraper.py) and write processed/adp_table.csv."""
    season = int(pd.read_parquet(filepath / "prediction_data.parquet", columns=["season"])["season"].max()) + 1      # same rule export_projections uses
    adp = pd.read_csv(filepath.parent / "external" / f"adp_{season}.csv")      # source of truth; adp_table.csv is output
    adp_table = pd.DataFrame({"Player": adp["name"], "Position": adp["position"], "ADP": adp["adp"],
                              "Team": adp["team"], "player_id": adp["player_id"]})
    adp_table = normalize_names(adp_table)
    adp_table = adp_table.dropna(subset=["ADP"]).drop_duplicates("player_id")
    adp_table = adp_table.sort_values("ADP").reset_index(drop=True)
    adp_table.to_csv(filepath.parent/"processed"/ "adp_table.csv", index=False)
    qb_predictions = add_adp_helper(adp_table, qb_predictions)
    qb_predictions = qb_predictions.dropna(subset=["adp"])
    rb_predictions = add_adp_helper(adp_table, rb_predictions)
    rb_predictions = rb_predictions.dropna(subset=["adp"])
    wr_predictions = add_adp_helper(adp_table, wr_predictions)
    wr_predictions = wr_predictions.dropna(subset=["adp"])
    te_predictions = add_adp_helper(adp_table, te_predictions)
    te_predictions = te_predictions.dropna(subset=["adp"])
    return qb_predictions, rb_predictions, wr_predictions, te_predictions



def add_adp_helper(adp_table, prediction_df):
    prediction_df = prediction_df.drop(columns=["adp"], errors="ignore")
    merged_df = prediction_df.merge(adp_table[["player_id", "ADP"]], on="player_id", how="left")
    merged_df = merged_df.rename(columns={"ADP" : "adp"})
    
    return merged_df

def normalize_names(df):
    df["merge_name"] = (df["Player"].str.lower()
                      .str.replace(".", "", regex=False)
                      .str.replace("'", "", regex=False)
                      .str.replace("iii", "")
                      .str.replace("iI", "")
                      .str.replace("jr", "")
                      .str.strip())
    return df

def compute_vor(df, baseline_pos):
    df = df.sort_values(by="projected_ppr", ascending=False).reset_index(drop=True)
    df['vor'] = (df["projected_ppr"] - df["projected_ppr"]
                             .iloc[baseline_pos])
                             
    return df

def compute_ceiling_floor(df, rmse):
    mask = (df["games"] < 13) & (df["games_delta"] < -5)
    scaled = df["projected_ppr"] * (17/df["games"])
    capped = np.minimum(scaled, df["projected_ppr"] * 2)
    rmse_ceiling = df["projected_ppr"] + rmse

    df["ceiling"] = np.where(mask, np.maximum(capped, rmse_ceiling), rmse_ceiling)
    df["floor"] = (df["projected_ppr"] - rmse).clip(lower=0)
    df["availability_flag"] = mask

    return df

def compute_value_gap(df):
    df = df.sort_values(by="vor", ascending = False).reset_index(drop=True)
    df["vor_rank"] = df["vor"].rank(ascending=False, method="min")
    df["value_gap"] = df["adp"] - df["vor_rank"]
    return df

def compute_tiers(df):
    df['tier'] = 8 - pd.qcut(df['vor'], q=8, labels=False)   
    return df




if __name__ == "__main__":
    qb_predictions, rb_predictions, wr_predictions, te_predictions= load_predictions()
    qb_predictions, rb_predictions, wr_predictions, te_predictions = add_adp(qb_predictions, rb_predictions, wr_predictions, te_predictions)
    save(qb_predictions, "qb_with_adp")  #positional debugging tables; predict.py's *_predictions files stay untouched
    save(rb_predictions, "rb_with_adp")
    save(wr_predictions, "wr_with_adp")
    save(te_predictions, "te_with_adp")

    # players the model cannot score (rookies, no prior NFL season) get an ADP-derived projection
    adp_table = pd.read_csv(filepath / "adp_table.csv")
    modeled_ids = set(pd.concat([qb_predictions, rb_predictions, wr_predictions, te_predictions])["player_id"])
    fallback = market_projections(adp_table, modeled_ids, fit_position_curves(load_history()))
    frames = []
    for position, frame in zip(["QB", "RB", "WR", "TE"], [qb_predictions, rb_predictions, wr_predictions, te_predictions]):
        frames.append(pd.concat([frame.assign(market_estimate=False), fallback[fallback["position"] == position]],
                                ignore_index=True))
    qb_predictions, rb_predictions, wr_predictions, te_predictions = frames

    qb_predictions = compute_vor(qb_predictions, REPLACEMENT_RANK["QB"])
    rb_predictions = compute_vor(rb_predictions, REPLACEMENT_RANK["RB"])
    wr_predictions = compute_vor(wr_predictions, REPLACEMENT_RANK["WR"])
    te_predictions = compute_vor(te_predictions, REPLACEMENT_RANK["TE"])

    qb_predictions = compute_ceiling_floor(qb_predictions, RMSE["QB"])
    rb_predictions = compute_ceiling_floor(rb_predictions, RMSE["RB"])
    wr_predictions = compute_ceiling_floor(wr_predictions, RMSE["WR"])
    te_predictions = compute_ceiling_floor(te_predictions, RMSE["TE"])

    predictions_df = pd.concat([qb_predictions, rb_predictions, wr_predictions, te_predictions])
    predictions_df = compute_value_gap(predictions_df)
    predictions_df = compute_tiers(predictions_df)
    check_advisor_table(predictions_df)
    save(predictions_df, "predictions_table")
    






    


