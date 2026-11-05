"""The live advisor table: next season's model projections with FantasyPros ADP attached, plus ADP-curve rows for players the model cannot score.

Writes pipeline/adp_table.csv and pipeline/predictions_table.parquet, which export_projections.py turns into the live projections file.
VOR here only orders the table (the export's pool and tie-breaks follow that order); the C# side values the pool itself.
"""
import pandas as pd
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.paths import PIPELINE, ROOT
from src.data.pipeline import save
from src.data.validate import check_advisor_table
from src.data.market_fallback import load_history, fit_position_curves, market_projections

POSITIONS = ["QB", "RB", "WR", "TE"]
REPLACEMENT_RANK = {"QB": 12, "RB": 29, "WR": 41, "TE": 12}


def load_predictions():
    """The per-position projections predict.py wrote, as {position: frame} with a position column."""
    return {position: pd.read_parquet(PIPELINE / f"{position.lower()}_predictions.parquet").assign(position=position) for position in POSITIONS}


def load_adp_table():
    """FantasyPros ADP for the prediction season (data/external/adp_<season>.csv, written by adp_scraper.py), one row per player, by ADP; also written to pipeline/adp_table.csv."""
    season = int(pd.read_parquet(PIPELINE / "prediction_data.parquet", columns=["season"])["season"].max()) + 1      # same rule export_projections uses
    adp = pd.read_csv(ROOT / "data" / "external" / f"adp_{season}.csv")      # source of truth; adp_table.csv is output
    adp_table = pd.DataFrame({"Player": adp["name"], "Position": adp["position"], "ADP": adp["adp"],
                              "Team": adp["team"], "player_id": adp["player_id"]})
    adp_table = normalize_names(adp_table)
    adp_table = adp_table.dropna(subset=["ADP"]).drop_duplicates("player_id")
    adp_table = adp_table.sort_values("ADP").reset_index(drop=True)
    adp_table.to_csv(PIPELINE / "adp_table.csv", index=False)
    return adp_table


def add_adp(adp_table, prediction_df):
    """The predictions with an adp column; players without an ADP are dropped (the draft pool is the ADP-ranked players)."""
    merged = prediction_df.drop(columns=["adp"], errors="ignore").merge(adp_table[["player_id", "ADP"]], on="player_id", how="left")
    return merged.rename(columns={"ADP": "adp"}).dropna(subset=["adp"])


def normalize_names(df):
    """A merge_name column: the Player name lower-cased, without periods, apostrophes and suffixes."""
    df["merge_name"] = (df["Player"].str.lower()
                      .str.replace(".", "", regex=False)
                      .str.replace("'", "", regex=False)
                      .str.replace("iii", "")
                      .str.replace("iI", "")
                      .str.replace("jr", "")
                      .str.strip())
    return df


def compute_vor(df, baseline_pos):
    """Sorted by projection, with vor = projection minus the projection at row baseline_pos (the replacement player)."""
    df = df.sort_values(by="projected_ppr", ascending=False).reset_index(drop=True)
    df['vor'] = (df["projected_ppr"] - df["projected_ppr"]
                             .iloc[baseline_pos])
    return df


def rank_by_vor(df):
    """The table ordered by VOR, best first (the order export_projections' pool and ADP tie-breaks inherit)."""
    return df.sort_values(by="vor", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    adp_table = load_adp_table()
    predictions = {position: add_adp(adp_table, frame) for position, frame in load_predictions().items()}

    # players the model cannot score (rookies, no prior NFL season) get an ADP-derived projection
    adp_table = pd.read_csv(PIPELINE / "adp_table.csv")
    modeled_ids = set(pd.concat(predictions.values())["player_id"])
    fallback = market_projections(adp_table, modeled_ids, fit_position_curves(load_history()))
    frames = [compute_vor(pd.concat([frame.assign(market_estimate=False), fallback[fallback["position"] == position]], ignore_index=True),
                          REPLACEMENT_RANK[position])
              for position, frame in predictions.items()]

    predictions_df = rank_by_vor(pd.concat(frames))
    check_advisor_table(predictions_df)
    save(predictions_df, "predictions_table")
