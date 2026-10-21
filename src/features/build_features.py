import pandas as pd
from pathlib import Path
import numpy as np
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
RAW_DIR = Path(__file__).parent.parent.parent / "data" / "raw"



DELTA_SHIFT_COLS = [
        "games",
        "attempts",
        "carries",
        "targets",
        "completions_pg",
        "attempts_pg",
        "passing_yards_pg",
        "passing_tds_pg",
        "passing_interceptions_pg",
        "sacks_suffered_pg",
        "passing_first_downs_pg",    
        "carries_pg",
        "rushing_yards_pg",
        "rushing_tds_pg",
        "rushing_first_downs_pg",
        "targets_pg",
        "receptions_pg",
        "receiving_yards_pg",
        "receiving_tds_pg",
        "receiving_first_downs_pg",
        "target_share",
        "air_yards_share",
        "wopr",
        "passing_cpoe",
        "passing_air_yards_pg",
        "receiving_air_yards_pg",
        "receiving_yards_after_catch_pg",
    ]


def add_per_game(df):
    PER_GAME_COLS = [
    # Passing volume
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "sacks_suffered",
    "passing_first_downs",

    # Rushing volume
    "carries",
    "rushing_yards",
    "rushing_tds",
    "rushing_first_downs",

    # Receiving volume
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "receiving_first_downs",
    "receiving_air_yards",
    "receiving_yards_after_catch",

    # Passing volume
    "passing_air_yards",
]

    for col in PER_GAME_COLS:
        df[f"{col}_pg"] = df[col]/df["games"]
    df.loc[df["games"] ==0, [f"{c}_pg" for c in PER_GAME_COLS]]= 0
    return df

def add_lag(df):
    LAG_COLS = [
    # total volume features
    "games",
    "attempts",
    "carries",
    "targets",


    # Per-game volume features
    "completions_pg",
    "attempts_pg",
    "passing_yards_pg",
    "passing_tds_pg",
    "passing_interceptions_pg",
    "sacks_suffered_pg",
    "passing_first_downs_pg",

    "carries_pg",
    "rushing_yards_pg",
    "rushing_tds_pg",
    "rushing_first_downs_pg",

    "targets_pg",
    "receptions_pg",
    "receiving_yards_pg",
    "receiving_tds_pg",
    "receiving_first_downs_pg",

    # EPA & efficiency (RAW, NOT per-game)
    "passing_epa",
    "rushing_epa",
    "receiving_epa",
    "pacr",
    "racr",
    "passing_cpoe",

    # Air yards & YAC per game
    "passing_air_yards_pg",
    "receiving_air_yards_pg",
    "receiving_yards_after_catch_pg",


    # Opportunity / role shares
    "target_share",
    "air_yards_share",
    "wopr",


    # Prior fantasy output (RAW totals)
    "fantasy_points",
    "fantasy_points_ppr",

    "late_target_pct",
    "late_snap_pct"
]
    
    REQUIRED_LAG_COLS = [
        "games", "attempts", "carries", "targets",
        "carries_pg", "rushing_yards_pg", "rushing_tds_pg", "rushing_first_downs_pg",
        "targets_pg", "receptions_pg", "receiving_yards_pg", "receiving_tds_pg",
        "receiving_first_downs_pg",
        "fantasy_points", "fantasy_points_ppr",
        "late_target_pct", "late_snap_pct"
    ]

    df["target_ppr"] = df["fantasy_points_ppr"]
    delta_df = df.copy()
    delta_df[DELTA_SHIFT_COLS] = (df.groupby("player_id")[DELTA_SHIFT_COLS].shift(2))
    df[LAG_COLS] = (df.groupby("player_id")[LAG_COLS].shift(1))
    df = df.dropna(subset=REQUIRED_LAG_COLS)
    return df, delta_df

