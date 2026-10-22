"""Data-integrity checks. Errors raise DataIntegrityError and stop the run; soft problems warn.

Every check here exists because the problem it catches happened silently: legacy team codes dropping rows,
junk 'Team' rows inflating team_games, a target-season feature leaking into training, and prediction rows that
disagreed with training rows. tests/test_data_integrity.py runs the same checks against the real data.
"""

import warnings
import numpy as np
import pandas as pd
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.features.team_context import TEAM_MAP

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]
CANONICAL_TEAMS = {"ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND",
                   "JAX", "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF",
                   "TB", "TEN", "WAS"}
NO_TEAM = "FA"  # projection files: rookie not yet drafted, unsigned veteran, or team unknown
MIN_ROWS_PER_SEASON = 250
RETENTION_MIN = 0.97
DRIFT_IGNORE = {"rookie_year"}  # calendar-driven: the prediction season is always the newest
# columns present in only one of the two frames by design
TRAIN_ONLY = {"target_ppr"}
PREDICTION_ONLY = {"injury_flag"}
RANGES = {"target_ppr": (-20, 600), "games": (1, 18), "implied_total": (10, 40), "age": (18, 50),
          "draft_number": (1, 300), "target_share": (0, 1), "wopr": (0, 3)}
NO_NULLS = ["player_id", "season", "position", "target_ppr", "implied_total", "age", "draft_number", "games"]


class DataIntegrityError(AssertionError):
    pass


class DataIntegrityWarning(UserWarning):
    pass


def _raise_if(errors, label):
    if errors:
        raise DataIntegrityError(f"[{label}] " + "; ".join(errors))


def _warn(message, label):
    warnings.warn(f"[{label}] {message}", DataIntegrityWarning, stacklevel=3)


def drop_junk_rows(df, id_col):
    """Raw nflverse files contain team-total rows with no player ID (games = 256-272)."""
    junk = df[id_col].isna()
    if junk.any():
        print(f"[validate] dropped {int(junk.sum())} rows with null {id_col}")
    return df[~junk]


def check_raw_seasonal(seasonal):
    errors = []
    if seasonal["player_id"].isna().any():
        errors.append(f"{int(seasonal['player_id'].isna().sum())} rows with null player_id")
    dupes = int(seasonal.duplicated(["player_id", "season"]).sum())
    if dupes:
        errors.append(f"{dupes} duplicate (player_id, season) rows")
    if not seasonal["games"].between(0, 18).all():
        errors.append(f"games outside 0-18 (max {seasonal['games'].max()})")
    unknown = set(seasonal["recent_team"].dropna().replace(TEAM_MAP)) - CANONICAL_TEAMS
    if unknown:
        errors.append(f"unknown team codes {sorted(unknown)}")
    _raise_if(errors, "raw seasonal")


def check_raw_roster(roster):
    errors = []
    if roster["gsis_id"].isna().any():
        errors.append(f"{int(roster['gsis_id'].isna().sum())} rows with null gsis_id")
    unknown = set(roster["team"].dropna().replace(TEAM_MAP)) - CANONICAL_TEAMS
    if unknown:
        errors.append(f"unknown team codes {sorted(unknown)}")
    _raise_if(errors, "raw roster")
    dupes = int(roster.duplicated(["gsis_id", "season", "week"]).sum())
    if dupes:
        _warn(f"{dupes} duplicate (gsis_id, season, week) roster rows (first one wins)", "raw roster")


def check_retention(expected, actual, label, min_ratio=RETENTION_MIN):
    """expected/actual: row counts indexed by season. A merge or filter must not silently shrink a season."""
    ratio = (actual.reindex(expected.index).fillna(0) / expected).dropna()
    bad = ratio[ratio < min_ratio]
    _raise_if([f"{label}: season {s} kept {r:.1%} of rows (min {min_ratio:.0%})" for s, r in bad.items()], "retention")


def check_no_row_loss(before, after, label):
    _raise_if([f"{label}: {before - after} of {before} rows lost"] if after < before else [], "retention")


