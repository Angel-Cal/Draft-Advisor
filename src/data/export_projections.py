"""Export projections_<season>_v1.json for the C# side (contract: .claude/projection_schema_v1.md).

One live file (next season's projections, ADP from the Underdog CSV) and one backtest file per held-out season
(walk-forward projections, FantasyPros ADP, plus the actual points the simulator scores rosters with). Both use the
same schema so the simulator runs the code path the app ships.

The pool is the ADP-ranked players, as in the live advisor table. Anyone the model cannot score gets an ADP-curve
projection flagged market_estimate (backtests fit that curve leaving the exported season out).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.data.run_manifest import _git, check_freshness, update_manifest
from src.data.validate import NO_TEAM, check_projection_file
from src.draft.market_fallback import fit_position_curves, load_history, market_projections
from src.draft.vor import RMSE
from src.features.role_context import build_role_context
from src.features.team_context import TEAM_MAP

ROOT = Path(__file__).parent.parent.parent
PROCESSED = ROOT / "data" / "processed"
POSITIONS = ["QB", "RB", "WR", "TE"]
BACKTEST_SEASONS = range(2021, 2026)
WEEKS = 18
POOL_RANK = 300  # the live advisor table holds the ~300 players ranked by Underdog
TEAM_FIXES = {**TEAM_MAP, "JAC": "JAX", "LAR": "LA"}  # FantasyPros / 4for4 spellings -> nflverse
SCHEMA_COLUMNS = ["player_id", "player_name", "position", "team", "projected_ppr", "projected_half",
                  "projected_standard", "games", "games_delta", "adp", "injury_flag", "market_estimate", "actual_ppr"]


ROLE_COLUMNS = ["absence_share_prev", "team_changed", "rookie_r1_teammate"]    # optional schema fields, WR rows only (the study behind them is WR-only)


def attach_role_context(df, context, season):
    """Add the optional role-context fields (src/features/role_context.py) for this season; null for everyone but WRs and for players with no history."""
    this = context[context["season"] == season][["player_id"] + ROLE_COLUMNS]
    df = df.merge(this, on="player_id", how="left")
    for column in ROLE_COLUMNS:
        df.loc[df["position"] != "WR", column] = float("nan")
    df["absence_share_prev"] = df["absence_share_prev"].astype(float).round(3)
    for flag in ("team_changed", "rookie_r1_teammate"):
        df[flag] = df[flag].astype("boolean")          # true / false / null in the JSON
    return df


def _team(series):
    """nflverse spelling; pre-draft rookies (TBD), unsigned veterans (FA, -) and unknowns all become NO_TEAM."""
    return series.replace(TEAM_FIXES).replace({"TBD": NO_TEAM, "-": NO_TEAM}).fillna(NO_TEAM)


def _finish(df):
    """Fill the schema columns: half/standard stay null until Phase 3, ints are ints, floats are rounded."""
    df = df.assign(projected_half=float("nan"), projected_standard=float("nan"))
    if "actual_ppr" not in df.columns:
        df["actual_ppr"] = float("nan")
    df["games"] = df["games"].round().astype("Int64")
    df["games_delta"] = df["games_delta"].round().astype("Int64")
    df["injury_flag"] = df["injury_flag"].astype(bool)
    df["market_estimate"] = df["market_estimate"].astype(bool)
    for col in ["projected_ppr", "adp", "actual_ppr"]:
        df[col] = df[col].astype(float).round(2)
    columns = SCHEMA_COLUMNS + (["weekly_ppr"] if "weekly_ppr" in df.columns else [])
    return df[columns].sort_values("adp").reset_index(drop=True)


def durability_flag(seasonal, before_season):
    """player_id -> True if they averaged under 15 games over their qualifying seasons before `before_season`.

    Same rule as build_features.add_injury_flag (>= 2 seasons of >= 4 games), recomputed point-in-time so a backtest
    row only sees seasons the drafter would have known. The recommender reads this as `injury_flag`.
    """
    s = seasonal[seasonal["position"].isin(POSITIONS) & (seasonal["games"] >= 4) & (seasonal["season"] < before_season)]
    per_season = s.groupby(["player_id", "season"])["games"].sum().groupby("player_id").agg(["mean", "count"])
    return (per_season["count"] >= 2) & (per_season["mean"] < 15)


def build_live(table, roster, adp_table):
    """table: predictions_table.parquet; roster: roster_2026; adp_table: adp_table.csv (4for4 + player_id)."""
    teams = (roster.sort_values("week").groupby("gsis_id").tail(1).set_index("gsis_id")["team"])
    adp_table = adp_table.assign(key=adp_table["player_id"].fillna("market:" + adp_table["merge_name"]))
    adp_teams = adp_table.drop_duplicates("key").set_index("key")["Team"]

    df = table.rename(columns={"underdog": "adp"}).copy()
    df["team"] = df["player_id"].map(teams).fillna(df["player_id"].map(adp_teams))
    df["team"] = _team(df["team"])
    return _finish(df)


def weekly_lists(weekly, season):
    """player_id -> 18 values, regular-season PPR for weeks 1-18; None where the player did not play (bye, injury, inactive)."""
    w = weekly[(weekly["season"] == season) & (weekly["season_type"] == "REG")]
    by_player = {}
    for player_id, week, points in zip(w["player_id"], w["week"], w["fantasy_points_ppr"]):
        by_player.setdefault(player_id, [None] * WEEKS)[int(week) - 1] = round(float(points), 2)
    return by_player


def build_backtest(season, oos, adp, training, seasonal, curves, weekly=None):
    """oos: season_<year>.parquet; adp: adp_<year>.csv; training: training_data; seasonal: raw season stats.

    curves must NOT have seen this season (market rows would otherwise be fit on their own outcome).
    """
    pool = adp[adp["position"].isin(POSITIONS) & (adp["rank"] <= POOL_RANK)].copy()
    pool["team"] = _team(pool["team"])

    scored = oos.merge(pool[["player_id", "team", "adp"]], on="player_id")
    lagged = training[training["season"] == season].set_index("player_id")[["games", "games_delta"]]
    scored = scored.join(lagged, on="player_id")
    scored["injury_flag"] = scored["player_id"].map(durability_flag(seasonal, season)).fillna(False)
    scored = scored.rename(columns={"oos_pred_ppr": "projected_ppr"}).assign(market_estimate=False)

    # market rows go through the same function the live advisor uses, which expects the 4for4-style table
    table = pd.DataFrame({"Player": pool["name"], "merge_name": pool["name"].str.lower(),
                          "Position": pool["position"] + "-00", "ADP": pool["adp"], "Underdog": pool["adp"],
                          "player_id": pool["player_id"]})
    market = market_projections(table, set(oos["player_id"]), curves).rename(columns={"underdog": "adp"})
    market = market.merge(pool[["player_id", "team"]], on="player_id")

    actual = seasonal[seasonal["season"] == season].set_index("player_id")["fantasy_points_ppr"]
    market["actual_ppr"] = market["player_id"].map(actual)
    zero_games = market["actual_ppr"].isna()
    market["actual_ppr"] = market["actual_ppr"].fillna(0.0)  # drafted, never played: that is what a real roster scores
    print(f"  {season}: {len(scored)} model-scored + {len(market)} market rows ({int(zero_games.sum())} played zero games)")

    result = pd.concat([scored, market], ignore_index=True)
    if weekly is not None:      # a player with no weekly rows never played: all weeks empty
        by_player = weekly_lists(weekly, season)
        result["weekly_ppr"] = [by_player.get(player_id, [None] * WEEKS) for player_id in result["player_id"]]
    return _finish(result)


def to_document(df, season, kind, adp_source):
    return {
        "schema_version": "v1", "kind": kind, "season": season, "adp_source": adp_source,
        "position_rmse": RMSE, "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "players": json.loads(df.to_json(orient="records")),  # NaN -> null, numpy types -> JSON types
    }


def write(doc):
    check_projection_file(doc)  # validate before writing, so a bad run can't leave a half-valid file behind
    path = PROCESSED / f"projections_{doc['season']}_v1.json"
    path.write_text(json.dumps(doc, indent=1, allow_nan=False))
    print(f"wrote {path.name}: {len(doc['players'])} players ({doc['kind']}, adp={doc['adp_source']})")
    return path


if __name__ == "__main__":
    prediction = pd.read_parquet(PROCESSED / "prediction_data.parquet")
    live_season = int(prediction["season"].max()) + 1

    position_files = [PROCESSED / f"{p.lower()}_predictions.parquet" for p in POSITIONS]
    check_freshness(position_files, [PROCESSED / "predictions_table.parquet"], label="export (advisor table)")
    weekly = pd.read_parquet(ROOT / "data" / "raw" / "weekly_20_25.parquet",
                             columns=["player_id", "season", "week", "season_type", "fantasy_points_ppr", "team", "position", "targets"])
    roster_columns = ["gsis_id", "season", "week", "team", "position", "years_exp", "draft_number"]
    roster = pd.concat([pd.read_parquet(ROOT / "data" / "raw" / "seasonal_roster_20_25.parquet", columns=roster_columns),
                        pd.read_parquet(ROOT / "data" / "raw" / "roster_2026.parquet", columns=roster_columns)], ignore_index=True)
    context = build_role_context(weekly, roster)
    live = build_live(pd.read_parquet(PROCESSED / "predictions_table.parquet"),
                      pd.read_parquet(ROOT / "data" / "raw" / "roster_2026.parquet"),
                      pd.read_csv(PROCESSED / "adp_table.csv"))
    live = attach_role_context(live, context, live_season)
    written = [write(to_document(live, live_season, "live", "underdog"))]

    training = pd.read_parquet(PROCESSED / "training_data.parquet")
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")
    seasonal = seasonal[seasonal["player_id"].notna()]
    history = load_history()
    for season in BACKTEST_SEASONS:
        oos_path = PROCESSED / f"season_{season}.parquet"
        check_freshness([PROCESSED / "training_data.parquet"], [oos_path], label=f"export (season {season})")
        curves = fit_position_curves(history[history["season"] != season])
        backtest = build_backtest(season, pd.read_parquet(oos_path),
                                  pd.read_csv(ROOT / "data" / "external" / f"adp_{season}.csv"),
                                  training, seasonal, curves, weekly)
        backtest = attach_role_context(backtest, context, season)
        written.append(write(to_document(backtest, season, "backtest", "fantasypros")))

    update_manifest("export", {"files": [p.name for p in written], "validation": "passed"})
