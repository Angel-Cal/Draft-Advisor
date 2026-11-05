"""Major injuries (torn ACL, torn Achilles and the like): candidates found in nflverse data, confirmed by hand.

nflverse injury reports name only the body part, so they cannot tell a torn ACL from a knee sprain. This module finds
the candidates (a season that ended early, or a whole season missed) for players drafted the next year;
each one is checked against a news report and recorded in data/external/major_injuries.csv (tracked in git). Only
rows marked major in that file feed the export. Run this module to list the candidates not yet reviewed.
"""

import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent.parent.parent
CURATED = ROOT / "data" / "external" / "major_injuries.csv"
CANDIDATES = ROOT / "data" / "external" / "major_injury_candidates.csv"
CURATED_COLUMNS = ["player_id", "player_name", "season", "week", "injury", "major", "source"]
BODY_PARTS = ("knee", "achilles")
WEEKS_LEFT = 6          # he must have missed at least this many weeks at the end of the season for it to count as season-ending
REPORT_WINDOW = 3       # injury reports this many weeks after his last game are read for the body part


def regular_season_weeks(season):
    """Weeks in the regular season, byes included (17 before the 17-game era, 18 from 2021)."""
    return 17 if season < 2021 else 18


def season_ending_candidates(injuries, weekly, roster, pools):
    """Players whose season S may have ended with a major injury, limited to players in the draft pool of season S+1.

    injuries: injury reports (season, week, gsis_id, report_primary_injury, report_secondary_injury);
    weekly: weekly stats (player_id, season, week, season_type); roster: weekly rosters (gsis_id, season, week, status);
    pools: season -> set of player_ids drafted that season. A candidate stopped playing with WEEKS_LEFT or more weeks to
    go; or missed the last weeks with a knee or Achilles report, or on reserve with no report naming another body part
    (a late tear matters most for next season); or played no game in S after playing in S-1.
    The body part on his last injury report within REPORT_WINDOW weeks of his last game is kept as a hint; a player
    placed straight on injured reserve drops off the reports, so a missing report does not rule him out.
    """
    played = weekly[weekly["season_type"] == "REG"].groupby(["player_id", "season"])["week"].agg(["max", "count"])
    reports = injuries.assign(part=(injuries["report_primary_injury"].fillna("") + " " +
                                    injuries["report_secondary_injury"].fillna("")).str.lower().str.strip())
    reserve = roster[roster["status"] == "RES"].groupby(["gsis_id", "season"])["week"].max()
    rows = []
    for draft_season, ids in pools.items():
        season = draft_season - 1
        for player_id in ids:
            if (player_id, season) in played.index:
                last, games = played.loc[(player_id, season)]
                hits = reports[(reports["gsis_id"] == player_id) & (reports["season"] == season) &
                               reports["week"].between(last, last + REPORT_WINDOW) & (reports["part"] != "")]
                part = hits["part"].iloc[-1] if len(hits) else ""
                weeks = regular_season_weeks(season)
                knee_or_achilles = last < weeks and any(b in part for b in BODY_PARTS)
                on_reserve = last < weeks and part == "" and reserve.get((player_id, season), 0) > last
                if last > weeks - WEEKS_LEFT and not (knee_or_achilles or on_reserve):
                    continue
                why = "knee/Achilles report" if knee_or_achilles else "season ended early"
                rows.append((player_id, season, int(last), int(games), part, why))
            elif (player_id, season - 1) in played.index:
                rows.append((player_id, season, None, 0, "", "missed the whole season"))
    return pd.DataFrame(rows, columns=["player_id", "season", "last_week", "games", "reported", "why"])


def load_major_injuries(path=CURATED):
    """(player_id, season) -> {"season", "week", "injury"} for every confirmed major injury in the curated file."""
    if not Path(path).exists():
        return {}
    df = pd.read_csv(path)
    df = df[df["major"].astype(str).str.lower() == "true"]
    return {(r.player_id, int(r.season)): {"season": int(r.season), "week": None if pd.isna(r.week) else int(r.week), "injury": r.injury}
            for r in df.itertuples()}


def _pools():
    """Draft season -> player_ids in that season's exported projection file (model-scored and market rows alike)."""
    pools = {}
    for path in sorted((ROOT / "data" / "processed").glob("projections_*_v1.json")):
        doc = json.loads(path.read_text())
        pools[doc["season"]] = {p["player_id"] for p in doc["players"] if not p["player_id"].startswith("market:")}
    return pools


if __name__ == "__main__":
    injuries = pd.read_parquet(ROOT / "data" / "raw" / "injuries_18_25.parquet")
    weekly = pd.read_parquet(ROOT / "data" / "raw" / "weekly_20_25.parquet", columns=["player_id", "player_name", "season", "week", "season_type"])
    roster = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_roster_20_25.parquet", columns=["gsis_id", "season", "week", "status"])
    found = season_ending_candidates(injuries, weekly, roster, _pools())
    names = weekly.drop_duplicates("player_id").set_index("player_id")["player_name"]
    found.insert(1, "player_name", found["player_id"].map(names))
    reviewed = pd.read_csv(CURATED) if CURATED.exists() else pd.DataFrame(columns=CURATED_COLUMNS)
    done = set(zip(reviewed["player_id"], reviewed["season"].astype(int)))
    todo = found[[(p, s) not in done for p, s in zip(found["player_id"], found["season"])]].sort_values(["season", "player_name"])
    todo.to_csv(CANDIDATES, index=False)
    print(f"{len(found)} candidates, {len(todo)} not yet reviewed -> {CANDIDATES.relative_to(ROOT)}")
    if "--print" in sys.argv:
        print(todo.to_string(index=False))