def check_training(df):
    errors = []
    missing = [c for c in NO_NULLS if c not in df.columns]
    _raise_if([f"missing columns {missing}"] if missing else [], "training")
    if df.duplicated(["player_id", "season"]).any():
        errors.append(f"{int(df.duplicated(['player_id', 'season']).sum())} duplicate (player_id, season) rows")
    for col in NO_NULLS:
        if df[col].isna().any():
            errors.append(f"{int(df[col].isna().sum())} nulls in {col}")
    for col, (lo, hi) in RANGES.items():
        if col in df.columns and not df[col].dropna().between(lo, hi).all():
            errors.append(f"{col} outside [{lo}, {hi}] (min {df[col].min():.3g}, max {df[col].max():.3g})")
    if not set(df["position"].astype(str)) <= set(SKILL_POSITIONS):
        errors.append(f"unexpected positions {sorted(set(df['position'].astype(str)) - set(SKILL_POSITIONS))}")
    counts = df.groupby("season").size()
    thin = counts[counts < MIN_ROWS_PER_SEASON]
    if len(thin):
        errors.append(f"seasons with fewer than {MIN_ROWS_PER_SEASON} rows: {thin.to_dict()}")
    gaps = set(range(int(counts.index.min()), int(counts.index.max()) + 1)) - set(counts.index)
    if gaps:
        errors.append(f"missing seasons {sorted(gaps)}")
    _raise_if(errors, "training")


def check_prediction(prediction, training):
    """Prediction rows must be shaped exactly like training rows, with prediction-season inputs."""
    errors = []
    train_cols, pred_cols = set(training.columns) - TRAIN_ONLY, set(prediction.columns) - PREDICTION_ONLY
    if train_cols != pred_cols:
        errors.append(f"column mismatch: only in training {sorted(train_cols - pred_cols)}, "
                      f"only in prediction {sorted(pred_cols - train_cols)}")
    if prediction["player_id"].duplicated().any():
        errors.append("duplicate player_id in prediction rows")
    _raise_if(errors, "prediction")

    in_both = [c for c in training.columns if c in prediction.columns]
    if in_both != [c for c in prediction.columns if c in training.columns]:
        _warn("column order differs from training (predict.py aligns by name)", "prediction")
    changed = [c for c in in_both if str(training[c].dtype) != str(prediction[c].dtype)]
    if changed:
        _warn(f"dtype differs from training for {changed}", "prediction")

    # stale-input guard: age should have advanced a year relative to each player's last training row
    last = training.sort_values("season").groupby("player_id").tail(1).set_index("player_id")["age"]
    joined = prediction.set_index("player_id")["age"].reindex(last.index).dropna()
    advanced = ((joined - last.reindex(joined.index)) == 1).mean() if len(joined) else 1.0
    if advanced < 0.8:
        errors.append(f"only {advanced:.0%} of players' age advanced one year vs their last training row "
                      "(prediction rows may carry last season's age/experience/team)")
    _raise_if(errors, "prediction")

    if prediction["implied_total"].isna().mean() > 0.15:
        _warn(f"{prediction['implied_total'].isna().mean():.0%} of prediction rows have no implied_total", "prediction")
    numeric = [c for c in in_both if pd.api.types.is_numeric_dtype(training[c]) and c not in ({"season", "player_id"} | DRIFT_IGNORE)]
    std = training[numeric].std().replace(0, np.nan)
    drift = ((prediction[numeric].mean() - training[numeric].mean()) / std).abs().dropna().sort_values(ascending=False)
    flagged = drift[drift > 1.0]
    if len(flagged):
        _warn("feature drift vs training (|standardized mean shift| > 1): "
              + ", ".join(f"{c} {v:.2f}" for c, v in flagged.head(5).items()), "prediction")


def check_prediction_outputs(frames):
    """frames: {position: DataFrame} as written by predict.py."""
    errors = []
    for position, df in frames.items():
        if df.empty:
            errors.append(f"{position}: no rows")
            continue
        if df["player_id"].duplicated().any():
            errors.append(f"{position}: duplicate player_id")
        if df["projected_ppr"].isna().any() or not np.isfinite(df["projected_ppr"]).all():
            errors.append(f"{position}: non-finite projected_ppr")
        elif not df["projected_ppr"].between(-50, 600).all():
            errors.append(f"{position}: projected_ppr outside [-50, 600]")
    _raise_if(errors, "prediction outputs")


