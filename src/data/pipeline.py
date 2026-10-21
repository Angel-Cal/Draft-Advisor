import pandas as pd
import nflreadpy as nflread
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.features.build_features import build_features, build_prediction_features


RAW_DIR = Path(__file__).parent.parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent.parent / "data" / "processed"

def load_data():
    seasonal = pd.read_parquet(RAW_DIR /'seasonal_20_25.parquet')
    pbp = pd.read_parquet(RAW_DIR/'pbp_20_25.parquet')
    roster = pd.read_parquet(RAW_DIR /'seasonal_roster_20_25.parquet')
    id = pd.read_parquet(RAW_DIR/'ids.parquet')
    snaps = pd.read_parquet(RAW_DIR/'snap_counts_20_25.parquet')

    return seasonal, roster, pbp, id, snaps

def load_predictions():
    adp_table = pd.read_csv(Path(__file__).parent.parent.parent / "data" / "external" / "4for4-adp-table.csv")
    qb_predictions = pd.read_parquet(PROCESSED_DIR / "qb_predictions.parquet")
    rb_predictions = pd.read_parquet(PROCESSED_DIR / "rb_predictions.parquet")
    wr_predictions = pd.read_parquet(PROCESSED_DIR / "wr_predictions.parquet")
    te_predictions = pd.read_parquet(PROCESSED_DIR / "te_predictions.parquet")

    return adp_table, qb_predictions, rb_predictions, wr_predictions, te_predictions

def clean_data(roster, season):
    ROSTER_KEEP_COLS = [
        "gsis_id",
        "season",
        "team",
        "position",
        "birth_date",
        "height",
        "weight",
        "years_exp",
        "college",
        "rookie_year",
        "draft_number",
        "draft_club",
    ]
    SEASON_KEEP_COLS = [
        # Keys
        "player_id", "season", "season_type", "games", "player_name",

        # Passing
        "completions", "attempts", "passing_yards", "passing_tds",
        "passing_interceptions", "sacks_suffered", "passing_first_downs", "passing_epa",
        "passing_cpoe", "passing_air_yards",

        # Rushing
        "carries", "rushing_yards", "rushing_tds",
        "rushing_first_downs", "rushing_epa",

        # Receiving
        "targets", "receptions", "receiving_yards", "receiving_tds",
        "receiving_first_downs", "receiving_epa",
        "receiving_air_yards", "receiving_yards_after_catch",

        # Efficiency
        "pacr", "racr",

        # Opportunity / role
        "target_share", "air_yards_share", "wopr",

        # Fantasy outputs
        "fantasy_points", "fantasy_points_ppr"
    ]

    filtered_roster = roster[roster["position"].isin(["QB", "RB", "WR", "TE"])] 
    season_filtered = season[SEASON_KEEP_COLS]
    end_roster = (
        filtered_roster[ROSTER_KEEP_COLS + ["week"]]
        .sort_values(["season", "week"])
        .groupby(["gsis_id", "season"], as_index=False)
        .last()
        .drop(columns=["week"], errors="ignore")
        .rename(columns={"gsis_id": "player_id"})
        )
    end_roster["age"] = end_roster.apply(
        lambda row: (pd.Timestamp(f"{row['season']}-09-01") - pd.Timestamp(row["birth_date"])).days // 365, axis=1
    )
    end_roster = end_roster.drop(columns=["birth_date"])
    assert end_roster.groupby(["player_id", "season"]).size().max() == 1


    merged_df = season_filtered.merge(end_roster, on=["player_id", "season"], how = "inner")
    print(f"After roster merge: {len(merged_df)}")
    merged_df = merged_df[merged_df['games'] >= 4]
    print(f"After games filter: {len(merged_df)}")
    merged_df['draft_number'] = merged_df['draft_number'].replace(['nan', 'None'], '300').astype(float)
    totals_df = load_totals()
    merged_df = merged_df.merge(totals_df, on =['team', 'season'])
    print(f"After totals merge: {len(merged_df)}")

    team_stats = (season.groupby(['recent_team', 'season'])
        .agg(team_targets=('targets', 'sum'),
             team_air_yards=('receiving_air_yards', 'sum'),
             team_games=('games', 'max'))
        .reset_index()
        .rename(columns={'recent_team': 'team'}))
    merged_df = merged_df.merge(team_stats, on=['team', 'season'], how='left')
    merged_df['target_share'] = (merged_df['targets'] / merged_df['games']) / (merged_df['team_targets'] / merged_df['team_games'])
    merged_df['air_yards_share'] = (merged_df['receiving_air_yards'] / merged_df['games']) / (merged_df['team_air_yards'] / merged_df['team_games'])
    merged_df['wopr'] = 1.5 * merged_df['target_share'] + 0.7 * merged_df['air_yards_share']
    merged_df = merged_df.drop(columns=['team_targets', 'team_air_yards', 'team_games'])

    return merged_df

def save_data_as_parquet(df, file_name):
    filepath = PROCESSED_DIR / f'{file_name}.parquet'
    df.to_parquet(filepath)

def save_data_as_csv(df, file_name):
    filepath = PROCESSED_DIR / f'{file_name}.csv'
    df.to_csv(filepath, index='false')

def save(df, filename):
    save_data_as_csv(df, filename)
    save_data_as_parquet(df, filename)

def load_totals():
    schedules = nflread.load_schedules(list(range(2015, 2026))).to_pandas()
    schedules = schedules[schedules['game_type'] == 'REG']
    schedules['home_implied_total'] = (schedules['total_line'] / 2 + schedules['spread_line'] / 2)
    schedules['away_implied_total'] = (schedules['total_line']/2 - schedules['spread_line']/2)

    home_df = schedules[['home_team', 'season', 'home_implied_total']].copy()
    home_df = home_df.rename(columns= {'home_team' : 'team', 'home_implied_total' : "implied_total"})

    away_df = schedules[['away_team', 'season', 'away_implied_total']].copy()
    away_df = away_df.rename(columns= {'away_team' : 'team', 'away_implied_total' : "implied_total"})

    totals_df = pd.concat([home_df, away_df]).groupby(['team', 'season']).mean().reset_index()
    return totals_df






if __name__ == "__main__":
    seasonal, roster, pbp, id, snaps = load_data()
    df = clean_data(roster, seasonal)
    prediction_df = build_prediction_features(df, pbp, id, snaps)

    df = build_features(df, pbp, id, snaps)
    save(df, "training_data")
    save(prediction_df, "prediction_data")
    print(f"Saved {len(df)} rows to {PROCESSED_DIR}")


    


    








