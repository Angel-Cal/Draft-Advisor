import pandas as pd
import nflreadpy as nflread
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.features.build_features import build_features, build_prediction_features
from src.features.team_context import build_team_context, add_rb_features, TEAM_MAP


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
    end_roster["team"] = end_roster["team"].replace(TEAM_MAP)  # legacy codes (OAK, SD, ARZ...) -> current
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

def load_totals(seasons=range(2014, 2026)):
    schedules = nflread.load_schedules(list(seasons)).to_pandas()
    schedules = schedules[schedules['game_type'] == 'REG']
    schedules['home_implied_total'] = (schedules['total_line'] / 2 + schedules['spread_line'] / 2)
    schedules['away_implied_total'] = (schedules['total_line']/2 - schedules['spread_line']/2)

    home_df = schedules[['home_team', 'season', 'home_implied_total']].copy()
    home_df = home_df.rename(columns= {'home_team' : 'team', 'home_implied_total' : "implied_total"})

    away_df = schedules[['away_team', 'season', 'away_implied_total']].copy()
    away_df = away_df.rename(columns= {'away_team' : 'team', 'away_implied_total' : "implied_total"})

    totals_df = pd.concat([home_df, away_df])
    totals_df['team'] = totals_df['team'].replace(TEAM_MAP)
    totals_df = totals_df.groupby(['team', 'season']).mean().reset_index()
    return totals_df






def advance_to_prediction_season(prediction_df, roster, totals, season=2026):
    """Prediction rows hold last season's age, experience and team total; swap in the prediction season's.

    Players missing from the new roster (retired, unsigned) get age/experience advanced by one and no implied total.
    """
    r = (roster[roster["position"].isin(["QB", "RB", "WR", "TE"])].sort_values("week")
         .groupby("gsis_id", as_index=False).first().rename(columns={"gsis_id": "player_id"}))
    r["age_new"] = (pd.Timestamp(f"{season}-09-01") - pd.to_datetime(r["birth_date"])).dt.days // 365
    r["team"] = r["team"].replace(TEAM_MAP)
    r = r.merge(totals[totals["season"] == season][["team", "implied_total"]], on="team", how="left")
    r = r[["player_id", "age_new", "years_exp", "implied_total"]].rename(
        columns={"years_exp": "years_exp_new", "implied_total": "implied_total_new"})

    df = prediction_df.merge(r, on="player_id", how="left")
    df["age"] = df["age_new"].fillna(df["age"] + 1)
    df["years_exp"] = df["years_exp_new"].fillna(df["years_exp"] + 1)
    df["implied_total"] = df["implied_total_new"]
    return df.drop(columns=["age_new", "years_exp_new", "implied_total_new"])


if __name__ == "__main__":
    seasonal, roster, pbp, id, snaps = load_data()
    df = clean_data(roster, seasonal)
    prediction_df = build_prediction_features(df, pbp, id, snaps)

    df = build_features(df, pbp, id, snaps)

    roster_2026 = pd.read_parquet(RAW_DIR / "roster_2026.parquet")
    prediction_df = advance_to_prediction_season(prediction_df, roster_2026, load_totals([2026]))
    context = build_team_context(seasonal, pd.concat([roster, roster_2026], ignore_index=True))
    df = add_rb_features(df, context)
    prediction_df = add_rb_features(prediction_df, context, season_offset=1)
    save(df, "training_data")
    save(prediction_df, "prediction_data")
    print(f"Saved {len(df)} rows to {PROCESSED_DIR}")


    


    








