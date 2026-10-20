import pandas as pd
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.data.pipeline import save

RMSE = {"QB": 78.68, "RB": 62.10, "WR": 54.87, "TE": 39.25}
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
    id = pd.read_parquet(filepath.parent / "raw" / "ids.parquet" )
    adp_table = pd.read_csv(filepath  / "adp_table.csv")

    id = id[id["position"].isin(["QB", "RB", "WR", "TE"])]
    adp_table = normalize_names(adp_table)
    adp_table = add_player_id(adp_table, id)
    adp_table = fix_duplicates(adp_table)
    adp_table = adp_table.dropna(subset=["Underdog"])
    adp_table.to_csv(filepath.parent/"processed"/ "adp_table.csv")
    qb_predictions = add_adp_helper(adp_table, qb_predictions)
    qb_predictions = qb_predictions.dropna(subset=["underdog"])
    rb_predictions = add_adp_helper(adp_table, rb_predictions)
    rb_predictions = rb_predictions.dropna(subset=["underdog"])
    wr_predictions = add_adp_helper(adp_table, wr_predictions)
    wr_predictions = wr_predictions.dropna(subset=["underdog"])
    te_predictions = add_adp_helper(adp_table, te_predictions)
    te_predictions = te_predictions.dropna(subset=["underdog"])
    return qb_predictions, rb_predictions, wr_predictions, te_predictions



def add_adp_helper(adp_table, prediction_df):
    prediction_df = prediction_df.drop(columns=["underdog"], errors="ignore")
    merged_df = prediction_df.merge(adp_table[["player_id", "Underdog"]], on="player_id", how="left")
    merged_df = merged_df.rename(columns={"Underdog" : "underdog"})
    
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

def fix_duplicates(adp_table):
    NAME_TO_ID = {"oronde gadsden": "00-0040189", "kyle williams": "00-0040131", "chris brooks": "00-0038685"}
    overrides = adp_table["merge_name"].map(NAME_TO_ID)
    adp_table["player_id"] = overrides.combine_first(adp_table["player_id"])
    adp_table = adp_table.drop_duplicates()
    return adp_table

def add_player_id(adp_table, id):
    adp_table = adp_table.drop(columns=["player_id"], errors="ignore") # prevents duplicate cols being created on each pipeline run 
    merged_table = adp_table.merge(id[["merge_name", "gsis_id"]], on="merge_name", how="left")
    merged_table = merged_table.rename(columns={"gsis_id" : "player_id"})

    return merged_table


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
    df["value_gap"] = df["underdog"] - df["vor_rank"]
    return df

def compute_tiers(df):
    df['tier'] = 8 - pd.qcut(df['vor'], q=8, labels=False)   
    return df




if __name__ == "__main__":
    qb_predictions, rb_predictions, wr_predictions, te_predictions= load_predictions()
    qb_predictions, rb_predictions, wr_predictions, te_predictions = add_adp(qb_predictions, rb_predictions, wr_predictions, te_predictions)
    save(qb_predictions, "qb_predictions")  #save positional tables for easier debugging
    save(rb_predictions, "rb_predictions")
    save(wr_predictions, "wr_predictions")
    save(te_predictions, "te_predictions")

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
    save(predictions_df, "predictions_table")
    






    