def add_surge_features(df, pbp, id, snaps):
    # Compute target pct
    pass_plays = pbp[pbp['receiver_player_id'].notna()]
    full_targets = (pass_plays
        .groupby(['receiver_player_id', 'season'])
        .size()
        .reset_index(name='full_targets'))
    full_targets = full_targets[full_targets['full_targets'] >= 10]
    late_targets = (pass_plays[pass_plays['week'] >= 13]
        .groupby(['receiver_player_id', 'season'])
        .size()
        .reset_index(name='late_targets'))
    target_surge = full_targets.merge(late_targets, on=['receiver_player_id', 'season'], how='left')
    target_surge['late_targets'] = target_surge['late_targets'].fillna(0)
    target_surge['late_target_pct'] = target_surge['late_targets'] / target_surge['full_targets']
    target_surge = target_surge.rename(columns={'receiver_player_id': 'player_id'})

    # Compute snap pct
    id_lookup = id[['gsis_id', 'pfr_id']].dropna(subset=['gsis_id', 'pfr_id']).drop_duplicates()
    snaps = snaps.merge(id_lookup, left_on='pfr_player_id', right_on='pfr_id', how='left')
    snaps = snaps.dropna(subset=['gsis_id'])
    late_snaps = (snaps[snaps['week'] >= 13]
        .groupby(['gsis_id', 'season'])['offense_snaps']
        .sum()
        .reset_index(name='late_snaps'))
    full_snaps = (snaps
        .groupby(['gsis_id', 'season'])['offense_snaps']
        .sum()
        .reset_index(name='full_snaps'))
    full_snaps = full_snaps[full_snaps['full_snaps'] > 0]
    snap_surge = full_snaps.merge(late_snaps, on=['gsis_id', 'season'], how='left')
    snap_surge['late_snaps'] = snap_surge['late_snaps'].fillna(0)
    snap_surge['late_snap_pct'] = snap_surge['late_snaps'] / snap_surge['full_snaps']
    snap_surge = snap_surge.rename(columns={'gsis_id': 'player_id'})

    df = df.merge(target_surge[['player_id', 'season', 'late_target_pct']], on=['player_id', 'season'], how='left')
    df = df.merge(snap_surge[['player_id', 'season', 'late_snap_pct']], on=['player_id', 'season'], how='left')
    df[['late_target_pct', 'late_snap_pct']] = df[['late_target_pct', 'late_snap_pct']].fillna(0.35)
    return df

def compute_deltas(df, delta_df):
    for col in DELTA_SHIFT_COLS:
        df[f"{col}_delta"] = df[col] - delta_df[col]
    delta_cols = [f"{col}_delta" for col in DELTA_SHIFT_COLS]
    df[delta_cols] = df[delta_cols].fillna(0)
    return df
 
def add_injury_flag(df):
    games_per_season = df.groupby(["player_id", "season"])["games"].sum().reset_index()
    season_counts = games_per_season.groupby("player_id")["season"].nunique()
    valid_players = season_counts[season_counts >= 2].index

    games_per_season = games_per_season[games_per_season["player_id"].isin(valid_players)]
    avg_games = games_per_season.groupby("player_id")["games"].mean().reset_index(name="avg_games_played")

    return avg_games[["player_id", "avg_games_played"]].assign(
        injury_flag=avg_games["avg_games_played"] < 15
        )[["player_id", "injury_flag"]]

def remove_cols(df):
    DROP_COLS = [
        # Passing outcomes
        "passing_yards",
        "passing_tds",
        "passing_interceptions",
        "sacks_suffered",
        "passing_first_downs",

        # Rushing outcomes
        "rushing_yards",
        "rushing_tds",
        "rushing_first_downs",

        # Receiving outcomes
        "receiving_yards",
        "receiving_tds",
        "receiving_first_downs",
        "receptions",
        "receiving_air_yards",
        "receiving_yards_after_catch",
        "passing_air_yards",

        # General outcome totals
        "completions",
        
        # Unecessary categoricals
        "team",
        "college",
        "draft_club",
        "season_type",
    ]
    df = df.drop(columns = DROP_COLS)
    return df

def convert_categoricals(df):
    df['position'] = df['position'].astype('category')
    return df

    

def build_features(df, pbp, id, snaps):
    df = df.sort_values(['player_id', 'season'])
    df = add_per_game(df)
    df = convert_categoricals(df)
    df = add_surge_features(df, pbp, id, snaps)
    df, delta_df = add_lag(df)
    df = compute_deltas(df, delta_df)
    df = remove_cols(df)
    df = df.drop(columns=['player_id', 'player_name'])
    return df

def build_prediction_features(df, pbp, id, snaps):
    injury_flags = add_injury_flag(df)

    df_recent = df[df['season'].isin([2024, 2025])].copy()
    df_recent = df_recent.sort_values(['player_id', 'season'])
    df_recent = add_per_game(df_recent)
    df_recent = convert_categoricals(df_recent)

    delta_df = df_recent.copy()
    delta_df[DELTA_SHIFT_COLS] = df_recent.groupby('player_id')[DELTA_SHIFT_COLS].shift(1)

    df_2025 = df_recent[df_recent['season'] == 2025].copy()
    delta_df_2025 = delta_df[delta_df['season'] == 2025].copy()

    df_2025 = compute_deltas(df_2025, delta_df_2025)
    df_2025 = add_surge_features(df_2025, pbp, id, snaps)
    df_2025 = df_2025.merge(injury_flags, on="player_id", how="left")
    df_2025["injury_flag"] = df_2025["injury_flag"].fillna(False)
    df_2025 = remove_cols(df_2025)
    return df_2025