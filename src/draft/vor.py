import pandas as pd
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.data.pipeline import save
from src.data.validate import check_advisor_table
from src.draft.market_fallback import load_history, fit_position_curves, market_projections

# pooled walk-forward RMSE, test seasons 2021-2025, mean over 5 model seeds (tests/test_data_integrity.py keeps this honest)
RMSE = {"QB": 84.28, "RB": 62.24, "WR": 56.00, "TE": 39.56}
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
    adp_table = pd.read_csv(filepath.parent / "external" / "4for4-adp-table.csv")  # source of truth; adp_table.csv is output

    id = id[id["position"].isin(["QB", "RB", "WR", "TE"])]
    adp_table = normalize_names(adp_table)
    adp_table = add_player_id(adp_table, id)
    adp_table = fix_duplicates(adp_table)
    adp_table = adp_table.dropna(subset=["Underdog"])
    adp_table = adp_table.sort_values("player_id", na_position="last").drop_duplicates(["Player", "Position"])
    adp_table = adp_table.sort_values("ADP").reset_index(drop=True)
    adp_table.to_csv(filepath.parent/"processed"/ "adp_table.csv", index=False)
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
    """Match on (name, position) with one player per name+position; rows without a gsis_id are never matched.

    Falls back to a name-only match for active players when the sources disagree on position (e.g. Taysom Hill).
    """
    adp_table = adp_table.drop(columns=["player_id"], errors="ignore") # prevents duplicate cols being created on each pipeline run
    adp_table["pos"] = adp_table["Position"].str[:2]
    ids = id.dropna(subset=["gsis_id"]).sort_values("draft_year", ascending=False)  # newest player wins a name clash
    by_position = ids.drop_duplicates(["merge_name", "position"]).rename(columns={"position": "pos", "gsis_id": "player_id"})
    merged_table = adp_table.merge(by_position[["merge_name", "pos", "player_id"]], on=["merge_name", "pos"], how="left")

    active = ids[ids["db_season"] >= ids["db_season"].max() - 1]
    unique_active = active.drop_duplicates("merge_name", keep=False).set_index("merge_name")["gsis_id"]
    merged_table["player_id"] = merged_table["player_id"].fillna(merged_table["merge_name"].map(unique_active))
    return merged_table.drop(columns="pos")


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
    






    


