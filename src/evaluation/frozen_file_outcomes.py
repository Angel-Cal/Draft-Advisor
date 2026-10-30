"""Attach a season's outcomes to a frozen projections file, so the simulator can score the advisor on it (.claude/PREREGISTRATION_2026.md, "Advisor edge").

Reads a projections file (the frozen 2026 live file, or an earlier backtest file for the dry run), checks its SHA-256 when `--expect-sha256` is given, and writes a copy of kind `backtest` in which every
player carries `actual_ppr` (the regular-season PPR total, 0.0 for a player with no stats: drafted, never played) and `weekly_ppr` (18 weeks, null where the player did not play), built exactly as
export_projections.build_backtest does. Projections, ADP, flags and every other field are copied untouched.

Run (after the season, with the raw stats refreshed through it):
  python src/evaluation/frozen_file_outcomes.py --season 2026 --source data/processed/projections_2026_v1.json --out data/processed/score2026 \\
      --expect-sha256 ebe202bea8cb69798c28f9aa30b0d697422859de06dee02a7c495dd7a1f9518c [--seasonal data/raw/seasonal_20_25.parquet] [--weekly data/raw/weekly_20_25.parquet]
  dotnet run -c Release --project csharp/src/DraftBot.Sim -- backtest --data data/processed/score2026 --seasons 2026 --seeds 200 [--wr 2]
Dry run on a season whose outcomes are known: `--season 2025 --source data/processed/projections_2025_v1.json --out <dir> --check-against data/processed/projections_2025_v1.json` must report no difference.
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.data.export_projections import WEEKS, weekly_lists
from src.data.validate import check_projection_file

ROOT = Path(__file__).parent.parent.parent


def with_outcomes(doc, seasonal, weekly, season):
    """A copy of the projections document as a backtest file with the season's actual_ppr and weekly_ppr on every player."""
    actual = seasonal[(seasonal["season"] == season) & seasonal["player_id"].notna()].set_index("player_id")["fantasy_points_ppr"]
    by_player = weekly_lists(weekly, season)
    out = dict(doc, kind="backtest")
    out["players"] = [dict(p, actual_ppr=round(float(actual.get(p["player_id"], 0.0)), 2), weekly_ppr=by_player.get(p["player_id"], [None] * WEEKS)) for p in doc["players"]]
    return out


def option(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if __name__ == "__main__":
    season = int(option("--season", "2026"))
    source = Path(option("--source", str(ROOT / "data" / "processed" / f"projections_{season}_v1.json")))
    out_dir = Path(option("--out", str(ROOT / "data" / "processed" / f"score{season}")))
    expected = option("--expect-sha256")
    if expected and hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        sys.exit(f"{source} does not match the frozen SHA-256 {expected}; refusing to score it")
    seasonal = pd.read_parquet(option("--seasonal", str(ROOT / "data" / "raw" / "seasonal_20_25.parquet")))
    weekly = pd.read_parquet(option("--weekly", str(ROOT / "data" / "raw" / "weekly_20_25.parquet")),
                             columns=["player_id", "season", "week", "season_type", "fantasy_points_ppr"])
    doc = with_outcomes(json.loads(source.read_text()), seasonal, weekly, season)
    check_projection_file(doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"projections_{season}_v1.json").write_text(json.dumps(doc))
    played = sum(1 for p in doc["players"] if p["actual_ppr"] > 0)
    print(f"wrote {out_dir / f'projections_{season}_v1.json'}: {len(doc['players'])} players, {played} with points")
    reference = option("--check-against")
    if reference:
        ref = {p["player_id"]: p for p in json.loads(Path(reference).read_text())["players"]}
        bad = [p["player_id"] for p in doc["players"] if p["actual_ppr"] != ref[p["player_id"]]["actual_ppr"] or p["weekly_ppr"] != ref[p["player_id"]]["weekly_ppr"]]
        print(f"compared with {reference}: {len(bad)} players differ in actual_ppr or weekly_ppr" + (f" ({bad[:5]})" if bad else ""))