def check_adp_matches(adp, top_n=200):
    """Every player the market ranks highly must have a player_id, or the benchmark silently drops them."""
    unmatched = adp[adp["player_id"].isna() & (adp["rank"] <= top_n)]
    errors = []
    if len(unmatched):
        errors.append(f"{len(unmatched)} players ranked <= {top_n} have no player_id: "
                      f"{unmatched[['season', 'name']].astype(str).agg(' '.join, axis=1).head(5).tolist()}")
    dupes = adp.dropna(subset=["player_id"]).duplicated(["season", "player_id"])
    if dupes.any():
        errors.append(f"{int(dupes.sum())} duplicate (season, player_id) ADP rows")
    _raise_if(errors, "adp")


def check_projection_file(doc):
    """doc: the dict written to projections_<season>_v1.json (header + players). C# trusts these guarantees."""
    errors = []
    if doc.get("schema_version") != "v1":
        errors.append(f"schema_version {doc.get('schema_version')!r} is not 'v1'")
    if doc.get("kind") not in ("live", "backtest"):
        errors.append(f"kind {doc.get('kind')!r} must be 'live' or 'backtest'")
    rmse = doc.get("position_rmse", {})
    if set(rmse) != set(SKILL_POSITIONS) or not all(v > 0 for v in rmse.values()):
        errors.append(f"position_rmse must hold a positive value for each of {SKILL_POSITIONS}, got {rmse}")
    players = pd.DataFrame(doc.get("players", []))
    if players.empty:
        errors.append("no players")
        _raise_if(errors, "projection file")
    required = ["player_id", "player_name", "position", "team", "projected_ppr", "games", "games_delta", "adp",
                "injury_flag", "market_estimate"]
    missing = [c for c in required if c not in players.columns]
    _raise_if(errors + ([f"missing columns {missing}"] if missing else []), "projection file")

    if players["player_id"].duplicated().any():
        errors.append(f"{int(players['player_id'].duplicated().sum())} duplicate player_id rows")
    for col in required:
        if players[col].isna().any():
            errors.append(f"{int(players[col].isna().sum())} nulls in {col}")
    if not set(players["position"]) <= set(SKILL_POSITIONS):
        errors.append(f"unexpected positions {sorted(set(players['position']) - set(SKILL_POSITIONS))}")
    unknown_teams = set(players["team"].dropna()) - CANONICAL_TEAMS - {NO_TEAM}
    if unknown_teams:
        errors.append(f"unknown team codes {sorted(unknown_teams)}")
    if not players["projected_ppr"].dropna().between(-50, 600).all():
        errors.append("projected_ppr outside [-50, 600]")
    synthetic = players["player_id"].str.startswith("market:")
    if (synthetic & ~players["market_estimate"].astype(bool)).any():
        errors.append("synthetic market: ids on rows not flagged market_estimate")
    if doc.get("kind") == "backtest":
        if "actual_ppr" not in players.columns or players["actual_ppr"].isna().any():
            errors.append("backtest file needs a non-null actual_ppr on every player")
        elif (players["actual_ppr"] < -20).any():
            errors.append("actual_ppr below -20")
    _raise_if(errors, "projection file")


def check_advisor_table(table):
    """The draft advisor's player table: one row per player, every value present, market rows flagged."""
    errors = []
    dupes = table["player_id"].duplicated()
    if dupes.any():
        errors.append(f"{int(dupes.sum())} duplicate player_id rows, e.g. {table.loc[dupes, 'player_id'].head(3).tolist()}")
    for col in ["projected_ppr", "vor", "tier", "underdog", "position", "market_estimate"]:
        if col in table.columns and table[col].isna().any():
            errors.append(f"{int(table[col].isna().sum())} nulls in {col}")
    if "market_estimate" in table.columns and not table["market_estimate"].isin([True, False]).all():
        errors.append("market_estimate must be True/False")
    _raise_if(errors, "advisor table")
