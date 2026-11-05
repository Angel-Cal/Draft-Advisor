"""Export projections_<season>_v1.json for the C# side (contract: .claude/projection_schema_v1.md).

One live file (next season's projections, ADP from the FantasyPros export) and one backtest file per held-out season
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
from src.paths import LIVE, OOS, PIPELINE
from src.data.run_manifest import _git, check_freshness, update_manifest
from src.data.validate import NO_TEAM, check_projection_file
from src.draft.market_fallback import fit_position_curves, load_history, market_projections
from src.data.major_injuries import load_major_injuries
from src.draft.vor import RMSE
from src.features.role_context import build_role_context
from src.features.team_context import TEAM_MAP

ROOT = Path(__file__).parent.parent.parent
POSITIONS = ["QB", "RB", "WR", "TE"]
BACKTEST_SEASONS = range(2021, 2026)
WEEKS = 18
POOL_RANK = 300  # the live advisor table holds the ~300 players ranked by ADP
TEAM_FIXES = {**TEAM_MAP, "JAC": "JAX", "LAR": "LA"}  # FantasyPros spellings -> nflverse
SCHEMA_COLUMNS = ["player_id", "player_name", "position", "team", "projected_ppr", "projected_half",
                  "projected_standard", "games", "games_delta", "adp", "injury_flag", "market_estimate", "actual_ppr"]


ROLE_COLUMNS = ["absence_share_prev", "team_changed", "rookie_r1_teammate"]    # optional schema fields, WR rows only (the study behind them is WR-only)
HISTORY_SEASONS = 3     # the injury flag looks at this many seasons before the draft
MISSED_PER_SEASON = 4   # ... and flags an average of this many missed games or more per season


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
    df["injury_flag"] = df["injury_flag"].astype(bool) if "injury_flag" in df.columns else False   # set by attach_injury_history
    df["market_estimate"] = df["market_estimate"].astype(bool)
    for col in ["projected_ppr", "adp", "actual_ppr"]:
        df[col] = df[col].astype(float).round(2)
    columns = SCHEMA_COLUMNS + (["weekly_ppr"] if "weekly_ppr" in df.columns else [])
    return df[columns].sort_values("adp").reset_index(drop=True)


def season_games(season):
    """Regular-season games a team played that season (16 before 2021, 17 from 2021)."""
    return 16 if season < 2021 else 17


def games_history(seasonal, before_season):
    """player_id -> [{"season", "games", "of"}, ...], oldest first: his last HISTORY_SEASONS seasons before `before_season`.

    Seasons start at the first one he has stats for, so a newer player has fewer. A season inside that span with no stats
    counts as 0 games (a season lost to injury drops out of the stats entirely). Games are capped at the season length
    (a mid-season trade can show one extra).
    """
    s = seasonal[seasonal["position"].isin(POSITIONS) & (seasonal["season"] < before_season)]
    played = s.groupby(["player_id", "season"])["games"].sum()
    first = s.groupby("player_id")["season"].min()
    history = {}
    for player_id, start in first.items():
        seasons = range(max(start, before_season - HISTORY_SEASONS), before_season)
        history[player_id] = [{"season": int(y), "games": int(min(played.get((player_id, y), 0), season_games(y))),
                               "of": season_games(y)} for y in seasons]
    return history


def injury_flag(history, major_injury):
    """True if he missed MISSED_PER_SEASON or more games per season on average over his history, or is coming off a
    confirmed major injury (torn knee ligament or Achilles, data/external/major_injuries.csv) last season."""
    if major_injury is not None:
        return True
    if not history:
        return False
    return sum(h["of"] - h["games"] for h in history) / len(history) >= MISSED_PER_SEASON


def attach_injury_history(df, seasonal, season, major):
    """Add the optional games_history and major_injury fields and set injury_flag from them (the same rule live and in
    backtests, point-in-time: only seasons before `season`). major: load_major_injuries() output."""
    history = games_history(seasonal, season)
    df = df.copy()
    df["games_history"] = [history.get(player_id) for player_id in df["player_id"]]
    df["major_injury"] = [major.get((player_id, season - 1)) for player_id in df["player_id"]]
    df["injury_flag"] = [injury_flag(h, m) for h, m in zip(df["games_history"], df["major_injury"])]
    return df


def build_live(table, roster, adp_table):
    """table: predictions_table.parquet; roster: roster_2026; adp_table: adp_table.csv (FantasyPros ADP + player_id)."""
    teams = (roster.sort_values("week").groupby("gsis_id").tail(1).set_index("gsis_id")["team"])
    adp_table = adp_table.assign(key=adp_table["player_id"].fillna("market:" + adp_table["merge_name"]))
    adp_teams = adp_table.drop_duplicates("key").set_index("key")["Team"]

    df = table[table["adp"].rank(method="first") <= POOL_RANK].copy()      # the same pool size as the backtests
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
    scored = scored.rename(columns={"oos_pred_ppr": "projected_ppr"}).assign(market_estimate=False)

    # market rows go through the same function the live advisor uses, which expects the live ADP table's shape
    table = pd.DataFrame({"Player": pool["name"], "merge_name": pool["name"].str.lower(),
                          "Position": pool["position"], "ADP": pool["adp"],
                          "player_id": pool["player_id"]})
    market = market_projections(table, set(oos["player_id"]), curves)
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
    path = LIVE / f"projections_{doc['season']}_v1.json"
    path.write_text(json.dumps(doc, indent=1, allow_nan=False))
    print(f"wrote {path.name}: {len(doc['players'])} players ({doc['kind']}, adp={doc['adp_source']})")
    return path


if __name__ == "__main__":
    # `--seasons 2019,2020` exports only those backtest files (no live file, no manifest update), so earlier seasons can be added without rewriting the rest
    only = [int(x) for x in sys.argv[sys.argv.index("--seasons") + 1].split(",")] if "--seasons" in sys.argv else None
    prediction = pd.read_parquet(PIPELINE / "prediction_data.parquet")
    live_season = int(prediction["season"].max()) + 1

    position_files = [PIPELINE / f"{p.lower()}_predictions.parquet" for p in POSITIONS]
    if only is None:
        check_freshness(position_files, [PIPELINE / "predictions_table.parquet"], label="export (advisor table)")
    weekly = pd.read_parquet(ROOT / "data" / "raw" / "weekly_20_25.parquet",
                             columns=["player_id", "season", "week", "season_type", "fantasy_points_ppr", "team", "position", "targets"])
    roster_columns = ["gsis_id", "season", "week", "team", "position", "years_exp", "draft_number"]
    roster = pd.concat([pd.read_parquet(ROOT / "data" / "raw" / "seasonal_roster_20_25.parquet", columns=roster_columns),
                        pd.read_parquet(ROOT / "data" / "raw" / "roster_2026.parquet", columns=roster_columns)], ignore_index=True)
    context = build_role_context(weekly, roster)
    seasonal = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_20_25.parquet")
    seasonal = seasonal[seasonal["player_id"].notna()]
    major = load_major_injuries()
    written = []
    if only is None:
        live = build_live(pd.read_parquet(PIPELINE / "predictions_table.parquet"),
                          pd.read_parquet(ROOT / "data" / "raw" / "roster_2026.parquet"),
                          pd.read_csv(PIPELINE / "adp_table.csv"))
        live = attach_role_context(live, context, live_season)
        live = attach_injury_history(live, seasonal, live_season, major)
        written.append(write(to_document(live, live_season, "live", "fantasypros")))

    training = pd.read_parquet(PIPELINE / "training_data.parquet")
    history = load_history()
    for season in only or BACKTEST_SEASONS:
        oos_path = OOS / f"season_{season}.parquet"
        check_freshness([PIPELINE / "training_data.parquet"], [oos_path], label=f"export (season {season})")
        curves = fit_position_curves(history[history["season"] != season])
        backtest = build_backtest(season, pd.read_parquet(oos_path),
                                  pd.read_csv(ROOT / "data" / "external" / f"adp_{season}.csv"),
                                  training, seasonal, curves, weekly)
        backtest = attach_role_context(backtest, context, season)
        backtest = attach_injury_history(backtest, seasonal, season, major)
        written.append(write(to_document(backtest, season, "backtest", "fantasypros")))

    if only is None:
        update_manifest("export", {"files": [p.name for p in written], "validation": "passed"})
